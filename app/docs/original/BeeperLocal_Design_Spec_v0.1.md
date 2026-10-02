# BeeperLocal Design Specification v0.1

Status: Draft for MVP implementation  
Target: macOS-first local-first unified messaging client  
Primary goal: Prove that multiple messaging services can be unified, stored, searched, and operated from a local desktop application without routing message history through a proprietary application backend.

---

## 1. Product Definition

BeeperLocal is a local-first desktop messaging client inspired by the unified inbox model of Beeper.

The product is **not** defined as “offline messaging.” Network access to each messaging provider is still required. “Local-first” means that message normalization, local history, search indexes, application state, and later AI processing are performed on the user’s device by default.

### Core product promise

- Multiple messaging services appear in one inbox.
- Messages are normalized into one internal data model.
- History is persisted locally.
- Search is local.
- Sending and receiving are routed through provider-specific connectors.
- The application does not require a proprietary cloud backend for core operation.

---

## 2. MVP Scope

### Target platform

- macOS only.
- Single local user.
- Single device.

### Required MVP capabilities

1. Connect at least two messaging sources through a common connector interface.
2. Fetch conversations.
3. Fetch message history.
4. Normalize provider-specific messages into a common model.
5. Persist normalized data in a local SQLite database.
6. Show a unified inbox.
7. Open a conversation and read messages.
8. Send a text message when supported by the connector.
9. Receive or sync new messages.
10. Search locally across stored messages.
11. Survive application restart without losing local history or sync state.

### Explicit non-goals for v0.1

- Voice/video calls.
- Full reaction parity.
- Advanced thread parity.
- Multi-device synchronization.
- Cloud backup.
- Mobile application.
- Local LLM features.
- Remote AI processing.
- Plugin marketplace.
- Full end-to-end-encryption reimplementation.
- Reverse-engineered authentication flows.
- Automation based on user-account tokens that violate provider terms.

---

## 3. System Architecture

```text
┌──────────────────────────────┐
│        Desktop UI            │
│ React / TypeScript           │
│                              │
│ - Unified Inbox              │
│ - Conversation View          │
│ - Search                     │
│ - Settings                   │
└──────────────┬───────────────┘
               │ narrow IPC / commands
┌──────────────▼───────────────┐
│          Local Core          │
│                              │
│ - Unified data model         │
│ - Conversation service       │
│ - Sync orchestration         │
│ - Search service             │
│ - Outgoing queue             │
│ - Deduplication              │
│ - Provider registry          │
└───────┬──────────┬───────────┘
        │          │
        │          └──────────────┐
        ▼                         ▼
┌──────────────┐          ┌────────────────┐
│ Local SQLite│          │ Connector Layer│
│ + FTS       │          │                │
│             │          │ Telegram       │
│ messages    │          │ Slack/Matrix   │
│ threads     │          │ future...      │
│ accounts    │          └───────┬────────┘
│ sync_state  │                  │
└──────────────┘                  ▼
                          Messaging providers
```

---

## 4. Architectural Principles

### 4.1 Local-first

The local database is the UI’s primary read model. Connectors synchronize provider data into the local store; the UI should not directly depend on provider APIs.

### 4.2 Provider isolation

Provider-specific behavior must remain behind a connector interface. UI components must not contain Telegram-, Slack-, WhatsApp-, or other provider-specific networking logic.

### 4.3 Normalized core model

Provider payloads are converted into normalized internal types before being stored or exposed to most of the application.

### 4.4 Narrow privilege boundaries

The renderer/UI must not have direct access to credentials, arbitrary filesystem APIs, shell execution, or unrestricted provider tokens.

### 4.5 Replaceable connectors

A connector should be replaceable without rewriting the UI, database, or search system.

### 4.6 No unsafe shortcuts

Do not obtain user session tokens by scraping browser storage, intercepting credentials, automating unsupported user-account login flows, or reverse engineering provider authentication as part of the MVP.

