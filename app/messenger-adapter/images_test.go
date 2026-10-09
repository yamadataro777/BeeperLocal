package main

import (
	"bytes"
	"encoding/base64"
	"go.mau.fi/whatsmeow"
	"image"
	"image/png"
	"io"
	"net/http"
	"strings"
	"testing"
)

func imageFixture() *imageInput {
	var data bytes.Buffer
	_ = png.Encode(&data, image.NewNRGBA(image.Rect(0, 0, 12, 8)))
	return &imageInput{Data: base64.StdEncoding.EncodeToString(data.Bytes()), Mime: "image/png", Width: 12, Height: 8}
}
func TestImageEnvelopeCarriesAuthenticatedMediaAndMobileThumbnailDimensions(t *testing.T) {
	v := imageFixture()
	data, err := v.bytes()
	if err != nil {
		t.Fatal("valid image rejected")
	}
	uploaded := whatsmeow.UploadResponse{DirectPath: "/fixture", ObjectID: "fixture-object", MediaKey: make([]byte, 32), FileSHA256: make([]byte, 32), FileEncSHA256: make([]byte, 32)}
	payload, err := imagePayload(v, len(data), uploaded)
	if err != nil {
		t.Fatal("image payload rejected")
	}
	media, err := payload.GetPayload().GetContent().GetImageMessage().Decode()
	if err != nil || media.GetAncillary().GetWidth() != 12 || media.GetAncillary().GetHeight() != 8 {
		t.Fatal("image dimensions lost")
	}
	ancillary := media.GetIntegral().GetTransport().GetAncillary()
	if ancillary.GetThumbnail().GetThumbnailWidth() == 0 || ancillary.GetThumbnail().GetThumbnailHeight() == 0 || ancillary.GetObjectID() == "" || ancillary.GetMimetype() != "image/png" {
		t.Fatal("mobile clients cannot display attachment")
	}
	for _, changed := range []*imageInput{nil, {Data: v.Data, Mime: "image/jpeg", Width: 12, Height: 8}, {Data: v.Data, Mime: v.Mime, Width: 99, Height: 8}} {
		if _, err := changed.bytes(); err == nil {
			t.Fatal("invalid image accepted")
		}
	}
	cmd := command{Op: "send_image", RequestID: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", Conversation: "222@msgr", Image: v}
	if !validSend(cmd) {
		t.Fatal("image command rejected")
	}
	cmd.Text = "unexpected caption"
	if validSend(cmd) {
		t.Fatal("mixed ambiguous payload accepted")
	}
}

type imageHTTPFunc func(*http.Request) (*http.Response, error)

func (f imageHTTPFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestImageUploadRejectsRedirectAndSecondWrite(t *testing.T) {
	calls := 0
	guard := &imageTransport{next: imageHTTPFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.GetBody != nil {
			t.Fatal("replay enabled")
		}
		return &http.Response{StatusCode: 307, Header: http.Header{"Location": []string{"https://evil.invalid/private"}}, Body: io.NopCloser(strings.NewReader("")), Request: r}, nil
	})}
	client := &http.Client{Transport: guard, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, _ := http.NewRequest("POST", "https://rupload.facebook.com/wa-msgr/mms/image/fixture", strings.NewReader("ciphertext"))
	response, err := client.Do(req)
	if err != nil {
		t.Fatal("redirect should be surfaced")
	}
	response.Body.Close()
	if calls != 1 {
		t.Fatal("redirect followed")
	}
	if _, err = guard.RoundTrip(req); err == nil || calls != 1 {
		t.Fatal("second write allowed")
	}
}
