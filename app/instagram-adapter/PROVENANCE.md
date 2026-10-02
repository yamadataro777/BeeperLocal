# Instagram adapter provenance

The locally validated upstream is `go.mau.fi/mautrix-meta` at commit `e012f9f83ee0abd332b6160f57ecd07014c2d445`, copied from `/Users/haruotsuchiya/BeeperLocal_Instagram_PoC/meta` on 2026-09-30. That source checkout was clean when copied. No credentials, databases, compiled PoC executables, or Git metadata were copied.

The `meta/pkg` source tree, go.mod, go.sum, README, LICENSE and LICENSE.exceptions are retained. The original repository remains unchanged. The upstream license and exceptions are available alongside the source. This is an independent development build, not a new distribution policy or commercial-permission conclusion.

Local additions: `meta/cmd/beeperlocal-ig/main.go` and `main_test.go`.

Local modifications:

- `meta/pkg/instameow/graphql.go`: text send disables GraphQL reload retry.
- `meta/pkg/messagix/httpclient/graphql.go`: `IGDirectTextSendMutation` uses exactly one HTTP attempt without redirect following. Read operations keep their existing behavior.

The dependency versions are the existing upstream go.mod/go.sum; no guessed or floating SDK version was installed. Built with Go 1.27.1 on macOS arm64.
