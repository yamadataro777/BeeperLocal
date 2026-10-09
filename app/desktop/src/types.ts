export type Provider = 'line' | 'instagram' | 'slack' | 'x' | 'messenger';
export type Conversation = { id: string; title: string; provider: Provider; preview: string; lastMessageAt: string | null; avatarVersion?: string | null; kind?: string; unreadCount?: number };
export type Message = { id: string; text: string; sentAt: string; direction: 'incoming' | 'outgoing' | 'unknown'; attachmentCount: number; attachments?: { kind: 'image' | 'video' | 'audio' | 'file'; index: number; name?: string; local?: boolean }[]; media?: { kind: 'image' | 'sticker' }; profile?: { conversationId: string; messageId: string } };
export type Status = { connection: 'offline' | 'connecting' | 'connected' | 'error'; receiving: 'stopped' | 'starting' | 'recovering' | 'waiting' | 'reconnecting' | 'error'; errorCode: string | null; selectedId: string | null; retryAttempt?: number; storagePaused?: boolean; profileErrorCode?: string | null };
export type Snapshot = Status & { unreadCount?: number; conversations: Conversation[]; catalogLimited: boolean; pendingSends: { requestId: string; conversationId: string | null; text: string; imageDigest?: string | null; status: string; createdAt: string }[] };
export type History = { conversationId: string; messages: Message[]; olderCursor?: string | null; sync?: { backfill?: boolean; complete?: boolean; exhausted?: boolean; coverage?: string; lastSync?: string }; lastRecovery: string | null; historyLimit: number | null; historyLimited: boolean; limitReached: boolean; unsupportedLegacyCount?: number; legacyMessageCount?: number };
export type SearchResult = Message & { conversationId: string; title: string };
export type SearchResponse = { results: SearchResult[]; scanned: number; scanLimit: number };
export type CoreEvent = Partial<Status> & { event: string; provider?: Provider; conversationId?: string; error?: string };
export type ClientGrant = { id: string; name: string; conversationIds: string[]; read: boolean; send: boolean; createdAt: string };
export type StorageCounts = { messages?: number; conversations?: number; sync_receipts?: number; outgoing_requests?: number };
export type Management = { mcp: { enabled: boolean; running: boolean; port: number; url: string; errorCode: string | null }; clients: ClientGrant[]; storage: { paused: boolean; path: string; counts: StorageCounts; retention: string }; accountAvailable: boolean };
export type ClientRegistration = { client: ClientGrant; token: string; url: string };
export type DeletionPreview = { confirmation: string; counts: StorageCounts; expiresInSeconds: number };
export type Request = { provider?: Provider } & ({ op: 'slack_login_start' | 'slack_login_status' | 'slack_login_cancel' | 'line_login_status' | 'line_login_cancel' | 'x_login_status' | 'x_login_cancel' | 'messenger_login_start' | 'messenger_login_status' | 'messenger_login_cancel' } | { op: 'x_login_start'; unlockOnly: boolean } | { op: 'line_login_start'; replace: boolean } | { op: 'avatar'; conversationId: string } | { op: 'snapshot' | 'refresh' | 'stop' | 'management' | 'storage_delete_preview' }
  | { op: 'connect'; interactive?: boolean }
  | { op: 'select' | 'messages'; conversationId: string }
  | { op: 'messages_older'; conversationId: string; before: string }
  | { op: 'mark_read'; conversationId: string; throughMessageId: string }
  | { op: 'history_backfill'; conversationId: string | null; enabled: boolean }
  | { op: 'slack_profile'; conversationId: string; messageId?: string }
  | { op: 'line_media'; conversationId: string; messageId: string; retry: boolean }
  | { op: 'attachment_media'; conversationId: string; messageId: string; index: number; retry: boolean }
  | { op: 'search'; query: string }
  | { op: 'send'; conversationId: string; text: string; requestId: string }
  | { op: 'send_image'; conversationId: string; dataUrl: string; requestId: string }
  | { op: 'mcp_configure'; enabled: boolean; port: number }
  | { op: 'mcp_register'; name: string; conversationIds: string[]; read: boolean; send: boolean }
  | { op: 'mcp_revoke'; clientId: string }
  | { op: 'storage_pause'; paused: boolean }
  | { op: 'storage_delete'; confirmation: string });

export type LoginState = { stage: string; matrix?: boolean[][]; pin?: string; errorCode?: string; configured?: boolean };
