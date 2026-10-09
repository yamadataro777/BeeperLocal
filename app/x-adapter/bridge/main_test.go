package main

import (
	"context"
	"encoding/json"
	"errors"
	tw "go.mau.fi/mautrix-twitter/pkg/twittermeow"
	"go.mau.fi/mautrix-twitter/pkg/twittermeow/data/endpoints"
	"go.mau.fi/mautrix-twitter/pkg/twittermeow/data/types"
	"io"
	"net/http"
	"strings"
	"testing"
)

type inspectTransport func(*http.Request) (*http.Response, error)

func (f inspectTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestHistoryWireHasInitialBoundsAndPreservesPagination(t *testing.T) {
	for _, bounds := range [][2]string{{"", ""}, {"12345", "67890"}} {
		c := newClient("")
		calls := 0
		c.HTTP.Transport = inspectTransport(func(r *http.Request) (*http.Response, error) {
			calls++
			if r.Method != "GET" {
				t.Fatal("history must be read-only")
			}
			var variables map[string]any
			if json.Unmarshal([]byte(r.URL.Query().Get("variables")), &variables) != nil {
				t.Fatal("missing GraphQL variables")
			}
			sequence, key := bounds[0], bounds[1]
			if sequence == "" {
				sequence = latestHistoryBound
			}
			if key == "" {
				key = latestHistoryBound
			}
			if variables["min_local_sequence_id"] != sequence || variables["min_conversation_key_version"] != key {
				t.Fatal("history bounds missing or overwritten")
			}
			return &http.Response{StatusCode: 200, Header: http.Header{}, Request: r, Body: io.NopCloser(strings.NewReader(`{"data":{"get_conversation_page":{"encoded_message_events":[],"has_more":false}}}`))}, nil
		})
		b := bridge{c: c, authenticated: true}
		if _, err := b.run(context.Background(), request{Op: "conversation", Conversation: "1111-2222", Before: bounds[0], KeyVersion: bounds[1]}); err != nil {
			t.Fatal("history request failed")
		}
		if calls != 1 {
			t.Fatal("history retried")
		}
	}
}

type fakeTransport struct {
	calls  int
	status int
}

func (f *fakeTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	f.calls++
	return &http.Response{StatusCode: f.status, Header: http.Header{"Location": []string{"https://x.com/replay"}}, Body: io.NopCloser(strings.NewReader("{}")), Request: r}, nil
}
func TestSendRedirectNeverReplays(t *testing.T) {
	for _, status := range []int{301, 302, 303, 307, 308, 500} {
		base := &fakeTransport{status: status}
		guard := &oneShot{next: base}
		client := &http.Client{Transport: guard, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
		req, _ := http.NewRequest("POST", endpoints.SEND_MESSAGE_MUTATION_URL, strings.NewReader("private"))
		resp, err := client.Do(req)
		if err != nil {
			t.Fatal("unexpected error")
		}
		resp.Body.Close()
		if base.calls != 1 {
			t.Fatal("replayed request")
		}
		if req.GetBody != nil {
			t.Fatal("automatic transport replay remains enabled")
		}
		if _, err = guard.RoundTrip(req); err == nil || base.calls != 1 {
			t.Fatal("second dispatch allowed")
		}
	}
}
func TestSendRejectsUnexpectedDestination(t *testing.T) {
	for _, url := range []string{"http://x.com/send", "https://example.com/send"} {
		base := &fakeTransport{status: 200}
		guard := &oneShot{next: base}
		req, _ := http.NewRequest("POST", url, nil)
		if _, err := guard.RoundTrip(req); err == nil || base.calls != 0 {
			t.Fatal("unexpected endpoint allowed")
		}
	}
}
func TestUnauthenticatedCannotSendOrRead(t *testing.T) {
	b := bridge{}
	for _, op := range []string{"send", "keys", "inbox", "conversation", "session", "listen", "web_login"} {
		if _, err := b.run(context.Background(), request{Op: op}); err == nil {
			t.Fatal("unauthenticated operation allowed")
		}
	}
}
func TestFixedErrorsDoNotLeak(t *testing.T) {
	if safeCode(io.ErrUnexpectedEOF) != "x_request_failed" {
		t.Fatal("unexpected code")
	}
	if safeCode(invalid) != "invalid_request" {
		t.Fatal("unexpected code")
	}
}

func TestClientCanStartWithoutPersistentCryptoStore(t *testing.T) {
	c := newClient("")
	if c.GetSession() == nil {
		t.Fatal("missing session")
	}
}

func TestBootstrapRedirectPreservedWithRetriesDisabled(t *testing.T) {
	old := tw.MaxHTTPRetries
	tw.MaxHTTPRetries = 0
	defer func() { tw.MaxHTTPRetries = old }()
	c := newClient("")
	base := &fakeTransport{status: 307}
	c.HTTP.Transport = base
	c.HTTP.CheckRedirect = func(*http.Request, []*http.Request) error { return tw.ErrRedirectAttempted }
	resp, _, err := c.MakeRequest(context.Background(), "https://x.com/bootstrap", "GET", http.Header{}, nil, types.ContentTypeNone)
	if !errors.Is(err, tw.ErrRedirectAttempted) || resp == nil || base.calls != 1 {
		t.Fatal("redirect response lost or retried")
	}
}

func TestCiphertextFetchUsesFixedHostAndRejectsRedirectOrLargeBody(t *testing.T) {
	for _, status := range []int{200, 302} {
		c := newClient("")
		count := 0
		c.HTTP.Transport = inspectTransport(func(r *http.Request) (*http.Response, error) {
			count++
			if r.URL.Scheme != "https" || r.URL.Host != "ton.x.com" || r.Method != "GET" || !strings.Contains(r.URL.Path, "/xchat_media/g123/fixturehash") {
				t.Fatal("media endpoint changed")
			}
			return &http.Response{StatusCode: status, Header: http.Header{"Location": []string{"https://evil.test/private"}}, Request: r, Body: io.NopCloser(strings.NewReader("fixture ciphertext"))}, nil
		})
		data, err := c.DownloadBeeperLocalCiphertext(context.Background(), "g123", "fixturehash")
		if count != 1 || (status == 200 && (err != nil || len(data) == 0)) || (status == 302 && err == nil) {
			t.Fatal("media redirect/response guard failed")
		}
		for _, bad := range []string{"../private", "x?token=secret", "https://evil.test"} {
			if _, err := c.DownloadBeeperLocalCiphertext(context.Background(), "g123", bad); err == nil || count != 1 {
				t.Fatal("untrusted media path accepted")
			}
		}
	}
	c := newClient("")
	c.HTTP.Transport = inspectTransport(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: http.Header{}, Request: r, Body: io.NopCloser(strings.NewReader(strings.Repeat("x", 4*1024*1024+65537)))}, nil
	})
	if _, err := c.DownloadBeeperLocalCiphertext(context.Background(), "111:222", "fixturehash"); err == nil {
		t.Fatal("oversized ciphertext accepted")
	}
}