---

## 5. Recommended Technology Stack

### Desktop shell

- Tauri 2

### UI

- React
- TypeScript
- Vite

### Local backend

- Rust where OS/security boundaries matter.
- TypeScript is acceptable for pure presentation/domain helpers.

### Storage

- SQLite
- SQLite FTS5 for full-text search.

### Credential storage

- macOS Keychain through a narrow backend abstraction.

### Testing

- Rust unit/integration tests for backend/core logic.
- Vitest for TypeScript logic.
- Playwright or Tauri-compatible end-to-end tests for critical UI flows where practical.

---

## 6. Core Domain Model

### Account

```ts
interface Account {
  id: string;
  provider: ProviderKind;
  displayName: string;
  providerAccountId?: string;
  status: "connected" | "disconnected" | "error";
}
```

### Conversation

```ts
interface Conversation {
  id: string;
  provider: ProviderKind;
  providerConversationId: string;
  accountId: string;
  title: string;
  kind: "dm" | "group" | "channel";
  lastMessageAt?: string;
  unreadCount: number;
}
```

### UnifiedMessage

```ts
interface UnifiedMessage {
  id: string;
  provider: ProviderKind;
  providerMessageId: string;
  conversationId: string;
  accountId: string;
  senderId: string;
  senderDisplayName?: string;
  text?: string;
  sentAt: string;
  editedAt?: string;
  replyToMessageId?: string;
  direction: "incoming" | "outgoing";
  status?: "queued" | "sent" | "delivered" | "read" | "failed";
  attachments: Attachment[];
}
```

### Attachment

```ts
interface Attachment {
  id: string;
  kind: "image" | "video" | "audio" | "file" | "other";
  filename?: string;
  mimeType?: string;
  sizeBytes?: number;
  remoteUrl?: string;
  localPath?: string;
  thumbnailPath?: string;
}
```

---

## 7. Connector Interface

All providers implement the same high-level contract.

```ts
interface MessagingConnector {
  provider: ProviderKind;

  connect(): Promise<void>;
  disconnect(): Promise<void>;
  getConnectionStatus(): Promise<ConnectionStatus>;

  listConversations(input?: {
    cursor?: string;
    limit?: number;
  }): Promise<ConversationPage>;

  listMessages(input: {
    providerConversationId: string;
    cursor?: string;
    limit?: number;
  }): Promise<MessagePage>;

  sendText(input: {
    providerConversationId: string;
    text: string;
    clientRequestId: string;
  }): Promise<SendResult>;

  sync(input: SyncRequest): Promise<SyncResult>;
}
```

The interface may be adjusted during implementation, but provider-specific network calls must not leak into the UI layer.

---

## 8. Connector Selection for MVP

The first connectors should be chosen by viability, not by market importance.

### Selection criteria

1. Official or clearly supported API/client access exists.
2. User authentication can be implemented without extracting hidden session tokens.
3. Conversation history can be read.
4. Text messages can preferably be sent.
5. Incremental synchronization is possible.
6. Rate-limit behavior is documented.
7. Provider terms do not require obviously unsafe automation.

### Default implementation order

1. MockConnector — deterministic fixture data for development and tests.
2. Telegram — preferred first real connector if required API credentials and supported client integration are available.
3. Slack or Matrix — preferred second real connector depending accessible credentials and API constraints.

If a real connector is blocked by credentials or provider approval, the architecture and UI should still be completed using MockConnector, but the MVP is not considered integration-complete until two real sources have been demonstrated.

---

## 9. Local Database

Minimum tables:

```text
accounts
conversations
participants
messages
attachments
sync_state
outgoing_queue
app_settings
```

### Required database behavior

- Schema migrations.
- Unique constraints on provider/account/provider-object identifiers.
- Transactional upserts during sync.
- Message deduplication.
- Indexed conversation sorting.
- FTS5 search index for message text.
- Durable sync cursors/checkpoints.

