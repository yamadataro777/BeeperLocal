"""TTY-only secrets and control-character-free terminal rendering."""
from __future__ import annotations
import getpass
import sys
import unicodedata
import warnings
from .errors import AppError


def secret_prompt(prompt: str) -> str:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise AppError("INTERACTIVE_REQUIRED")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            value = getpass.getpass(prompt).strip()
        except (getpass.GetPassWarning, EOFError):
            raise AppError("INTERACTIVE_REQUIRED") from None
    if not value or any(unicodedata.category(c).startswith("C") for c in value):
        raise AppError("INVALID_INPUT")
    return value


def safe_text(value: str, max_length: int = 160) -> str:
    # Strip ESC, OSC, C0/C1, bidi/zero-width format controls, surrogates.
    text = "".join(" " if unicodedata.category(c).startswith("C") or c.isspace() else c for c in str(value))
    text = " ".join(text.split())
    return text if len(text) <= max_length else text[:max_length] + "…"


def preview_line(message, *, preview: bool = False) -> str:
    when = message.sent_at.astimezone().isoformat(timespec="seconds")
    if not preview:
        return f"{when} [{message.provider}] message={message.id[:12]} [本文非表示]"
    body = message.text or (f"[添付 {message.attachment_count}件]" if message.attachment_count else "[本文なし]")
    return f"{when} [{message.provider}] {safe_text(message.conversation_title, 40)} | {safe_text(message.sender_id, 30)}: {safe_text(body)}"
