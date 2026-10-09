package main

import (
	"context"
	"encoding/base64"
	tw "go.mau.fi/mautrix-twitter/pkg/twittermeow"
	"go.mau.fi/mautrix-twitter/pkg/twittermeow/data/endpoints"
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestEncryptedImageUploadPhasesOnce(t *testing.T) {
	old := tw.MaxHTTPRetries
	tw.MaxHTTPRetries = 0
	defer func() { tw.MaxHTTPRetries = old }()
	for _, failure := range []int{0, 1, 2, 3} {
		c := newClient("")
		count := 0
		cipher := strings.Repeat("encrypted-fixture", 20)
		c.HTTP.Transport = inspectTransport(func(r *http.Request) (*http.Response, error) {
			count++
			if r.GetBody != nil {
				t.Fatal("transport replay enabled")
			}
			body := ""
			status := 200
			switch count {
			case 1:
				if r.URL.String() != endpoints.INITIALIZE_XCHAT_MEDIA_UPLOAD_URL {
					t.Fatal("wrong init target")
				}
				body = `{"data":{"xchat_initialize_media_upload":{"__typename":"XChatInitializeMediaUploadSuccess","resume_upload_url":"/xchat_media/1111-2222/hash?resume=fixture","media_hash_key":"hash","resume_id":"fixture"}}}`
			case 2:
				data, _ := io.ReadAll(r.Body)
				if string(data) != cipher || r.URL.Host != "ton.x.com" || r.URL.Query().Get("partNumber") != "0" {
					t.Fatal("wrong encrypted chunk")
				}
				body = `{}`
			case 3:
				if r.URL.String() != endpoints.FINALIZE_XCHAT_MEDIA_UPLOAD_URL {
					t.Fatal("wrong final target")
				}
				body = `{"data":{"xchat_finalize_media_upload":{"__typename":"XChatFinalizeMediaUploadSuccess"}}}`
			default:
				t.Fatal("replayed write")
			}
			if count == failure {
				status = 500
			}
			return &http.Response{StatusCode: status, Header: http.Header{}, Request: r, Body: io.NopCloser(strings.NewReader(body))}, nil
		})
		b := bridge{c: c, authenticated: true}
		result, err := b.run(context.Background(), request{Op: "upload_image", Conversation: "1111-2222", MessageID: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", Data: base64.StdEncoding.EncodeToString([]byte(cipher))})
		if failure == 0 {
			if err != nil || result.(map[string]any)["media_hash_key"] != "hash" || count != 3 {
				t.Fatal("valid upload did not finish")
			}
		} else if err == nil || count != failure {
			t.Fatal("failure retried or finalized")
		}
	}
}

func TestImageTransportRejectsRepeatsRedirectsAndOutOfOrderChunks(t *testing.T) {
	base := &fakeTransport{status: 200}
	guard := &imageUploadTransport{next: base}
	request := func(address string) error {
		r, _ := http.NewRequest("POST", address, strings.NewReader("ciphertext"))
		response, err := guard.RoundTrip(r)
		if response != nil {
			response.Body.Close()
		}
		return err
	}
	if request(endpoints.INITIALIZE_XCHAT_MEDIA_UPLOAD_URL) != nil {
		t.Fatal("init failed")
	}
	for _, address := range []string{endpoints.INITIALIZE_XCHAT_MEDIA_UPLOAD_URL, "https://evil.test/i/ton/data/xchat_media/x?partNumber=0", "https://ton.x.com/i/ton/data/xchat_media/x?partNumber=1", endpoints.FINALIZE_XCHAT_MEDIA_UPLOAD_URL} {
		if request(address) == nil || base.calls != 1 {
			t.Fatal("unexpected write")
		}
	}
	if request("https://ton.x.com/i/ton/data/xchat_media/x?resume=fixture&partNumber=0") != nil {
		t.Fatal("chunk failed")
	}
	if request("https://ton.x.com/i/ton/data/xchat_media/x?resume=fixture&partNumber=0") == nil {
		t.Fatal("chunk replay")
	}
	if request("https://ton.x.com/i/ton/data/xchat_media/other?resume=fixture&partNumber=1") == nil {
		t.Fatal("target changed")
	}
	if request(endpoints.FINALIZE_XCHAT_MEDIA_UPLOAD_URL) != nil {
		t.Fatal("complete failed")
	}
	if request(endpoints.FINALIZE_XCHAT_MEDIA_UPLOAD_URL) == nil || base.calls != 3 {
		t.Fatal("complete replay")
	}
}
