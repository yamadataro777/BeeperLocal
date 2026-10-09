"""Frozen entry point. Runtime verification never reads credentials or local data."""
import sys
from beeperlocal.desktop import main


def verify_runtime():
    import logging
    logging.disable(logging.CRITICAL)
    try:
        from beeperlocal.mcp_server import sdk_app
        import uvicorn
        from beeperlocal.native_keychain import NativeKeychain
        from chat_xdk import Chat
        from beeperlocal.x_worker import run
        from beeperlocal.tls import client_context
        import ssl
        tls = client_context()
        assert tls.check_hostname and tls.verify_mode == ssl.CERT_REQUIRED
        Chat().lock()  # Native crypto loads without credentials or network access.
        NativeKeychain()  # Load native frameworks only; no item access.
        # Construct the packaged HTTP stack without opening a socket or touching Core.
        from types import SimpleNamespace
        app = sdk_app(SimpleNamespace(provider="line"), 28641)
        config = uvicorn.Config(app, loop='asyncio', http='h11', ws='none', lifespan='on', log_config=None)
        config.load()
        print('{"runtimeReady":true,"mcp":true,"xCrypto":true,"systemTLS":true,"version":"0.9.5"}')
        return 0
    except Exception:
        print('{"runtimeReady":false,"error":"RUNTIME_INCOMPLETE"}')
        return 1


def verify_public_tls():
    """A TLS handshake only. No provider API, credentials, local DB or message access."""
    import socket
    from beeperlocal.tls import client_context
    try:
        with socket.create_connection(('slack.com', 443), timeout=15) as connection:
            with client_context().wrap_socket(connection, server_hostname='slack.com') as secured:
                assert secured.getpeercert()
        print('{"tlsVerified":true}')
        return 0
    except Exception:
        print('{"tlsVerified":false,"error":"TLS_VERIFICATION_FAILED"}')
        return 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--release-status']:
        import json
        from beeperlocal.release_status import release_status
        print(json.dumps(release_status()))
        raise SystemExit(0)
    if sys.argv[1:] == ['--verify-public-tls']:
        raise SystemExit(verify_public_tls())
    if sys.argv[1:] == ['--slack-login']:
        from beeperlocal.slack_setup import main as slack_login
        raise SystemExit(slack_login())
    if sys.argv[1:] == ['--verify-slack-login']:
        from beeperlocal.slack_setup import verify_runtime as verify_slack_login
        raise SystemExit(verify_slack_login())
    if sys.argv[1:] == ['--instagram-login']:
        from beeperlocal.instagram_setup import main as instagram_login
        raise SystemExit(instagram_login())
    if sys.argv[1:] == ['--verify-instagram-login']:
        from beeperlocal.instagram_setup import verify_runtime as verify_instagram_login
        raise SystemExit(verify_instagram_login())
    if sys.argv[1:] == ['--x-worker']:
        from beeperlocal.x_worker import main as x_main
        raise SystemExit(x_main())
    if sys.argv[1:] == ['--verify-runtime']:
        raise SystemExit(verify_runtime())
    if sys.argv[1:]:
        raise SystemExit(2)
    raise SystemExit(main())