### Data ownership

The normalized local database is the application’s source of truth for rendering, not a provider cache embedded directly in React state.

---

## 10. Sync Engine

The sync subsystem must support:

1. Initial sync.
2. Incremental sync.
3. Restart/resume.
4. Deduplication.
5. Retry with bounded exponential backoff.
6. Rate-limit awareness.
7. Error isolation per account/provider.
8. Persistence of provider cursors/checkpoints.

### Simplified flow

```text
Connector
  ↓
fetch delta
  ↓
normalize
  ↓
transactional upsert
  ↓
update sync_state
  ↓
UI observes local DB changes
```

---

## 11. Outgoing Messages

The UI must not directly call provider networking code.

```text
UI
 ↓
Create local outgoing item
 ↓
outgoing_queue
 ↓
Connector send
 ↓
Provider result
 ↓
Update local message status
```

Use a `clientRequestId` or equivalent idempotency mechanism when possible to reduce duplicate sends after retries.

---

## 12. Search

### MVP

- Local keyword search.
- SQLite FTS5.
- Search across all stored message text.
- Filter by conversation and provider where practical.

### Post-MVP

- Semantic search.
- Local embedding index.
- Local LLM summarization/retrieval.

These are explicitly excluded from v0.1.

---

## 13. Attachment Strategy

Avoid eagerly downloading every full-resolution attachment.

Preferred policy:

```text
Metadata         -> local DB
Thumbnail        -> local cache when useful
Full attachment  -> download on demand
```

The MVP should support displaying basic attachment metadata and opening provider-hosted content where allowed. Large attachment caching is not required.

---

## 14. Security Boundary

Security-sensitive areas are implementation-critical and must receive separate review.

### High-risk areas

- OAuth/session tokens.
- Encryption keys.
- Keychain access.
- IPC/command permissions.
- Auto-update trust chain.
- Code signing.
- Connector sandboxing.
- Attachment parsing.
- Supply-chain dependencies.

### Required MVP rules

1. No plaintext token file in the repository or user-data directory.
2. No credentials committed to git.
3. No provider token exposed to the React renderer.
4. No arbitrary shell command API exposed to the renderer.
5. No unrestricted filesystem bridge from renderer to backend.
6. Secrets must be accessed through a narrow credential service.
7. Logs must redact secrets.
8. Authentication errors must not dump raw tokens or cookies.
9. `.env` files containing secrets must be gitignored.
10. Any cryptography beyond OS-provided secret storage requires explicit security review before release.

---

## 15. IPC Rules

Renderer-to-backend IPC must expose narrowly scoped commands such as:

```text
list_conversations()
get_messages(conversation_id)
search_messages(query)
send_text(conversation_id, text)
connect_account(provider)
disconnect_account(account_id)
```

Do not expose generic APIs such as:

```text
read_file(path)
write_file(path, bytes)
execute_shell(command)
read_all_tokens()
raw_http_request(url, headers, body)
```

unless a later reviewed design explicitly requires them.

---

## 16. Update and Distribution Security

Not required for the first local developer build, but required before external distribution:

- macOS code signing.
- Notarization.
- Signed release artifacts.
- Verified auto-update signatures.
- Reproducible or auditable release process where practical.

---

## 17. Development Phases

### Phase 0 — Technical proof

Goal: prove connector viability before polishing UI.

Required result:

```text
Real Connector A -> fetch >=50 messages
Real Connector B -> fetch >=50 messages
                 -> normalize
                 -> display in one chronological CLI/debug view
```

This closes the first technical Closed Loop.

### Phase 1 — Core abstraction

- Connector interface.
- Unified domain models.
- MockConnector.
- Provider registry.

### Phase 2 — Local persistence

- SQLite schema.
- Migrations.
- Upsert path.
- FTS search.
- Sync checkpoints.

### Phase 3 — Desktop UI

- Account status.
- Unified inbox.
- Conversation view.
- Search.

