import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { errorText, isDemo, request as rawRequest, subscribe } from './bridge';
import type { Conversation, CoreEvent, History, Message, SearchResponse, SearchResult, Snapshot, Provider, Request } from './types';
import './style.css';
import { SettingsPanel } from './SettingsPanel';
import { LoginPanel } from './LoginPanel';
import { Avatar } from './Avatar';

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
  try { const saved = localStorage.getItem('beeperlocal.provider'); return saved === 'instagram' || saved === 'slack' ? saved : 'line'; }
  catch { return 'line'; }
}

function App() {
  const [provider, setProvider] = useState<Provider>(savedProvider);
  const providerRef = useRef<Provider>(provider);
  const providerLabel = provider === 'slack' ? 'Slack' : provider === 'instagram' ? 'Instagram' : 'LINE';
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
  const [settings, setSettings] = useState(false);
  const [login, setLogin] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
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
  const scrollToBottom = () => { timeline.current?.scrollTo({ top: timeline.current.scrollHeight }); setNewMessages(false); followBottom.current = true; };
  const conversation = state.conversations.find(c => c.id === selected);
  const draft = selected ? drafts[selected] ?? '' : '';
  const connected = state.connection === 'connected';
  const displayedError = error || (state.errorCode ? errorText(state.errorCode) : '');
  const draftSize = provider === 'instagram' ? new TextEncoder().encode(draft).length : draft.length;
  const textLimit = provider === 'line' ? 10000 : 4000;

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

  async function connect() {
    if (connectLock.current) return;
    connectLock.current = true;
    setBusy(`${providerRef.current === 'slack' ? 'Slack' : providerRef.current === 'instagram' ? 'Instagram' : 'LINE'}に接続しています`); setError(''); setNotice('');
    try {
      const result = await request<Snapshot>({ op: 'connect' });
      setState(result);
      const identity = result.selectedId;
      selectedRef.current = identity; setSelected(identity);
      if (identity) await loadMessages(identity);
      setNotice(`${providerRef.current === 'slack' ? 'Slack' : providerRef.current === 'instagram' ? 'Instagram' : 'LINE'}への接続を確認しました`);
    } catch (cause) { if (providerRef.current === 'line' && cause === 'LINE_LOGIN_REQUIRED') { setLogin(true); setError(''); } else setError(errorText(cause)); }
    finally { connectLock.current = false; setBusy(''); }
  }

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const onEvent = (event: CoreEvent) => {
      if (disposed || (event.event !== 'fatal' && (event.provider ?? 'line') !== providerRef.current)) return;
      if (event.event === 'status') {
        setState(current => ({ ...current, connection: event.connection ?? current.connection,
          receiving: event.receiving ?? current.receiving, errorCode: event.errorCode ?? null,
          storagePaused: event.storagePaused ?? current.storagePaused, retryAttempt: event.retryAttempt ?? current.retryAttempt }));
      }
      if (event.event === 'data_cleared') {
        selectedRef.current = null; setSelected(null); setHistory(null); setSearch(null); setQuery('');
        setSearchAnchor(null); setHighlight(null); setDrafts({}); setNotice(''); setError('');
        void loadSnapshot();
      }
      if (event.event === 'fatal') setError(errorText(event.error));
      if (event.event === 'messages_changed') {
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(async () => {
          if (disposed || (event.provider ?? 'line') !== providerRef.current) return;
          try {
            await loadSnapshot();
            if (selectedRef.current) await loadMessages(selectedRef.current);
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
        if (!disposed && !result.storagePaused) await connect();
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
    if (followBottom.current && !highlight) requestAnimationFrame(scrollToBottom);
    else setNewMessages(true);
  }, [history?.messages]);

  useEffect(() => {
    if (!highlight) return;
    requestAnimationFrame(() => document.getElementById(`message-${highlight}`)?.scrollIntoView({ block: 'center' }));
  }, [highlight, history, searchAnchor]);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setSearchOpen(true); setTimeout(() => searchInput.current?.focus(), 0);
      }
      if (event.key === 'Escape') { setSettings(false); setSearchOpen(false); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, []);

  useEffect(() => {
    if (!searchOpen) return;
    let cancelled = false;
    if (!query.trim()) { setSearch(null); setSearching(false); return; }
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const result = await request<SearchResponse>({ op: 'search', query });
        if (!cancelled) setSearch(result);
      } catch (cause) { if (!cancelled) setError(errorText(cause)); }
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
    setBusy('直近の履歴を取得しています'); setError('');
    try {
      await request({ op: 'refresh' });
      if (selectedRef.current) await loadMessages(selectedRef.current);
      await loadSnapshot(); setNotice('直近の履歴を更新しました');
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(''); }
  }

  async function send() {
    if (sendLock.current || !selected || !draft.trim() || draftSize > textLimit || !connected || busy) return;
    sendLock.current = true;
    const identity = selected, text = draft;
    setBusy('送信しています'); setError(''); setNotice('');
    try {
      await request({ op: 'send', conversationId: identity, text, requestId: crypto.randomUUID() });
      setDrafts(current => current[identity] === text ? { ...current, [identity]: '' } : current);
      setNotice(`${providerLabel}が送信を受け付けました`); followBottom.current = true;
      await loadMessages(identity); await loadSnapshot();
    } catch (cause) {
      setError(errorText(cause));
      try { await loadSnapshot(); } catch { /* Keep the original fixed error. */ }
    } finally { sendLock.current = false; setBusy(''); composer.current?.focus(); }
  }

  async function switchProvider(next: Provider) {
    if (busy || login) return;
    setSearchOpen(false); setShowChat(false);
    if (next === providerRef.current) return;
    providerRef.current = next; setProvider(next);
    try { localStorage.setItem('beeperlocal.provider', next); } catch { /* Preference is optional; never store content. */ }
    setState(initial); selectedRef.current = null; setSelected(null); setHistory(null);
    setQuery(''); setSearch(null); setFilter(''); setHighlight(null); setSearchAnchor(null);
    setNewMessages(false); followBottom.current = true;
    setNotice(''); setError(''); setBusy('保存済みの会話を読み込んでいます');
    try {
      const result = await loadSnapshot();
      selectedRef.current = result.selectedId; setSelected(result.selectedId);
      if (result.selectedId) await loadMessages(result.selectedId);
      if (result.connection !== 'connected' && !result.storagePaused) await connect();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(''); }
  }

  const receivingLabel = state.storagePaused ? '保存停止中' : state.receiving === 'reconnecting' ? `再接続中（${state.retryAttempt ?? 1}回目）` : state.receiving === 'waiting' ? 'この会話を受信待機中' : state.receiving === 'error' ? '受信が停止しています' : state.receiving === 'recovering' || state.receiving === 'starting' ? '受信を準備中' : '受信停止中';
  const visibleConversations = state.conversations.filter(c => c.title.toLocaleLowerCase().includes(filter.toLocaleLowerCase()));
  const pending = state.pendingSends.filter(s => s.conversationId === selected);
  const rows = history?.conversationId === selected ? history.messages : [];
  const anchorOutside = searchAnchor && !rows.some(m => m.id === searchAnchor.id);

  return <div className={`app ${showChat ? 'show-chat' : ''}`}>
    <aside className="rail" aria-label="サービス">
      <div className="brand"><span className="brand-mark"><Icon name="chat" size={23}/></span><span>BeeperLocal</span></div>
      <button className={`search-launch ${searchOpen ? 'active' : ''}`} onClick={() => { setSearchOpen(true); setTimeout(() => searchInput.current?.focus(), 0); }}><Icon name="search"/><span>検索</span><kbd>⌘ K</kbd></button>
      <div className="rail-label">サービス</div>
      <button className={`service ${provider === 'line' ? 'active' : ''}`} disabled={!!busy || login} onClick={() => void switchProvider('line')}><span className="line-logo">LINE</span><span>LINE</span><span className={`status-dot ${provider === 'line' && connected ? 'online' : ''}`}/></button>
      <button className={`service ${provider === 'instagram' ? 'active' : ''}`} disabled={!!busy || login} onClick={() => void switchProvider('instagram')}><span className="provider-mark">◎</span><span>Instagram</span></button>
      <button className={`service ${provider === 'slack' ? 'active' : ''}`} disabled={!!busy || login} onClick={() => void switchProvider('slack')}><span className="provider-mark">#</span><span>Slack</span></button>
      <button className="service" disabled><span className="provider-mark x-mark">𝕏</span><span>𝕏<small>準備中</small></span></button>
      <div className="rail-bottom">
        <button className="settings-button" onClick={() => setSettings(true)}><Icon name="settings"/><span>接続設定</span></button>
        <div className="local-note"><Icon name="lock" size={15}/><span>このMacに暗号化保存</span></div>
        {isDemo && <div className="demo-note">デザイン確認用・架空データ</div>}
      </div>
    </aside>

    <section className="inbox" aria-label={searchOpen ? '検索結果' : '会話一覧'}>
      <div className="inbox-title"><div><h1>{searchOpen ? '検索' : 'メッセージ'}</h1><p>{searchOpen ? 'このMacに保存した会話から' : `${state.conversations.length}件の会話`}</p></div>{searchOpen && <button className="icon-button" aria-label="検索を閉じる" onClick={() => setSearchOpen(false)}><Icon name="close"/></button>}</div>
      {searchOpen ? <div className="search-field"><Icon name="search"/><input ref={searchInput} autoFocus aria-label="保存済みメッセージを検索" placeholder="保存済みメッセージを検索" value={query} onChange={e => setQuery(e.target.value)} maxLength={500}/></div>
      : <div className="search-field"><Icon name="search" size={17}/><input aria-label="会話を絞り込む" placeholder="会話を絞り込む" value={filter} onChange={e => setFilter(e.target.value)}/></div>}
      <div className="connection-strip"><span className={`status-dot ${connected ? 'online' : ''}`}/><span>{connected ? `${providerLabel} 接続確認済み` : state.connection === 'connecting' ? `${providerLabel}に接続中…` : state.conversations.length ? '保存済みの会話を表示' : `${providerLabel} 未接続`}</span><button onClick={connect} disabled={!!busy} aria-label={`${providerLabel}へ再接続`}><Icon name="refresh" size={15}/></button></div>
      <div className="conversation-scroll">
        {searchOpen ? <>
          {!query.trim() && <div className="list-empty"><Icon name="search" size={27}/><p>メッセージを探す</p><span>言葉や相手の名前で検索できます。</span></div>}
          {searching && <p className="search-count" role="status">検索中…</p>}
          {!searching && search && <p className="search-count">{search.results.length}件の検索結果</p>}
          {!searching && search?.results.length === 0 && <div className="list-empty"><p>見つかりませんでした</p><span>保存済みの検索範囲には一致する内容がありません。</span></div>}
          {search?.results.map(hit => <button key={hit.id} className={`search-result ${highlight === hit.id ? 'selected' : ''}`} disabled={!!busy} onClick={() => { const c = state.conversations.find(c => c.id === hit.conversationId); if (c) void choose(c, hit); }}><strong>{hit.title}</strong><span>{hit.text}</span><time>{day(hit.sentAt)}</time></button>)}
        </> : <>
          {!visibleConversations.length && <div className="list-empty"><Icon name="chat" size={30}/><p>{filter ? '一致する会話がありません' : '会話をここにまとめます'}</p><span>{filter ? '別の名前で絞り込んでください。' : `${providerLabel}へ接続すると、会話が表示されます。`}</span>{!filter && <button className="primary small" disabled={!!busy} onClick={connect}>{providerLabel}に接続</button>}</div>}
          {visibleConversations.map((c, index) => <button className={`conversation ${selected === c.id ? 'selected' : ''}`} disabled={!!busy} key={c.id} onClick={() => void choose(c)} onKeyDown={event => { if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); const next = event.key === 'ArrowDown' ? index + 1 : index - 1; const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('.conversation'); buttons?.[next]?.focus(); } }}>
            <Avatar conversation={c} tone={index} connected={connected}/><span className="conversation-copy"><span className="conversation-heading"><strong>{c.title}</strong>{c.lastMessageAt && <time>{listDate(c.lastMessageAt)}</time>}</span><span className="preview">{c.preview || '会話を開いて履歴を取得'}</span><span className="provider-caption">{providerLabel}</span></span>
          </button>)}
        </>}
      </div>
      <div className="inbox-footer">{searchOpen ? '保存済みの最新10,000件まで・最大50結果' : state.catalogLimited ? (provider === 'instagram' ? '取得できたDMのみ表示・全会話の取得は未対応' : '一覧は最大500件まで表示') : provider === 'slack' ? '本人が参加するDM・グループDM・チャンネル' : '1対1のテキスト会話に対応'}</div>
    </section>

    <main className="chat-pane">
      {conversation ? <>
        <header className="chat-header"><button className="icon-button mobile-back" aria-label="会話一覧へ戻る" onClick={() => setShowChat(false)}><Icon name="back"/></button><Avatar conversation={conversation} compact connected={connected}/><div className="chat-person"><h2>{conversation.title}</h2><p><span className="line-word">{providerLabel}</span><span className={`status-dot ${state.receiving === 'waiting' ? 'online' : ''}`}/>{provider === 'slack' && state.receiving === 'waiting' ? '定期取得待機中（約65秒ごと）' : receivingLabel}</p></div><button className="secondary refresh-button" onClick={refresh} disabled={!!busy || !connected}><Icon name="refresh" size={16}/><span>履歴を更新</span></button></header>
        <div className="activity" aria-live="polite">{busy ? <><span className="spinner"/>{busy}</> : displayedError ? <span className="error-text"><Icon name="alert" size={15}/>{displayedError}</span> : notice ? <><Icon name="check" size={15}/>{notice}</> : <><Icon name="lock" size={14}/>メッセージはこのMacに暗号化して保存されます</>}</div>
        {pending.length > 0 && <div className="pending-banner" role="status">結果が未確定の送信が{pending.length}件あります。再送する前に履歴を確認してください。</div>}
        <div className="timeline" ref={timeline} onScroll={() => { const element = timeline.current; if (element) followBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 70; }} aria-label="メッセージ履歴">
          {anchorOutside && <div className="search-context"><span>検索で見つかった過去のメッセージ</span><MessageBubble message={searchAnchor} highlighted/><p>以下は直近の保存済み履歴です</p></div>}
          {rows.length === 0 && <div className="empty-history"><Icon name="chat" size={33}/><p>この会話を始めましょう</p><span>{busy ? '履歴を取得しています。' : '保存済みのテキストメッセージはまだありません。'}</span></div>}
          {rows.map((message, index) => <React.Fragment key={message.id}>{(index === 0 || day(message.sentAt) !== day(rows[index - 1].sentAt)) && <div className="date-divider"><span>{day(message.sentAt)}</span></div>}<MessageBubble message={message} highlighted={highlight === message.id}/></React.Fragment>)}
        </div>
        {newMessages && <button className="new-messages" onClick={() => { setHighlight(null); setSearchAnchor(null); scrollToBottom(); }}>新着へ ↓</button>}
        <div className="history-scope">直近{history?.historyLimit ?? (provider === 'instagram' ? 20 : provider === 'slack' ? 15 : 100)}件までの履歴を確認{history?.lastRecovery ? ` · 最終取得 ${time(history.lastRecovery)}` : ''}<span>{provider === 'slack' ? 'スレッドはMCPから個別取得・ファイル本文と既読は未対応' : '画像・スタンプ・既読は未対応'}</span></div>
        <section className="composer" aria-label="メッセージを作成">
          <textarea ref={composer} aria-label="メッセージ" placeholder={connected ? `${conversation.title} にメッセージ` : '接続後に送信できます。下書きは入力できます。'} value={draft} maxLength={textLimit} onChange={e => { const text = e.target.value; if (selected) setDrafts(current => ({ ...current, [selected]: text })); }} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing && !composing.current) { event.preventDefault(); void send(); } }}/>
          <div className="composer-footer"><span>Enterで改行 · ⌘Enterで送信{provider === 'instagram' ? ` · ${draftSize}/4,000バイト` : draft.length > 9000 ? ` · ${draft.length}/10,000` : ''}</span><button className="primary send-button" disabled={!!busy || !connected || !draft.trim() || draftSize > textLimit} onClick={() => void send()}><Icon name="send" size={16}/><span>{busy === '送信しています' ? '送信中' : '送信'}</span></button></div>
        </section>
      </> : <div className="welcome"><div className="welcome-icon"><Icon name="chat" size={40}/></div><span className="eyebrow">YOUR CONVERSATIONS, LOCALLY.</span><h2>いつもの会話を、このMacに。</h2><p>{providerLabel}の会話を選ぶと、履歴を読みながら<br/>そのまま返信できます。</p><button className="primary welcome-connect" onClick={connect} disabled={!!busy} aria-busy={!!busy}><span>{providerLabel}に接続する</span>{busy ? <span className="spinner"/> : <Icon name="arrow" size={17}/>}</button><div className="welcome-feedback">{busy ? <p className="welcome-progress" role="status">{busy}</p> : displayedError ? <div className="welcome-error" role="alert"><strong>接続を完了できませんでした</strong><p>{displayedError}</p></div> : null}</div><div className="welcome-foot"><Icon name="lock" size={15}/>ローカル保存 · キーチェーンで保護</div></div>}
    </main>

    {provider === 'line' && login && <LoginPanel existing={state.conversations.length > 0 || connected} close={() => setLogin(false)} completed={() => { setLogin(false); void connect(); }}/>}
    <dialog ref={settingsDialog} className="settings-modal" aria-labelledby="settings-title" onCancel={() => setSettings(false)} onClick={e => { if (e.target === e.currentTarget) setSettings(false); }}>{settings && (provider !== 'instagram' ? <SettingsPanel key={provider} provider={provider} conversations={state.conversations} connected={connected} busy={!!busy} close={() => setSettings(false)} connect={() => void connect()} changed={loadSnapshot} login={() => { setSettings(false); setLogin(true); }}/> : <div className="settings-content"><div className="modal-heading"><h2 id="settings-title">Instagram接続</h2><button className="icon-button" aria-label="設定を閉じる" onClick={() => setSettings(false)}>×</button></div><p className="settings-description">このMacで確認したInstagramログインと保存済みの会話を使います。選択中の1対1テキストDMを受信します。</p><p className="settings-description">履歴は直近の1ページ（最大20件）です。全履歴・グループ・画像・消えるメッセージには対応していません。保存データはLINEとは別の暗号化領域に保持します。</p><div className="settings-actions"><button className="primary" disabled={!!busy || state.storagePaused} onClick={() => { setSettings(false); void connect(); }}>再接続・一覧更新</button><button className="secondary" disabled={!!busy || !connected} onClick={() => { setSettings(false); void request({ op: 'stop' }).then(loadSnapshot).catch(cause => setError(errorText(cause))); }}>受信を停止</button><button className="secondary" disabled={!!busy} onClick={() => { setSettings(false); void request({ op: 'storage_pause', paused: !state.storagePaused }).then(loadSnapshot).catch(cause => setError(errorText(cause))); }}>{state.storagePaused ? '保存を再開' : '保存を停止'}</button></div><p className="settings-description">ログインが切れた場合はInstagram接続.commandを実行し、本人確認後に再接続してください。Instagramの保存データ削除とMCP接続は未対応です。</p><p className="version">BeeperLocal 0.8.3 · Mac開発版</p></div>)}</dialog>
  </div>;
}

function MessageBubble({ message, highlighted }: { message: Message; highlighted: boolean }) {
  return <article id={`message-${message.id}`} className={`message-row ${message.direction === 'outgoing' ? 'outgoing' : 'incoming'} ${highlighted ? 'highlighted' : ''}`}><div className="message-content"><div className="bubble">{message.text || 'テキストなし'}</div><time>{time(message.sentAt)}</time></div></article>;
}

createRoot(document.getElementById('root')!).render(<App/>);
