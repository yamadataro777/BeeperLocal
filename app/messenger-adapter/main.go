// AGPL-3.0-or-later. Messenger transport using the pinned messagix source.
package main

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/rs/zerolog"
	"go.mau.fi/mautrix-meta/pkg/messagix"
	"go.mau.fi/mautrix-meta/pkg/messagix/cookies"
	"go.mau.fi/mautrix-meta/pkg/messagix/table"
	"go.mau.fi/mautrix-meta/pkg/messagix/types"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waConsumerApplication"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/store/sqlstore"
	wa "go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"
)

const maxIPC = 6 * 1024 * 1024

type savedState struct {
	Version             int                               `json:"version"`
	Cookies             map[cookies.MetaCookieName]string `json:"cookies"`
	DeviceDB            string                            `json:"device_db,omitempty"`
	RegistrationPending bool                              `json:"registration_pending,omitempty"`
}
type message struct {
	Provider     string `json:"provider"`
	Account      string `json:"account"`
	Conversation string `json:"conversation"`
	ID           string `json:"id"`
	Sender       string `json:"sender"`
	Direction    string `json:"direction"`
	Text         string `json:"text"`
	Timestamp    int64  `json:"timestamp"`
}
type deletion struct {
	Conversation string `json:"conversation"`
	ID           string `json:"id"`
	Sender       string `json:"sender"`
}

type conversation struct {
	ID    string `json:"id"`
	Title string `json:"title"`
}
type request struct {
	Op    string     `json:"op"`
	State savedState `json:"state"`
}
type command struct {
	Op           string      `json:"op"`
	RequestID    string      `json:"request_id"`
	Conversation string      `json:"conversation"`
	Text         string      `json:"text"`
	Image        *imageInput `json:"image,omitempty"`
}
type wire struct {
	mu       sync.Mutex
	in       *bufio.Scanner
	out      *json.Encoder
	acks     chan bool
	commands chan command
	closed   chan struct{}
}

// Exactly one reader demultiplexes persistence ACKs and user send requests.
func (w *wire) readCommands() {
	defer close(w.closed)
	for w.in.Scan() {
		var value map[string]json.RawMessage
		if json.Unmarshal(w.in.Bytes(), &value) != nil {
			return
		}
		if _, ok := value["ok"]; ok {
			var ack bool
			if len(value) != 1 || json.Unmarshal(value["ok"], &ack) != nil {
				return
			}
			select {
			case w.acks <- ack:
			default:
				return
			}
		} else {
			var cmd command
			if len(value) != 4 || json.Unmarshal(w.in.Bytes(), &cmd) != nil || !validSend(cmd) {
				return
			}
			select {
			case w.commands <- cmd:
			default:
				return
			}
		}
	}
}

var targetPattern = regexp.MustCompile(`^[1-9][0-9]{0,127}@msgr$`)
var requestPattern = regexp.MustCompile(`^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$`)

func validSend(cmd command) bool {
	if !requestPattern.MatchString(cmd.RequestID) || !targetPattern.MatchString(cmd.Conversation) {
		return false
	}
	if cmd.Op == "send_image" {
		_, err := cmd.Image.bytes()
		return cmd.Text == "" && err == nil
	}
	return cmd.Op == "send" && cmd.Image == nil && utf8.ValidString(cmd.Text) && utf8.RuneCountInString(cmd.Text) <= 4000 && strings.TrimSpace(cmd.Text) != ""
}
func textPayload(body string) *waConsumerApplication.ConsumerApplication {
	return &waConsumerApplication.ConsumerApplication{Payload: &waConsumerApplication.ConsumerApplication_Payload{
		Payload: &waConsumerApplication.ConsumerApplication_Payload_Content{Content: &waConsumerApplication.ConsumerApplication_Content{
			Content: &waConsumerApplication.ConsumerApplication_Content_MessageText{MessageText: &waCommon.MessageText{Text: proto.String(body)}}}}}}
}
func (w *wire) sendResult(cmd command, row *message) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.out.Encode(map[string]any{"kind": "send_result", "request_id": cmd.RequestID, "message": row})
}

