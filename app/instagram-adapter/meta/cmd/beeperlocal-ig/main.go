// BeeperLocal Instagram adapter. Private JSON-lines IPC only.
// Uses the locally validated mautrix-meta source; see ../PROVENANCE.md.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/rs/zerolog"
	"go.mau.fi/mautrix-meta/pkg/instameow"
	"go.mau.fi/mautrix-meta/pkg/instameow/slidetypes"
	"go.mau.fi/mautrix-meta/pkg/messagix/cookies"
	"go.mau.fi/mautrix-meta/pkg/messagix/httpclient"
	"go.mau.fi/mautrix-meta/pkg/messagix/methods"
	"go.mau.fi/mautrix-meta/pkg/messagix/types"
	"maunium.net/go/mautrix/bridgev2"
)

const maxFrame = 1024 * 1024

type safeError string

func (e safeError) Error() string { return string(e) }

type session struct {
	Cookies  map[cookies.MetaCookieName]string `json:"cookies"`
	WWWClaim string                            `json:"www_claim"`
}
type request struct {
	Op        string   `json:"op"`
	Session   *session `json:"session"`
	AccountID string   `json:"account_id"`
	ThreadID  string   `json:"thread_id"`
	Limit     int      `json:"limit"`
	Text      string   `json:"text"`
	Timeout   int      `json:"timeout"`
	FromNow   bool     `json:"from_now"`
}
type conversation struct {
	ID     string `json:"id"`
	Title  string `json:"title"`
	LongID string `json:"long_id"`
}
type message struct {
	ID        string `json:"id"`
	ThreadID  string `json:"thread_id"`
	SenderID  string `json:"sender_id"`
	SentAt    string `json:"sent_at"`
	EditedAt  string `json:"edited_at,omitempty"`
	Text      string `json:"text"`
	Direction string `json:"direction"`
}
type authField struct {
	ID      string   `json:"id"`
	Options []string `json:"options,omitempty"`
}
type wire struct {
	input  *bufio.Scanner
	output *json.Encoder
	mu     sync.Mutex
}

