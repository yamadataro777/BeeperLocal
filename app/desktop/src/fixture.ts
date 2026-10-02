// Development-only transport. Never included in the production bridge branch.
import type { CoreEvent, Request, Snapshot, Message, History, Management, LoginState } from './types';
const one = 'a'.repeat(64), two = 'b'.repeat(64);
const messages: Record<string, Message[]> = {
  [one]: [
    { id: '1', text: '週末、少し早めに集まろうか。', sentAt: '2026-09-30T03:12:00Z', direction: 'incoming', attachmentCount: 0 },
    { id: '2', text: 'いいね。11時にいつものカフェでどう？', sentAt: '2026-09-30T03:13:00Z', direction: 'outgoing', attachmentCount: 0 },
    { id: '3', text: '了解！楽しみにしてる。', sentAt: '2026-09-30T03:14:00Z', direction: 'incoming', attachmentCount: 0 },
  ],
  [two]: [{ id: '4', text: '資料を確認しました。ありがとうございます。', sentAt: '2026-09-29T08:00:00Z', direction: 'incoming', attachmentCount: 0 }],
};
let state: Snapshot = { connection: 'offline', receiving: 'stopped', errorCode: null, selectedId: one, catalogLimited: false, pendingSends: [], conversations: [
  { id: one, title: '山田 はな（架空）', provider: 'line', avatarVersion: 'fixture', preview: '了解！楽しみにしてる。', lastMessageAt: '2026-09-30T03:14:00Z' },
  { id: two, title: '佐藤 りく（架空）', provider: 'line', avatarVersion: 'fixture', preview: '資料を確認しました。ありがとうございます。', lastMessageAt: '2026-09-29T08:00:00Z' },
] };
let management: Management = { mcp: { enabled: false, running: false, port: 28641, url: 'http://127.0.0.1:28641/mcp', errorCode: null }, clients: [], storage: { paused: false, path: '/fixture/messages.sqlite3', counts: { messages: 4, conversations: 2, outgoing_requests: 0 }, retention: 'until_deleted' }, accountAvailable: true };
const listeners = new Set<(event: CoreEvent) => void>();
const scenario = new URLSearchParams(location.search).get('scenario');
let keychainFailedOnce = false;
let login: LoginState = { stage: 'idle' };
let loginAt = 0, loggedIn = false;
const onboarding = scenario?.startsWith('onboarding');
if (onboarding) { state.conversations = []; state.selectedId = null; }
const matrix = Array.from({length: 21}, (_, y) => Array.from({length: 21}, (_, x) => (x * y + x + y) % 3 === 0));
const history = (id: string): History => ({ conversationId: id, messages: messages[id] ?? [], lastRecovery: new Date().toISOString(), historyLimit: 100, historyLimited: true, limitReached: false });
export function subscribe(callback: (event: CoreEvent) => void) { listeners.add(callback); return () => { listeners.delete(callback); }; }
export async function request(value: Request) {
  if (value.provider === 'instagram') return instagramRequest(value);
  if (value.provider === 'slack') return slackRequest(value);
  await new Promise(resolve => setTimeout(resolve, 80));
  if (['snapshot', 'connect'].includes(value.op) && (scenario === 'keychain-session' || (scenario === 'keychain-once' && !keychainFailedOnce))) {
    keychainFailedOnce = true;
    throw 'KEYCHAIN_SESSION_AUTH_FAILED';
  }
  switch (value.op) {
    case 'avatar': return { image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', pending: false };
    case 'line_login_start':
      loginAt = Date.now(); login = { stage: 'code', matrix };
      return structuredClone(login);
    case 'line_login_status':
      if (login.stage !== 'idle' && login.stage !== 'cancelled') {
        const elapsed = Date.now() - loginAt;
        if (scenario === 'onboarding-success' && elapsed > 2400) { loggedIn = true; login = { stage: 'completed' }; }
        else if (scenario === 'onboarding-success' && elapsed > 1000) login = { stage: 'pin', pin: '123456' };
        else if (scenario === 'onboarding-failed' && elapsed > 1000) login = { stage: 'failed', errorCode: 'LINE_LOGIN_FAILED' };
      }
      return structuredClone(login);
    case 'line_login_cancel': if (login.stage !== 'completed') login = { stage: 'cancelled' }; return structuredClone(login);
    case 'management': return structuredClone(management);
    case 'mcp_configure': management.mcp = { enabled: value.enabled, running: value.enabled, port: value.port, url: `http://127.0.0.1:${value.port}/mcp`, errorCode: null }; return structuredClone(management);
    case 'mcp_register': {
      const client = { id: crypto.randomUUID(), name: value.name, conversationIds: value.conversationIds, read: value.read, send: value.send, createdAt: new Date().toISOString() };
      management.clients.push(client);
      return { client, token: 'blc_FIXTURE_TOKEN_SHOWN_ONCE', url: management.mcp.url };
    }
    case 'mcp_revoke': management.clients = management.clients.filter(c => c.id !== value.clientId); return structuredClone(management);
    case 'storage_pause':
      management.storage.paused = value.paused;
      state.storagePaused = value.paused;
      if (value.paused) { state.connection = 'offline'; state.receiving = 'stopped'; }
      return structuredClone(management);
    case 'storage_delete_preview': management.storage.paused = true; state.storagePaused = true; state.connection = 'offline'; state.receiving = 'stopped'; return { confirmation: 'fixture-confirmation', counts: management.storage.counts, expiresInSeconds: 120 };
    case 'storage_delete':
      if (value.confirmation !== 'fixture-confirmation') throw 'DELETE_CONFIRMATION_EXPIRED';
      Object.keys(messages).forEach(key => delete messages[key]); state.conversations = []; state.selectedId = null;
      management.clients = []; management.mcp.enabled = management.mcp.running = false; management.storage.counts = {};
      listeners.forEach(fn => fn({ event: 'data_cleared', ...state }));
      return { management: structuredClone(management) };
    case 'snapshot': return structuredClone(state);
    case 'connect': if (onboarding && !loggedIn) throw 'LINE_LOGIN_REQUIRED'; state = { ...state, connection: 'connected', receiving: 'waiting' }; return structuredClone(state);
    case 'select': state.selectedId = value.conversationId; return history(value.conversationId);
    case 'messages': return history(value.conversationId);
    case 'stop': state = { ...state, connection: 'offline', receiving: 'stopped' }; return structuredClone(state);
    case 'refresh': return { inserted: 0, updated: 3, historyLimited: true };
    case 'search': return { results: Object.entries(messages).flatMap(([id, rows]) => rows.filter(m => m.text.includes(value.query)).map(m => ({ ...m, conversationId: id, title: state.conversations.find(c => c.id === id)!.title }))), scanned: 4, scanLimit: 10000 };
    case 'send': {
      if (value.text === '結果不明のテスト') throw 'LINE_SEND_UNKNOWN';
      const message: Message = { id: value.requestId, text: value.text, direction: 'outgoing', sentAt: new Date().toISOString(), attachmentCount: 0 };
      messages[value.conversationId].push(message);
      listeners.forEach(fn => fn({ event: 'messages_changed', conversationId: value.conversationId }));
      return { status: 'acknowledged', messageId: message.id };
    }
  }
}

const slackId = 'd'.repeat(64);
const slackRows: Message[] = [{ id: 'slack-root', text: 'Slackの架空メッセージです。', sentAt: '2026-10-01T03:00:00Z', direction: 'incoming', attachmentCount: 0 }];
let slackState: Snapshot = { connection: 'offline', receiving: 'stopped', selectedId: slackId, errorCode: null, catalogLimited: false, pendingSends: [], conversations: [{ id: slackId, title: 'Slackテスト（架空）', provider: 'slack', preview: slackRows[0].text, lastMessageAt: slackRows[0].sentAt }] };
let slackManagement: Management = { mcp: { enabled: false, running: false, port: 28642, url: 'http://127.0.0.1:28642/mcp', errorCode: null }, clients: [], storage: { paused: false, path: '/fixture/messages.sqlite3', counts: {}, retention: 'until_deleted' }, accountAvailable: true };
async function slackRequest(value: Request) {
  await new Promise(resolve => setTimeout(resolve, 80));
  switch (value.op) {
    case 'snapshot': return structuredClone(slackState);
    case 'connect': slackState.connection = 'connected'; slackState.receiving = 'waiting'; return structuredClone(slackState);
    case 'messages': case 'select': return { conversationId: slackId, messages: structuredClone(slackRows), historyLimit: 15, historyLimited: true, limitReached: false, lastRecovery: new Date().toISOString() };
    case 'stop': slackState.connection = 'offline'; slackState.receiving = 'stopped'; return structuredClone(slackState);
    case 'refresh': return { inserted: 0, updated: slackRows.length, historyLimited: true };
    case 'search': return { results: slackRows.filter(m => m.text.includes(value.query)).map(m => ({ ...m, conversationId: slackId, title: 'Slackテスト（架空）' })), scanned: slackRows.length, scanLimit: 10000 };
    case 'send': {
      if (value.conversationId !== slackId) throw 'CONVERSATION_UNAVAILABLE';
      if (value.text === '結果不明のテスト') { slackState.pendingSends.push({ requestId: value.requestId, conversationId: slackId, text: value.text, status: 'unknown', createdAt: new Date().toISOString() }); throw 'SLACK_SEND_UNKNOWN'; }
      if (!slackRows.some(m => m.id === value.requestId)) slackRows.push({ id: value.requestId, text: value.text, sentAt: new Date().toISOString(), direction: 'outgoing', attachmentCount: 0 });
      listeners.forEach(fn => fn({ event: 'messages_changed', provider: 'slack', conversationId: slackId }));
      return { status: 'acknowledged', messageId: value.requestId };
    }
    case 'management': return structuredClone(slackManagement);
    case 'mcp_configure': slackManagement.mcp = { enabled: value.enabled, running: value.enabled, port: value.port, url: `http://127.0.0.1:${value.port}/mcp`, errorCode: null }; return structuredClone(slackManagement);
    case 'mcp_register': {
      const client = { id: crypto.randomUUID(), name: value.name, conversationIds: value.conversationIds, read: value.read, send: value.send, createdAt: new Date().toISOString() };
      slackManagement.clients.push(client); return { client, token: 'blc_SLACK_FIXTURE_ONLY', url: slackManagement.mcp.url };
    }
    case 'mcp_revoke': slackManagement.clients = slackManagement.clients.filter(c => c.id !== value.clientId); return structuredClone(slackManagement);
    case 'storage_pause': slackManagement.storage.paused = value.paused; slackState.storagePaused = value.paused; if (value.paused) { slackState.connection = 'offline'; slackState.receiving = 'stopped'; } return structuredClone(slackManagement);
    default: throw 'INVALID_INPUT';
  }
}

const igId = 'c'.repeat(64);
const igMessages: Message[] = [{ id: 'ig-1', text: 'Instagramの架空メッセージです。', sentAt: '2026-09-30T04:00:00Z', direction: 'incoming', attachmentCount: 0 }];
let igState: Snapshot = { connection: 'offline', receiving: 'stopped', selectedId: igId, errorCode: null, catalogLimited: true, pendingSends: [], conversations: [{ id: igId, title: 'Instagramの友人（架空）', provider: 'instagram', preview: igMessages[0].text, lastMessageAt: igMessages[0].sentAt }] };
export function emitStatus(provider: 'line' | 'instagram', patch: Partial<Snapshot>) {
  if (provider === 'instagram') igState = { ...igState, ...patch };
  else state = { ...state, ...patch };
  listeners.forEach(fn => fn({ event: 'status', provider, ...patch }));
}
function igHistory(): History { return { conversationId: igId, messages: structuredClone(igMessages), lastRecovery: new Date().toISOString(), historyLimit: 20, historyLimited: true, limitReached: true }; }
async function instagramRequest(value: Request) {
  await new Promise(resolve => setTimeout(resolve, 80));
  switch (value.op) {
    case 'snapshot': return structuredClone(igState);
    case 'connect': igState.connection = 'connected'; igState.receiving = 'waiting'; return structuredClone(igState);
    case 'messages': case 'select': if (value.conversationId !== igId) throw 'CONVERSATION_UNAVAILABLE'; return igHistory();
    case 'stop': igState.connection = 'offline'; igState.receiving = 'stopped'; return structuredClone(igState);
    case 'storage_pause': igState.storagePaused = value.paused; if (value.paused) { igState.connection = 'offline'; igState.receiving = 'stopped'; } return structuredClone(igState);
    case 'refresh': return { inserted: 0 };
    case 'search': return { results: igMessages.filter(m => m.text.includes(value.query)).map(m => ({ ...m, conversationId: igId, title: igState.conversations[0].title })), scanned: igMessages.length, scanLimit: 10000 };
    case 'send': {
      if (value.conversationId !== igId) throw 'CONVERSATION_UNAVAILABLE';
      if (value.text === '結果不明のテスト') { igState.pendingSends.push({ requestId: value.requestId, conversationId: igId, text: value.text, status: 'unknown', createdAt: new Date().toISOString() }); throw 'IG_SEND_UNKNOWN'; }
      const message: Message = { id: value.requestId, text: value.text, sentAt: new Date().toISOString(), direction: 'outgoing', attachmentCount: 0 };
      igMessages.push(message);
      listeners.forEach(fn => fn({ event: 'messages_changed', provider: 'instagram', conversationId: igId }));
      return { status: 'acknowledged', messageId: message.id };
    }
    default: throw 'INVALID_INPUT';
  }
}
