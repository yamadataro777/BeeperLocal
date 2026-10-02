package cli

import (
	"context"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"strings"
	"testing"

	"github.com/kongesque/line-cli/internal/session"
	"github.com/kongesque/line-cli/pkg/line"
	"github.com/makiuchi-d/gozxing"
	qrdecoder "github.com/makiuchi-d/gozxing/qrcode"
)

func TestDesktopJSONLoginPrivateStreamAndIndependentQRDecode(t *testing.T) {
	a, _, out, diagnostics, calls, locked := qrApp(t, "")
	a.Interactive = false
	if err := a.Run([]string{"login", "--qr", "--json"}); err != nil {
		t.Fatal(err)
	}
	if *calls != 1 || *locked {
		t.Fatal("incorrect dispatch or lock")
	}
	if diagnostics.Len() != 0 {
		t.Fatal("private login wrote diagnostics")
	}
	for _, secret := range []string{syntheticQRURL, "synthetic-access", "synthetic-certificate", "synthetic-export"} {
		if strings.Contains(out.String(), secret) {
			t.Fatal("credential or raw URL leaked")
		}
	}
	var events []map[string]json.RawMessage
	for _, row := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		var event map[string]json.RawMessage
		if err := json.Unmarshal([]byte(row), &event); err != nil {
			t.Fatal(err)
		}
		events = append(events, event)
	}
	if string(events[len(events)-1]["event"]) != `"completed"` {
		t.Fatal("missing saved completion")
	}
	var matrix [][]bool
	if err := json.Unmarshal(events[0]["matrix"], &matrix); err != nil {
		t.Fatal(err)
	}
	const scale = 5
	size := (len(matrix) + 8) * scale
	img := image.NewGray(image.Rect(0, 0, size, size))
	for y := 0; y < size; y++ {
		for x := 0; x < size; x++ {
			xx, yy := x/scale-4, y/scale-4
			shade := uint8(255)
			if xx >= 0 && yy >= 0 && yy < len(matrix) && xx < len(matrix) && matrix[yy][xx] {
				shade = 0
			}
			img.SetGray(x, y, color.Gray{Y: shade})
		}
	}
	bitmap, err := gozxing.NewBinaryBitmapFromImage(img)
	if err != nil {
		t.Fatal(err)
	}
	result, err := qrdecoder.NewQRCodeReader().Decode(bitmap, nil)
	if err != nil || result.GetText() != syntheticQRURL {
		t.Fatal("desktop QR did not decode exactly", err)
	}
}

func TestDesktopLoginReplacementAndCancellation(t *testing.T) {
	for _, force := range []bool{false, true} {
		a, _, out, _, calls, _ := qrApp(t, "")
		a.Interactive = false
		a.Manager.Store = &testStore{state: &session.State{AccessToken: "old", Generation: "old", MID: "old"}}
		args := []string{"login", "--json"}
		if force {
			args = append(args, "--force")
		}
		err := a.Run(args)
		if force {
			if err != nil || *calls != 1 {
				t.Fatal("explicit replacement failed", err)
			}
		} else {
			if err == nil || *calls != 0 || !strings.Contains(out.String(), "LINE_LOGIN_REPLACEMENT_REQUIRED") {
				t.Fatal("silent session replacement")
			}
		}
	}
	a, _, out, _, _, _ := qrApp(t, "")
	a.Interactive = false
	ctx, cancel := context.WithCancel(context.Background())
	a.Context = ctx
	a.LoginQR = func(ctx context.Context, notify func(session.QRLoginEvent) error) (*line.Profile, error) {
		cancel()
		return nil, ctx.Err()
	}
	if err := a.Run([]string{"login", "--json"}); err == nil || strings.Contains(out.String(), `"completed"`) {
		t.Fatal("cancelled login completed")
	}
}

type desktopChatAPI struct{ chatAPI }

func (f *desktopChatAPI) GetAllContactIds() ([]string, error) {
	panic("desktop names must include non-friends")
}
func (f *desktopChatAPI) GetContactsV2(ids []string) (*line.ContactsResponse, error) {
	result, err := f.chatAPI.GetContactsV2(ids)
	if err != nil {
		return nil, err
	}
	for id, c := range result.Contacts {
		c.Contact.PicturePath = "/synthetic-picture"
		result.Contacts[id] = c
	}
	return result, nil
}
func TestDesktopCatalogFiltersThenSortsThenLimitsAndIncludesProfiles(t *testing.T) {
	f := &desktopChatAPI{chatAPI: chatAPI{names: map[string]string{"u-old": "Old", "u-new": "Nonfriend name"}, boxes: []line.MessageBox{
		{ID: "u-old", LastMessages: []line.Message{{CreatedTime: "1000"}}},
		{ID: "c-group", LastMessages: []line.Message{{CreatedTime: "5000"}}},
		{ID: "u-new", LastMessages: []line.Message{{CreatedTime: "2000"}}},
	}}}
	a := chatTestApp(&f.chatAPI)
	a.Manager.NewClient = func(string) session.API { return f }
	if err := a.Run([]string{"chats", "--details", "--direct", "--json", "--limit", "1"}); err != nil {
		t.Fatal(err)
	}
	var rows []Chat
	if err := json.Unmarshal([]byte(a.Out.(fmt.Stringer).String()), &rows); err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 || rows[0].ID != "u-new" || rows[0].UpdatedAt != 2000 || rows[0].Name != "Nonfriend name" || rows[0].PicturePath != "/synthetic-picture" {
		t.Fatal("catalog metadata incorrect")
	}
	if !f.options[0].ActiveOnly || f.options[0].LastMessagesPerMessageBoxCount != 1 || fmt.Sprint(f.batches) != "[1]" {
		t.Fatal("wrong enrichment scope")
	}
}
