package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"net/http"
	"strings"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waConsumerApplication"
	"go.mau.fi/whatsmeow/proto/waMediaTransport"
	"google.golang.org/protobuf/proto"
)

type imageInput struct {
	Data   string `json:"data"`
	Mime   string `json:"mime"`
	Width  int    `json:"width"`
	Height int    `json:"height"`
}

func (v *imageInput) bytes() ([]byte, error) {
	bad := errors.New("invalid_image")
	if v == nil || len(v.Data) > (4*1024*1024+2)/3*4 {
		return nil, bad
	}
	data, err := base64.StdEncoding.Strict().DecodeString(v.Data)
	if err != nil || len(data) == 0 || len(data) > 4*1024*1024 {
		return nil, bad
	}
	cfg, format, err := image.DecodeConfig(bytes.NewReader(data))
	if err != nil || (format != "png" && format != "jpeg") || v.Mime != "image/"+format || cfg.Width != v.Width || cfg.Height != v.Height || cfg.Width <= 0 || cfg.Height <= 0 || cfg.Width > 16384 || cfg.Height > 16384 || cfg.Width*cfg.Height > 25000000 {
		return nil, bad
	}
	return data, nil
}

// One HTTP upload per user action. SDK/network redirects and retries cannot
// replay encrypted bytes or carry upload authentication to a different host.
type imageTransport struct {
	next http.RoundTripper
	used bool
}

func (t *imageTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	if t.used || r.Method != http.MethodPost || r.URL.Scheme != "https" || r.URL.Host != "rupload.facebook.com" || r.URL.User != nil || !strings.HasPrefix(r.URL.Path, "/wa-msgr/mms/image/") {
		return nil, errors.New("invalid_image_upload")
	}
	t.used = true
	r.GetBody = nil
	return t.next.RoundTrip(r)
}

func uploadImage(ctx context.Context, client *whatsmeow.Client, v *imageInput) (*waConsumerApplication.ConsumerApplication, error) {
	data, err := v.bytes()
	if err != nil {
		return nil, err
	}
	client.SetMediaHTTPClient(&http.Client{Transport: &imageTransport{next: http.DefaultTransport}, Timeout: 30 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }})
	uploaded, err := client.Upload(ctx, data, whatsmeow.MediaImage)
	if err != nil {
		return nil, err
	}
	return imagePayload(v, len(data), uploaded)
}

func imagePayload(v *imageInput, length int, uploaded whatsmeow.UploadResponse) (*waConsumerApplication.ConsumerApplication, error) {
	if uploaded.DirectPath == "" || uploaded.ObjectID == "" || len(uploaded.MediaKey) != 32 || len(uploaded.FileSHA256) != 32 || len(uploaded.FileEncSHA256) != 32 {
		return nil, errors.New("invalid_upload_ack")
	}
	w, h := v.Width, v.Height
	if w > 400 || h > 400 {
		if w >= h {
			h = max(1, h*400/w)
			w = 400
		} else {
			w = max(1, w*400/h)
			h = 400
		}
	}
	transport := &waMediaTransport.WAMediaTransport{
		Integral: &waMediaTransport.WAMediaTransport_Integral{FileSHA256: uploaded.FileSHA256, MediaKey: uploaded.MediaKey, FileEncSHA256: uploaded.FileEncSHA256,
			DirectPath: &uploaded.DirectPath, MediaKeyTimestamp: proto.Int64(time.Now().Unix())},
		Ancillary: &waMediaTransport.WAMediaTransport_Ancillary{FileLength: proto.Uint64(uint64(length)), Mimetype: &v.Mime, ObjectID: &uploaded.ObjectID,
			Thumbnail: &waMediaTransport.WAMediaTransport_Ancillary_Thumbnail{ThumbnailWidth: proto.Uint32(uint32(w)), ThumbnailHeight: proto.Uint32(uint32(h))}},
	}
	img := &waConsumerApplication.ConsumerApplication_ImageMessage{}
	err := img.Set(&waMediaTransport.ImageTransport{Integral: &waMediaTransport.ImageTransport_Integral{Transport: transport},
		Ancillary: &waMediaTransport.ImageTransport_Ancillary{Width: proto.Uint32(uint32(v.Width)), Height: proto.Uint32(uint32(v.Height))}})
	if err != nil {
		return nil, err
	}
	return &waConsumerApplication.ConsumerApplication{Payload: &waConsumerApplication.ConsumerApplication_Payload{
		Payload: &waConsumerApplication.ConsumerApplication_Payload_Content{Content: &waConsumerApplication.ConsumerApplication_Content{
			Content: &waConsumerApplication.ConsumerApplication_Content_ImageMessage{ImageMessage: img}}}}}, nil
}
