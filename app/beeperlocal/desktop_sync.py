"""Account-wide fair polling, resumable backfill and local unread state.

Provider cursors and read state commit with their messages. UI selection is never
changed by background work. Missing rows in a bounded page are not deletions.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import time

from .errors import AppError
from .models import StoredConversation, iso
from .receiver_retry import wait_for_retry


@dataclass
class HistoryPage:
    record: StoredConversation
    messages: list
    cursor: dict | None = None
    complete: bool = False
    deletions: list[str] = field(default_factory=list)
    coverage: str = 'available_history'
    followup: dict | None = None
    poll_metadata: dict | None = None


class DesktopSync:
    sync_interval = 5
    catalog_interval = 300

    def initialize_sync(self):
        self.sync_task = None
        self.sync_position = 0
        self.sync_turn = 0
        self.sync_state = {'mode': 'stopped', 'completedConversations': 0, 'totalConversations': 0}

    def supports_all_sync(self):
        return self.connector is not None and callable(getattr(self.connector, 'fetch_page', None))

    def read_state(self, identity):
        value = self.db.private_get('read.v1.' + identity, {'initialized': False, 'floor': '', 'unread': []})
        if (not isinstance(value, dict) or type(value.get('initialized')) is not bool
                or not isinstance(value.get('floor'), str) or not isinstance(value.get('unread'), list)
                or any(not isinstance(item, str) or len(item) != 64 for item in value['unread'])):
            raise AppError('LOCAL_DB_CORRUPT')
        return value

    def ingest(self, messages, *, records=(), historical=False, private_updates=None, deletions=(), **kwargs):
        rows = list(messages)
        catalog = {r.conversation.id: r for r in records}
        for message in rows:
            if (message.provider, message.account_id) != (self.provider, self.account_id):
                raise AppError('BAD_RESPONSE')
            if message.conversation_id not in catalog:
                catalog[message.conversation_id] = next((r for r in self._records() if r.conversation.id == message.conversation_id), None)
                if catalog[message.conversation_id] is None:
                    raise AppError('BAD_RESPONSE')
        updates, notifications = dict(private_updates or {}), []
        for record in catalog.values():
            if (record.provider, record.account_id) != (self.provider, self.account_id):
                raise AppError('BAD_RESPONSE')
            state = self.read_state(record.id)
            unread = set(state['unread'])
            scoped = [m for m in rows if m.conversation_id == record.conversation.id]
            new = [m for m in scoped if m.direction == 'incoming' and self.db.get_message(m.id) is None
                   and not self.db.conn.execute('SELECT 1 FROM message_tombstones WHERE id=?', (m.id,)).fetchone()]
            if not historical:
                unread.update(m.id for m in new if not state['floor'] or iso(m.sent_at) >= state['floor'])
            for target, mid in deletions:
                if target.id == record.id:
                    # Scope derivation reuses the message identity contract.
                    from hashlib import sha256
                    import json
                    unread.discard(sha256(json.dumps([target.provider, target.account_id, target.conversation.id, mid], separators=(',', ':')).encode()).hexdigest())
            if not state['initialized'] and historical:
                state['floor'] = max([iso(m.sent_at) for m in scoped], default=iso(datetime.now(timezone.utc)))
            added = len(unread - set(state['unread']))
            state.update(initialized=True, unread=sorted(unread))
            updates['read.v1.' + record.id] = state
            if added:
                notifications.append((record.id, added))
        result = self.db.upsert(rows, conversations=catalog.values(), private_updates=updates, deletions=deletions, **kwargs)
        for identity, count in notifications:
            self._notify('unread_changed', conversationId=identity, added=count)
        return result

    def mark_read(self, identity, through):
        record = self._record(identity)
        message = self.db.get_message(through)
        if message is None or (message.provider, message.account_id, message.conversation_id) != (self.provider, self.account_id, record.conversation.id):
            raise AppError('INVALID_INPUT')
        state = self.read_state(identity)
        remaining = []
        for mid in state['unread']:
            row = self.db.get_message(mid)
            if row is not None and (row.sent_at, row.id) > (message.sent_at, message.id):
                remaining.append(mid)
        state.update(initialized=True, floor=max(state['floor'], iso(message.sent_at)), unread=remaining)
        self.db.private_put('read.v1.' + identity, state)
        self._notify('read_changed', conversationId=identity)
        return {'unreadCount': len(remaining)}

    def start_all_sync(self):
        if self.sync_task and not self.sync_task.done():
            return
        self.receiving = 'waiting'
        self.sync_state['mode'] = 'syncing'
        self.sync_task = asyncio.create_task(self._sync_account())

    def backfill(self, identity, enabled):
        if type(enabled) is not bool:
            raise AppError('INVALID_INPUT')
        records = [self._record(identity)] if identity else self._current_records()
        for record in records:
            state = self.db.private_get('sync.v1.' + record.id, {})
            state['backfill'] = enabled
            self.db.private_put('sync.v1.' + record.id, state)
        return {'scheduledConversations': len(records)}

    async def _sync_account(self):
        attempts, next_catalog = 0, time.monotonic() + self.catalog_interval
        await wait_for_retry(self.sync_interval)
        while not self.settings['storagePaused']:
            try:
                async with self.operation_lock:
                    self.require_storage()
                    self.require_connected()
                    if time.monotonic() >= next_catalog:
                        choices = await self.connector.list_conversations(10000)
                        self.require_connected()
                        records = [StoredConversation(self.provider, self.account_id, c) for c in choices]
                        # Catalog limits must never delete saved conversations or their messages.
                        self.db.upsert([], conversations=records, private_updates={self.catalog_key(): [r.id for r in records]})
                        next_catalog = time.monotonic() + self.catalog_interval
                    records = self._current_records()
                    self.sync_state['totalConversations'] = len(records)
                    if records:
                        record = records[self.sync_position % len(records)]
                        self.sync_position += 1
                        state = self.db.private_get('sync.v1.' + record.id, {})
                        # Alternate old and recent pages per conversation, so backfill cannot starve new messages.
                        catching_up = bool(state.get('catchup'))
                        old = bool(not catching_up and state.get('backfill') and state.get('cursor') is not None
                                   and not state.get('complete') and state.get('nextOld', False))
                        cursor = state.get('catchup') if catching_up else state.get('cursor') if old else None
                        sync_fetch = getattr(self.connector, 'fetch_sync_page', None)
                        page = (await sync_fetch(record.conversation, cursor=cursor, metadata=state.get('provider', {}))
                                if callable(sync_fetch) else await self.connector.fetch_page(record.conversation, cursor=cursor))
                        self.require_connected()
                        if (not isinstance(page, HistoryPage) or page.record.id != record.id
                                or (page.poll_metadata is not None and not isinstance(page.poll_metadata, dict))
                                or (page.followup is not None and not isinstance(page.followup, dict))
                                or type(page.complete) is not bool or (page.cursor is not None and not isinstance(page.cursor, dict))
                                or any((m.provider, m.account_id, m.conversation_id) != (record.provider, record.account_id, record.conversation.id) for m in page.messages)
                                or any(not isinstance(mid, str) or not mid or len(mid) > 4096 for mid in page.deletions)):
                            raise AppError('BAD_RESPONSE')
                        if old and page.cursor is not None and page.cursor == cursor:
                            raise AppError('PAGINATION_STALLED')
                        initial = not self.read_state(record.id)['initialized']
                        overlap = any(self.db.get_message(m.id) is not None for m in page.messages)
                        if not old:
                            if page.followup is not None:
                                if catching_up and page.followup == cursor:
                                    raise AppError('PAGINATION_STALLED')
                                state['catchup'] = page.followup
                                state['catchupHistorical'] = initial or state.get('catchupHistorical', False)
                            elif not initial and not overlap and page.cursor and not page.complete:
                                if catching_up and page.cursor == cursor:
                                    raise AppError('PAGINATION_STALLED')
                                state['catchup'] = page.cursor
                            else:
                                state.pop('catchup', None)
                        was_historical = old or initial or (catching_up and state.get('catchupHistorical', False))
                        if not state.get('catchup'):
                            state.pop('catchupHistorical', None)
                        if old or 'cursor' not in state:
                            state.update(cursor=page.cursor, complete=page.complete, exhausted=page.cursor is None)
                        if page.poll_metadata is not None:
                            state['provider'] = page.poll_metadata
                        state.update(nextOld=not old, coverage=page.coverage, lastSync=iso(datetime.now(timezone.utc)))
                        # Once requested, full history continues across app restarts until exhausted.
                        self.ingest(page.messages, records=[page.record], historical=was_historical,
                            private_updates={'sync.v1.' + record.id: state},
                            deletions=[(record, mid) for mid in page.deletions])
                        self._notify('messages_changed', conversationId=record.id)
                        self.sync_state['completedConversations'] = min(len(records), self.sync_state['completedConversations'] + 1)
                    # LINE stream readiness owns the receiver status. Successful
                    # history polling must not conceal a disconnected stream.
                    if self.provider != 'line':
                        self.receiving, self.error_code, self.retry_attempt = 'waiting', None, 0
                    self.sync_state['mode'] = 'syncing'
                    self._notify('status', **self._status())
                attempts = 0
                await wait_for_retry(self.sync_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = exc.code if isinstance(exc, AppError) else 'UNEXPECTED_ERROR'
                if self.invalidate_line_session(code):
                    return
                if self.provider == 'line' and self.connection != 'connected':
                    return
                if code not in {'NETWORK_ERROR', 'HTTP_ERROR', 'RATE_LIMITED', 'LINE_REQUEST_FAILED',
                                'IG_REQUEST_FAILED', 'IG_REQUEST_TIMEOUT', 'X_REQUEST_FAILED', 'X_REQUEST_TIMEOUT'}:
                    self.receiving, self.error_code = 'error', code
                    self.sync_state['mode'] = 'error'
                    self._notify('status', **self._status())
                    return
                attempts += 1
                self.receiving, self.error_code, self.retry_attempt = 'reconnecting', code, attempts
                self.sync_state['mode'] = 'waiting'
                self._notify('status', **self._status())
                cooldowns = getattr(getattr(self.connector, 'api', None), 'cooldowns', {})
                delay = max(self.sync_interval, min(300, 5 * 2 ** min(attempts, 6)),
                            max(cooldowns.values(), default=0) - time.monotonic())
                await wait_for_retry(delay)
