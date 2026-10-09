package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"go.mau.fi/mautrix-meta/pkg/messagix/table"
	"go.mau.fi/whatsmeow/proto/waAdv"
	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waConsumerApplication"
	"go.mau.fi/whatsmeow/proto/waMsgApplication"
	"go.mau.fi/whatsmeow/store/sqlstore"
	wa "go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"
)

func TestDeviceSnapshotRetainsIdentityAndKeysInMemory(t *testing.T) {
	db, err := openMemory("")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	c := sqlstore.NewWithDB(db, "sqlite3", nil)
	ctx := context.Background()
	if err = c.Upgrade(ctx); err != nil {
		t.Fatal(err)
	}
	device := c.NewDevice()
	id := wa.JID{User: "123456", Device: 7, Server: wa.MessengerServer}
	device.ID = &id
	device.Account = &waAdv.ADVSignedDeviceIdentity{Details: []byte{}, AccountSignature: make([]byte, 64), AccountSignatureKey: make([]byte, 32), DeviceSignature: make([]byte, 64)}
	if err = device.Save(ctx); err != nil {
		t.Fatal(err)
	}
	key := append([]byte{}, device.IdentityKey.Priv[:]...)
	data, err := snapshot(db)
	if err != nil {
		t.Fatal(err)
	}
	restored, err := openMemory(base64.StdEncoding.EncodeToString(data))
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	store := sqlstore.NewWithDB(restored, "sqlite3", nil)
	devices, err := store.GetAllDevices(ctx)
	if err != nil || len(devices) != 1 || *devices[0].ID != id || !bytes.Equal(devices[0].IdentityKey.Priv[:], key) {
		t.Fatal("device identity changed")
	}
	var seq int
	var name, file string
	if err = restored.QueryRow("PRAGMA database_list").Scan(&seq, &name, &file); err != nil || file != "" {
		t.Fatal("device DB must remain in RAM")
	}
}

func TestCorruptSnapshotRejected(t *testing.T) {
	for _, state := range []string{"invalid!", base64.StdEncoding.EncodeToString([]byte("not sqlite"))} {
		if db, err := openMemory(state); err == nil {
			db.Close()
			t.Fatal("accepted damaged snapshot")
		}
	}
}

func TestCheckpointRequiresPositivePersistenceAck(t *testing.T) {
	for _, input := range []string{"", "{\"ok\":false}\n", "invalid\n", "{\"ok\":true}\n"} {
		var output bytes.Buffer
		w := &wire{in: bufio.NewScanner(strings.NewReader(input)), out: json.NewEncoder(&output)}
		err := w.checkpoint(savedState{Version: 1}, nil, nil)
		if (err == nil) != strings.Contains(input, "true") {
			t.Fatal("incorrect ACK gate")
		}
		if !bytes.Contains(output.Bytes(), []byte(`"kind":"checkpoint"`)) {
			t.Fatal("checkpoint absent")
		}
	}
}

func TestOversizedCheckpointDoesNotWrite(t *testing.T) {
	var output bytes.Buffer
	w := &wire{out: json.NewEncoder(&output)}
	if w.checkpoint(savedState{Version: 1, DeviceDB: strings.Repeat("x", maxIPC)}, nil, nil) == nil || output.Len() != 0 {
		t.Fatal("unbounded IPC")
	}
}

func TestUnknownRegistrationStopsBeforeNetwork(t *testing.T) {
	if run(nil, request{Op: "watch", State: savedState{Version: 1, RegistrationPending: true}}) != "registration_result_unknown" {
		t.Fatal("registration retried")
	}
}

func TestNoSendOperation(t *testing.T) {
	if run(nil, request{Op: "send", State: savedState{Version: 1}}) != "invalid_request" {
		t.Fatal("send accepted")
	}
}

func TestSendCommandsDoNotConsumePersistenceACK(t *testing.T) {
	input := `{"op":"send","request_id":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","conversation":"222@msgr","text":"fixture"}` + "\n" + `{"ok":true}` + "\n"
	w := &wire{in: bufio.NewScanner(strings.NewReader(input)), acks: make(chan bool, 1), commands: make(chan command, 1), closed: make(chan struct{})}
	w.readCommands()
	cmd := <-w.commands
	if !validSend(cmd) || !<-w.acks {
		t.Fatal("command and ACK crossed")
	}
	if textPayload(cmd.Text).GetPayload().GetContent().GetMessageText().GetText() != "fixture" {
		t.Fatal("text changed")
	}
	for _, bad := range []command{{Op: "send", RequestID: cmd.RequestID, Conversation: "222@g.us", Text: "fixture"}, {Op: "send", RequestID: cmd.RequestID, Conversation: cmd.Conversation, Text: strings.Repeat("x", 4001)}} {
		if validSend(bad) {
			t.Fatal("invalid send accepted")
		}
	}
}

