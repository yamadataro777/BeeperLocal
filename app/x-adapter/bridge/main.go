// SPDX-License-Identifier: AGPL-3.0-or-later
// Private, bounded NDJSON protocol. Never run this helper with terminal stdin.
package main

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/rs/zerolog"
	tw "go.mau.fi/mautrix-twitter/pkg/twittermeow"
	"go.mau.fi/mautrix-twitter/pkg/twittermeow/cookies"
	twcrypto "go.mau.fi/mautrix-twitter/pkg/twittermeow/crypto"
	"go.mau.fi/mautrix-twitter/pkg/twittermeow/data/endpoints"
	"go.mau.fi/mautrix-twitter/pkg/twittermeow/data/payload"
	"go.mau.fi/mautrix-twitter/pkg/twittermeow/data/response"
)

const maxFrame = 16 * 1024 * 1024

// X requires explicit initial history bounds. Matches the upstream backfill
// caller's xchatBackfillMaxInt; omitting either variable is rejected by X.
const latestHistoryBound = "9223372036854775807"

var invalid = errors.New("invalid_request")

type request struct {
	Op           string               `json:"op"`
	Value        string               `json:"value"`
	Field        string               `json:"field"`
	Cookies      string               `json:"cookies"`
	Session      *tw.CachedSession    `json:"session"`
	User         string               `json:"user"`
	Users        []string             `json:"users"`
	Cursor       *payload.XChatCursor `json:"cursor"`
	Conversation string               `json:"conversation"`
	Before       string               `json:"before"`
	KeyVersion   string               `json:"key_version"`
	Events       []string             `json:"events"`
	MessageID    string               `json:"message_id"`
	Token        string               `json:"token"`
	Content      string               `json:"content"`
	Signature    string               `json:"signature"`
	MediaHash    string               `json:"media_hash"`
	Data         string               `json:"data"`
}
type bridge struct {
	c             *tw.Client
	login         *tw.WebLoginSession
	status        tw.WebLoginStatus
	authenticated bool
}

func newClient(cookie string) *tw.Client {
	return tw.NewClient(cookies.NewCookiesFromString(cookie), nil, zerolog.Nop())
}
func safeCode(err error) string {
	if errors.Is(err, tw.ErrJetfuelCastleTokenRequired) {
		return "interactive_challenge_required"
	}
	if tw.IsAuthError(err) {
		return "reauth_required"
	}
	if errors.Is(err, invalid) {
		return "invalid_request"
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return "network_timeout"
	}
	return "x_request_failed"
}
func (b *bridge) loginResult(r *tw.WebLoginResult, err error) (any, error) {
	if err != nil {
		return nil, err
	}
	if r == nil {
		return nil, invalid
	}
	b.status = r.Status
	methods := []map[string]any{}
	for _, m := range r.AuthMethods {
		if m.Supported {
			methods = append(methods, map[string]any{"id": m.ID, "kind": m.Kind})
		}
	}
	challenge := "text"
	if r.Challenge != nil {
		if r.Challenge.IsTwoFactor {
			challenge = "code"
		}
		if r.Challenge.InputKind == tw.WebLoginChallengeInputKindPhoneNumber {
			challenge = "phone_number"
		}
	}
	return map[string]any{"status": r.Status, "methods": methods, "challenge": challenge}, nil
}
func (b *bridge) profile(ctx context.Context, expected string) (any, error) {
	p, err := b.c.LoadMessagesPage(ctx)
	if err != nil {
		return nil, err
	}
	if p.ID == "" || (expected != "" && p.ID != expected) {
		return nil, invalid
	}
	b.authenticated = true
	return map[string]any{"user": p.ID, "name": p.Name, "screen_name": p.ScreenName}, nil
}

// The transport is used only during a single send. No redirect or second POST
// can repeat the operation, even if a future library release adds retries.
type oneShot struct {
	next http.RoundTripper
	used bool
}

