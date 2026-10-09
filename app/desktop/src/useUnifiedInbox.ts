import { useEffect, useRef, useState } from 'react';
import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification';
import { isDemo, request, subscribe, errorText } from './bridge';
import type { Provider, Snapshot } from './types';

const providers: Provider[] = ['line', 'instagram', 'slack', 'x', 'messenger'];
const labels = { line: 'LINE', instagram: 'Instagram', slack: 'Slack', x: 'X', messenger: 'Messenger' };
function preference(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
export function rememberConnected(provider: Provider) {
  try { localStorage.setItem(`beeperlocal.connected.${provider}`, '1'); } catch { /* Non-sensitive preference. */ }
}

export function useUnifiedInbox(provider: Provider, state: Snapshot, isReading: (p: Provider, id?: string) => boolean) {
  const [counts, setCounts] = useState<Partial<Record<Provider, number>>>({});
  const [failures, setFailures] = useState<Partial<Record<Provider, string>>>({});
  const [enabled, setEnabled] = useState(preference('beeperlocal.notifications') === '1');
  const [notificationError, setNotificationError] = useState('');
  const context = useRef({ enabled, isReading }); context.current = { enabled, isReading };
  useEffect(() => { setCounts(c => ({ ...c, [provider]: state.unreadCount ?? state.conversations.reduce((n, c) => n + (c.unreadCount ?? 0), 0) })); }, [provider, state]);
  useEffect(() => {
    let disposed = false, unlisten: (() => void) | undefined;
    const timers = new Map<Provider, ReturnType<typeof setTimeout>>();
    let lastNotice = 0;
    async function refresh(p: Provider) {
      try {
        const s = await request<Snapshot>({ provider: p, op: 'snapshot' });
        if (!disposed) { setCounts(c => ({ ...c, [p]: s.unreadCount ?? s.conversations.reduce((n, c) => n + (c.unreadCount ?? 0), 0) })); setFailures(f => ({ ...f, [p]: s.errorCode ?? '' })); }
      } catch (e) { if (!disposed) setFailures(f => ({ ...f, [p]: errorText(e) })); }
    }
    void (async () => {
      unlisten = await subscribe(event => {
        const p = event.provider ?? 'line';
        if (!providers.includes(p) || disposed) return;
        if (['messages_changed', 'unread_changed', 'read_changed', 'data_cleared', 'status'].includes(event.event)) {
          clearTimeout(timers.get(p)); timers.set(p, setTimeout(() => void refresh(p), 200));
        }
        if (event.event === 'unread_changed' && context.current.enabled && !context.current.isReading(p, event.conversationId) && Date.now() - lastNotice > 5000) {
          lastNotice = Date.now();
          if (!isDemo) void isPermissionGranted().then(granted => {
            if (granted && !disposed) sendNotification({ title: 'BeeperLocal', body: `${labels[p]}に新着メッセージがあります。` });
          }).catch(() => setNotificationError('通知を表示できませんでした。macOSの通知設定を確認してください。'));
        }
      });
      if (disposed) { unlisten(); return; }
      // Reopen only services the user previously connected. A paused store stays paused.
      await Promise.all(providers.filter(p => p !== provider && preference(`beeperlocal.connected.${p}`) === '1').map(async p => {
        if (disposed) return;
        try {
          const s = await request<Snapshot>({ provider: p, op: 'snapshot' });
          if (!s.storagePaused && s.connection !== 'connected') await request({ provider: p, op: 'connect' });
          await refresh(p);
        } catch (e) { if (!disposed) setFailures(f => ({ ...f, [p]: errorText(e) })); }
      }));
    })();
    return () => { disposed = true; unlisten?.(); timers.forEach(clearTimeout); };
  }, []);
  async function toggleNotifications() {
    setNotificationError('');
    let next = !enabled;
    try {
      if (next && !isDemo) next = await isPermissionGranted() || await requestPermission() === 'granted';
      setEnabled(next);
      try { localStorage.setItem('beeperlocal.notifications', next ? '1' : '0'); } catch { /* Optional preference. */ }
      if (!next && !enabled) setNotificationError('macOSのシステム設定でBeeperLocalの通知を許可してください。');
    } catch { setNotificationError('通知の許可を確認できませんでした。'); }
  }
  return { counts, failures, total: Object.values(counts).reduce((n, v) => n + (v ?? 0), 0), enabled, toggleNotifications, notificationError };
}
