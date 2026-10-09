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
const mediaPhoto = 'data:image/png;base64,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';
const mediaSticker = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAALQAAAC0CAYAAAA9zQYyAAAEs0lEQVR4nO3d3Y1TOxhG4TiiECqIRC90Qh10Qi9IUwGdbK4iMYGQTJJtvz/rueTinG175RtPZiCHAwAAAAAAAAAAAAAAAAAAAAAAAAAAaDBWP0CK7efX7dn/xvjyg/N4Ehu4INyPIvT7EbRgwLcQ+HUEbRLxNcT9HkEbRnzN4A7eHXRCxNeM0rgrF50ccnvYVYttCrk17IpFNofcFnb04gi5L+zjIRQxd+5P3Ks09aD2NIKmddSEJubHJO1bxCsz6UBWG+bT2n5CEzP7GRM0MbOvlyy/vBDyPMPsCmI3oYmZ/Y4JmpjZ95igiZn9jwmamDVsBm+PygftsIlNNvHzkA5affNabcLnIhu08qbhIHs+kkGrbhb0z0kuaMVNgs95yQUNxASt9mqH37nJBK20KfA9P4mgVTYD/ucoETQQE7TCqxo553lsXjzyznX5hAYigmY6Z9sWTeklQRNzh21B1Fw5EGV60EznLtvkKc2ERpSpQTOdO20TpzQTGlGmBc107rZNmtJMaESZEjTTGbM6YEIjCkEjyu5Bc93AzB4+Hcqcvv3668/evn8+pDiFr++WqivHvw77f3/u5hS+vuVBK103bh2q+6E7rW/bsYuKCX3vYSod+kekr+8jKoJGj2PDdQN69uqDCY0oBI0oFUHf+z6s6/u16etbHrTi/fnWYboftuP6th06qZjQtw5V8bAf8Ra+vnuMlgmNjk+qrZrQyEfQiELQiPLyoLk/Y2UvTGhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEIWhEOar/pUdkG/wlWeA6rhyIEv2RFO0fz9C4D0xoRCFoRNklaN7pwKpO6iZ0w+eMNK83OujUb3ye9Ra8L9FBo89uQXOPxoo+jo1fXlvulaei959rgkaXXYNWvnakT+mT8Pr27KJiQl/7Mqt86M84XVlX+nWjJuiWw/yflvXvHrTytSNxSp/E17N3DzUTuuHqcSq+alQGnRw1MU8MWv3a4R61y3OPCR3UTehbX4Jd4rjned+KrhpnUyen2idk3YpXOQi3Zx+TvkpXB33vRFaKw+15o4NWjdohFPXnU/keiqAfuD/PDEfxmT4qOmjlKf3IN4V7hKTwDK7vcBH0i9/teCSumf+v2SqCVp/S6m/jOYS86ucPS3/g4RK1StguIa/8YVr0v5y0R0wrwnYKebXlP5J2mtKX9ozbOeKx8FcdlgftHvUrIneOV+33drhyvFhSnI4kfjlp9asaOecoEbTKZsD//GSCVtoU+J6bVNDAs+SCVnq1w++85IJW3CT4nJNk0KqbBf3zkQ1aedPaDeFzkQ5affMaDfHzkA/aYRNbDINzsAjaZTOTDZP9twnaaVPTDKN9twrabXMTDLP9tnrY5F87VTPMQrad0Ambrm4Y76t10O6br2iY76f1w1/iCtIbcsyETjyU2UbQvsUs5BLTuivkyAmdflivNEL3J3JRl5jW+SGfRS/uUnPYIzzks4pFNoc9SkI+q1psU9ijLOSzykWnxj1KI/5T/Qa4x03E7xG0YdxEfB1BGwROwPcjaKHQCRcAAAAAAAAAAAAAAAAAAAAAAAAAcNjPb7IpAu2CRpaaAAAAAElFTkSuQmCC';
const mediaPolls = new Map<string, number>();
if (scenario?.startsWith('line-media')) {
  messages[one] = [
    { id: 'media-photo', text: '画像', sentAt: '2026-10-02T03:14:00Z', direction: 'incoming', attachmentCount: 1, media: { kind: 'image' } },
    { id: 'media-sticker', text: 'スタンプ', sentAt: '2026-10-02T03:15:00Z', direction: 'outgoing', attachmentCount: 1, media: { kind: 'sticker' } },
  ];
}
let keychainFailedOnce = false;
let login: LoginState = { stage: 'idle' };
let loginAt = 0, loggedIn = false;
const onboarding = scenario?.startsWith('onboarding');
if (onboarding) { state.conversations = []; state.selectedId = null; }
if (scenario === 'beta-hidden') state.conversations = state.conversations.filter(c => c.id === one);
if (scenario === 'beta-paused') { state.conversations = []; state.selectedId = null; state.storagePaused = true; management.storage.paused = true; }
export const nextFailure: Record<string, string> = {};
export const calls: { provider: string; op: string }[] = [];
export function emitFatal() { listeners.forEach(fn => fn({ event: 'fatal', error: 'CORE_STOPPED' })); }
const matrix = Array.from({length: 21}, (_, y) => Array.from({length: 21}, (_, x) => (x * y + x + y) % 3 === 0));
const history = (id: string): History => ({ conversationId: id, messages: messages[id] ?? [], lastRecovery: new Date().toISOString(), historyLimit: 100, historyLimited: true, limitReached: false });
export function subscribe(callback: (event: CoreEvent) => void) { listeners.add(callback); return () => { listeners.delete(callback); }; }
export async function request(value: Request) {
  const provider = value.provider ?? 'line';
  calls.push({ provider, op: value.op });
  const key = `${provider}:${value.op}`;
  if (nextFailure[key]) { const code = nextFailure[key]; delete nextFailure[key]; throw code; }
  if (scenario === 'fresh-profile' && value.op === 'connect') {
    throw { line: 'LINE_LOGIN_REQUIRED', instagram: 'IG_LOGIN_REQUIRED', slack: 'SLACK_LOGIN_REQUIRED', x: 'X_LOGIN_REQUIRED', messenger: 'MESSENGER_LOGIN_REQUIRED' }[provider];
  }
  const extension = extensionRequest(value);
  if (extension !== undefined) return extension;
  if (value.provider === 'instagram') return instagramRequest(value);
  if (value.provider === 'slack') return slackRequest(value);
  if (value.provider === 'x') return xRequest(value);
  if (value.provider === 'messenger') return messengerRequest(value);
  await new Promise(resolve => setTimeout(resolve, 80));
  if (['snapshot', 'connect'].includes(value.op) && (scenario === 'keychain-session' || (scenario === 'keychain-once' && !keychainFailedOnce))) {
    keychainFailedOnce = true;
    throw 'KEYCHAIN_SESSION_AUTH_FAILED';
  }
  switch (value.op) {
    case 'line_media': {
      const polls = (mediaPolls.get(value.messageId) ?? 0) + 1;
      mediaPolls.set(value.messageId, polls);
      if (scenario === 'line-media-failure' && polls < 3) return { image: null, pending: false };
      if (polls === 1 || scenario === 'line-media-slow') return { image: null, pending: true };
      return { image: value.messageId === 'media-sticker' ? mediaSticker : mediaPhoto, pending: false };
    }
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
    case 'search': return { results: Object.entries(messages).flatMap(([id, rows]) => rows.filter(m => m.text.includes(value.query)).map(m => ({ ...m, conversationId: id, title: state.conversations.find(c => c.id === id)?.title ?? '一覧外の友人（架空）' }))), scanned: 4, scanLimit: 10000 };
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
const slackRows: Message[] = [{ id: 'slack-root', text: 'Slackの架空メッセージです。', sentAt: '2026-10-01T03:00:00Z', direction: 'incoming', attachmentCount: 0, profile: { conversationId: slackId, messageId: 'slack-root' } }];
let slackState: Snapshot = { connection: 'offline', receiving: 'stopped', selectedId: slackId, errorCode: null, catalogLimited: false, pendingSends: [], conversations: [{ id: slackId, title: 'Slackテスト（架空）', provider: 'slack', preview: slackRows[0].text, lastMessageAt: slackRows[0].sentAt, kind: scenario === 'slack-dm-profile' ? 'dm' : 'channel', avatarVersion: scenario === 'slack-dm-profile' ? 'slack-profile' : null }] };
let slackManagement: Management = { mcp: { enabled: false, running: false, port: 28642, url: 'http://127.0.0.1:28642/mcp', errorCode: null }, clients: [], storage: { paused: false, path: '/fixture/messages.sqlite3', counts: {}, retention: 'until_deleted' }, accountAvailable: true };
async function slackRequest(value: Request) {
  await new Promise(resolve => setTimeout(resolve, 80));
  switch (value.op) {
    case 'slack_profile': {
      if (scenario === 'slack-profiles-permission') {
        slackState.profileErrorCode = 'MISSING_SCOPE';
        listeners.forEach(fn => fn({ event: 'status', provider: 'slack', profileErrorCode: 'MISSING_SCOPE' }));
        return { name: null, image: null, pending: false, errorCode: 'MISSING_SCOPE' };
      }
      return { name: 'Slackの花子（架空）', image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', pending: false, errorCode: null };
    }
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

const xId = 'e'.repeat(64);
const xRows: Message[] = [{ id: 'x-signed-fixture', text: 'Xの架空メッセージです。', sentAt: '2026-10-01T04:00:00Z', direction: 'incoming', attachmentCount: 0 }];
let xState: Snapshot = { connection: 'offline', receiving: 'stopped', selectedId: xId, errorCode: null, catalogLimited: true, pendingSends: [], conversations: [{ id: xId, title: 'Xの友人（架空）', provider: 'x', preview: xRows[0].text, lastMessageAt: xRows[0].sentAt }] };
let xLogin: LoginState = { stage: 'idle' };
async function xRequest(value: Request) {
  await new Promise(resolve => setTimeout(resolve, 80));
  switch (value.op) {
    case 'snapshot': return structuredClone(xState);
    case 'connect': if (scenario === 'x-login' && xLogin.stage !== 'completed') throw 'X_LOGIN_REQUIRED'; xState.connection = 'connected'; xState.receiving = 'waiting'; return structuredClone(xState);
    case 'messages': case 'select': if (value.conversationId !== xId) throw 'CONVERSATION_UNAVAILABLE'; return { conversationId: xId, messages: scenario === 'x-empty' ? [] : structuredClone(xRows), historyLimit: 100, historyLimited: true, limitReached: false, unsupportedLegacyCount: 2, legacyMessageCount: scenario === 'x-legacy' ? 1 : 0, lastRecovery: new Date().toISOString() };
    case 'stop': xState.connection = 'offline'; xState.receiving = 'stopped'; return structuredClone(xState);
    case 'storage_pause': xState.storagePaused = value.paused; if (value.paused) { xState.connection = 'offline'; xState.receiving = 'stopped'; } return structuredClone(xState);
    case 'refresh': return { inserted: 0 };
    case 'search': return { results: xRows.filter(m => m.text.includes(value.query)).map(m => ({ ...m, conversationId: xId, title: xState.conversations[0].title })), scanned: xRows.length, scanLimit: 10000 };
    case 'send': {
      if (value.conversationId !== xId) throw 'CONVERSATION_UNAVAILABLE';
      if (value.text === '結果不明のテスト') { xState.pendingSends.push({ requestId: value.requestId, conversationId: xId, text: value.text, status: 'unknown', createdAt: new Date().toISOString() }); throw 'X_SEND_UNKNOWN'; }
      if (!xRows.some(m => m.id === value.requestId)) xRows.push({ id: value.requestId, text: value.text, sentAt: new Date().toISOString(), direction: 'outgoing', attachmentCount: 0 });
      listeners.forEach(fn => fn({ event: 'messages_changed', provider: 'x', conversationId: xId }));
      return { status: 'acknowledged', messageId: value.requestId, encrypted: true };
    }
    case 'x_login_start': xLogin = { stage: value.unlockOnly ? 'pin' : 'web' }; return structuredClone(xLogin);
    case 'x_login_status': return structuredClone(xLogin);
    case 'x_login_cancel': xLogin = { stage: 'cancelled' }; return structuredClone(xLogin);
    default: throw 'INVALID_INPUT';
  }
}

const messengerId = 'f'.repeat(64);
const messengerRows: Message[] = [{ id: 'messenger-text', text: 'Messengerの架空メッセージです。', sentAt: '2026-10-02T05:00:00Z', direction: 'incoming', attachmentCount: 0 }];
let messengerState: Snapshot = { connection: 'offline', receiving: 'stopped', selectedId: messengerId, errorCode: null, catalogLimited: true, pendingSends: [], conversations: [{ id: messengerId, title: 'Messengerの友人（架空）', provider: 'messenger', preview: messengerRows[0].text, lastMessageAt: messengerRows[0].sentAt }] };
let messengerLogin: LoginState = { stage: 'idle' };
async function messengerRequest(value: Request) {
  await new Promise(resolve => setTimeout(resolve, 80));
  switch (value.op) {
    case 'snapshot': return structuredClone(messengerState);
    case 'connect':
      if (scenario === 'messenger-login' && messengerLogin.stage !== 'completed') throw 'MESSENGER_LOGIN_REQUIRED';
      if (scenario === 'messenger-unknown') throw 'MESSENGER_REGISTRATION_UNKNOWN';
      messengerState.connection = 'connected'; messengerState.receiving = 'waiting'; return structuredClone(messengerState);
    case 'messages': case 'select':
      if (value.conversationId !== messengerId) throw 'CONVERSATION_UNAVAILABLE';
      return { conversationId: messengerId, messages: structuredClone(messengerRows), historyLimit: null, historyLimited: true, limitReached: false, lastRecovery: null };
    case 'refresh': return structuredClone(messengerState);
    case 'stop': messengerState.connection = 'offline'; messengerState.receiving = 'stopped'; return structuredClone(messengerState);
    case 'storage_pause': messengerState.storagePaused = value.paused; if (value.paused) { messengerState.connection = 'offline'; messengerState.receiving = 'stopped'; } return structuredClone(messengerState);
    case 'search': return { results: messengerRows.filter(m => m.text.includes(value.query)).map(m => ({ ...m, conversationId: messengerId, title: messengerState.conversations[0].title })), scanned: messengerRows.length, scanLimit: 10000 };
    case 'send': {
      if (value.conversationId !== messengerId) throw 'CONVERSATION_UNAVAILABLE';
      if (value.text === '結果不明のテスト') { messengerState.pendingSends.push({ requestId: value.requestId, conversationId: messengerId, text: value.text, status: 'unknown', createdAt: new Date().toISOString() }); throw 'MESSENGER_SEND_UNKNOWN'; }
      if (!messengerRows.some(m => m.id === value.requestId)) messengerRows.push({ id: value.requestId, text: value.text, sentAt: new Date().toISOString(), direction: 'outgoing', attachmentCount: 0 });
      return { status: 'acknowledged', messageId: value.requestId };
    }
    case 'messenger_login_start': messengerLogin = { stage: 'web' }; return structuredClone(messengerLogin);
    case 'messenger_login_status': return structuredClone(messengerLogin);
    case 'messenger_login_cancel': messengerLogin = { stage: 'cancelled' }; return structuredClone(messengerLogin);
    default: throw 'INVALID_INPUT';
  }
}

export const setupLaunches: string[] = [];
export async function openSetup(provider: 'instagram' | 'slack') { setupLaunches.push(provider); }

let slackLogin: LoginState = { stage: 'idle' };
const fixtureStates = { line: state, slack: slackState, instagram: igState, x: xState, messenger: messengerState };
function snapshotFor(p: keyof typeof fixtureStates) { return { line: state, slack: slackState, instagram: igState, x: xState, messenger: messengerState }[p]; }
function rowsFor(p: keyof typeof fixtureStates) { return p === 'line' ? messages[one] : p === 'slack' ? slackRows : p === 'instagram' ? igMessages : p === 'x' ? xRows : messengerRows; }
const backfillStates = new Map<string, boolean>();
function emptyManagement(port: number): Management {
  return { mcp: { enabled: false, running: false, port, url: `http://127.0.0.1:${port}/mcp`, errorCode: null },
    clients: [], accountAvailable: true, storage: { paused: false, path: '/fixture/encrypted.sqlite3', counts: {}, retention: 'until_deleted' } };
}
const providerManagement = { instagram: emptyManagement(28644), x: emptyManagement(28645), messenger: emptyManagement(28646) };
function extensionRequest(value: Request): unknown {
  const p = value.provider ?? 'line', s = snapshotFor(p);
  const own = p !== 'line' && p !== 'slack' ? providerManagement[p] : undefined;
  const managementFor = (): Management => {
    if (!own) return structuredClone(p === 'slack' ? slackManagement : management);
    own.storage = { ...own.storage, paused: !!s.storagePaused, counts: { messages: rowsFor(p)?.length ?? 0, conversations: s.conversations.length, outgoing_requests: s.pendingSends.length } };
    return structuredClone(own);
  };
  switch (value.op) {
    case 'send_image': {
      if (s.connection !== 'connected' || s.storagePaused || !s.conversations.some(c => c.id === value.conversationId)) throw 'CONVERSATION_UNAVAILABLE';
      const rows = p === 'line' ? messages[value.conversationId] : rowsFor(p);
      if (!rows.some(m => m.id === value.requestId)) rows.push({ id: value.requestId, text: '', sentAt: new Date().toISOString(), direction: 'outgoing', attachmentCount: 1, attachments: [{ index: 0, kind: 'image', local: true, name: '送信した画像' }] });
      listeners.forEach(fn => fn({ event: 'messages_changed', provider: p, conversationId: value.conversationId }));
      return { status: 'acknowledged', messageId: value.requestId };
    }
    case 'slack_login_start': slackLogin = { stage: 'web' }; return structuredClone(slackLogin);
    case 'slack_login_cancel': slackLogin = { stage: 'cancelled' }; return structuredClone(slackLogin);
    case 'slack_login_status': return { ...structuredClone(slackLogin), configured: !['fresh-profile', 'slack-unconfigured'].includes(scenario ?? '') };
    case 'management': if (own) return managementFor(); break;
    case 'mcp_configure': if (own) { own.mcp = { enabled: value.enabled, running: value.enabled, port: value.port, url: `http://127.0.0.1:${value.port}/mcp`, errorCode: null }; return managementFor(); } break;
    case 'mcp_register': if (own) {
      const client = { id: crypto.randomUUID(), name: value.name, conversationIds: value.conversationIds, read: value.read, send: value.send, createdAt: new Date().toISOString() };
      own.clients.push(client); return { client, token: `blc_FIXTURE_${p}_ONCE`, url: own.mcp.url };
    } break;
    case 'mcp_revoke': if (own) { own.clients = own.clients.filter(c => c.id !== value.clientId); return managementFor(); } break;
    case 'storage_delete_preview': if (p !== 'line') { s.storagePaused = true; s.connection = 'offline'; s.receiving = 'stopped'; if (p === 'slack') slackManagement.storage.paused = true; return { confirmation: `fixture-${p}`, counts: managementFor().storage.counts, expiresInSeconds: 120 }; } break;
    case 'storage_delete': if (p !== 'line') { if (value.confirmation !== `fixture-${p}`) throw 'DELETE_CONFIRMATION_EXPIRED'; const target = own ?? slackManagement; target.clients = []; target.mcp.enabled = target.mcp.running = false; rowsFor(p).splice(0); s.conversations = []; s.selectedId = null; s.pendingSends = []; s.unreadCount = 0; listeners.forEach(fn => fn({ event: 'data_cleared', provider: p })); return { management: managementFor() }; } break;
    case 'mark_read': s.unreadCount = 0; s.conversations.forEach(c => c.unreadCount = 0); listeners.forEach(fn => fn({ event: 'read_changed', provider: p, conversationId: value.conversationId })); return { unreadCount: 0 };
    case 'history_backfill': backfillStates.set(p, value.enabled); return { scheduledConversations: s.conversations.length };
    case 'messages': case 'select': if (scenario === 'extensions') return { conversationId: value.conversationId, messages: structuredClone(rowsFor(p)), olderCursor: 'fixture-older', historyLimited: true, sync: { backfill: !!backfillStates.get(p), complete: false } }; break;
    case 'messages_older': return { conversationId: value.conversationId, messages: [{ id: 'older-fixture', text: '過去ページの架空メッセージ', sentAt: '2026-01-01T00:00:00Z', direction: 'incoming', attachmentCount: 0 }], olderCursor: null, sync: { backfill: !!backfillStates.get(p), complete: false } };
    case 'attachment_media': return { pending: false, media: mediaPhoto };
  }
  return undefined;
}
export function addUnread(p: keyof typeof fixtureStates) {
  const s = snapshotFor(p); s.unreadCount = 3; if (s.conversations[0]) s.conversations[0].unreadCount = 3;
  listeners.forEach(fn => { fn({ event: 'unread_changed', provider: p, conversationId: s.conversations[0]?.id }); fn({ event: 'messages_changed', provider: p, conversationId: s.conversations[0]?.id }); });
}
if (scenario === 'extensions') {
  igState.conversations[0].kind = 'group'; xState.conversations[0].kind = 'group';
  for (const rows of [igMessages, xRows]) rows[0] = { ...rows[0], attachmentCount: 1, attachments: [{ index: 0, kind: 'image', name: 'fixture.png' }] };
}
if (scenario === 'fresh-profile') {
  for (const s of Object.values(fixtureStates)) { s.conversations = []; s.selectedId = null; s.pendingSends = []; s.unreadCount = 0; }
  for (const m of [management, slackManagement, ...Object.values(providerManagement)]) { m.accountAvailable = false; m.storage.counts = {}; }
}
