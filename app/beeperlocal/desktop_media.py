"""LINE previews: scoped saved messages, private pipes and bounded RAM only."""
import asyncio
import base64
from collections import OrderedDict
from io import BytesIO
import re
import warnings

from .errors import AppError

MAX_PREVIEW_BYTES = 4 * 1024 * 1024
MAX_CACHE_BYTES = 24 * 1024 * 1024


def allowed_attachment_url(provider, value):
    from urllib.parse import urlsplit
    try:
        u = urlsplit(value)
        domains = {'instagram': ('cdninstagram.com', 'fbcdn.net'),
                   'x': ('twimg.com', 'ton.twitter.com', 'ton.x.com')}.get(provider, ())
        return (u.scheme == 'https' and u.port in (None, 443) and not u.username and not u.password
                and not u.fragment and any(u.hostname == d or (u.hostname or '').endswith('.' + d) for d in domains))
    except (ValueError, TypeError):
        return False


async def download_attachment(provider, attachment):
    import httpx2
    url = attachment.get('url')
    if not allowed_attachment_url(provider, url):
        return None
    async with httpx2.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        async with client.stream('GET', url) as response:
            if response.status_code != 200:
                return None
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_PREVIEW_BYTES:
                    return None
            return bytes(data)


def attachment_preview(data, kind):
    if not data or len(data) > MAX_PREVIEW_BYTES:
        return None
    if kind == 'image':
        return image_preview(data)
    # Never render HTML, SVG, scripts or arbitrary files in the WebView.
    mime = None
    if len(data) >= 12 and data[4:8] == b'ftyp' and kind in {'video', 'audio'}:
        mime = 'video/mp4' if kind == 'video' else 'audio/mp4'
    elif kind == 'audio' and (data.startswith(b'ID3') or data[:2] in {b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'}):
        mime = 'audio/mpeg'
    elif kind == 'audio' and data.startswith(b'RIFF') and data[8:12] == b'WAVE':
        mime = 'audio/wav'
    return f'data:{mime};base64,' + base64.b64encode(data).decode() if mime else None


def image_preview(data):
    from PIL import Image, ImageOps
    # Decode/re-encode rather than handing arbitrary provider bytes to the WebView.
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP", "GIF"} or source.width * source.height > 64_000_000:
                return None
            source.seek(0)
            source.thumbnail((1600, 1600))
            picture = ImageOps.exif_transpose(source)
            alpha = "A" in picture.getbands() or "transparency" in picture.info
            picture = picture.convert("RGBA" if alpha else "RGB")
            output = BytesIO()
            # Do not propagate EXIF, comments or other private source metadata.
            picture.info.clear()
            picture.save(output, format="PNG" if alpha else "JPEG", quality=85)
            encoded = output.getvalue()
            if len(encoded) > MAX_PREVIEW_BYTES:
                picture.thumbnail((800, 800))
                output = BytesIO()
                picture.save(output, format="PNG" if alpha else "JPEG", quality=80)
                encoded = output.getvalue()
            if len(encoded) > MAX_PREVIEW_BYTES:
                return None
            mime = "image/png" if alpha else "image/jpeg"
            return f"data:{mime};base64," + base64.b64encode(encoded).decode()


async def download_sticker(sticker_id):
    if not isinstance(sticker_id, str) or not re.fullmatch(r"[0-9]{1,20}", sticker_id):
        return None
    import httpx2
    url = f"https://stickershop.line-scdn.net/stickershop/v1/sticker/{sticker_id}/iPhone/sticker_key@2x.png"
    async with httpx2.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200 or response.headers.get("content-type", "").split(";")[0].strip().lower() not in {"image/png", "image/webp", "image/gif"}:
                return None
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 2 * 1024 * 1024:
                    return None
            return bytes(data)


class DesktopMedia:
    def initialize_media(self):
        self.media_cache = OrderedDict()
        self.media_cache_bytes = 0
        self.media_tasks = {}
        self.media_generation = 0
        self.media_slots = asyncio.Semaphore(1)
        self.sticker_fetcher = download_sticker
        self.attachment_fetcher = download_attachment

    def attachment_media(self, conversation_id, message_id, index, retry):
        if type(index) is not int or type(retry) is not bool or not 0 <= index < 20:
            raise AppError('INVALID_INPUT')
        record = self._record(conversation_id)
        message = self.db.get_message(message_id)
        if message is None or (message.provider, message.account_id, message.conversation_id) != (self.provider, self.account_id, record.conversation.id):
            raise AppError('INVALID_INPUT')
        local = self.db.private_get('image.v1.' + message.id) if index == 0 else None
        if local:
            return {'media': local, 'pending': False}
        if self.provider not in {'instagram', 'x', 'slack'} or index >= len(message.attachments):
            raise AppError('INVALID_INPUT')
        unavailable = {'media': None, 'pending': False}
        if self.settings['storagePaused'] or self.login_active() or self.connection != 'connected':
            return unavailable
        key = (record.id, message.id, index)
        if retry and key in self.media_cache and self.media_cache[key] is None:
            self.media_cache.pop(key)
        if key in self.media_cache:
            self.media_cache.move_to_end(key)
            return {'media': self.media_cache[key], 'pending': False}
        if key not in self.media_tasks and len(self.media_tasks) < 16:
            generation, connector = self.media_generation, self.connector
            async def fetch():
                result = None
                try:
                    async with self.media_slots:
                        if self.provider == 'x' and message.attachments[index].get('media_hash_key'):
                            # The worker fetches/decrypts only its own saved, verified attachment.
                            async with self.operation_lock:
                                data = await connector.download_attachment(record.conversation, message.provider_message_id, index)
                        elif self.provider == 'slack':
                            async with self.operation_lock:
                                data = await connector.download_attachment(message.attachments[index])
                        else:
                            data = await self.attachment_fetcher(self.provider, message.attachments[index])
                        result = await asyncio.to_thread(attachment_preview, data, message.attachments[index]['kind'])
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
                finally:
                    self.media_tasks.pop(key, None)
                if generation == self.media_generation and not self.settings['storagePaused']:
                    self.media_cache[key] = result
                    self.media_cache_bytes += len(result or '')
                    while len(self.media_cache) > 64 or self.media_cache_bytes > MAX_CACHE_BYTES:
                        _, old = self.media_cache.popitem(last=False)
                        self.media_cache_bytes -= len(old or '')
            self.media_tasks[key] = asyncio.create_task(fetch())
        return {'media': None, 'pending': True}

    async def clear_media(self):
        self.media_generation += 1
        tasks = list(self.media_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.media_tasks.clear()
        self.media_cache.clear()
        self.media_cache_bytes = 0

    def line_media(self, conversation_id, message_id, retry):
        if self.provider != "line" or type(retry) is not bool or not isinstance(message_id, str) or not re.fullmatch(r"[a-f0-9]{64}", message_id):
            raise AppError("INVALID_INPUT")
        record = self._record(conversation_id)
        # Caller supplies only local hashes; route/metadata always come from encrypted storage.
        message = self.db.get_message(message_id)
        if (message is None or message.provider != "line" or message.account_id != self.account_id
                or message.conversation_id != record.conversation.id or message.media is None):
            raise AppError("INVALID_INPUT")
        key = (record.id, message.id)
        unavailable = {"image": None, "pending": False}
        if self.settings["storagePaused"] or self.login_active():
            return unavailable
        if retry and key in self.media_cache and self.media_cache[key] is None:
            self.media_cache.pop(key)
        if key in self.media_cache:
            self.media_cache.move_to_end(key)
            return {"image": self.media_cache[key], "pending": False}
        if self.connection != "connected" or self.connector is None:
            return unavailable
        if key not in self.media_tasks and len(self.media_tasks) < 16:
            generation, connector = self.media_generation, self.connector

            async def fetch():
                result = None
                try:
                    async with self.media_slots:
                        # Account/session check before reading a private LINE attachment.
                        if message.media["kind"] == "sticker":
                            data = await self.sticker_fetcher(message.media.get("sticker_id"))
                        else:
                            await connector.connect()
                            data = await connector.cli.download_image(record.conversation.id, message.provider_message_id)
                        if data:
                            result = await asyncio.to_thread(image_preview, data)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass  # Keep message visible, never expose raw provider errors.
                finally:
                    self.media_tasks.pop(key, None)
                if generation == self.media_generation and not self.settings["storagePaused"]:
                    self.media_cache[key] = result
                    self.media_cache_bytes += len(result or "")
                    while len(self.media_cache) > 64 or self.media_cache_bytes > MAX_CACHE_BYTES:
                        _, old = self.media_cache.popitem(last=False)
                        self.media_cache_bytes -= len(old or "")

            self.media_tasks[key] = asyncio.create_task(fetch())
        return {"image": None, "pending": True}
