export type Provider = 'line' | 'instagram' | 'slack';
export type Conversation = { id: string; title: string; provider: Provider; preview: string; lastMessageAt: string | null; avatarVersion?: string | null };
export type Message = { id: string; text: string; sentAt: string; direction: 'incoming' | 'outgoing' | 'unknown'; attachmentCount: number };
export type Status = { connection: 'offline' | 'connecting' | 'connected' | 'error'; receiving: 'stopped' | 'starting' | 'recovering' | 'waiting' | 'reconnecting' | 'error'; errorCode: string | null; selectedId: string | null; retryAttempt?: number; storagePaused?: boolean };
export type Snapshot = Status & { conversations: Conversation[]; catalogLimited: boolean; pendingSends: { requestId: string; conversationId: string | null; text: string; status: string; createdAt: string }[] };
export type History = { conversationId: string; messages: Message[]; lastRecovery: string | null; historyLimit: number | null; historyLimited: boolean; limitReached: boolean };
export type SearchResult = Message & { conversationId: string; title: string };
export type SearchResponse = { results: SearchResult[]; scanned: number; scanLimit: number };
export type CoreEvent = Partial<Status> & { event: string; provider?: Provider; conversationId?: string; error?: string };
export type ClientGrant = { id: string; name: string; conversationIds: string[]; read: boolean; send: boolean; createdAt: string };
export type StorageCounts = { messages?: number; conversations?: number; sync_receipts?: number; outgoing_requests?: number };
export type Management = { mcp: { enabled: boolean; running: boolean; port: number; url: string; errorCode: string | null }; clients: ClientGrant[]; storage: { paused: boolean; path: string; counts: StorageCounts; retention: string }; accountAvailable: boolean };
export type ClientRegistration = { client: ClientGrant; token: string; url: string };
export type DeletionPreview = { confirmation: string; counts: StorageCounts; expiresInSeconds: number };
export type Request = { provider?: Provider } & ({ op: 'line_login_status' | 'line_login_cancel' } | { op: 'line_login_start'; replace: boolean } | { op: 'avatar'; conversationId: string } | { op: 'snapshot' | 'connect' | 'refresh' | 'stop' | 'management' | 'storage_delete_preview' }
  | { op: 'select' | 'messages'; conversationId: string }
  | { op: 'search'; query: string }
  | { op: 'send'; conversationId: string; text: string; requestId: string }
  | { op: 'mcp_configure'; enabled: boolean; port: number }
  | { op: 'mcp_register'; name: string; conversationIds: string[]; read: boolean; send: boolean }
  | { op: 'mcp_revoke'; clientId: string }
  | { op: 'storage_pause'; paused: boolean }
  | { op: 'storage_delete'; confirmation: string });

export type LoginState = { stage: string; matrix?: boolean[][]; pin?: string; errorCode?: string };
