# Codex Implementation Instructions — BeeperLocal MVP v0.1

You are the implementation agent for **BeeperLocal**, a macOS-first local-first unified messaging client.

Read `BeeperLocal_Design_Spec_v0.1.md` before modifying code. Treat that document as the product and architecture specification unless this instruction file explicitly overrides it.

Your objective is not to imitate every Beeper feature. Your objective is to produce the smallest working system that proves the following:

> Two messaging sources can be integrated behind one connector interface, normalized into one local SQLite database, rendered in one inbox, searched locally, and used to send/receive text without a proprietary cloud backend.

---

# 1. Execution Mode

Work incrementally and keep the repository runnable at the end of every milestone.

Do not spend time on visual polish before connector viability, normalization, persistence, and synchronization work.

Do not silently replace real integration work with mocks. Mocks are required for deterministic testing, but final integration milestones must explicitly report whether real provider connectivity has been achieved.

When a provider requires credentials or manual account configuration that you cannot complete yourself:

1. Implement everything that does not require the secret.
2. Add a clear setup document.
3. Add validation code that fails with a precise actionable error.
4. Continue other implementation work.
5. Record the connector as `BLOCKED_BY_USER_CREDENTIALS`, not `DONE`.

Never invent credentials.

---

# 2. Required Stack

Use the following unless the repository already contains an equivalent approved stack:

- Tauri 2
- React
- TypeScript
- Vite
- Rust backend/core
- SQLite with FTS5

Use package versions that are compatible with the existing repository. Do not perform broad dependency upgrades unless required.

Prefer a small dependency surface.

---

# 3. Repository Structure

Use a structure close to the following. Adapt only where the framework requires it.

```text
beeperlocal/
├─ README.md
├─ docs/
│  ├─ architecture.md
│  ├─ connector-setup.md
│  ├─ security-notes.md
│  └─ development-status.md
├─ src/
│  ├─ app/
│  ├─ components/
│  ├─ features/
│  │  ├─ accounts/
│  │  ├─ inbox/
│  │  ├─ conversation/
│  │  └─ search/
│  ├─ lib/
│  └─ types/
├─ src-tauri/
│  ├─ src/
│  │  ├─ commands/
│  │  ├─ core/
│  │  ├─ db/
│  │  ├─ connectors/
│  │  │  ├─ mod.rs
│  │  │  ├─ mock/
│  │  │  ├─ telegram/
│  │  │  └─ slack_or_matrix/
│  │  ├─ credentials/
│  │  ├─ sync/
│  │  ├─ search/
│  │  └─ models/
│  └─ migrations/
└─ tests/
```

The renderer must not import provider SDKs directly.

---

# 4. First Deliverable: Architecture Skeleton

Implement the project skeleton before real connectors.

Required pieces:

1. Shared normalized models.
2. Connector trait/interface.
3. Connector registry.
4. MockConnector.
5. SQLite migration system.
6. Repository layer for accounts, conversations, messages, sync state, and outgoing queue.
7. Tauri commands with narrow typed arguments.
8. React shell that can render fixture conversations and messages through backend commands.

### Required connector abstraction

Create a Rust trait or equivalent backend interface with operations equivalent to:

```rust
async fn connect(...)
async fn disconnect(...)
async fn status(...)
async fn list_conversations(...)
async fn list_messages(...)
async fn send_text(...)
async fn sync(...)
```

Provider-specific DTOs must be converted into normalized core models before persistence.

Do not expose provider SDK objects across IPC.

---

# 5. Data Model and Database

Implement migrations for at least:

- accounts
- conversations
- participants
- messages
- attachments
- sync_state
- outgoing_queue
- app_settings

Minimum constraints:

- Every account has a local ID and provider type.
- Conversation uniqueness includes provider/account/providerConversationId.
- Message uniqueness includes provider/account/providerMessageId.
- Sync state is persisted per account and provider scope.
- Message text is indexed with SQLite FTS5.

### Persistence tests

Write tests proving:

1. Re-running the same message import does not duplicate messages.
2. Conversation upserts preserve identity.
3. Search returns expected message text.
4. Sync cursor survives database reopen.
5. Message ordering is deterministic.

---

# 6. MockConnector

Implement a deterministic MockConnector first.

It must contain:

- At least 5 conversations.
- At least 100 messages.
- Multiple senders.
- Incoming and outgoing messages.
- One or more attachments represented as metadata.
- Simulated incremental sync.
- Simulated send success.
- Optional simulated failure mode.

The purpose is to allow complete local-core and UI development without provider credentials.

Do not confuse this with real-provider completion.

---

# 7. Real Connector Strategy

## Connector A — Telegram preferred

Attempt Telegram first if the repository environment supports a documented, maintainable client integration and the user can supply required official API credentials.

