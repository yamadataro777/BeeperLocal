# Messenger adapter provenance

The dedicated Messenger receive helper uses the bundled `instagram-adapter/meta` messagix Facebook/E2EE implementation. It does not switch the Instagram CLI's platform.

- Upstream: https://github.com/mautrix/meta
- Pinned source: `e012f9f83ee0abd332b6160f57ecd07014c2d445` (same bundled source as Instagram).
- License: AGPL-3.0-or-later. See the bundled `INSTAGRAM-LICENSE.txt` and `INSTAGRAM-LICENSE.exceptions`. Exceptions granted to other entities do not apply to BeeperLocal.
- Local adapter, memory snapshot and IPC changes: `app/messenger-adapter/`, derived from `workstreams/messenger-verification/bridge/`.
- Native login: `app/messenger-adapter/native-login/main.swift`, copied and adapted from the dedicated verification login. Fresh nonpersistent WebKit store, private pipes only.
- Dependencies: `app/messenger-adapter/go.mod` and `go.sum`; pinned local replace references `../instagram-adapter/meta`.

This development integration does not resolve commercial distribution, source-offer scope or provider authorization requirements. No send implementation is included.