func (w *wire) status(code string) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.out.Encode(map[string]any{"kind": "status", "code": code}) != nil {
		os.Exit(3)
	}
}
func (w *wire) checkpoint(state savedState, messages []message, catalog []conversation, deleted ...[]deletion) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	payload := map[string]any{"kind": "checkpoint", "state": state, "messages": messages, "conversations": catalog}
	if len(deleted) > 0 {
		payload["deletions"] = deleted[0]
	}
	data, err := json.Marshal(payload)
	if err != nil || len(data) >= maxIPC-1 {
		return errors.New("state_limit")
	}
	if w.out.Encode(payload) != nil {
		return errors.New("private_pipe")
	}
	if w.acks != nil {
		select {
		case ok := <-w.acks:
			if !ok {
				return errors.New("persistence_failed")
			}
		case <-w.closed:
			return errors.New("private_pipe")
		case <-time.After(90 * time.Second):
			return errors.New("persistence_failed")
		}
		return nil
	}
	if !w.in.Scan() {
		return errors.New("private_pipe")
	}
	var ack struct {
		OK bool `json:"ok"`
	}
	if json.Unmarshal(w.in.Bytes(), &ack) != nil || !ack.OK {
		return errors.New("persistence_failed")
	}
	return nil
}

// Only explicit hybrid mappings are used. A Facebook thread key is not an E2EE JID.
func catalog(tbl *table.LSTable) []conversation {
	result := []conversation{}
	if tbl == nil {
		return result
	}
	mapping := map[int64]int64{}
	for _, item := range tbl.LSVerifyHybridThreadExists {
		if item.ThreadType == table.ENCRYPTED_OVER_WA_ONE_TO_ONE && item.ThreadJID > 0 {
			mapping[item.ThreadKey] = item.ThreadJID
		}
	}
	for _, item := range tbl.LSUpdateThreadAuthorityAndMappingWithOTIDFromJID {
		if item.ThreadJID > 0 {
			mapping[item.ThreadKey] = item.ThreadJID
		}
	}
	seen := map[string]bool{}
	for _, item := range tbl.LSDeleteThenInsertThread {
		jid := mapping[item.ThreadKey]
		if jid <= 0 || !item.ThreadType.IsOneToOne() || item.IsDisappearingMode || item.DisappearingSettingTtl > 0 {
			continue
		}
		id := wa.NewJID(strconv.FormatInt(jid, 10), wa.MessengerServer).String()
		if seen[id] {
			continue
		}
		seen[id] = true
		result = append(result, conversation{id, item.ThreadName})
		if len(result) >= 500 {
			break
		}
	}
	return result
}

// Ignore group, view-once and disappearing content instead of retaining it indefinitely.
// Only authenticated sender revokes in supported DM threads. Admin/group revokes are excluded.
func normalDeletion(ev *events.FBMessage, account string) []deletion {
	chat, sender := ev.Info.Chat.ToNonAD(), ev.Info.Sender.ToNonAD()
	if ev.Info.IsGroup || !targetPattern.MatchString(chat.String()) || !targetPattern.MatchString(sender.String()) || (sender.User != account && sender.User != chat.User) {
		return nil
	}
	key := ev.GetConsumerApplication().GetPayload().GetApplicationData().GetRevoke().GetKey()
	if !key.GetFromMe() || key.GetID() == "" || len(key.GetID()) > 4096 {
		return nil
	}
	return []deletion{{chat.String(), key.GetID(), sender.String()}}
}

func normalText(ev *events.FBMessage, account string) []message {
	if ev.Info.Chat.Server != wa.MessengerServer || ev.Info.IsGroup || ev.FBApplication.GetMetadata().GetEphemeral() != nil {
		return nil
	}
	content := ev.GetConsumerApplication().GetPayload().GetContent()
	body := content.GetMessageText().GetText()
	if body == "" {
		body = content.GetExtendedTextMessage().GetText().GetText()
	}
	if body == "" {
		return nil
	}
	direction := "incoming"
	if ev.Info.IsFromMe {
		direction = "outgoing"
	}
	return []message{{"messenger", account, ev.Info.Chat.ToNonAD().String(), ev.Info.ID, ev.Info.Sender.ToNonAD().String(), direction, body, ev.Info.Timestamp.Unix()}}
}

