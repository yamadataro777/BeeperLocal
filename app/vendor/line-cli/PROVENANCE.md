# Pinned LINE CLI desktop extension

Upstream: https://github.com/kongesque/line-cli
Tag: v0.4.0
Commit: 80d945ba582c0d1a59dbb4054d5c11e567021ab6
Desktop version: v0.4.0-beeperlocal.1
License: MIT, retained in LICENSE and bundled with the app.

This directory contains cmd/, internal/, pkg/, scripts/, go.mod and go.sum from that commit.
No user state, credentials or upstream .git directory is included.

Changes cover desktop presentation and a read-only local status field:

- `chats --details --direct --json` obtains activity timestamps, filters direct chats,
  sorts before applying the limit, and returns effective names and picture paths.
  Legacy `chats --json` remains compatible.
- `login --qr --json` supplies an explicit private NDJSON desktop stream. It renders
  QR matrices locally using the existing encoder and sends ephemeral PINs only
  on the private pipe. The raw QR URL, tokens, keys and profile are not emitted.
  It retains the storage snapshot, replacement check, session lock, QR state
  machine, phone approval and native Keychain save. Replacing an existing session
  requires the desktop user's explicit choice, passed as --force.
- Native `auth status --json` reports `line_validity=invalidated` when the stored
  session is already known to be invalid. It never asserts remote validity.
- Added synthetic regressions including an independent QR decoder.

No changes to provider protocol, generated LTSM code/data, encryption, message
sending, refresh or session persistence. Build from scripts/build-desktop.sh.

Profile CDN evidence: upstream beeper/line pkg/connector/userinfo.go constructs
https://profile.line-scdn.net + Contact.PicturePath. The app restricts downloads
to that HTTPS host, rejects redirects and caches bounded raster images in memory.
