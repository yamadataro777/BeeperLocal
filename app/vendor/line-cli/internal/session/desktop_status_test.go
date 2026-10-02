//go:build !linux

package session

import "testing"

func TestDesktopNativeStatusReportsOnlyKnownInvalidation(t *testing.T) {
	for _, invalid := range []bool{false, true} {
		status, err := nativeStorageStatus(&memoryStore{state: &State{AccessToken: "synthetic", MID: "synthetic", Invalidated: invalid}}, false, func() error { t.Fatal("status wrote storage"); return nil })
		if err != nil {
			t.Fatal(err)
		}
		if invalid && status.LINEValidity != "invalidated" {
			t.Fatal("known invalidation not reported")
		}
		if !invalid && status.LINEValidity != "not_checked" {
			t.Fatal("local presence asserted remote validity")
		}
	}
}
