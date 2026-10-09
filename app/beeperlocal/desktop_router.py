"""Provider-scoped GUI routing with independent request lanes and MCP permissions."""
import asyncio
from .desktop import DesktopCore
from .desktop_instagram import InstagramDesktop
from .desktop_slack import SlackDesktop
from .desktop_x import XDesktop
from .desktop_messenger import MessengerDesktop
from .errors import AppError


class DesktopRouter:
    def __init__(self, *, emit=None, line_factory=DesktopCore, instagram_factory=InstagramDesktop,
                 slack_factory=SlackDesktop, x_factory=XDesktop, messenger_factory=MessengerDesktop):
        self.emit = emit or (lambda event: None)
        self.factories = {"line": line_factory, "instagram": instagram_factory, "slack": slack_factory, "x": x_factory, "messenger": messenger_factory}
        self.cores = {}
        self.dispatch_locks = {provider: asyncio.Lock() for provider in self.factories}

    async def dispatch(self, request):
        if not isinstance(request, dict):
            raise AppError("INVALID_INPUT")
        if request == {"op": "prepare_update"}:
            for core in self.cores.values():
                async with core.operation_lock:
                    await core.cancel_login()
                    await core._stop_mcp()
                    await core.clear_media()
                    await core.stop_watch()
                    core.connection = 'offline'
                    core._notify('status', **core._status())
            return {'ready': True}
        provider = request.get("provider", "line")
        if not isinstance(provider, str) or provider not in self.factories:
            raise AppError("INVALID_INPUT")
        request = dict(request)
        if 'interactive' in request and request.get('op') != 'connect':
            raise AppError('INVALID_INPUT')
        interactive = request.pop('interactive', False)
        if type(interactive) is not bool:
            raise AppError('INVALID_INPUT')
        if provider not in self.cores:
            self.cores[provider] = self.factories[provider](
                emit=lambda event: self.emit({**event, "provider": provider}))
        # Serialize GUI commands within one provider, without making another
        # service wait for a network connection or history recovery.
        async with self.dispatch_locks[provider]:
            if interactive or request.get('op') in {'line_login_start', 'x_login_start', 'messenger_login_start', 'slack_login_start'}:
                from .credentials import retry_desktop_keychain
                retry_desktop_keychain(provider)
            result = await self.cores[provider].dispatch({k: v for k, v in request.items() if k != "provider"})
        return result

    async def close(self):
        for core in self.cores.values():
            await core.close()