func TestCatalogUsesExplicitHybridMapping(t *testing.T) {
	tbl := &table.LSTable{
		LSVerifyHybridThreadExists: []*table.LSVerifyHybridThreadExists{{ThreadKey: 111, ThreadJID: 222, ThreadType: table.ENCRYPTED_OVER_WA_ONE_TO_ONE}},
		LSDeleteThenInsertThread: []*table.LSDeleteThenInsertThread{
			{ThreadKey: 111, ThreadName: "fixture title", ThreadType: table.ENCRYPTED_OVER_WA_ONE_TO_ONE},
			{ThreadKey: 333, ThreadName: "unmapped fixture", ThreadType: table.ONE_TO_ONE},
		},
	}
	rows := catalog(tbl)
	if len(rows) != 1 || rows[0].ID != "222@msgr" {
		t.Fatal("thread identity was guessed")
	}
	tbl.LSDeleteThenInsertThread[0].IsDisappearingMode = true
	if len(catalog(tbl)) != 0 {
		t.Fatal("disappearing thread retained")
	}
}

func fixtureText() *events.FBMessage {
	return &events.FBMessage{
		Info:    wa.MessageInfo{MessageSource: wa.MessageSource{Chat: wa.NewJID("222", wa.MessengerServer), Sender: wa.NewJID("222", wa.MessengerServer)}, ID: "fixture-message", Timestamp: time.Unix(1790910000, 0)},
		Message: &waConsumerApplication.ConsumerApplication{Payload: &waConsumerApplication.ConsumerApplication_Payload{Payload: &waConsumerApplication.ConsumerApplication_Payload_Content{Content: &waConsumerApplication.ConsumerApplication_Content{Content: &waConsumerApplication.ConsumerApplication_Content_MessageText{MessageText: &waCommon.MessageText{Text: proto.String("fixture text")}}}}}},
	}
}

func TestTextDirectionAndEphemeralExclusion(t *testing.T) {
	ev := fixtureText()
	rows := normalText(ev, "123")
	if len(rows) != 1 || rows[0].Conversation != "222@msgr" || rows[0].Direction != "incoming" || rows[0].Provider != "messenger" {
		t.Fatal("incorrect text scope")
	}
	ev.Info.IsFromMe = true
	if normalText(ev, "123")[0].Direction != "outgoing" {
		t.Fatal("outgoing echo mislabeled")
	}
	ev.Info.IsGroup = true
	if len(normalText(ev, "123")) != 0 {
		t.Fatal("group retained")
	}
	ev.Info.IsGroup = false
	ev.FBApplication = &waMsgApplication.MessageApplication{Metadata: &waMsgApplication.MessageApplication_Metadata{Ephemeral: &waMsgApplication.MessageApplication_Metadata_ChatEphemeralSetting{ChatEphemeralSetting: &waMsgApplication.MessageApplication_EphemeralSetting{EphemeralExpiration: proto.Uint32(60)}}}}
	if len(normalText(ev, "123")) != 0 {
		t.Fatal("disappearing content retained")
	}
}

func TestAuthenticatedSenderRevokeOnly(t *testing.T) {
	ev := fixtureText()
	key := &waCommon.MessageKey{ID: proto.String("fixture-message"), FromMe: proto.Bool(true)}
	ev.Message = &waConsumerApplication.ConsumerApplication{Payload: &waConsumerApplication.ConsumerApplication_Payload{Payload: &waConsumerApplication.ConsumerApplication_Payload_ApplicationData{ApplicationData: &waConsumerApplication.ConsumerApplication_ApplicationData{ApplicationContent: &waConsumerApplication.ConsumerApplication_ApplicationData_Revoke{Revoke: &waConsumerApplication.ConsumerApplication_RevokeMessage{Key: key}}}}}}
	rows := normalDeletion(ev, "123")
	if len(rows) != 1 || rows[0].ID != "fixture-message" || rows[0].Conversation != "222@msgr" || rows[0].Sender != "222@msgr" {
		t.Fatal("revoke scope changed")
	}
	key.FromMe = proto.Bool(false)
	if len(normalDeletion(ev, "123")) != 0 {
		t.Fatal("admin revoke accepted")
	}
	key.FromMe = proto.Bool(true)
	ev.Info.Sender = wa.NewJID("333", wa.MessengerServer)
	if len(normalDeletion(ev, "123")) != 0 {
		t.Fatal("unrelated sender accepted")
	}
}
