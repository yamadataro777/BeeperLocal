package twittermeow

import (
	"context"
	"errors"
	"net/url"
	"regexp"
	"strings"
)

// The supervisor has already encrypted these bytes with the verified
// conversation key. No identity or conversation keys enter this transport.
func (c *Client) UploadBeeperLocalCiphertext(ctx context.Context, conversation, uploadID string, ciphertext []byte) (string, error) {
	bad := errors.New("invalid_media_upload")
	if len(ciphertext) < 24 || len(ciphertext) > 4*1024*1024+65536 {
		return "", bad
	}
	initial, err := c.initializeXChatMediaUpload(ctx, conversation, uploadID, len(ciphertext))
	if err != nil {
		return "", err
	}
	value := initial.Data.XChatInitializeMediaUpload
	u, err := url.Parse(value.ResumeUploadURL)
	if err != nil || u.IsAbs() || u.Host != "" || u.Fragment != "" || !strings.HasPrefix(u.Path, "/xchat_media/") || strings.Contains(u.Path, "..") || u.RawQuery == "" || u.Query().Has("partNumber") || len(value.ResumeUploadURL) > 8192 || value.ResumeID == "" || len(value.ResumeID) > 1024 || len(value.MediaHashKey) > 1024 || !regexp.MustCompile(`^[a-zA-Z0-9_-]+$`).MatchString(value.MediaHashKey) {
		return "", bad
	}
	parts, err := c.uploadMediaBytes(ctx, value.ResumeUploadURL, ciphertext)
	if err != nil {
		return "", err
	}
	result, err := c.finalizeXChatMediaUpload(ctx, conversation, uploadID, value.MediaHashKey, value.ResumeID, parts)
	if err != nil {
		return "", err
	}
	kind := strings.ToLower(result.Data.XChatFinalizeMediaUpload.TypeName)
	if kind == "" || strings.Contains(kind, "error") || strings.Contains(kind, "fail") {
		return "", bad
	}
	return value.MediaHashKey, nil
}