func (s *oneShot) RoundTrip(r *http.Request) (*http.Response, error) {
	if s.used || r.Method != http.MethodPost || r.URL.Scheme != "https" || r.URL.String() != endpoints.SEND_MESSAGE_MUTATION_URL {
		return nil, invalid
	}
	s.used = true
	// No GetBody prevents transport-level automatic replay after a stale connection.
	r.GetBody = nil
	return s.next.RoundTrip(r)
}
func (b *bridge) send(ctx context.Context, q request) (any, error) {
	if q.Conversation == "" || q.MessageID == "" || q.Content == "" || q.Signature == "" {
		return nil, invalid
	}
	transport, redirect := b.c.HTTP.Transport, b.c.HTTP.CheckRedirect
	b.c.HTTP.Transport = &oneShot{next: transport}
	b.c.HTTP.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	defer func() { b.c.HTTP.Transport = transport; b.c.HTTP.CheckRedirect = redirect }()
	r, err := b.c.SendRawEncryptedMessage(ctx, q.Conversation, q.MessageID, q.Token, q.Content, q.Signature)
	if err != nil {
		return nil, err
	}
	if len(r.Errors) > 0 || r.Data.XChatSendCreateMessageEvent.EncodedMessageEvent == "" {
		return nil, invalid
	}
	e, err := tw.DecodeSendMessageMutationMessageEvent(r.Data.XChatSendCreateMessageEvent.EncodedMessageEvent)
	if err != nil {
		return nil, err
	}
	raw, err := payload.Encode(e)
	if err != nil {
		return nil, err
	}
	return map[string]any{"event": base64.StdEncoding.EncodeToString(raw)}, nil
}
func inbox(p response.XChatInboxPage) (any, error) {
	if p.ErrorCode != "" || len(p.Errors) > 0 {
		return nil, invalid
	}
	return p, nil
}
func (b *bridge) run(ctx context.Context, q request) (any, error) {
	switch q.Op {
	case "web_login":
		b.authenticated = false
		if q.Cookies == "" {
			return nil, invalid
		}
		b.c = newClient(q.Cookies)
		return b.profile(ctx, q.User)
	case "hello":
		return map[string]any{"protocol": 1, "transport": "twittermeow", "crypto": "external-verified"}, nil
	case "login_start":
		b.c = newClient("")
		b.authenticated = false
		b.login = tw.NewWebLoginSession(b.c)
		return b.loginResult(b.login.Start(ctx))
	case "login_answer":
		if b.login == nil {
			return nil, invalid
		}
		switch {
		case b.status == tw.WebLoginStatusNeedsIdentifier && q.Field == "identifier":
			return b.loginResult(b.login.SubmitIdentifier(ctx, q.Value))
		case b.status == tw.WebLoginStatusNeedsPassword && q.Field == "password":
			return b.loginResult(b.login.SubmitPassword(ctx, q.Value))
		case b.status == tw.WebLoginStatusNeedsText && q.Field == "text":
			return b.loginResult(b.login.SubmitText(ctx, q.Value))
		case b.status == tw.WebLoginStatusNeedsAuthMethod && q.Field == "method":
			return b.loginResult(b.login.SubmitAuthMethod(ctx, q.Value))
		default:
			return nil, invalid
		}
	case "restore":
		b.authenticated = false
		if q.Cookies == "" || q.User == "" {
			return nil, invalid
		}
		b.c = newClient(q.Cookies)
		if q.Session != nil {
			b.c.SetSession(q.Session)
		}
		return b.profile(ctx, q.User)
	case "profile":
		if b.c == nil || b.status != tw.WebLoginStatusComplete {
			return nil, invalid
		}
		return b.profile(ctx, "")
	}
	if !b.authenticated && q.Op != "inspect" {
		return nil, invalid
	}
	switch q.Op {
	case "session":
		return map[string]any{"cookies": b.c.GetCookieString(), "session": b.c.GetSession(), "user": b.c.GetCurrentUserID()}, nil
	case "keys":
		if len(q.Users) == 0 || len(q.Users) > 100 {
			return nil, invalid
		}
		return b.c.GetPublicKeys(ctx, q.Users)
	case "inbox":
		if q.Cursor == nil {
			r, e := b.c.GetInitialXChatPage(ctx, payload.NewInitialXChatPageQueryVariables(""))
			if e != nil {
				return nil, e
			}
			if len(r.Errors) > 0 {
				return nil, invalid
			}
			return inbox(r.Data.GetInboxPage)
		}
		r, e := b.c.GetInboxPageRequest(ctx, payload.NewInboxPageRequestQueryVariables(q.Cursor))
		if e != nil {
			return nil, e
		}
		if len(r.Errors) > 0 {
			return nil, invalid
		}
		return inbox(r.Data.GetInboxPage)
	case "conversation":
		if q.Conversation == "" {
			return nil, invalid
		}
		if q.Before == "" {
			q.Before = latestHistoryBound
		}
		if q.KeyVersion == "" {
			q.KeyVersion = latestHistoryBound
		}
		r, e := b.c.GetConversationPage(ctx, payload.NewGetConversationPageQueryVariables(q.Conversation, q.Before, q.KeyVersion, nil))
		if e != nil {
			return nil, e
		}
		if len(r.Errors) > 0 {
			return nil, invalid
		}
		return r.Data.GetConversationPage, nil
	case "detail":
		if q.Conversation == "" {
			return nil, invalid
		}
		r, e := b.c.GetConversationData(ctx, payload.NewInboxPageConversationDataQueryVariables(q.Conversation, true))
		if e != nil {
			return nil, e
		}
		if len(r.Errors) > 0 {
			return nil, invalid
		}
		return r.Data.GetInboxPageConversationData.Data, nil
	case "inspect":
		if len(q.Events) > 1000 {
			return nil, invalid
		}
		out := []map[string]any{}
		for _, s := range q.Events {
			raw, e := base64.StdEncoding.DecodeString(s)
			if e != nil {
				return nil, invalid
			}
			var evt payload.MessageEvent
			if payload.Decode(raw, &evt) != nil {
				return nil, invalid
			}
			kind := "other"
			encrypted := false
			if evt.Detail != nil {
				if evt.Detail.MessageCreateEvent != nil {
					kind = "message"
					encrypted = evt.Detail.MessageCreateEvent.ConversationKeyVersion != nil
				} else if evt.Detail.ConversationKeyChangeEvent != nil {
					kind = "key_change"
				}
			}
			shape := map[string]any{"conversation": evt.ConversationId, "sequence": evt.SequenceId, "message_id": evt.MessageId, "token": evt.ConversationToken,
				"kind": kind, "encrypted": encrypted, "signature_present": evt.MessageEventSignature != nil}
			if kind == "message" && !encrypted && evt.MessageEventSignature == nil {
				shape["legacy"] = legacyText(&evt)
			}
			out = append(out, shape)
		}
		return out, nil
	case "media":
		if !regexp.MustCompile(`^(g[0-9]{1,128}|[0-9]{1,128}[:-][0-9]{1,128})$`).MatchString(q.Conversation) || (len(q.MediaHash) > 1024 || !regexp.MustCompile(`^[a-zA-Z0-9_-]+$`).MatchString(q.MediaHash)) {
			return nil, invalid
		}
		data, err := b.c.DownloadBeeperLocalCiphertext(ctx, q.Conversation, q.MediaHash)
		if err != nil {
			return nil, err
		}
		return map[string]any{"data": base64.StdEncoding.EncodeToString(data)}, nil
	case "send":
		return b.send(ctx, q)
	case "upload_image":
		return b.uploadImage(ctx, q)
	case "listen":
		// Socket frames are wake-up hints only. Authenticated history is fetched and
		// verified by the supervisor before storage; no cursor is advanced here.
		listenCtx, cancel := context.WithTimeout(ctx, 40*time.Second)
		defer cancel()
		ready := make(chan bool, 1)
		socket := newClient(b.c.GetCookieString())
		session := *b.c.GetSession()
		socket.SetSession(&session)
		socket.SetCurrentUserID(b.c.GetCurrentUserID())
		socket.RawXChatHandler = func(_ context.Context, m *payload.Message) error {
			if m.MessageEvent != nil || m.BatchedMessageEvents != nil || m.MessageInstruction != nil {
				select {
				case ready <- true:
				default:
				}
			}
			return nil
		}
		defer socket.Disconnect()
		if err := socket.StartXChatWebsocket(listenCtx); err != nil {
			return nil, err
		}
		select {
		case <-ready:
			return map[string]any{"changed": true}, nil
		case <-listenCtx.Done():
			return map[string]any{"changed": false}, nil
		}
	default:
		return nil, invalid
	}
}

