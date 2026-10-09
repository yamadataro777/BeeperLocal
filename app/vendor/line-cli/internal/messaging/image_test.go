package messaging

import (
	"bytes"
	"image"
	"image/png"
	"testing"
)

func TestImageTypeAndEncryptedRoundTrip(t *testing.T) {
	var out bytes.Buffer
	if err := png.Encode(&out, image.NewNRGBA(image.Rect(0, 0, 12, 8))); err != nil {
		t.Fatal(err)
	}
	attachment := Attachment{Name: "image.png", Data: out.Bytes(), Image: true}
	if attachment.Validate() != nil || attachment.contentType() != 1 || attachmentSID(attachment.contentType()) != "emi" {
		t.Fatal("image transport type incorrect")
	}
	ciphertext, key, err := encryptFile(attachment.Data)
	if err != nil || bytes.Equal(ciphertext, attachment.Data) {
		t.Fatal("image encryption failed")
	}
	restored, err := decryptFile(ciphertext, key)
	if err != nil || !bytes.Equal(restored, attachment.Data) {
		t.Fatal("image did not round trip")
	}
	ciphertext[0] ^= 1
	if _, err = decryptFile(ciphertext, key); err == nil {
		t.Fatal("tampered image accepted")
	}
	attachment.Data = []byte("not an image")
	if attachment.Validate() == nil {
		t.Fatal("invalid image accepted")
	}
	if (Attachment{}).contentType() != 14 {
		t.Fatal("existing file type changed")
	}
}
