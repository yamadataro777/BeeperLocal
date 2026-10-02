package cli

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/kongesque/line-cli/internal/session"
	qrcode "github.com/yeqown/go-qrcode/v2"
)

// Private desktop pipe only. QR matrices/PINs are ephemeral and never written to disk.
// The existing storage snapshot, session lock and phone approval remain authoritative.
func (a *App) loginQRJSON(options loginOptions) (err error) {
	enc := json.NewEncoder(a.Out)
	code := "LINE_LOGIN_FAILED"
	defer func() {
		if err != nil {
			var outcome *session.LoginError
			if errors.As(err, &outcome) && (outcome.Dispatched || outcome.Approved) {
				code = "LINE_LOGIN_UNKNOWN"
			}
			_ = enc.Encode(map[string]any{"event": "failed", "code": code})
			err = errors.New(code)
		}
	}()
	if err = qrDebugCheck(); err != nil {
		return err
	}
	if err = a.prepareLogin(); err != nil {
		return err
	}
	// A pipe cannot answer replacement prompts. Only the explicit desktop choice passes --force.
	interactive := a.Interactive
	a.Interactive = false
	keep, checkErr := a.confirmLoginReplacement(options.force)
	a.Interactive = interactive
	if checkErr != nil || keep {
		if errors.Is(checkErr, errSavedSessionConfirmation) || keep {
			code = "LINE_LOGIN_REPLACEMENT_REQUIRED"
		}
		if checkErr != nil {
			return checkErr
		}
		return errors.New(code)
	}
	unlock, err := a.lock()
	if err != nil {
		return err
	}
	defer unlock()
	if err = a.Manager.CheckLogin(a.loginContext(), a.loginSnapshot); err != nil {
		return err
	}
	ctx, cancel := context.WithCancel(a.loginContext())
	defer cancel()
	login := a.LoginQR
	if login == nil {
		login = a.Manager.LoginQR
	}
	profile, err := login(ctx, func(event session.QRLoginEvent) error {
		data := map[string]any{"event": event.Kind, "attempt": event.Attempt}
		switch event.Kind {
		case session.QRLoginCode:
			qr, e := qrcode.NewWith(event.URL, qrcode.WithEncodingMode(qrcode.EncModeByte), qrcode.WithErrorCorrectionLevel(qrcode.ErrorCorrectionMedium))
			if e != nil {
				return errors.New("QR encoding failed")
			}
			matrix := new(qrMatrixWriter)
			if e = qr.Save(matrix); e != nil {
				return errors.New("QR rendering failed")
			}
			data["matrix"] = matrix.bitmap
			data["expiresIn"] = int(event.ExpiresIn.Seconds())
		case session.QRLoginPIN:
			data["pin"] = event.PIN
		case session.QRLoginExpired, session.QRLoginScanned, session.QRLoginPhoneAccepted, session.QRLoginApproved:
		default:
			return errors.New("invalid login event")
		}
		return enc.Encode(data)
	})
	if err != nil {
		return err
	}
	if profile == nil {
		return errors.New("no completed profile")
	}
	return enc.Encode(map[string]any{"event": "completed"})
}