// Legacy text has server-authenticated provenance, never an X Chat signature.
// The caller keeps every signed/encrypted envelope on the crypto path.
func legacyText(evt *payload.MessageEvent) (result map[string]any) {
	result = map[string]any{"status": "unsupported"}
	defer func() {
		if recover() != nil {
			result = map[string]any{"status": "unsupported"}
		}
	}()
	if evt.Detail == nil || evt.Detail.MessageCreateEvent == nil || evt.MessageEventSignature != nil {
		return
	}
	create := evt.Detail.MessageCreateEvent
	if create.ConversationKeyVersion != nil || create.TtlMsec != nil || create.IsUserMetadata() {
		return
	}
	// Decode the wrapper first: the upstream direct decoder can panic on
	// nested structs before reaching its wrapper fallback.
	entry, err := twcrypto.ParseMessageEntryContentsBytes(create.Contents)
	var contents *payload.MessageContents
	if err == nil {
		contents = entry.Message
	} else {
		contents, err = twcrypto.ParseMessageContentsBytes(create.Contents)
	}
	if err != nil || contents == nil || contents.MessageText == nil || *contents.MessageText == "" {
		return
	}
	return map[string]any{"status": "text", "text": *contents.MessageText,
		"sender_id": evt.SenderId, "created_at_msec": evt.CreatedAtMsec}
}

