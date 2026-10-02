"""Private GUI onboarding and bounded in-memory profile images. No auth data in logs/DB."""
import asyncio
import base64
from collections import OrderedDict
from contextlib import aclosing, suppress
from hashlib import sha256
import re

from .connectors.line import attach_session
from .errors import AppError


def picture_version(path):
    return sha256(path.encode()).hexdigest() if valid_picture_path(path) else None


def valid_picture_path(path):
    return isinstance(path, str) and bool(re.fullmatch(r"/[A-Za-z0-9_./-]{1,1024}", path)) and ".." not in path and not path.startswith("//")


async def download_avatar(path):
    if not valid_picture_path(path):
        return None
    import httpx2
    async with httpx2.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", "https://profile.line-scdn.net" + path) as response:
            if response.status_code != 200:
                return None
            mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                return None
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 512 * 1024: return None
            value = bytes(data)
            valid = ((mime == "image/jpeg" and value.startswith(b"\xff\xd8\xff")) or
                     (mime == "image/png" and value.startswith(b"\x89PNG\r\n\x1a\n")) or
                     (mime == "image/gif" and value[:6] in {b"GIF87a", b"GIF89a"}) or
                     (mime == "image/webp" and value.startswith(b"RIFF") and value[8:12] == b"WEBP"))
            return "data:" + mime + ";base64," + base64.b64encode(value).decode() if valid else None


class DesktopProfiles:
    def initialize_profiles(self):
        self.login_task = None
        self.login_state = {"stage": "idle"}
        self.avatar_cache = OrderedDict()
        self.avatar_tasks = {}
        self.avatar_slots = asyncio.Semaphore(4)
        self.avatar_generation = 0
        self.avatar_fetcher = download_avatar

    def login_active(self):
        return self.login_task is not None and not self.login_task.done()

    def require_no_login(self):
        if self.login_active(): raise AppError("LINE_LOGIN_IN_PROGRESS")

    def set_login_state(self, **state):
        self.login_state = state  # Replace, so expired QR/PIN data cannot survive a transition.
        self._notify("line_login_changed")  # Secrets are only in the private status response.

    async def start_login(self, replace):
        if type(replace) is not bool: raise AppError("INVALID_INPUT")
        self.require_no_login()
        self.require_storage()
        async with self.operation_lock:
            self._save_settings(mcpEnabled=False)
            await self._stop_mcp()
            await self.stop_watch()
            await self.clear_avatars()
            self.connection = "offline"
            self.error_code = None
            cli = self.connector_factory(self.credentials).cli
            self.set_login_state(stage="starting")
            self.login_task = asyncio.create_task(self._run_login(cli, replace))
        self._notify("status", **self._status())
        return self.login_state

    async def _run_login(self, cli, replace):
        try:
            completed = False
            async with asyncio.timeout(600):
                async with aclosing(cli.login_events(replace=replace)) as events:
                    async for event in events:
                        kind = event.get("event")
                        state = {"stage": kind}
                        if kind == "code":
                            matrix = event.get("matrix")
                            if (not isinstance(matrix, list) or not 21 <= len(matrix) <= 177 or len(matrix) % 4 != 1
                                or any(not isinstance(row, list) or len(row) != len(matrix) or any(type(x) is not bool for x in row) for row in matrix)):
                                raise AppError("LINE_LOGIN_FAILED")
                            state["matrix"] = matrix
                        elif kind == "pin":
                            pin = event.get("pin")
                            if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4,12}", pin): raise AppError("LINE_LOGIN_FAILED")
                            state["pin"] = pin
                        elif kind == "failed":
                            code = event.get("code")
                            raise AppError(code if code in {"LINE_LOGIN_REPLACEMENT_REQUIRED", "LINE_LOGIN_UNKNOWN"} else "LINE_LOGIN_FAILED")
                        elif kind == "completed":
                            completed = True
                            self.set_login_state(stage="saving")
                            continue
                        elif kind not in {"expired", "scanned", "phone_accepted", "approved"}:
                            raise AppError("LINE_LOGIN_FAILED")
                        if completed: raise AppError("LINE_LOGIN_FAILED")
                        self.set_login_state(**state)
                if not completed: raise AppError("LINE_LOGIN_FAILED")
                await attach_session(self.credentials, cli)
                self.account_id = self.credentials.load("line")["account_id"]
                self.connector = None
                self.selected_id = None
                self.deletion_challenge = None
                self._notify("data_cleared", **self._status())
                self.set_login_state(stage="completed")
        except asyncio.CancelledError:
            self.set_login_state(stage="cancelled")
            raise
        except Exception as exc:
            self.set_login_state(stage="failed", errorCode=exc.code if isinstance(exc, AppError) else "LINE_LOGIN_UNKNOWN" if completed else "LINE_LOGIN_FAILED")

    async def cancel_login(self):
        task, self.login_task = self.login_task, None
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError): await task
        # A completed login remains completed; cancellation cannot undo phone approval.
        if self.login_state.get("stage") != "completed": self.set_login_state(stage="cancelled")
        return self.login_state

    async def clear_avatars(self):
        self.avatar_generation += 1
        tasks = list(self.avatar_tasks.values())
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        self.avatar_tasks.clear()
        self.avatar_cache.clear()

    def avatar(self, identity):
        record = self._record(identity)
        path = record.conversation.locator.get("picture_path", "")
        version = picture_version(path)
        key = (record.id, version)
        if not version: return {"image": None, "pending": False}
        if key in self.avatar_cache:
            self.avatar_cache.move_to_end(key)
            return {"image": self.avatar_cache[key], "pending": False}
        if self.settings["storagePaused"] or self.connection != "connected" or self.login_active():
            return {"image": None, "pending": False}
        if key not in self.avatar_tasks and len(self.avatar_tasks) < 64:
            generation = self.avatar_generation
            async def fetch():
                result = None
                try:
                    async with self.avatar_slots: result = await self.avatar_fetcher(path)
                except asyncio.CancelledError: raise
                except Exception: pass
                finally: self.avatar_tasks.pop(key, None)
                if generation == self.avatar_generation and not self.settings["storagePaused"]:
                    self.avatar_cache[key] = result
                    while len(self.avatar_cache) > 128: self.avatar_cache.popitem(last=False)
            self.avatar_tasks[key] = asyncio.create_task(fetch())
        return {"image": None, "pending": True}