func run(w *wire, r request) string {
	if r.Op != "watch" || r.State.Version != 1 {
		return "invalid_request"
	}
	state := r.State
	if state.RegistrationPending {
		return "registration_result_unknown"
	}
	jar := &cookies.Cookies{Platform: types.Facebook}
	jar.UpdateValues(state.Cookies)
	if len(jar.GetMissingCookieNames()) != 0 {
		return "login_required"
	}
	logger := zerolog.Nop()
	client := messagix.NewClient(jar, logger, &messagix.Config{})
	ctx, cancel := context.WithCancel(logger.WithContext(context.Background()))
	defer cancel()
	loadCtx, loadCancel := context.WithTimeout(ctx, 45*time.Second)
	user, tbl, err := client.LoadMessagesPage(loadCtx)
	loadCancel()
	if err != nil {
		return "inbox_failed"
	}
	if user == nil || user.GetFBID() <= 0 || strconv.FormatInt(user.GetFBID(), 10) != jar.Get(cookies.FBCookieCUser) {
		return "account_mismatch"
	}
	db, err := openMemory(state.DeviceDB)
	if err != nil {
		return "device_restore_failed"
	}
	defer db.Close()
	container := sqlstore.NewWithDB(db, "sqlite3", nil)
	if container.Upgrade(ctx) != nil {
		return "device_restore_failed"
	}
	devices, err := container.GetAllDevices(ctx)
	if err != nil || len(devices) > 1 {
		return "device_restore_failed"
	}
	// A saved database without its device is corrupt/ambiguous, never a new login.
	if state.DeviceDB != "" && len(devices) != 1 {
		return "device_restore_failed"
	}
	device := container.NewDevice()
	if len(devices) == 1 {
		device = devices[0]
		if device.ID == nil || device.ID.User != strconv.FormatInt(user.GetFBID(), 10) {
			return "account_mismatch"
		}
	}
	client.SetDevice(device)
	var stateMu sync.Mutex
	save := func(messages []message, conversations []conversation, deleted ...[]deletion) error {
		data, e := snapshot(db)
		if e != nil {
			return e
		}
		state.DeviceDB = base64.StdEncoding.EncodeToString(data)
		state.Cookies = jar.GetAll()
		return w.checkpoint(state, messages, conversations, deleted...)
	}
	if len(devices) == 0 {
		state.RegistrationPending = true
		if save(nil, nil) != nil {
			return "persistence_failed"
		}
		regCtx, regCancel := context.WithTimeout(ctx, 45*time.Second)
		err = client.RegisterE2EE(regCtx, user.GetFBID())
		regCancel()
		if err != nil || device.Save(ctx) != nil {
			return "registration_result_unknown"
		}
		state.RegistrationPending = false
		if save(nil, nil) != nil {
			return "persistence_failed"
		}
	}
	if save(nil, catalog(tbl)) != nil {
		return "persistence_failed"
	}
	e2ee, err := client.PrepareE2EEClient()
	if err != nil {
		return "device_restore_failed"
	}
	e2ee.EnableAutoReconnect = false
	e2ee.InitialAutoReconnect = false
	e2ee.PreRetryCallback = func(_ *events.Receipt, _ wa.MessageID, _ int, _ *waE2E.Message) bool { return false }
	e2ee.SynchronousAck = true
	e2ee.EnableDecryptedEventBuffer = true
	connected := make(chan struct{}, 1)
	failed := make(chan string, 1)
	fail := func(code string) {
		select {
		case failed <- code:
		default:
		}
	}
	e2ee.AddEventHandlerWithSuccessStatus(func(evt any) bool {
		stateMu.Lock()
		defer stateMu.Unlock()
		switch ev := evt.(type) {
		case *events.Connected:
			if save(nil, nil) != nil {
				fail("persistence_failed")
				return false
			}
			w.status("connected")
			select {
			case connected <- struct{}{}:
			default:
			}
		case *events.FBMessage:
			rows := normalText(ev, strconv.FormatInt(user.GetFBID(), 10))
			if save(rows, nil, normalDeletion(ev, strconv.FormatInt(user.GetFBID(), 10))) != nil {
				fail("persistence_failed")
				return false
			}
		case *events.UndecryptableMessage:
			fail("decrypt_failed")
			return false
		case events.PermanentDisconnect:
			fail("provider_rejected")
			return false
		case *events.Disconnected:
			fail("connection_lost")
			return false
		}
		return true
	})
	if e2ee.Connect() != nil {
		e2ee.Disconnect()
		return "connection_lost"
	}
	defer e2ee.Disconnect()
	select {
	case <-connected:
	case code := <-failed:
		return code
	case <-time.After(45 * time.Second):
		return "connection_lost"
	}
	// Heartbeats persist ratchet/session changes even during idle periods. Parent enforces a deadline.
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	seenRequests := map[string]bool{}
	for {
		select {
		case <-w.closed:
			return "connection_lost"
		case cmd := <-w.commands:
			if !validSend(cmd) || seenRequests[cmd.RequestID] {
				return "invalid_request"
			}
			seenRequests[cmd.RequestID] = true
			jid, parseErr := wa.ParseJID(cmd.Conversation)
			if parseErr != nil {
				return "invalid_request"
			}
			// No reconnect is enabled; an ambiguous write is never issued again.
			sendCtx, sendCancel := context.WithTimeout(ctx, 60*time.Second)
			payload := textPayload(cmd.Text)
			var sendErr error
			if cmd.Op == "send_image" {
				payload, sendErr = uploadImage(sendCtx, e2ee, cmd.Image)
			}
			var resp whatsmeow.SendResponse
			if sendErr == nil {
				resp, sendErr = e2ee.SendFBMessage(sendCtx, jid, payload, nil, whatsmeow.SendRequestExtra{Timeout: 25 * time.Second})
			}
			sendCancel()
			stateMu.Lock()
			var row *message
			var rows []message
			if sendErr == nil && resp.ID != "" && !resp.Timestamp.IsZero() {
				row = &message{"messenger", strconv.FormatInt(user.GetFBID(), 10), cmd.Conversation, resp.ID,
					device.ID.ToNonAD().String(), "outgoing", cmd.Text, resp.Timestamp.Unix()}
				rows = []message{*row}
			}
			err = save(rows, nil) // Persist ratchet changes even when the send outcome is unknown.
			stateMu.Unlock()
			if err != nil {
				return "persistence_failed"
			}
			if w.sendResult(cmd, row) != nil {
				return "connection_lost"
			}
		case code := <-failed:
			return code
		case <-ticker.C:
			stateMu.Lock()
			err = save(nil, nil)
			stateMu.Unlock()
			if err != nil {
				return "persistence_failed"
			}
			w.status("heartbeat")
		}
	}
}

func main() {
	for _, file := range []*os.File{os.Stdin, os.Stdout} {
		info, err := file.Stat()
		if err != nil || info.Mode()&os.ModeNamedPipe == 0 {
			os.Exit(2)
		}
	}
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 4096), maxIPC)
	w := &wire{in: scanner, out: json.NewEncoder(os.Stdout)}
	defer func() {
		if recover() != nil {
			w.status("internal_failure")
			os.Exit(1)
		}
	}()
	if !scanner.Scan() {
		os.Exit(2)
	}
	var r request
	if json.Unmarshal(scanner.Bytes(), &r) != nil {
		os.Exit(2)
	}
	w.acks, w.commands, w.closed = make(chan bool, 1), make(chan command, 1), make(chan struct{})
	go w.readCommands()
	w.status(run(w, r))
	os.Exit(1)
}