func main() {
	// Refuse accidental terminal use: protocol responses contain private material.
	info, err := os.Stdin.Stat()
	if err != nil || info.Mode()&os.ModeCharDevice != 0 {
		os.Exit(2)
	}
	zerolog.SetGlobalLevel(zerolog.Disabled)
	tw.MaxHTTPRetries = 0
	defer func() {
		if recover() != nil {
			os.Exit(3)
		}
	}()
	b := bridge{}
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 65536), maxFrame)
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	for scanner.Scan() {
		var q request
		decoder := json.NewDecoder(strings.NewReader(scanner.Text()))
		decoder.DisallowUnknownFields()
		var result any
		var err error
		if decoder.Decode(&q) != nil {
			err = invalid
		} else {
			var extra any
			if decoder.Decode(&extra) != io.EOF {
				err = invalid
			} else {
				ctx, cancel := context.WithTimeout(context.Background(), 55*time.Second)
				result, err = b.run(ctx, q)
				cancel()
			}
		}
		reply := map[string]any{"ok": err == nil}
		if err != nil {
			reply["error"] = safeCode(err)
		} else {
			reply["result"] = result
		}
		raw, e := json.Marshal(reply)
		if e != nil || len(raw) >= maxFrame {
			raw = []byte(`{"ok":false,"error":"response_too_large"}`)
		}
		if _, e = out.Write(append(raw, '\n')); e != nil {
			return
		}
		if out.Flush() != nil {
			return
		}
	}
}
