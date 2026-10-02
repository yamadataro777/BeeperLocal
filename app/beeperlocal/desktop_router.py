"""Provider-scoped GUI routing with independent LINE and Slack MCP permissions."""
from .desktop import DesktopCore
from .desktop_instagram import InstagramDesktop
from .desktop_slack import SlackDesktop
from .errors import AppError


class DesktopRouter:
    def __init__(self, *, emit=None, line_factory=DesktopCore, instagram_factory=InstagramDesktop,
                 slack_factory=SlackDesktop):
        self.emit = emit or (lambda event: None)
        self.factories = {"line": line_factory, "instagram": instagram_factory, "slack": slack_factory}
        self.cores = {}

    async def dispatch(self, request):
        if not isinstance(request, dict):
            raise AppError("INVALID_INPUT")
        provider = request.get("provider", "line")
        if not isinstance(provider, str) or provider not in self.factories:
            raise AppError("INVALID_INPUT")
        if provider not in self.cores:
            self.cores[provider] = self.factories[provider](
                emit=lambda event: self.emit({**event, "provider": provider}))
        result = await self.cores[provider].dispatch({k: v for k, v in request.items() if k != "provider"})
        return result

    async def close(self):
        for core in self.cores.values():
            await core.close()
