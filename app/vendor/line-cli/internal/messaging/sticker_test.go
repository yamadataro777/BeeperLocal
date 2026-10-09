package messaging

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/kongesque/line-cli/pkg/line"
)

func TestDecodeStickerExportsOnlyNumericStickerID(t *testing.T) {
	client := &Client{}
	for _, id := range []string{"52002734", "", "../private", "https://evil.test/", "123?token=private", strings.Repeat("9", 21)} {
		msg := &line.Message{ID: "123", ContentType: 7, ContentMetadata: map[string]string{"STKID": id, "STKPKGID": "PRIVATE_PACKAGE", "DOWNLOAD_URL": "PRIVATE_URL"}}
		decoded := client.Decode("u-peer", msg)
		if decoded.Status != "attachment" || decoded.ContentType != 7 || decoded.Text != "" {
			t.Fatal("missing sticker placeholder")
		}
		if id == "52002734" && decoded.StickerID != id {
			t.Fatal("sticker ID lost")
		}
		if id != "52002734" && decoded.StickerID != "" {
			t.Fatal("untrusted sticker ID exposed")
		}
		data, err := json.Marshal(decoded)
		if err != nil || strings.Contains(string(data), "PRIVATE_") {
			t.Fatal("private metadata exposed")
		}
	}
}