Requirements:

- Supported user authentication flow.
- Fetch at least 50 messages from real history.
- Normalize conversations and messages.
- Persist incremental sync state.
- Send text if supported by the chosen integration.
- Never expose raw credentials to the React renderer.

If Telegram integration would require unsafe token extraction or an undocumented credential bypass, stop that path and document the blocker.

## Connector B — Slack or Matrix

Choose the second connector using this priority:

1. Existing credentials/configuration in the repo.
2. Official/documented access.
3. Ability to read history.
4. Ability to send text.
5. Incremental sync support.

Prefer Slack when authorized OAuth access is available. Prefer Matrix when a user-accessible homeserver/account is available and Slack authorization is impractical.

Do not use Discord user tokens, browser token extraction, or similar unsupported user-account automation.

---

# 8. Phase 0 Closed Loop — CLI/Debug Proof

Before polished UI work, create a developer command or debug view that proves real integration.

Success condition:

```text
Provider A: >= 50 real messages fetched
Provider B: >= 50 real messages fetched
Both -> normalized -> merged -> sorted chronologically
```

Output a concise report containing:

- Provider.
- Account identity label, without exposing secrets.
- Conversations fetched.
- Messages fetched.
- Oldest timestamp.
- Newest timestamp.
- Normalization errors.
- Duplicates removed.

Do not print message bodies by default in logs. A debug flag may permit sanitized previews.

When this is successful, update `docs/development-status.md` and mark the Connector Viability loop as closed.

---

# 9. Sync Engine

Implement a synchronization service independent of the UI.

Required behavior:

1. Initial sync.
2. Incremental sync.
3. Persisted cursor/checkpoint.
4. Restart/resume.
5. Deduplication.
6. Per-connector error isolation.
7. Bounded exponential retry.
8. Rate-limit handling where provider SDK/API exposes it.
9. Cancellation on app shutdown.

### Important rule

Update the sync checkpoint only after the associated local database transaction succeeds.

Avoid designs where the cursor advances before message persistence.

---

# 10. Tauri IPC Surface

Expose only narrow application commands.

Target commands:

```text
list_accounts
connect_account
disconnect_account
list_conversations
get_messages
search_messages
send_text
sync_account
get_sync_status
```

Do not expose:

- arbitrary filesystem read/write
- arbitrary shell execution
- raw HTTP proxy
- credential dump
- generic SQL execution
- generic provider SDK invocation

All commands must validate arguments.

---

# 11. Credential Service

Create a credential abstraction even if real connectors are not yet wired.

Required behavior:

- macOS Keychain or OS credential store for persistent secrets.
- Backend-only access.
- No secret values returned over IPC.
- No secret values logged.
- Test abstraction may use an in-memory secret store.

Do not create plaintext `tokens.json`, `credentials.json`, or equivalent.

If a provider SDK itself persists state, document exactly where it is stored and whether it contains secrets.

---

# 12. Unified Inbox UI

Only after the local core works, implement the minimum UI.

### Left pane

- Conversation list.
- Provider icon/label.
- Conversation title.
- Last message preview.
- Last activity time.
- Unread count.

### Main pane

- Conversation title.
- Provider/account indicator.
- Ordered messages.
- Sender display name where available.
- Timestamp.
- Text composer.
- Send button.

### Search

- Search box.
- Query local FTS index.
- Show matching message, conversation, timestamp, and short snippet.

### Settings/account view

- Connector/account list.
- Connected/disconnected/error status.
- Connect/disconnect action.
- Manual sync action.

Do not invest in animation, theming, avatars, complex media rendering, or native-app parity until acceptance criteria pass.

---

# 13. Outgoing Queue

Sending must pass through a local outgoing queue.

Required flow:

1. UI submits message text.
2. Backend creates a local queued message and unique client request ID.
3. Backend attempts connector send.
4. On success, update provider ID/status.
5. On retriable failure, preserve queue item and retry according to policy.
6. On permanent failure, mark failed and surface a non-secret error.

The UI should show queued/sent/failed state.

Prevent duplicate sends after restart where possible.

---

# 14. Search

Use SQLite FTS5 for MVP.

Required:

- Search message text.
- Return conversation ID.
- Return message ID.
- Return timestamp.
- Return short snippet.
- Optional provider filter.
- Optional conversation filter.

Do not implement embeddings, vector databases, or local LLMs in v0.1.

---

# 15. Logging

Implement structured logging with redaction.

Allowed:

- connector name
- account local ID
- operation
- message count
- timings
- cursor type or opaque hash
- error category

Forbidden:

- access token
- refresh token
- cookie
- password
- raw authorization header
- full private message body in normal logs

Create one redaction helper and use it consistently.

---

# 16. Security Constraints

Treat these as hard constraints:

