"""Bounded Slack profile lookup for GUI-visible, locally known participants."""
import asyncio
from collections import OrderedDict
import re
import time
from hashlib import sha256
from urllib.parse import urlsplit

from .desktop_profiles import download_raster
from .errors import AppError

USER_ID = re.compile(r"[UW][A-Z0-9]{1,80}\Z")


def valid_avatar_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and url.hostname in {"avatars.slack-edge.com", "secure.gravatar.com"}
                and url.port in {None, 443} and not url.username and not url.password
                and not url.fragment and "\\" not in value and bool(url.path))
    except ValueError:
        return False


def profile_view(data, user_id):
    user = data.get("user")
    if not isinstance(user, dict) or user.get("id") != user_id:
        raise AppError("BAD_RESPONSE")
    profile = user.get("profile")
    if not isinstance(profile, dict):
        raise AppError("BAD_RESPONSE")
    name = next((s.strip()[:200] for s in (profile.get("display_name"), profile.get("real_name"),
                 user.get("real_name"), user.get("name")) if isinstance(s, str) and s.strip()), None)
    url = next((profile.get(k) for k in ("image_72", "image_48", "image_192")
                if valid_avatar_url(profile.get(k))), None)
    # Email, status, custom fields and the raw user object are never retained.
    return {"name": name, "url": url}


async def download_slack_avatar(url):
    return await download_raster(url) if valid_avatar_url(url) else None


class SlackProfiles:
    def initialize_slack_profiles(self):
        self.slack_profiles = OrderedDict()
        self.slack_profile_tasks = {}
        self.slack_profile_generation = 0
        self.slack_profile_error = None
        self.slack_avatar_fetcher = download_slack_avatar

    async def clear_avatars(self):
        self.slack_profile_generation += 1
        tasks = list(self.slack_profile_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.slack_profile_tasks.clear()
        self.slack_profiles.clear()
        await super().clear_avatars()

    def slack_profile_key(self, user_id):
        return 'slack-profile.v1.' + sha256((self.account_id + ':' + user_id).encode()).hexdigest()

    def cached_slack_profile(self, user_id, *, stale=False):
        key = (self.account_id, user_id)
        value = self.slack_profiles.get(key)
        if value is None:
            saved = self.db.private_get(self.slack_profile_key(user_id))
            if isinstance(saved, dict) and isinstance(saved.get('savedAt'), (int, float)):
                value = {'name': saved.get('name'), 'image': saved.get('image'),
                         'expires': time.monotonic() + max(0, min(3600, saved['savedAt'] + 3600 - time.time()))}
                self.slack_profiles[key] = value
                while len(self.slack_profiles) > 128: self.slack_profiles.popitem(last=False)
        if value and (stale or value["expires"] > time.monotonic()):
            self.slack_profiles.move_to_end(key)
            return value
        return None

    def slack_profile(self, identity, message_id=None):
        record = self._record(identity)
        if message_id is None:
            user_id = record.conversation.locator.get("peer_user_id")
        else:
            if not isinstance(message_id, str) or not re.fullmatch(r"[a-f0-9]{64}", message_id):
                raise AppError("INVALID_INPUT")
            message = next((m for m in self.db.list_messages("slack", self.account_id,
                record.conversation.id, limit=100) if m.id == message_id), None)
            if message is None:
                raise AppError("CONVERSATION_UNAVAILABLE")
            user_id = message.sender_id
        empty = {"name": None, "image": None, "pending": False, "errorCode": self.slack_profile_error}
        if not isinstance(user_id, str) or not USER_ID.fullmatch(user_id):
            return empty
        cached = self.cached_slack_profile(user_id, stale=True)
        if cached:
            empty.update(name=cached['name'], image=cached['image'])
        if self.settings["storagePaused"] or self.connection != "connected" or (cached and cached['expires'] > time.monotonic()):
            return empty
        if self.slack_profile_error:
            return empty
        key = (self.account_id, user_id)
        if key not in self.slack_profile_tasks and len(self.slack_profile_tasks) < 64:
            generation = self.slack_profile_generation
            async def fetch():
                name, image, expires = None, None, time.monotonic() + 60
                try:
                    # Share the provider operation lock so auth/account changes
                    # cannot race a history fetch or send through the same API.
                    async with self.operation_lock:
                        if (generation != self.slack_profile_generation or key[0] != self.account_id
                                or self.connection != "connected" or self.settings["storagePaused"]
                                or self.slack_profile_error):
                            return
                        profile = await self.connector.fetch_user_profile(user_id)
                    name = profile["name"]
                    if profile["url"]:
                        async with self.avatar_slots:
                            image = await self.slack_avatar_fetcher(profile["url"])
                    expires = time.monotonic() + 3600
                except asyncio.CancelledError:
                    raise
                except AppError as exc:
                    if exc.code == "MISSING_SCOPE":
                        self.slack_profile_error = "MISSING_SCOPE"
                        self._notify("status", **self._status())
                except Exception:
                    pass
                finally:
                    self.slack_profile_tasks.pop(key, None)
                if (generation == self.slack_profile_generation and key[0] == self.account_id
                        and not self.settings["storagePaused"] and self.connection == "connected"):
                    if cached:
                        name, image = name or cached['name'], image or cached['image']
                    self.slack_profiles[key] = {"name": name, "image": image, "expires": expires}
                    if name or image:
                        self.db.profile_cache_put('slack', self.account_id, self.slack_profile_key(user_id),
                            {'name': name, 'image': image, 'savedAt': time.time()})
                    while len(self.slack_profiles) > 128:
                        self.slack_profiles.popitem(last=False)
                    self._notify("profiles_changed", conversationId=identity)
            self.slack_profile_tasks[key] = asyncio.create_task(fetch())
        return {**empty, "pending": True}