func (w *wire) emit(v any) error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.output.Encode(v)
}
func (w *wire) read(v any) error {
	if !w.input.Scan() {
		return safeError("IG_PROTOCOL_ERROR")
	}
	if json.Unmarshal(w.input.Bytes(), v) != nil {
		return safeError("IG_PROTOCOL_ERROR")
	}
	return nil
}
func (w *wire) ask(fields []authField) (map[string]string, error) {
	if err := w.emit(map[string]any{"type": "auth_step", "fields": fields}); err != nil {
		return nil, err
	}
	var answer struct {
		Input map[string]string `json:"input"`
	}
	if err := w.read(&answer); err != nil {
		return nil, err
	}
	if answer.Input == nil {
		return nil, safeError("IG_PROTOCOL_ERROR")
	}
	for _, f := range fields {
		v, ok := answer.Input[f.ID]
		if !ok || v == "" || len(v) > 4096 {
			return nil, safeError("INVALID_INPUT")
		}
		if len(f.Options) > 0 {
			found := false
			for _, opt := range f.Options {
				if opt == v {
					found = true
				}
			}
			if !found {
				return nil, safeError("INVALID_INPUT")
			}
		}
	}
	return answer.Input, nil
}
func (w *wire) steps(ctx context.Context, stepper func(context.Context, map[string]string) (*bridgev2.LoginStep, error)) error {
	var input map[string]string
	for i := 0; i < 12; i++ {
		step, err := stepper(ctx, input)
		if err != nil {
			return err
		}
		if step == nil {
			return nil
		}
		if step.UserInputParams == nil || len(step.UserInputParams.Fields) == 0 {
			return safeError("IG_AUTH_ACTION_REQUIRED")
		}
		fields := []authField{}
		for _, f := range step.UserInputParams.Fields {
			fields = append(fields, authField{ID: f.ID, Options: f.Options})
		}
		input, err = w.ask(fields)
		if err != nil {
			return err
		}
	}
	return safeError("IG_AUTH_ACTION_REQUIRED")
}
func (w *wire) login(ctx context.Context, client *instameow.Client) error {
	input, err := w.ask([]authField{{ID: "username"}, {ID: "password"}})
	if err != nil {
		return err
	}
	challenge, err := client.CreateInstagramWebSession(ctx, input["username"], input["password"])
	if errors.Is(err, instameow.ErrInstagramWebCookieConsentRequired) {
		consent, consentErr := w.ask([]authField{{ID: "cookie_consent", Options: []string{"accept", "cancel"}}})
		if consentErr != nil {
			return consentErr
		}
		if consent["cookie_consent"] != "accept" {
			return safeError("IG_AUTH_ACTION_REQUIRED")
		}
		challenge, err = client.ContinueInstagramWebSessionAfterCookieConsent(ctx, input["username"], input["password"])
	}
	clear(input)
	if err != nil {
		return err
	}
	if challenge != nil {
		if challenge.ChallengeURL != "" {
			return safeError("IG_AUTH_ACTION_REQUIRED")
		}
		if challenge.AuthPlatform {
			if err = w.steps(ctx, client.DoInstagramWebAuthPlatformSteps); err != nil {
				return err
			}
		} else {
			code, err := w.ask([]authField{{ID: "verification_code"}})
			if err != nil {
				return err
			}
			err = client.CompleteInstagramWebSessionTwoFactor(ctx, code["verification_code"])
			clear(code)
			if err != nil {
				return err
			}
		}
	}
	return w.steps(ctx, client.DoInstagramWebAccountManagerSteps)
}
func decimalID(v string) bool {
	if len(v) == 0 || len(v) > 128 || v[0] == '0' {
		return false
	}
	for _, c := range v {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}
func directThread(t *slidetypes.ThreadInfo) (conversation, error) {
	if t == nil || t.IsGroup || (t.ThreadSubtype != slidetypes.ThreadSubtypeDirect && t.ThreadSubtype != slidetypes.ThreadSubtypeDirectBusiness) {
		return conversation{}, safeError("IG_DIRECT_ONLY")
	}
	if t.ID != t.ThreadFBID || !decimalID(t.ThreadFBID) || (t.ThreadID != "" && !decimalID(t.ThreadID)) {
		return conversation{}, safeError("BAD_RESPONSE")
	}
	title := t.ThreadTitle
	if title == "" {
		title = "Instagram DM"
	}
	return conversation{ID: t.ThreadFBID, Title: title, LongID: t.ThreadID}, nil
}
func normalize(m *slidetypes.Message, threadID, ownFBID string) (*message, error) {
	if m == nil {
		return nil, safeError("BAD_RESPONSE")
	}
	// Expiring/view-once content is deliberately not retained.
	if !m.ExpirationTimestampMS.IsZero() || !m.ViewExpirationTimestampMS.IsZero() {
		return nil, nil
	}
	content, ok := m.Content.Content.(*slidetypes.MessageContentText)
	if !ok {
		return nil, nil
	}
	// ID is the canonical GraphQL message identity used by the upstream bridge.
	if m.ID == "" || (m.ThreadFBID != "" && m.ThreadFBID != threadID) || m.SenderFBID <= 0 || m.TimestampMS.UnixMilli() <= 0 {
		return nil, safeError("BAD_RESPONSE")
	}
	direction := "incoming"
	sender := strconv.FormatInt(m.SenderFBID, 10)
	if sender == ownFBID {
		direction = "outgoing"
	}
	result := &message{ID: m.ID, ThreadID: threadID, SenderID: sender, SentAt: m.TimestampMS.UTC().Format(time.RFC3339Nano), Text: content.TextBody, Direction: direction}
	var editedAt time.Time
	for _, edit := range m.SlideEditHistory {
		if edit.TimestampMS.After(editedAt) {
			editedAt = edit.TimestampMS.Time
		}
	}
	if !editedAt.IsZero() {
		result.EditedAt = editedAt.UTC().Format(time.RFC3339Nano)
	}
	return result, nil
}
func safeCode(err error) string {
	var code safeError
	if errors.As(err, &code) {
		return string(code)
	}
	if _, ok := instameow.InstagramWebChallengeURL(err); ok {
		return "IG_AUTH_ACTION_REQUIRED"
	}
	switch {
	case errors.Is(err, httpclient.ErrRateLimited):
		return "RATE_LIMITED"
	case errors.Is(err, httpclient.ErrTokenInvalidated), errors.Is(err, instameow.ErrInstagramWebCredentialsRejected), errors.Is(err, instameow.ErrInstagramWebTwoFactorCodeRejected):
		return "CREDENTIALS_INVALID"
	case errors.Is(err, httpclient.ErrChallengeRequired), errors.Is(err, httpclient.ErrCheckpointRequired), errors.Is(err, httpclient.ErrConsentRequired), errors.Is(err, instameow.ErrInstagramWebCheckpointCAPTCHA), errors.Is(err, instameow.ErrInstagramWebCheckpointUnsupported):
		return "IG_AUTH_ACTION_REQUIRED"
	case errors.Is(err, context.DeadlineExceeded):
		return "IG_REQUEST_TIMEOUT"
	default:
		return "IG_REQUEST_FAILED"
	}
}
func (w *wire) saveSession(client *instameow.Client, accountID, ownFBID string) error {
	return w.emit(map[string]any{"type": "session", "account_id": accountID, "own_fbid": ownFBID,
		"session": session{Cookies: client.GetCookies().GetAll(), WWWClaim: client.GetCookies().IGWWWClaim}})
}
func fetchThread(ctx context.Context, client *instameow.Client, id string) (*slidetypes.ThreadInfo, error) {
	response, err := client.GetThread(ctx, slidetypes.MakeGetThreadInfoRequest(id))
	if err != nil {
		return nil, err
	}
	if response == nil {
		return nil, safeError("BAD_RESPONSE")
	}
	t := response.ThreadInfo.AsIGDirectThread
	conv, err := directThread(t)
	if err != nil {
		return nil, err
	}
	if conv.ID != id {
		return nil, safeError("BAD_RESPONSE")
	}
	return t, nil
}
func readHistory(t *slidetypes.ThreadInfo, ownFBID string, limit int) ([]message, int, int, bool, error) {
	if t.SlideMessages == nil {
		return nil, 0, 0, false, safeError("BAD_RESPONSE")
	}
	messages := []message{}
	excluded := 0
	raw := 0
	for _, edge := range t.SlideMessages.Edges {
		if raw >= limit {
			break
		}
		raw++
		m, err := normalize(edge.Node, t.ThreadFBID, ownFBID)
		if err != nil {
			return nil, 0, 0, false, err
		}
		if m == nil {
			excluded++
			continue
		}
		messages = append(messages, *m)
	}
	page := t.SlideMessages.PageInfo
	limited := page.HasNextPage || page.HasPreviousPage || len(t.SlideMessages.Edges) > limit || raw >= limit
	return messages, raw, excluded, limited, nil
}
func (w *wire) run(ctx context.Context, req request) error {
	switch req.Op {
	case "login", "whoami", "conversations", "history", "send", "watch":
	default:
		return safeError("INVALID_INPUT")
	}
	if req.Limit == 0 {
		req.Limit = 20
	}
	if req.Limit < 1 || req.Limit > 100 || req.Timeout < 0 || req.Timeout > 600 {
		return safeError("INVALID_INPUT")
	}
	if req.Op == "history" || req.Op == "send" || req.Op == "watch" {
		if !decimalID(req.ThreadID) {
			return safeError("INVALID_INPUT")
		}
	}
	if req.Op == "send" && (strings.TrimSpace(req.Text) == "" || len(req.Text) > 4000) {
		return safeError("INVALID_INPUT")
	}
	jar := &cookies.Cookies{Platform: types.Instagram}
	jar.UpdateValues(nil)
	if req.Op != "login" {
		if req.Session == nil || !decimalID(req.AccountID) {
			return safeError("CREDENTIALS_MISSING")
		}
		jar.UpdateValues(req.Session.Cookies)
		jar.IGWWWClaim = req.Session.WWWClaim
		if len(jar.GetMissingCookieNames()) > 0 {
			return safeError("CREDENTIALS_INVALID")
		}
		if jar.Get(cookies.IGCookieDSUserID) != req.AccountID {
			return safeError("ACCOUNT_CHANGED")
		}
	}
	client := instameow.NewClient(instameow.ClientParams{Cookies: jar, Log: zerolog.Nop(), DisableTyping: true, EventHandler: func(context.Context, slidetypes.ClientEvent) error { return nil }})
	defer client.Disconnect()
	if req.Op == "login" {
		if err := w.login(ctx, client); err != nil {
			return err
		}
	}
	user, mailbox, err := client.LoadIndex(ctx)
	if err != nil {
		return err
	}
	if user == nil || mailbox == nil || !decimalID(user.ID) || client.GetOwnFBID() <= 0 {
		return safeError("BAD_RESPONSE")
	}
	if req.AccountID != "" && user.ID != req.AccountID {
		return safeError("ACCOUNT_CHANGED")
	}
	accountID := user.ID
	ownFBID := strconv.FormatInt(client.GetOwnFBID(), 10)
	if err = w.saveSession(client, accountID, ownFBID); err != nil {
		return err
	}
	// Require the parent to persist the session before any operation (especially send).
	var ack struct {
		Saved bool `json:"session_saved"`
	}
	if err = w.read(&ack); err != nil {
		return err
	}
	if !ack.Saved {
		return safeError("IG_SESSION_NOT_SAVED")
	}
	switch req.Op {
	case "login", "whoami":
		return w.emit(map[string]any{"type": "result", "account_id": accountID, "own_fbid": ownFBID})
	case "conversations":
		rows := []conversation{}
		seen := map[string]bool{}
		for _, edge := range mailbox.ThreadsByFolder.Edges {
			conv, e := directThread(edge.Node.AsIGDirectThread)
			if e == safeError("IG_DIRECT_ONLY") {
				continue
			}
			if e != nil {
				return e
			}
			if !seen[conv.ID] && len(rows) < req.Limit {
				seen[conv.ID] = true
				rows = append(rows, conv)
			}
		}
		return w.emit(map[string]any{"type": "result", "conversations": rows, "limited": mailbox.ThreadsByFolder.PageInfo.HasNextPage || len(rows) >= req.Limit})
	}
	t, err := fetchThread(ctx, client, req.ThreadID)
	if err != nil {
		return err
	}
	conv, _ := directThread(t)
	switch req.Op {
	case "history":
		messages, raw, excluded, limited, err := readHistory(t, ownFBID, req.Limit)
		if err != nil {
			return err
		}
		if err = w.saveSession(client, accountID, ownFBID); err != nil {
			return err
		}
		if err = w.read(&ack); err != nil || !ack.Saved {
			return safeError("IG_SESSION_NOT_SAVED")
		}
		return w.emit(map[string]any{"type": "result", "conversation": conv, "messages": messages, "raw_items": raw, "excluded_events": excluded, "history_limited": limited})
	case "send":
		// GetThread has just verified the selected canonical GraphQL thread ID.
		// IGThreadIGID uses ThreadFBID/ID (upstream meta.IGID), not the long ThreadID.
		attribution := "igd_web_chat_tab:in_thread"
		resp, err := client.SendMessage(ctx, &slidetypes.SendTextRequest{IGThreadIGID: &conv.ID, OfflineThreadingID: strconv.FormatInt(methods.GenerateEpochID(), 10), Text: slidetypes.SensitiveString{Value: req.Text}, SendAttribution: &attribution})
		// The vendored SendMessage path is patched to one attempt at HTTP and GraphQL layers.
		if err != nil || resp == nil || resp.Message.ID == "" || resp.Message.TimestampMS.UnixMilli() <= 0 {
			return safeError("IG_SEND_UNKNOWN")
		}
		m := message{ID: resp.Message.ID, ThreadID: conv.ID, SenderID: ownFBID, SentAt: resp.Message.TimestampMS.UTC().Format(time.RFC3339Nano), Text: req.Text, Direction: "outgoing"}
		return w.emit(map[string]any{"type": "result", "message": m, "conversation": conv, "encrypted": false})
	case "watch":
		return w.watch(ctx, client, req, t, accountID, ownFBID)
	}
	return safeError("INVALID_INPUT")
}
func (w *wire) watch(ctx context.Context, client *instameow.Client, req request, t *slidetypes.ThreadInfo, accountID, ownFBID string) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	fail := make(chan error, 1)
	fatal := func(err error) {
		select {
		case fail <- err:
		default:
		}
		cancel()
	}
	client.SetEventHandler(func(_ context.Context, evt slidetypes.ClientEvent) error {
		switch e := evt.(type) {
		case *slidetypes.Connected:
			return w.emit(map[string]any{"type": "status", "code": "connected"})
		case *slidetypes.Disconnected:
			return w.emit(map[string]any{"type": "status", "code": "reconnecting"})
		case *slidetypes.AuthError:
			fatal(safeError("CREDENTIALS_INVALID"))
		case *slidetypes.ResnapshotRequired:
			fatal(safeError("IG_RESYNC_REQUIRED"))
		case *slidetypes.Delta:
			event, ok := e.Data.(*slidetypes.NewMessageEvent)
			if !ok || event.Message == nil {
				return nil
			}
			threadID := e.ThreadIGID
			if threadID == "" {
				threadID = event.Message.ThreadFBID
			}
			if threadID != req.ThreadID {
				return nil
			}
			m, err := normalize(event.Message, req.ThreadID, ownFBID)
			if err != nil {
				fatal(err)
				return err
			}
			if m != nil {
				return w.emit(map[string]any{"type": "message", "source": "realtime", "message": m})
			}
		}
		return nil
	})
	// LoadIndex established the subscription sequence before this bounded history read.
	// No cursor is persisted: only committed messages are durable; restart backfills again.
	if !req.FromNow {
		messages, raw, excluded, limited, err := readHistory(t, ownFBID, req.Limit)
		if err != nil {
			return err
		}
		if err = w.emit(map[string]any{"type": "history", "conversation": conversation{ID: t.ThreadFBID, Title: t.ThreadTitle, LongID: t.ThreadID}, "messages": messages, "raw_items": raw, "excluded_events": excluded, "history_limited": limited}); err != nil {
			return err
		}
		var ack struct {
			Saved bool `json:"history_saved"`
		}
		if err = w.read(&ack); err != nil || !ack.Saved {
			return safeError("IG_PROTOCOL_ERROR")
		}
	}
	stopped := make(chan struct{})
	go func() { client.Connect(ctx); close(stopped) }()
	if req.Timeout > 0 {
		timer := time.NewTimer(time.Duration(req.Timeout) * time.Second)
		defer timer.Stop()
		select {
		case <-ctx.Done():
		case <-timer.C:
		case <-stopped:
			fatal(safeError("IG_REQUEST_FAILED"))
		}
	} else {
		select {
		case <-ctx.Done():
		case <-stopped:
			fatal(safeError("IG_REQUEST_FAILED"))
		}
	}
	cancel()
	select {
	case err := <-fail:
		return err
	default:
	}
	return w.emit(map[string]any{"type": "done"})
}
func main() {
	zerolog.SetGlobalLevel(zerolog.Disabled)
	nop := zerolog.Nop()
	zerolog.DefaultContextLogger = &nop
	// No raw session/message output to an interactive terminal.
	for _, file := range []*os.File{os.Stdin, os.Stdout} {
		info, err := file.Stat()
		if err != nil || info.Mode()&os.ModeNamedPipe == 0 {
			os.Exit(2)
		}
	}
	w := &wire{input: bufio.NewScanner(os.Stdin), output: json.NewEncoder(os.Stdout)}
	w.input.Buffer(make([]byte, 4096), maxFrame)
	defer func() {
		if recover() != nil {
			_ = w.emit(map[string]any{"type": "error", "code": "IG_REQUEST_FAILED"})
		}
	}()
	var req request
	if err := w.read(&req); err != nil {
		_ = w.emit(map[string]any{"type": "error", "code": safeCode(err)})
		return
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
	defer cancel()
	var timeout context.CancelFunc
	if req.Op == "login" {
		ctx, timeout = context.WithTimeout(ctx, 10*time.Minute)
	} else if req.Op != "watch" {
		ctx, timeout = context.WithTimeout(ctx, 70*time.Second)
	}
	if timeout != nil {
		defer timeout()
	}
	if err := w.run(ctx, req); err != nil && !errors.Is(err, io.EOF) {
		_ = w.emit(map[string]any{"type": "error", "code": safeCode(err)})
	}
}
