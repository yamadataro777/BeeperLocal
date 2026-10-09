// SPDX-License-Identifier: AGPL-3.0-or-later
package twittermeow

import (
	"context"
	"errors"
	"go.mau.fi/mautrix-twitter/pkg/twittermeow/data/endpoints"
	"io"
	"net/http"
	"net/url"
	"regexp"
)

// Return bounded ciphertext only. The supervisor verifies key signatures and
// the secretstream final frame; no raw key is passed into this transport.
func (c *Client) DownloadBeeperLocalCiphertext(ctx context.Context, conversation, hash string) ([]byte, error) {
	if !regexp.MustCompile(`^(g[0-9]{1,128}|[0-9]{1,128}[:-][0-9]{1,128})$`).MatchString(conversation) || (len(hash) > 1024 || !regexp.MustCompile(`^[a-zA-Z0-9_-]+$`).MatchString(hash)) {
		return nil, errors.New("invalid_request")
	}
	headers := c.buildHeaders(HeaderOpts{WithNonAuthBearer: true, WithXCsrfToken: true, WithCookies: true, Origin: endpoints.BASE_URL, Referer: endpoints.BASE_URL + "/"})
	previous := c.HTTP
	local := *previous
	local.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	c.HTTP = &local
	defer func() { c.HTTP = previous }()
	response, _, err := c.MakeRequestFull(ctx, MakeRequestParams{URL: endpoints.TON_UPLOAD_BASE_URL + "/i/ton/data/xchat_media/" + url.PathEscape(conversation) + "/" + hash, Method: http.MethodGet, Headers: headers, DontReadBody: true})
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, errors.New("media_unavailable")
	}
	const limit = 4*1024*1024 + 65536
	data, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if err != nil || len(data) > limit {
		return nil, errors.New("media_unavailable")
	}
	return data, nil
}
