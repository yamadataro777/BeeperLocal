"""Single-image GUI sends: bounded input, durable intent and no automatic retry."""
from __future__ import annotations
import asyncio
import base64
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import re
import warnings

from .errors import AppError
from .outbox import OutgoingRequest
from .desktop_media import image_preview

MAX_IMAGE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, repr=False)
class OutgoingImage:
    data: bytes
    mime: str
    width: int
    height: int
    digest: str
    preview: str

    @property
    def name(self):
        return 'image.png' if self.mime == 'image/png' else 'image.jpg'

    def wire(self):
        return {'data': base64.b64encode(self.data).decode(), 'mime': self.mime,
                'width': self.width, 'height': self.height}


def decode_image(value):
    from PIL import Image, ImageOps
    if not isinstance(value, str) or len(value) > (MAX_IMAGE_BYTES + 2) // 3 * 4 + 32:
        raise AppError('IMAGE_TOO_LARGE')
    match = re.fullmatch(r'data:(image/(?:jpeg|png));base64,([A-Za-z0-9+/=]+)', value)
    if not match:
        raise AppError('IMAGE_FORMAT_UNSUPPORTED')
    try:
        data = base64.b64decode(match[2], validate=True)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise AppError('IMAGE_TOO_LARGE')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {'PNG', 'JPEG'} or Image.MIME[source.format] != match[1]:
                    raise ValueError()
                if source.width * source.height > 25_000_000 or max(source.size) > 16384:
                    raise AppError('IMAGE_TOO_LARGE')
                source.load()
                picture = ImageOps.exif_transpose(source).convert('RGBA' if source.format == 'PNG' else 'RGB')
                picture.info.clear()  # Do not upload EXIF/GPS, comments or embedded profiles.
                stream = BytesIO()
                picture.save(stream, format=source.format, quality=92)
                normalized = stream.getvalue()
                if len(normalized) > MAX_IMAGE_BYTES:
                    raise AppError('IMAGE_TOO_LARGE')
                preview = image_preview(normalized)
                if not preview:
                    raise ValueError()
                return OutgoingImage(normalized, match[1], picture.width, picture.height, sha256(data).hexdigest(), preview)
    except AppError:
        raise
    except Exception:
        raise AppError('IMAGE_FORMAT_UNSUPPORTED') from None


def image_from_wire(value):
    if not isinstance(value, dict) or set(value) != {'data', 'mime', 'width', 'height'} or not isinstance(value['data'], str) or value['mime'] not in {'image/jpeg', 'image/png'}:
        raise AppError('INVALID_INPUT')
    image = decode_image('data:' + value['mime'] + ';base64,' + value['data'])
    if type(value['width']) is not int or type(value['height']) is not int or (image.width, image.height) != (value['width'], value['height']):
        raise AppError('INVALID_INPUT')
    # Already normalized by the GUI Core; preserve the exact uploaded raster.
    return replace(image, data=base64.b64decode(value['data'], validate=True))


class DesktopImageSending:
    def message_view(self, message):
        from .desktop import message_view
        value = message_view(message)
        if self.db.private_get('image.v1.' + message.id):
            value.pop('media', None)
            value['attachmentCount'] = max(1, value['attachmentCount'])
            value['attachments'] = [{'kind': 'image', 'index': 0, 'local': True, 'name': '送信した画像'}]
        return value

    async def send_image(self, identity, data_url, request_id):
        self.require_storage()
        self.require_connected()
        record = self._record(identity)
        if identity != self.selected_id:
            raise AppError('CONVERSATION_CHANGED')
        image = await asyncio.to_thread(decode_image, data_url)
        try:
            intent = OutgoingRequest(request_id, self.provider, self.account_id, record.conversation.id,
                                     '', 'sending', datetime.now(timezone.utc), image_digest=image.digest)
        except (ValueError, TypeError, AttributeError):
            raise AppError('INVALID_INPUT') from None
        if self.db.request_retired(request_id):
            raise AppError(self.send_unknown)
        previous = self.db.get_outgoing(request_id)
        if previous:
            if (previous.provider, previous.account_id, previous.conversation_id, previous.image_digest) != (
                    intent.provider, intent.account_id, intent.conversation_id, image.digest):
                raise AppError('INVALID_INPUT')
            if previous.status == 'acknowledged':
                return {'status': 'acknowledged', 'messageId': previous.message_id, 'duplicateSuppressed': True}
            raise AppError(self.send_unknown)
        await self.connector.connect()
        def authorize():
            self.require_storage()
            self.require_connected()
            if self.account_id != intent.account_id or self.connector.account_id != intent.account_id:
                raise AppError('ACCOUNT_CHANGED')
            if self.selected_id != identity or self.connector.selected_conversation().id != record.conversation.id:
                raise AppError('CONVERSATION_CHANGED')
        authorize()
        self.db.upsert([], outgoing_requests=[intent])
        try:
            result = await self.connector.send_image_to(record.conversation, image, authorize=authorize)
            message = result.message
            if (message.provider, message.account_id, message.conversation_id, message.direction) != (
                    self.provider, intent.account_id, record.conversation.id, 'outgoing'):
                raise AppError(self.send_unknown)
        except BaseException:
            self.db.upsert([], outgoing_requests=[replace(intent, status='unknown')])
            raise
        try:
            self.db.upsert([message], conversations=[record], outgoing_requests=[replace(intent,
                status='acknowledged', message_id=message.id)], private_updates={'image.v1.' + message.id: image.preview})
        except Exception:
            raise AppError(self.sent_not_stored) from None
        self._notify('messages_changed', conversationId=identity)
        return {'status': 'acknowledged', 'messageId': message.id, 'encrypted': result.encrypted}