1. Never place secrets in React state.
2. Never return secrets from Tauri commands.
3. Never commit secrets.
4. Never scrape browser credential stores.
5. Never automate unsupported provider login flows by stealing session tokens.
6. Never add an unrestricted shell bridge.
7. Never add generic filesystem access to the renderer.
8. Never implement custom cryptography when OS secret storage suffices.
9. Never weaken TLS verification.
10. Never disable certificate verification to “make it work.”

If a task appears to require violating one of these constraints, stop that subtask, document the blocker, and continue on another milestone.

---

# 17. Testing Requirements

At minimum, implement tests for:

### Core

- normalization
- conversation identity
- message identity
- deduplication
- ordering
- sync checkpoint update
- retry classification

### Database

- migrations
- upsert
- FTS search
- reopen/restart durability

### Connector fixtures

- provider payload -> normalized model
- malformed payload handling
- pagination or cursor logic

### UI smoke path

- app loads
- conversation list renders
- conversation opens
- search returns a result
- send action calls backend

Do not make network-dependent tests part of the default deterministic test suite. Real connector smoke tests should be explicitly marked and run only when credentials are configured.

---

# 18. Development Milestones

## M0 — Bootable shell

Done when:

- Tauri app launches.
- React UI renders.
- Rust command roundtrip works.

## M1 — Core + DB + MockConnector

Done when:

- migrations run.
- fixture conversations/messages sync into SQLite.
- restart preserves data.
- search works.
- deduplication tests pass.

## M2 — Real Connector A

Done when:

- account connects.
- >=50 real messages import.
- incremental sync works.
- send works if provider supports it.

## M3 — Real Connector B

Same acceptance criteria as M2.

## M4 — Unified UI

Done when:

- conversations from both real connectors appear together.
- each conversation opens correctly.
- search spans both.

## M5 — Outgoing queue

Done when:

- send status is persisted.
- retry behavior is tested.
- restart does not trivially duplicate sends.

## M6 — Security pass

Done when:

- secrets are in Keychain/approved secret store.
- renderer cannot retrieve secrets.
- IPC surface is reviewed.
- logs are redacted.
- `docs/security-notes.md` documents remaining risks.

## M7 — MVP acceptance

Run all acceptance checks from the design specification and create a final status table.

---

# 19. Status Tracking

Maintain `docs/development-status.md` with this exact structure:

```markdown
# Development Status

## Current Milestone
M?

## Working
- ...

## Blocked
- ...

## User Action Required
- ...

## Security Review Required
- ...

## Tests
- unit: PASS/FAIL
- integration: PASS/FAIL
- e2e: PASS/FAIL
- real connector A: PASS/BLOCKED/FAIL
- real connector B: PASS/BLOCKED/FAIL

## Closed Loops
- Connector Viability: OPEN/CLOSED
- Local Persistence: OPEN/CLOSED
- Unified Product Interaction: OPEN/CLOSED

## Next Highest-Leverage Action
- ...
```

Update this file whenever a milestone materially changes.

---

# 20. Definition of Done

Do not declare the MVP complete because the UI looks correct.

The MVP is complete only when:

- The macOS application runs.
- SQLite persistence works.
- Two real messaging sources have been demonstrated.
- >=50 messages have been imported from each.
- Both are normalized into the same model.
- Both appear in one local inbox.
- Local search spans imported data.
- Incremental sync survives restart.
- Sending works for send-capable connectors.
- Core tests pass.
- Credentials are not stored in plaintext app files.
- Credentials are not exposed to the renderer.
- Remaining security risks are documented.

If the second real connector is still blocked by user credentials or provider authorization, explicitly report the project as **MVP CORE COMPLETE / INTEGRATION INCOMPLETE**, not complete.

---

# 21. Final Reporting Format

At the end of each substantial run, report only actionable information:

```text
Implemented:
- ...

Verified:
- ...

Blocked:
- ...

User action required:
- ...

Security review required:
- ...

Next highest-leverage step:
- ...
```

Do not claim a feature is verified unless you actually ran the relevant test or real integration check.

---

# 22. Start Order

Start in this order:

1. Inspect existing repository.
2. Preserve useful existing work.
3. Create/update architecture docs.
4. Make the app boot.
5. Implement normalized models and connector trait.
6. Implement SQLite migrations/repositories.
7. Implement MockConnector and tests.
8. Implement basic inbox/conversation/search UI.
9. Implement real Connector A.
10. Run the 50-message proof.
11. Implement real Connector B.
12. Run the combined chronology proof.
13. Implement outgoing queue.
14. Harden credential handling and IPC.
15. Run acceptance tests.
16. Update development status with an explicit continuation/replace/abandon decision for each connector.

The highest priority is closing the connector-viability loop with executable evidence, not building visual polish.