### Phase 4 — Sending

- Outgoing queue.
- Send text.
- Retry and status update.

### Phase 5 — Security hardening

- Keychain integration.
- IPC audit.
- Log redaction.
- Threat model review.

### Phase 6 — Packaging

- macOS bundle.
- Code signing/notarization when external distribution begins.

---

## 18. MVP Acceptance Criteria

The MVP is accepted only when all of the following are true:

- [ ] Application launches on macOS.
- [ ] Local SQLite database is created through migrations.
- [ ] At least two real messaging sources can be connected, or one real source plus a documented blocker for the second during development; final integration-complete status still requires two.
- [ ] At least 50 messages can be imported from each validated real connector.
- [ ] Messages are normalized into the shared model.
- [ ] Imported messages remain available after restart.
- [ ] Unified inbox displays conversations from multiple providers.
- [ ] Conversation view displays ordered messages.
- [ ] Local text search returns stored messages.
- [ ] Text sending works for every connector that supports sending in the MVP.
- [ ] Duplicate sync runs do not duplicate stored messages.
- [ ] Incremental sync resumes from stored checkpoints.
- [ ] No provider secret is stored in plaintext application files.
- [ ] No secret is exposed to the React renderer or logs.
- [ ] Tests cover normalization, deduplication, persistence, search, and at least one connector fixture.

---

## 19. Closed Loop Definition for This Project

A development loop counts as closed only when it reaches an external or executable result and produces a decision.

### Loop 1 — Connector viability

Hypothesis: two provider integrations can operate locally behind a shared connector interface.

Minimum execution:

1. Connect provider A.
2. Fetch at least 50 messages.
3. Connect provider B.
4. Fetch at least 50 messages.
5. Normalize both datasets.
6. Display them together.
7. Decide: continue, replace connector, or abandon provider.

### Loop 2 — Local-first persistence

Hypothesis: provider history can be normalized into SQLite and resumed safely after restart.

Minimum execution:

1. Sync.
2. Kill application.
3. Restart.
4. Resume incremental sync.
5. Verify no duplicates.
6. Decide whether data model/sync state is sufficient.

### Loop 3 — Product interaction

Hypothesis: a unified inbox is materially usable with multiple sources.

Minimum execution:

1. Render real imported conversations.
2. Search real history.
3. Send at least one message through each send-capable connector.
4. Note friction.
5. Decide the next UX priority.

---

## 20. Key Risks

### Risk A — Connector viability

The largest product risk is not the UI. It is whether each target messaging service permits stable, maintainable integration for the desired user-account use case.

### Risk B — Authentication and credential handling

A functional connector can still be unacceptable if it requires unsafe session-token extraction or insecure credential storage.

### Risk C — Provider API changes

Connector breakage must be isolated from the local core.

### Risk D — Scope explosion

Feature parity with each native messaging app is explicitly not an MVP requirement.

### Risk E — Hidden cloud dependency

Any SDK or library introduced into the core path must be checked to ensure message data is not silently routed through an external service.

---

## 21. Post-MVP Expansion

Only after the MVP works:

- Additional connectors.
- Local semantic search.
- Local LLM assistant.
- Smart notification triage.
- Contact identity merging across providers.
- Better attachment caching.
- Connector sandbox/runtime isolation.
- Mobile companion app.
- Optional encrypted multi-device sync.

---

## 22. Decision Summary

The project should be treated as three separate engineering problems:

1. **Messaging integration:** provider-specific connectivity and sync.
2. **Local-first application architecture:** normalization, storage, search, UI, and queues.
3. **Security:** credentials, IPC, signing, update trust, and supply-chain controls.

Codex can implement a large share of the local-first application architecture and routine connector code. Security-sensitive code may also be generated by Codex, but it must not be accepted solely because it compiles or passes tests. The largest early uncertainty is connector viability, so the project must validate real provider integrations before investing heavily in product polish.
