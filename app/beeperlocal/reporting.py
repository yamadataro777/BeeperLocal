"""Only allowlisted, body-free proof metadata is written to disk."""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from .errors import AppError

REPORT_NAMES = {"last-proof.json", "last-fetch-telegram.json", "last-fetch-slack.json", "last-fetch-matrix.json", "last-fetch-line.json", "last-sync.json"}
ROOT_KEYS = {"schema_version", "application", "generated_at", "mode", "loop_status", "volume_loop_status", "acceptance", "volume_acceptance", "scope", "providers"}
ROW_KEYS = {"provider", "status", "volume_status", "requested_limit", "normalized_unique_messages", "real_messages", "conversations_requested", "conversations_fetched", "raw_items", "excluded_events", "duplicates_removed", "normalization_errors", "history_limited", "oldest", "newest", "error_codes"}


def default_state_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BeeperLocalPoC"
    return Path.home() / ".local" / "state" / "BeeperLocalPoC"


def private_directory(path: Path) -> None:
    for candidate in [path, *path.parents]:
        if candidate.is_symlink():
            raise AppError("UNSAFE_PATH")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise AppError("UNSAFE_PATH")
    path.chmod(0o700)


def save_report(report: dict, name: str = "last-proof.json", directory: Path | None = None) -> Path:
    if name not in REPORT_NAMES or set(report) - ROOT_KEYS:
        raise AppError("INVALID_INPUT")
    if not isinstance(report.get("providers"), list) or any(set(row) - ROW_KEYS for row in report["providers"]):
        raise AppError("INVALID_INPUT")
    directory = directory or default_state_dir()
    private_directory(directory)
    dest = directory / name
    if dest.is_symlink():
        raise AppError("UNSAFE_PATH")
    fd, temporary = tempfile.mkstemp(prefix=".report-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, dest)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return dest


def read_report(directory: Path | None = None) -> dict:
    path = (directory or default_state_dir()) / "last-proof.json"
    if not path.exists():
        raise AppError("NO_REPORT")
    if path.is_symlink():
        raise AppError("UNSAFE_PATH")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) - ROOT_KEYS:
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise AppError("BAD_RESPONSE") from None
