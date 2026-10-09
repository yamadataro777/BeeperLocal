"""Common provider registration with explicit optional capabilities."""
from importlib import import_module
from ..errors import AppError

PROVIDERS = {
    "x": ("XConnector", frozenset({"fetch", "list_conversations", "send_text", "watch"})),
    "instagram": ("InstagramConnector", frozenset({"fetch", "list_conversations", "send_text", "watch"})),
    "matrix": ("MatrixConnector", frozenset({"fetch", "list_conversations"})),
    "slack": ("SlackConnector", frozenset({"fetch", "list_conversations", "fetch_thread", "send_text"})),
    "telegram": ("TelegramConnector", frozenset({"fetch", "list_conversations"})),
    "line": ("LineConnector", frozenset({"fetch", "list_conversations", "send_text", "watch"})),
}


def require_capability(provider, operation):
    if provider not in PROVIDERS or operation not in PROVIDERS[provider][1]:
        raise AppError("CONNECTOR_CAPABILITY_UNSUPPORTED")


def create_connector(provider, store, *, max_wait=240, notice=None):
    if provider not in PROVIDERS:
        raise AppError("INVALID_INPUT")
    cls = getattr(import_module("." + provider, __package__), PROVIDERS[provider][0])
    options = {"max_wait": max_wait, "notice": notice} if provider == "slack" else {}
    return cls(store, **options)
