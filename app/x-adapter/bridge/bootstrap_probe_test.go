package main

import (
	"context"
	"github.com/rs/zerolog"
	tw "go.mau.fi/mautrix-twitter/pkg/twittermeow"
	"os"
	"runtime/debug"
	"strings"
	"testing"
	"time"
)

// Explicit opt-in, credential-free probe; excluded from ordinary offline tests.
func TestPublicBootstrap(t *testing.T) {
	if os.Getenv("X_CONNECTOR_PUBLIC_PROBE") != "1" {
		t.Skip("network opt-in required")
	}
	zerolog.SetGlobalLevel(zerolog.Disabled)
	tw.MaxHTTPRetries = 0
	defer func() {
		if recover() != nil {
			for _, line := range strings.Split(string(debug.Stack()), "\n") {
				if strings.Contains(line, ".go:") {
					t.Log(strings.TrimSpace(line))
				}
			}
			t.Error("bootstrap_panic")
		}
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	result, err := tw.NewWebLoginSession(newClient("")).Start(ctx)
	if err != nil {
		t.Log("code=" + safeCode(err))
		return
	}
	t.Log("status=" + string(result.Status))
}
