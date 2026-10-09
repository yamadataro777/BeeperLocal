package main

import (
	"context"
	"encoding/base64"
	"net/http"
	"regexp"
	"strconv"
	"strings"

	"go.mau.fi/mautrix-twitter/pkg/twittermeow/data/endpoints"
)

// Exact endpoints and once-per-part writes, even if an SDK later adds retries.
type imageUploadTransport struct {
	next   http.RoundTripper
	phase  int
	part   int
	prefix string
}

func (t *imageUploadTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	if r.Method != http.MethodPost || r.URL.Scheme != "https" || r.URL.User != nil || r.URL.Fragment != "" {
		return nil, invalid
	}
	address := r.URL.String()
	switch {
	case address == endpoints.INITIALIZE_XCHAT_MEDIA_UPLOAD_URL && t.phase == 0:
		t.phase = 1
	case address == endpoints.FINALIZE_XCHAT_MEDIA_UPLOAD_URL && t.phase == 1 && t.part > 0:
		t.phase = 2
	case r.URL.Host == "ton.x.com" && strings.HasPrefix(r.URL.Path, "/i/ton/data/xchat_media/") && t.phase == 1 && t.part < 9:
		q := r.URL.Query()
		if len(q["partNumber"]) != 1 || q.Get("partNumber") != strconv.Itoa(t.part) {
			return nil, invalid
		}
		q.Del("partNumber")
		prefix := r.URL.Path + "?" + q.Encode()
		if t.part == 0 {
			t.prefix = prefix
		} else if t.prefix != prefix {
			return nil, invalid
		}
		t.part++
	default:
		return nil, invalid
	}
	r.GetBody = nil
	return t.next.RoundTrip(r)
}

func (b *bridge) uploadImage(ctx context.Context, q request) (any, error) {
	if !regexp.MustCompile(`^(g[0-9]{1,128}|[0-9]{1,128}[:-][0-9]{1,128})$`).MatchString(q.Conversation) || !regexp.MustCompile(`^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$`).MatchString(q.MessageID) || len(q.Data) > (4*1024*1024+65536+2)/3*4 {
		return nil, invalid
	}
	ciphertext, err := base64.StdEncoding.Strict().DecodeString(q.Data)
	if err != nil {
		return nil, invalid
	}
	transport, redirect := b.c.HTTP.Transport, b.c.HTTP.CheckRedirect
	b.c.HTTP.Transport = &imageUploadTransport{next: transport}
	b.c.HTTP.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	defer func() { b.c.HTTP.Transport = transport; b.c.HTTP.CheckRedirect = redirect }()
	hash, err := b.c.UploadBeeperLocalCiphertext(ctx, q.Conversation, q.MessageID, ciphertext)
	if err != nil {
		return nil, err
	}
	return map[string]any{"media_hash_key": hash}, nil
}
