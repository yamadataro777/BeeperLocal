import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { errorText, isDemo, request as rawRequest, subscribe } from './bridge';
import type { Conversation, CoreEvent, History, Message, SearchResponse, SearchResult, Snapshot, Provider, Request } from './types';
import './style.css';
import { SettingsPanel } from './SettingsPanel';
import { LoginPanel } from './LoginPanel';
import { MessengerLoginPanel, MessengerSettingsPanel } from './MessengerPanel';
import { XLoginPanel } from './XLoginPanel';
import { XSettingsPanel } from './XSettingsPanel';
import { Avatar } from './Avatar';
import { SlackMessageProfile } from './SlackProfile';
import { LineMedia } from './LineMedia';
import { HelpPanel } from './HelpPanel';
import { SetupButton } from './SetupButton';
import { rememberConnected, useUnifiedInbox } from './useUnifiedInbox';
import { UpdateButton } from './UpdateButton';
import { AttachmentMedia } from './AttachmentMedia';
import { clearProfileCache } from './profileCache';
import { ImageComposer, type ImageDraft } from './ImageComposer';

function Icon({ name, size = 19 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    chat: <><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/><path d="M8 10h8M8 14h5"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.6-2L20 8M4 16l2.3 3A7 7 0 0 0 18 17"/></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/></>,
    arrow: <><path d="m7 5 7 7-7 7M3 12h15"/></>,
    send: <><path d="m21 3-7 18-4-7-7-4 18-7ZM10 14 21 3"/></>,
    back: <><path d="m14 6-6 6 6 6"/></>,
    close: <><path d="m6 6 12 12M6 18 18 6"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="m9 3-.7 2.2-2.2 1L4 6 2 10l2 1.5v2L2 15l2 4 2.1-.2 2.2 1L9 22h6l.7-2.2 2.2-1 2.1.2 2-4-2-1.5v-2L22 10l-2-4-2.1.2-2.2-1L15 3H9Z"/></>,
    check: <><path d="m5 12 4 4L19 6"/></>,
    alert: <><path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5M12 17v.1"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? paths.chat}</svg>;
}

const initial: Snapshot = { conversations: [], catalogLimited: false, pendingSends: [], connection: 'offline', receiving: 'stopped', errorCode: null, selectedId: null };
const time = (date: string) => new Date(date).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
const day = (date: string) => new Date(date).toLocaleDateString('ja-JP', { month: 'long', day: 'numeric', weekday: 'short' });
const listDate = (date: string) => { const d = new Date(date), now = new Date(); return d.toDateString() === now.toDateString() ? time(date) : d.toLocaleDateString('ja-JP', { ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' as const } : {}), month: 'numeric', day: 'numeric' }); };

function savedProvider(): Provider {
  try { const saved = localStorage.getItem('beeperlocal.provider'); return saved === 'instagram' || saved === 'slack' || saved === 'x' || saved === 'messenger' ? saved : 'line'; }
  catch { return 'line'; }
}

function App() {
  const [provider, setProvider] = useState<Provider>(savedProvider);
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 699px)').matches);
  const providerRef = useRef<Provider>(provider);
  const providerLabel = provider === 'messenger' ? 'Messenger' : provider === 'x' ? '𝕏' : provider === 'slack' ? 'Slack' : provider === 'instagram' ? 'Instagram' : 'LINE';
  async function request<T>(value: Request): Promise<T> {
    return rawRequest<T>({ ...value, provider: providerRef.current });
  }

  const [state, setState] = useState<Snapshot>(initial);
  const [selected, setSelected] = useState<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState('保存済みの会話を読み込んでいます');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [settings, setSettings] = useState(false);
  const [help, setHelp] = useState(false);
  const [updating, setUpdating] = useState(false);
  const helpDialog = useRef<HTMLDialogElement>(null);
  const [login, setLogin] = useState(false);
  const [xUnlockOnly, setXUnlockOnly] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [uncertainSends, setUncertainSends] = useState<Record<string, string>>({});
  const [confirmedRetry, setConfirmedRetry] = useState(false);
  const [imageSelected, setImageSelected] = useState(false);
  const [uncertainImages, setUncertainImages] = useState<Record<string, string>>({});
  const [highlight, setHighlight] = useState<string | null>(null);
  const [searchAnchor, setSearchAnchor] = useState<SearchResult | null>(null);
  const [showChat, setShowChat] = useState(false);
  const [newMessages, setNewMessages] = useState(false);
  const composing = useRef(false);
  const sendLock = useRef(false);
  const connectLock = useRef(false);
  const searchInput = useRef<HTMLInputElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const settingsDialog = useRef<HTMLDialogElement>(null);
  const timeline = useRef<HTMLDivElement>(null);
  const followBottom = useRef(true);
  const inbox = useUnifiedInbox(provider, state, (p, id) => document.hasFocus() && document.visibilityState === 'visible' && p === providerRef.current && id === selectedRef.current && followBottom.current && (!narrow || showChat) && !settings && !help);
  const scrollToBottom = () => { timeline.current?.scrollTo({ top: timeline.current.scrollHeight }); setNewMessages(false); followBottom.current = true; };
  const conversation = state.conversations.find(c => c.id === selected) ??
    (searchAnchor?.conversationId === selected ? { id: searchAnchor.conversationId, title: searchAnchor.title, provider, preview: searchAnchor.text, lastMessageAt: searchAnchor.sentAt } : undefined);
  const draftKey = `${provider}:${selected}`;
  const draft = selected ? drafts[draftKey] ?? '' : '';
  const connected = state.connection === 'connected';
  const lineLoginRequired = provider === 'line' && ['LINE_LOGIN_REQUIRED', 'LINE_SESSION_REVOKED'].includes(state.errorCode ?? '');
  const receiverHealthy = connected && !['starting', 'reconnecting', 'error', 'stopped'].includes(state.receiving);
  const displayedError = error || (state.errorCode ? errorText(state.errorCode) : '');
  const draftSize = provider === 'instagram' || provider === 'x' ? new TextEncoder().encode(draft).length : draft.length;
  const textLimit = provider === 'line' || provider === 'x' ? 10000 : 4000;
  const ambiguousDraft = !!draft.trim() && (uncertainSends[draftKey] === draft ||
    state.pendingSends.some(item => item.conversationId === selected && item.text === draft));
  const retryBlocked = ambiguousDraft && !confirmedRetry;
  useEffect(() => { setConfirmedRetry(false); }, [draftKey, draft]);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 699px)');
    const changed = () => setNarrow(media.matches);
    media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);

  async function loadMessages(identity: string) {
    const scope = providerRef.current;
    const result = await request<History>({ op: 'messages', conversationId: identity });
    if (providerRef.current === scope && selectedRef.current === identity) setHistory(result);
  }

  async function loadSnapshot() {
    const scope = providerRef.current;
    const result = await request<Snapshot>({ op: 'snapshot' });
    if (providerRef.current === scope) setState(result);
    return result;
  }

  async function connect(interactive = true) {
    if (connectLock.current) return;
    connectLock.current = true;
    const label = { line: 'LINE', instagram: 'Instagram', slack: 'Slack', x: '𝕏', messenger: 'Messenger' }[providerRef.current];
    setBusy(`${label}に接続しています`); setError(''); setNotice('');
    try {
      const result = await request<Snapshot>({ op: 'connect', ...(interactive ? { interactive: true } : {}) });
      rememberConnected(providerRef.current);
      setState(result);
      const identity = result.selectedId;
      selectedRef.current = identity; setSelected(identity);
      if (identity) await loadMessages(identity);
      setNotice(`${label}への接続を確認しました`);
    } catch (cause) {
      if (providerRef.current === 'line' && ['LINE_LOGIN_REQUIRED', 'LINE_SESSION_REVOKED'].includes(String(cause))) { setLogin(true); setError(''); }
      else if (providerRef.current === 'messenger' && (cause === 'MESSENGER_LOGIN_REQUIRED' || cause === 'MESSENGER_AUTH_FAILED')) { setLogin(true); setError(''); }
      else if (providerRef.current === 'x' && (cause === 'X_LOGIN_REQUIRED' || cause === 'X_UNLOCK_REQUIRED')) { setXUnlockOnly(cause === 'X_UNLOCK_REQUIRED'); setLogin(true); setError(''); }
      else setError(errorText(cause));
    }
    finally { connectLock.current = false; setBusy(''); }
  }

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const onEvent = (event: CoreEvent) => {
      if (!disposed && event.event === 'data_cleared') clearProfileCache(event.provider ?? 'line');
      if (disposed || (event.event !== 'fatal' && (event.provider ?? 'line') !== providerRef.current)) return;
      if (event.event === 'status') {
        setState(current => ({ ...current, connection: event.connection ?? current.connection,
          receiving: event.receiving ?? current.receiving, errorCode: event.errorCode ?? null,
          storagePaused: event.storagePaused ?? current.storagePaused, retryAttempt: event.retryAttempt ?? current.retryAttempt,
          profileErrorCode: event.profileErrorCode === undefined ? current.profileErrorCode : event.profileErrorCode }));
      }
      if (event.event === 'data_cleared') {
        selectedRef.current = null; setSelected(null); setHistory(null); setSearch(null); setQuery('');
        setSearchAnchor(null); setHighlight(null);
        setDrafts(current => Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(`${providerRef.current}:`))));
        setUncertainSends(current => Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(`${providerRef.current}:`))));
        setUncertainImages(current => Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(`${providerRef.current}:`))));
        setNotice(''); setError('');
        void loadSnapshot().catch(cause => setError(errorText(cause)));
      }
      if (event.event === 'fatal') {
        setError(errorText(event.error));
        setState(current => ({ ...current, connection: 'offline', receiving: 'error', errorCode: event.error ?? 'CORE_STOPPED' }));
      }
      if (event.event === 'messages_changed' || event.event === 'profiles_changed' || event.event === 'read_changed') {
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(async () => {
          if (disposed || (event.provider ?? 'line') !== providerRef.current) return;
          try {
            await loadSnapshot();
            if (selectedRef.current && event.event !== 'read_changed') {
              if (followBottom.current) await loadMessages(selectedRef.current);
              else setNewMessages(true);
            }
          } catch (cause) { if (!disposed) setError(errorText(cause)); }
        }, 150);
      }
    };
    void (async () => {
      try {
        unlisten = await subscribe(onEvent);
        if (disposed) { unlisten(); return; }
        const result = await loadSnapshot();
        if (disposed) return;
        if (result.selectedId) {
          selectedRef.current = result.selectedId; setSelected(result.selectedId);
          await loadMessages(result.selectedId);
        }
        if (!disposed && !result.storagePaused) await connect(false);
        else if (!disposed) { setBusy(''); setNotice('保存を停止中です。設定から再開できます。'); }
      } catch (cause) { if (!disposed) { setError(errorText(cause)); setBusy(''); } }
    })();
    return () => { disposed = true; clearTimeout(refreshTimer); unlisten?.(); };
  }, []);

  useEffect(() => {
    if (settings) settingsDialog.current?.showModal();
    else settingsDialog.current?.close();
  }, [settings]);

  useEffect(() => {
    if (help) helpDialog.current?.showModal();
    else helpDialog.current?.close();
  }, [help]);

  useEffect(() => {
    const mark = () => {
      const last = history?.messages.at(-1);
      if (!last || !selected || !(conversation?.unreadCount ?? 0) || !document.hasFocus() || document.visibilityState !== 'visible' || !followBottom.current || (narrow && !showChat) || settings || help || searchAnchor) return;
      void request({ op: 'mark_read', conversationId: selected, throughMessageId: last.id }).then(loadSnapshot).catch(() => { /* Keep unread until a later successful read. */ });
    };
    const timer = setTimeout(mark, 400);
    window.addEventListener('focus', mark); document.addEventListener('visibilitychange', mark);
    return () => { clearTimeout(timer); window.removeEventListener('focus', mark); document.removeEventListener('visibilitychange', mark); };
  }, [history, selected, conversation?.unreadCount, narrow, showChat, settings, help, searchAnchor, newMessages]);

  async function olderHistory() {
    if (!selected || !history?.olderCursor || busy) return;
    const identity = selected, scope = provider;
    setBusy('保存済みの過去履歴を読み込んでいます');
    try {
      const page = await request<History>({ op: 'messages_older', conversationId: identity, before: history.olderCursor });
      if (providerRef.current !== scope || selectedRef.current !== identity) return;
      const height = timeline.current?.scrollHeight ?? 0;
      followBottom.current = false;
      setHistory(current => current ? { ...current, olderCursor: page.olderCursor, messages: [...page.messages.filter(m => !current.messages.some(c => c.id === m.id)), ...current.messages] } : page);
      requestAnimationFrame(() => { if (timeline.current) timeline.current.scrollTop += timeline.current.scrollHeight - height; });
    } catch (e) { setError(errorText(e)); } finally { setBusy(''); }
  }

  async function backfill(all = false) {
    if (!selected && !all) return;
    const identity = selected, scope = provider;
    const enabled = all || !history?.sync?.backfill;
    try {
      await rawRequest({ op: 'history_backfill', provider: scope, conversationId: all ? null : identity, enabled });
      if (providerRef.current !== scope || selectedRef.current !== identity) return;
      if (identity) {
        const updated = await rawRequest<History>({ op: 'messages', provider: scope, conversationId: identity });
        if (providerRef.current !== scope || selectedRef.current !== identity) return;
        setHistory(current => current ? { ...current, sync: updated.sync } : updated);
      }
      setNotice(all ? '全会話の取得可能な過去履歴を順番に取り込みます' : enabled ? '取得可能な過去履歴を順番に取り込みます' : '過去履歴の取り込みを停止しました');
    } catch (e) {
      if (providerRef.current === scope && selectedRef.current === identity) setError(errorText(e));
    }
  }

  useEffect(() => {
    if (followBottom.current && !highlight) requestAnimationFrame(scrollToBottom);
    else setNewMessages(true);
  }, [history?.messages]);

  useEffect(() => {
    if (!highlight) return;
    requestAnimationFrame(() => document.getElementById(`message-${highlight}`)?.scrollIntoView({ block: 'center' }));
  }, [highlight, history, searchAnchor]);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (document.querySelector('dialog[open]')) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setSearchOpen(true); setTimeout(() => searchInput.current?.focus(), 0);
      }
      if (event.key === 'Escape') { setSettings(false); setSearchOpen(false); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);

  useEffect(() => {
    if (!searchOpen) { setSearching(false); return; }
    let cancelled = false;
    setSearch(null); setSearchError('');
    if (!query.trim()) { setSearching(false); return; }
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const result = await request<SearchResponse>({ op: 'search', query });
        if (!cancelled) setSearch(result);
      } catch (cause) { if (!cancelled) setSearchError(errorText(cause)); }
      finally { if (!cancelled) setSearching(false); }
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query, searchOpen, provider]);

  async function choose(record: Conversation, hit?: SearchResult) {
    if (busy) return;
    selectedRef.current = record.id; setSelected(record.id); setHistory(null);
    setSearchAnchor(hit ?? null); setHighlight(hit?.id ?? null); setShowChat(true);
    followBottom.current = !hit; setNewMessages(false);
    setBusy('会話を開いています'); setError(''); setNotice('');
    try {
      // Render local history immediately; provider recovery follows separately.
      await loadMessages(record.id);
      const result = await request<History>({ op: 'select', conversationId: record.id });
      if (selectedRef.current === record.id) setHistory(result);
      await loadSnapshot();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(''); composer.current?.focus(); }
  }

  async function refresh() {
    setBusy(provider === 'messenger' ? 'Messengerへ再接続しています' : '直近の履歴を取得しています'); setError('');
    try {
      await request({ op: 'refresh' });
      if (selectedRef.current) await loadMessages(selectedRef.current);
      await loadSnapshot(); setNotice(provider === 'messenger' ? 'Messengerの受信を再開しました' : '直近の履歴を更新しました');
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(''); }
  }

  async function send() {
    if (sendLock.current || !selected || !draft.trim() || draftSize > textLimit || !connected || state.storagePaused || retryBlocked || busy) return;
    sendLock.current = true;
    const identity = selected, text = draft, key = draftKey;
    setBusy('送信しています'); setError(''); setNotice('');
    try {
      await request({ op: 'send', conversationId: identity, text, requestId: crypto.randomUUID() });
      setDrafts(current => current[key] === text ? { ...current, [key]: '' } : current);
      setUncertainSends(current => { const next = { ...current }; delete next[key]; return next; });
      setNotice(`${providerLabel}が送信を受け付けました`); followBottom.current = true;
      await loadMessages(identity); await loadSnapshot();
    } catch (cause) {
      if (typeof cause === 'string' && (cause.endsWith('_SEND_UNKNOWN') || cause.endsWith('_SENT_NOT_STORED') || ['CORE_TIMEOUT', 'CORE_STOPPED'].includes(cause))) {
        setUncertainSends(current => ({ ...current, [key]: text }));
        setConfirmedRetry(false);
      }
      setError(errorText(cause));
      try { await loadSnapshot(); } catch { /* Keep the original fixed error. */ }
    } finally { sendLock.current = false; setBusy(''); composer.current?.focus(); }
  }

  async function sendImage(image: ImageDraft): Promise<boolean> {
    if (sendLock.current || !selected || !connected || state.storagePaused || busy) return false;
    sendLock.current = true;
    const identity = selected, key = draftKey;
    setBusy('画像を送信しています'); setError(''); setNotice('');
    try {
      await request({ op: 'send_image', conversationId: identity, dataUrl: image.dataUrl, requestId: crypto.randomUUID() });
      setUncertainImages(current => { const next = { ...current }; delete next[key]; return next; });
      setNotice(`${providerLabel}が画像の送信を受け付けました`); followBottom.current = true;
      await loadMessages(identity); await loadSnapshot();
      return true;
    } catch (cause) {
      // A failed upload/commit may still have reached the recipient. Never
      // mint a second request automatically, even when the Core went away.
      setUncertainImages(current => ({ ...current, [key]: image.digest }));
      setError(errorText(cause));
      try { await loadSnapshot(); } catch { /* Preserve original error. */ }
      return false;
    } finally { sendLock.current = false; setBusy(''); }
  }

  async function switchProvider(next: Provider) {
    if (busy || login) return;
    setSearchOpen(false); setShowChat(false);
    if (next === providerRef.current) return;
    providerRef.current = next; setProvider(next);
    try { localStorage.setItem('beeperlocal.provider', next); } catch { /* Preference is optional; never store content. */ }
    setState(initial); selectedRef.current = null; setSelected(null); setHistory(null);
    setQuery(''); setSearch(null); setSearchError(''); setFilter(''); setHighlight(null); setSearchAnchor(null);
    setNewMessages(false); followBottom.current = true;
    setNotice(''); setError(''); setBusy('保存済みの会話を読み込んでいます');
    try {
      const result = await loadSnapshot();
      selectedRef.current = result.selectedId; setSelected(result.selectedId);
      if (result.selectedId) await loadMessages(result.selectedId);
      if (result.connection !== 'connected' && !result.storagePaused) await connect(false);
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(''); }
  }

  const receivingLabel = state.storagePaused ? '保存停止中' : state.receiving === 'reconnecting' ? `再接続中（${state.retryAttempt ?? 1}回目）` : state.receiving === 'waiting' ? (provider === 'messenger' ? '暗号化テキストを受信待機中' : '全会話の新着を確認中') : state.receiving === 'error' ? '受信が停止しています' : state.receiving === 'recovering' || state.receiving === 'starting' ? '受信を準備中' : '受信停止中';
  const visibleConversations = state.conversations.filter(c => c.title.toLocaleLowerCase().includes(filter.toLocaleLowerCase()));
  const pending = state.pendingSends.filter(s => s.conversationId === selected);
  const rows = history?.conversationId === selected ? history.messages : [];
  const anchorOutside = searchAnchor && !rows.some(m => m.id === searchAnchor.id);

  return <div className={`app ${showChat ? 'show-chat' : ''}`}>
    <aside className="rail" aria-label="サービス">
      <div className="brand"><span className="brand-mark"><Icon name="chat" size={23}/></span><span>BeeperLocal</span></div>
      <button className={`search-launch ${searchOpen ? 'active' : ''}`} onClick={() => { setSearchOpen(true); setTimeout(() => searchInput.current?.focus(), 0); }}><Icon name="search"/><span>検索</span><kbd>⌘ K</kbd></button>
      <div className="rail-label">サービス <span aria-label="全サービスの未読">未読 {inbox.total}</span></div>
      <button className={`service ${provider === 'line' ? 'active' : ''}`} disabled={!!busy || login} onClick={() => void switchProvider('line')}><span className="line-logo">LINE</span><span>LINE</span>{!!inbox.counts.line && <span className="unread-badge" aria-label="LINEの未読">{inbox.counts.line}</span>}{inbox.failures.line && <span title={inbox.failures.line} aria-label="LINEの接続を確認してください">!</span>}<span className={`status-dot ${provider === 'line' && receiverHealthy ? 'online' : ''}`}/></button>
      <button className={`service ${provider === 'instagram' ? 'active' : ''}`} disabled={!!busy || login} onClick={() => void switchProvider('instagram')}><span className="provider-mark">◎</span><span>Instagram</span>{!!inbox.counts.instagram && <span className="unread-badge" aria-label="Instagramの未読">{inbox.counts.instagram}</span>}{inbox.failures.instagram && <span title={inbox.failures.instagram} aria-label="Instagramの接続を確認してください">!</span>}</button>
      <button className={`service ${provider === 'slack' ? 'active' : ''}`} disabled={!!busy || login} onClick={() => void switchProvider('slack')}><span className="provider-mark">#</span><span>Slack</span>{!!inbox.counts.slack && <span className="unread-badge" aria-label="Slackの未読">{inbox.counts.slack}</span>}{inbox.failures.slack && <span title={inbox.failures.slack} aria-label="Slackの接続を確認してください">!</span>}</button>
      <button className={`service ${provider === 'x' ? 'active' : ''}`} disabled={!!busy || login} onClick={() => void switchProvider('x')}><span className="provider-mark x-mark">𝕏</span><span>𝕏</span>{!!inbox.counts.x && <span className="unread-badge" aria-label="𝕏の未読">{inbox.counts.x}</span>}{inbox.failures.x && <span title={inbox.failures.x} aria-label="𝕏の接続を確認してください">!</span>}</button>
      <button className={`service ${provider === 'messenger' ? 'active' : ''}`} disabled={!!busy || login} onClick={() => void switchProvider('messenger')}><span className="provider-mark">↯</span><span>Messenger</span>{!!inbox.counts.messenger && <span className="unread-badge" aria-label="Messengerの未読">{inbox.counts.messenger}</span>}{inbox.failures.messenger && <span title={inbox.failures.messenger} aria-label="Messengerの接続を確認してください">!</span>}</button>
      <div className="rail-bottom"><button className="settings-button" onClick={() => void inbox.toggleNotifications()} aria-pressed={inbox.enabled}>通知 {inbox.enabled ? "オン" : "オフ"}</button>{inbox.notificationError && <p role="status">{inbox.notificationError}</p>}
        <UpdateButton blocked={!!busy || login || imageSelected || Object.values(drafts).some(value => value.length > 0)} busyChanged={value => { setUpdating(value); setBusy(value ? '更新を確認・適用しています' : ''); }}/>
        <button className="settings-button" aria-label="接続設定" disabled={updating} onClick={() => setSettings(true)}><Icon name="settings"/><span>接続設定</span></button>
        <button className="settings-button" aria-label="使い方・ベータ版の対応範囲" onClick={() => setHelp(true)}><Icon name="chat"/><span>使い方・対応範囲</span></button>
        <div className="local-note"><Icon name="lock" size={15}/><span>このMacに暗号化保存</span></div>
        {isDemo && <div className="demo-note">デザイン確認用・架空データ</div>}
      </div>
    </aside>

    <section className="inbox" aria-label={searchOpen ? '検索結果' : '会話一覧'}>
      <div className="inbox-title"><div><h1>{searchOpen ? '検索' : 'メッセージ'}</h1><p>{searchOpen ? 'このMacに保存した会話から' : `${state.conversations.length}件の会話`}</p></div>{searchOpen && <button className="icon-button" aria-label="検索を閉じる" onClick={() => setSearchOpen(false)}><Icon name="close"/></button>}</div>
      {searchOpen ? <div className="search-field"><Icon name="search"/><input ref={searchInput} autoFocus aria-label="保存済みメッセージを検索" placeholder="保存済みメッセージを検索" value={query} onChange={e => setQuery(e.target.value)} maxLength={500}/></div>
      : <div className="search-field"><Icon name="search" size={17}/><input aria-label="会話を絞り込む" placeholder="会話を絞り込む" value={filter} onChange={e => setFilter(e.target.value)}/></div>}
      <div className="connection-strip"><span className={`status-dot ${receiverHealthy ? 'online' : ''}`}/><span>{lineLoginRequired ? 'LINE 再ログインが必要です' : connected && state.receiving === 'reconnecting' ? `${providerLabel} 再接続中…` : connected && state.receiving === 'error' ? `${providerLabel} 受信が停止しています` : connected && state.receiving === 'starting' ? `${providerLabel} 受信を確認中…` : connected ? `${providerLabel} 接続確認済み` : state.connection === 'connecting' ? `${providerLabel}に接続中…` : state.conversations.length ? '保存済みの会話を表示' : `${providerLabel} 未接続`}</span><button onClick={() => void connect()} disabled={!!busy || !!state.storagePaused} aria-label={`${providerLabel}へ再接続`}><Icon name="refresh" size={15}/></button></div>
      {lineLoginRequired && <div className="profile-notice" role="status">保存済みの会話を表示しています。<button disabled={!!busy || !!state.storagePaused} onClick={() => setLogin(true)}>QRコードで再連携</button></div>}
      <div className="conversation-scroll">
        {narrow && !showChat && (busy || displayedError || state.storagePaused) && <div className="mobile-feedback" role={displayedError ? 'alert' : 'status'}><p>{busy || displayedError || '保存を停止中です。接続設定から再開できます。'}</p>{!busy && <button className="secondary" onClick={() => setSettings(true)}>接続設定を開く</button>}</div>}
        {searchOpen ? <>
          {!query.trim() && <div className="list-empty"><Icon name="search" size={27}/><p>メッセージを探す</p><span>言葉や相手の名前で検索できます。</span></div>}
          {searching && <p className="search-count" role="status">検索中…</p>}
          {searchError && <p className="settings-error" role="alert">検索を完了できませんでした。{searchError}</p>}
          {!searching && search && <p className="search-count">{search.results.length}件の検索結果</p>}
          {!searching && search?.results.length === 0 && <div className="list-empty"><p>見つかりませんでした</p><span>保存済みの検索範囲には一致する内容がありません。</span></div>}
          {search?.results.map(hit => <button key={hit.id} className={`search-result ${highlight === hit.id ? 'selected' : ''}`} disabled={!!busy} onClick={() => { const c = state.conversations.find(c => c.id === hit.conversationId); void choose(c ?? { id: hit.conversationId, title: hit.title, provider, preview: hit.text, lastMessageAt: hit.sentAt }, hit); }}><strong>{hit.title}</strong><span>{hit.text}</span><time>{day(hit.sentAt)}</time></button>)}
        </> : <>
          {!visibleConversations.length && <div className="list-empty"><Icon name="chat" size={30}/><p>{filter ? '一致する会話がありません' : '会話をここにまとめます'}</p><span>{filter ? '別の名前で絞り込んでください。' : `${providerLabel}へ接続すると、会話が表示されます。`}</span>{!filter && <button className="primary small" disabled={!!busy || !!state.storagePaused} onClick={() => void connect()}>{providerLabel}に接続</button>}</div>}
          {visibleConversations.map((c, index) => <button className={`conversation ${selected === c.id ? 'selected' : ''}`} disabled={!!busy} key={c.id} onClick={() => void choose(c)} onKeyDown={event => { if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); const next = event.key === 'ArrowDown' ? index + 1 : index - 1; const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('.conversation'); buttons?.[next]?.focus(); } }}>
            <Avatar conversation={c} tone={index} connected={connected}/><span className="conversation-copy"><span className="conversation-heading"><strong>{c.title}</strong>{c.lastMessageAt && <time>{listDate(c.lastMessageAt)}</time>}</span><span className="preview">{c.preview || '会話を開いて履歴を取得'}</span><span className="provider-caption">{providerLabel}{c.kind === "group" ? " · グループ" : ""} {!!c.unreadCount && <span className="unread-badge">未読 {c.unreadCount}</span>}</span></span>
          </button>)}
        </>}
      </div>
      <div className="inbox-footer">{connected && provider !== "line" && provider !== "messenger" && <button className="secondary" onClick={() => void backfill(true)} disabled={!!busy || !!state.storagePaused}>全会話の過去履歴を取得</button>}{searchOpen ? '保存済みの最新10,000件まで・最大50結果' : provider === 'messenger' ? 'この端末で取得・保存した会話を表示' : state.catalogLimited ? (provider === 'instagram' || provider === 'x' ? '会話一覧の取得範囲に制限があります' : '会話一覧の取得範囲に制限があります') : provider === 'slack' ? '本人が参加するDM・グループDM・チャンネル' : provider === 'line' ? '1対1の会話・画像・スタンプに対応' : '取得済みのDM・グループを表示'}</div>
    </section>

    <main className="chat-pane">
      {conversation ? <>
        <header className="chat-header"><button className="icon-button mobile-back" aria-label="会話一覧へ戻る" onClick={() => setShowChat(false)}><Icon name="back"/></button><Avatar conversation={conversation} compact connected={connected}/><div className="chat-person"><h2>{conversation.title}</h2><p><span className="line-word">{providerLabel}</span><span className={`status-dot ${state.receiving === 'waiting' ? 'online' : ''}`}/>{provider === 'slack' && state.receiving === 'waiting' ? '定期取得待機中（全会話を順番に・約65秒/ページ）' : receivingLabel}</p></div><button className="secondary refresh-button" onClick={refresh} disabled={!!busy || !connected || !!state.storagePaused}><Icon name="refresh" size={16}/><span>{provider === 'messenger' ? '受信を再接続' : '履歴を更新'}</span></button></header>
        <div className="activity" aria-live="polite">{busy ? <><span className="spinner"/>{busy}</> : displayedError ? <span className="error-text"><Icon name="alert" size={15}/>{displayedError}</span> : notice ? <><Icon name="check" size={15}/>{notice}</> : <><Icon name="lock" size={14}/>メッセージはこのMacに暗号化して保存されます</>}</div>
        {provider === 'slack' && state.profileErrorCode === 'MISSING_SCOPE' && <div className="profile-notice" role="status">名前とプロフィール画像を表示するには、Slack側でプロフィール閲覧の許可が必要です。<button onClick={() => setSettings(true)}>接続設定</button></div>}
        {pending.length > 0 && <div className="pending-banner" role="status">結果が未確定の送信が{pending.length}件あります。再送する前に履歴を確認してください。</div>}
        <div className="timeline" ref={timeline} onScroll={() => { const element = timeline.current; if (element) followBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 70; }} aria-label="メッセージ履歴">
          {history?.olderCursor && <button className="secondary older-history" onClick={() => void olderHistory()} disabled={!!busy}>保存済みの過去履歴を表示</button>}
          {anchorOutside && <div className="search-context"><span>検索で見つかった過去のメッセージ</span><MessageBubble provider={provider} message={searchAnchor} conversationId={conversation.id} highlighted connected={connected}/><p>以下は直近の保存済み履歴です</p></div>}
          {rows.length === 0 && <div className="empty-history"><Icon name="chat" size={33}/><p>{provider === 'x' || provider === 'messenger' ? '表示できる本文がまだありません' : 'この会話を始めましょう'}</p><span>{busy ? '履歴を取得しています。' : provider === 'x' && history?.unsupportedLegacyCount ? '未対応の形式のため表示できない履歴があります。' : '保存済みのメッセージはまだありません。'}</span></div>}
          {rows.map((message, index) => <React.Fragment key={message.id}>{(index === 0 || day(message.sentAt) !== day(rows[index - 1].sentAt)) && <div className="date-divider"><span>{day(message.sentAt)}</span></div>}<MessageBubble provider={provider} message={message} conversationId={conversation.id} highlighted={highlight === message.id} connected={connected} onMediaLoad={() => { if (followBottom.current) scrollToBottom(); }}/></React.Fragment>)}
        </div>
        {newMessages && <button className="new-messages" onClick={() => { setHighlight(null); setSearchAnchor(null); if (selected) void loadMessages(selected); scrollToBottom(); }}>新着へ ↓</button>}
        <div className="history-scope"><span>このMacの保存履歴 · 未読はこのMacで管理</span>{provider === 'x' && <span>X Chatは署名を検証 · 旧形式DMは署名なし</span>}{provider === 'x' && !!history?.legacyMessageCount && <span>旧形式の本文{history.legacyMessageCount}件（署名なし）</span>}{provider === 'x' && !!history?.unsupportedLegacyCount && <span>未対応の旧形式が{history.unsupportedLegacyCount}件あります</span>}<span>{history?.sync?.complete ? 'サービスから取得可能な範囲の終端まで取得済み' : history?.sync?.exhausted && provider !== 'line' ? '追加取得できる履歴はありません（取得範囲に制限あり）' : history?.sync?.backfill ? '過去履歴を順番に取得中' : provider === 'line' ? 'LINEが提供する直近の範囲を同期' : provider === 'messenger' ? 'この端末への配信を保存 · 暗号化バックアップ復元は未対応' : 'サービスの保存期間・取得権限の範囲で同期'}</span>{provider !== 'line' && provider !== 'messenger' && <button className="secondary" disabled={!connected || !!state.storagePaused || !!busy || !!history?.sync?.exhausted} onClick={() => void backfill()}>{history?.sync?.exhausted ? '過去履歴の取得を終了' : history?.sync?.backfill ? 'この会話の過去取得を停止' : 'この会話の過去履歴を取得'}</button>}</div>
        <ImageComposer key={draftKey} disabled={!!busy} blocked={!connected || !!state.storagePaused} recipient={conversation.title} pending={pending.flatMap(item => item.imageDigest ? [item.imageDigest] : [])} uncertain={uncertainImages[draftKey]} changed={setImageSelected} send={sendImage}>
          <textarea disabled={updating} ref={composer} aria-label="メッセージ" placeholder={state.storagePaused ? '保存を停止中です。接続設定から再開できます。' : connected ? `${conversation.title} にメッセージ` : '接続後に送信できます。下書きは入力できます。'} value={draft} maxLength={textLimit} onChange={e => { const text = e.target.value; if (selected) setDrafts(current => ({ ...current, [draftKey]: text })); }} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing && !composing.current) { event.preventDefault(); void send(); } }}/>
          <div className="composer-footer"><span>Enterで改行 · ⌘Enterで送信{provider === 'instagram' || provider === 'x' ? ` · ${draftSize}/${textLimit.toLocaleString()}バイト` : draftSize > textLimit * 0.9 ? ` · ${draftSize}/${textLimit.toLocaleString()}文字` : ''}</span><button className="primary send-button" disabled={!!busy || !connected || !!state.storagePaused || retryBlocked || !draft.trim() || draftSize > textLimit} onClick={() => void send()}><Icon name="send" size={16}/><span>{busy === '送信しています' ? '送信中' : '送信'}</span></button></div>
          {ambiguousDraft && <label className="retry-confirm"><input type="checkbox" checked={confirmedRetry} onChange={e => setConfirmedRetry(e.target.checked)}/>この下書きは送信済みの可能性があります。履歴・相手側で未着を確認して再送します。</label>}
        </ImageComposer>
      </> : <div className="welcome"><div className="welcome-icon"><Icon name="chat" size={40}/></div><span className="eyebrow">YOUR CONVERSATIONS, LOCALLY.</span><h2>いつもの会話を、このMacに。</h2><p>{provider === 'messenger' ? 'Messengerで受信した会話を、このMacで閲覧・検索できます。' : <>{providerLabel}の会話を選ぶと、履歴を読みながら<br/>そのまま返信できます。</>}</p><button className="primary welcome-connect" onClick={() => void connect()} disabled={!!busy || !!state.storagePaused} aria-busy={!!busy}><span>{providerLabel}に接続する</span>{busy ? <span className="spinner"/> : <Icon name="arrow" size={17}/>}</button><div className="welcome-feedback">{state.storagePaused && !busy ? <div className="welcome-error" role="status"><strong>保存を停止中です</strong><p>接続設定から保存を再開できます。保存済みの閲覧と検索は利用できます。</p><button className="secondary" onClick={() => setSettings(true)}>接続設定を開く</button></div> : busy ? <p className="welcome-progress" role="status">{busy}</p> : displayedError ? <div className="welcome-error" role="alert"><strong>接続を完了できませんでした</strong><p>{displayedError}</p>{(provider === 'instagram' || provider === 'slack') && <SetupButton key={provider} provider={provider} disabled={!!busy || !!state.storagePaused} changed={loadSnapshot}/>}</div> : null}</div><div className="welcome-foot"><Icon name="lock" size={15}/>ローカル保存 · キーチェーンで保護</div></div>}
    </main>

    {provider === 'line' && login && <LoginPanel existing={state.conversations.length > 0 || connected} close={() => setLogin(false)} completed={() => { setLogin(false); void connect(); }}/>}
    {provider === 'messenger' && login && <MessengerLoginPanel close={() => setLogin(false)} completed={() => { setLogin(false); void connect(); }}/>}
    {provider === 'x' && login && <XLoginPanel unlockOnly={xUnlockOnly} close={() => setLogin(false)} completed={() => { setLogin(false); void connect(); }}/>}
    <dialog ref={helpDialog} className="settings-modal" aria-labelledby="help-title" onCancel={() => setHelp(false)} onClick={event => { if (event.target === event.currentTarget) setHelp(false); }}>{help && <HelpPanel close={() => setHelp(false)} provider={provider} state={state}/>}</dialog>
    <dialog ref={settingsDialog} className="settings-modal" aria-labelledby="settings-title" onCancel={() => setSettings(false)} onClick={e => { if (e.target === e.currentTarget) setSettings(false); }}>
      {settings && <SettingsPanel key={provider} provider={provider} conversations={state.conversations} connected={connected} busy={!!busy}
        close={() => setSettings(false)} connect={() => void connect()} changed={loadSnapshot}
        login={() => { setSettings(false); setLogin(true); }}>
        {provider === 'messenger' && <MessengerSettingsPanel busy={!!busy} connected={connected} paused={!!state.storagePaused}
          connect={() => { setSettings(false); void connect(); }} login={() => { setSettings(false); setLogin(true); }}
          stop={() => { setSettings(false); void request({ op: 'stop' }).then(loadSnapshot).catch(cause => setError(errorText(cause))); }}/>}
        {provider === 'x' && <XSettingsPanel busy={!!busy} connected={connected} paused={!!state.storagePaused}
          connect={() => { setSettings(false); void connect(); }} login={() => { setSettings(false); setXUnlockOnly(false); setLogin(true); }}
          stop={() => { setSettings(false); void request({ op: 'stop' }).then(loadSnapshot).catch(cause => setError(errorText(cause))); }}/>}
        {provider === 'instagram' && <section aria-label="Instagram接続">
          <p className="settings-description">このMacで確認したInstagramログインを使い、DM・参加済みグループを順番に同期します。</p>
          <p className="settings-description">取得できる過去履歴を追加できます。受信した画像・動画・音声はクリックして表示します。添付送信・新規グループ作成・消えるメッセージは未対応です。保存データは専用の暗号化領域に保持します。</p>
          <div className="settings-actions"><button className="primary" disabled={!!busy || state.storagePaused} onClick={() => { setSettings(false); void connect(); }}>再接続・一覧更新</button><button className="secondary" disabled={!!busy || !connected || !!state.storagePaused} onClick={() => { setSettings(false); void request({ op: 'stop' }).then(loadSnapshot).catch(cause => setError(errorText(cause))); }}>受信を停止</button></div>
          <p className="settings-description">初回やログインが切れた場合は、下のボタンから本人ログインし、完了後に再接続してください。外部AIへの会話の許可は「MCP接続」で設定できます。</p>
          <SetupButton provider="instagram" disabled={!!busy || !!state.storagePaused} changed={loadSnapshot}/>
        </section>}
      </SettingsPanel>}
    </dialog>
  </div>;
}

function MessageBubble({ provider, message, conversationId, highlighted, connected, onMediaLoad }: { provider: Provider; message: Message; conversationId: string; highlighted: boolean; connected: boolean; onMediaLoad?: () => void }) {
  return <article id={`message-${message.id}`} className={`message-row ${message.direction === 'outgoing' ? 'outgoing' : 'incoming'} ${highlighted ? 'highlighted' : ''}`}><div className="message-content">{message.profile && <SlackMessageProfile {...message.profile} connected={connected} outgoing={message.direction === 'outgoing'}/>} {message.media ? <LineMedia message={message} conversationId={conversationId} connected={connected} onLoad={onMediaLoad}/> : <div className="bubble">{message.text || (message.attachments?.length ? '' : 'テキストなし')}</div>}{!!message.attachments?.length && <AttachmentMedia message={message} provider={provider} conversationId={conversationId} connected={connected} onLoad={onMediaLoad}/>}<time>{time(message.sentAt)}</time></div></article>;
}

createRoot(document.getElementById('root')!).render(<App/>);
