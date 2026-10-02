package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/rs/zerolog"
	"go.mau.fi/mautrix-meta/pkg/instameow"
	"go.mau.fi/mautrix-meta/pkg/instameow/slidetypes"
	"go.mau.fi/mautrix-meta/pkg/messagix/cookies"
	"go.mau.fi/mautrix-meta/pkg/messagix/types"
	"go.mau.fi/util/jsontime"
)

func fixtureMessage() *slidetypes.Message {
	return &slidetypes.Message{ID: "mid.GRAPHQL", MessageID: "different-legacy-id", ThreadFBID: "123", SenderFBID: 77,
		TimestampMS: jsontime.UnixMilliString{Time: time.UnixMilli(1790726400000)},
		Content:     slidetypes.MessageContentWrapper{Content: &slidetypes.MessageContentText{TextBody: "PRIVATE_FIXTURE_TEXT"}}}
}
func TestNormalizeUsesCanonicalIDAndDirection(t *testing.T) {
	m, err := normalize(fixtureMessage(), "123", "77")
	if err != nil || m.ID != "mid.GRAPHQL" || m.Direction != "outgoing" || m.Text != "PRIVATE_FIXTURE_TEXT" {
		t.Fatal("normalization failed")
	}
	if _, err = normalize(fixtureMessage(), "456", "77"); err == nil {
		t.Fatal("cross-thread message accepted")
	}
}
func TestMissingInnerThreadBindsOnlyToVerifiedContainer(t *testing.T) {
	raw := fixtureMessage()
	raw.ThreadFBID = ""
	m, err := normalize(raw, "123", "77")
	if err != nil || m.ThreadID != "123" {
		t.Fatal("verified thread context was not used")
	}
}
func TestExcludeExpiringAndNonText(t *testing.T) {
	raw := fixtureMessage()
	raw.ExpirationTimestampMS = raw.TimestampMS
	if m, err := normalize(raw, "123", "77"); err != nil || m != nil {
		t.Fatal("expiring message retained")
	}
	raw = fixtureMessage()
	raw.Content.Content = &slidetypes.MessageContentImage{}
	if m, err := normalize(raw, "123", "77"); err != nil || m != nil {
		t.Fatal("non-text message retained")
	}
}
func TestDirectConversationIsValidated(t *testing.T) {
	thread := &slidetypes.ThreadInfo{ID: "123", ThreadFBID: "123", ThreadID: "999888777", ThreadSubtype: slidetypes.ThreadSubtypeDirect}
	conv, err := directThread(thread)
	if err != nil || conv.ID != "123" || conv.LongID != "999888777" {
		t.Fatal("canonical thread mapping failed")
	}
	thread.IsGroup = true
	if _, err = directThread(thread); err != safeError("IG_DIRECT_ONLY") {
		t.Fatal("group accepted")
	}
	thread.IsGroup = false
	thread.ID = "456"
	if _, err = directThread(thread); err == nil {
		t.Fatal("mismatched graph ID accepted")
	}
}
func TestBoundedHistoryCountsAndLimits(t *testing.T) {
	thread := &slidetypes.ThreadInfo{ThreadFBID: "123", SlideMessages: &slidetypes.SlideMessages{
		Edges:    []slidetypes.Node[*slidetypes.Message]{{Node: fixtureMessage()}, {Node: fixtureMessage()}},
		PageInfo: slidetypes.PageInfo{HasNextPage: true}}}
	messages, raw, excluded, limited, err := readHistory(thread, "77", 1)
	if err != nil || len(messages) != 1 || raw != 1 || excluded != 0 || !limited {
		t.Fatal("history bounds incorrect")
	}
}
func TestPrivateProtocolInvalidRequest(t *testing.T) {
	w := &wire{input: bufio.NewScanner(strings.NewReader("")), output: json.NewEncoder(io.Discard)}
	if err := w.run(context.Background(), request{Op: "unknown"}); err != safeError("INVALID_INPUT") {
		t.Fatal("invalid operation accepted")
	}
	if err := w.run(context.Background(), request{Op: "send", ThreadID: "123", Text: "hello"}); err != safeError("CREDENTIALS_MISSING") {
		t.Fatal("missing credentials accepted")
	}
}
func TestSafeErrorDoesNotExposeResponse(t *testing.T) {
	if code := safeCode(errors.New("PRIVATE_TOKEN_CANARY response text")); code != "IG_REQUEST_FAILED" {
		t.Fatal("raw error escaped")
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestSendNeverRetriesHTTPErrorRedirectOrReload(t *testing.T) {
	for _, scenario := range []string{"server_error", "redirect", "reload", "network_error", "success"} {
		t.Run(scenario, func(t *testing.T) {
			jar := &cookies.Cookies{Platform: types.Instagram}
			jar.UpdateValues(nil)
			client := instameow.NewClient(instameow.ClientParams{Cookies: jar, Log: zerolog.Nop()})
			calls := 0
			client.GetHTTP().SetTransportOverride(roundTripFunc(func(req *http.Request) (*http.Response, error) {
				calls++
				if calls > 1 {
					t.Fatal("send request retried")
				}
				if err := req.ParseForm(); err != nil {
					t.Fatal("bad form")
				}
				if req.Form.Get("fb_api_req_friendly_name") != "IGDirectTextSendMutation" {
					t.Fatal("unexpected request")
				}
				status := 200
				body := `{"error":1357004,"errorSummary":"reload"}`
				header := http.Header{}
				switch scenario {
				case "server_error":
					status = 500
				case "redirect":
					status = 307
					header.Set("Location", "https://www.instagram.com/redirect")
				case "network_error":
					return nil, errors.New("connection reset")
				case "success":
					body = `{"data":{"xig_direct_text_send_with_slide_messaging_response":{"id":"mid.GRAPHQL","message_id":"legacy","timestamp_ms":"1790726400000"}}}`
				}
				return &http.Response{StatusCode: status, Header: header, Body: io.NopCloser(bytes.NewBufferString(body)), Request: req}, nil
			}))
			threadID := "123"
			response, err := client.SendMessage(context.Background(), &slidetypes.SendTextRequest{IGThreadIGID: &threadID, Text: slidetypes.SensitiveString{Value: "fixture"}})
			if calls != 1 {
				t.Fatal("incorrect attempt count")
			}
			if scenario == "success" && (err != nil || response == nil || response.Message.ID != "mid.GRAPHQL") {
				t.Fatal("send acknowledgement lost")
			}
		})
	}
}
