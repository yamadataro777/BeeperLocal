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
        NativeKeychain()  # Load native frameworks only; no item access.
        # Construct the packaged HTTP stack without opening a socket or touching Core.
        app = sdk_app(object(), 28641)
        config = uvicorn.Config(app, loop='asyncio', http='h11', ws='none', lifespan='on', log_config=None)
        config.load()
        print('{"runtimeReady":true,"mcp":true,"version":"0.8.1"}')
        return 0
    except Exception:
        print('{"runtimeReady":false,"error":"RUNTIME_INCOMPLETE"}')
        return 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--verify-runtime']:
        raise SystemExit(verify_runtime())
    if sys.argv[1:]:
        raise SystemExit(2)
    raise SystemExit(main())
