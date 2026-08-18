# DESIGN SPECIFICATION: WebSocket Domain-Event Delivery & Dormant Pipeline Wiring

- **Document ID**: `SPEC-WS-DELIVERY-001`
- **Revision**: `1.0`
- **Date**: 2026-08-18
- **Status**: `PROPOSED` (Awaiting Build Approval)
- **Author**: Design Agent
- **Prerequisite RECON**: Two independent repo-verified RECON passes (2026-08-18)
  confirmed the EventBus wiring gap, the dormant crash→health pipeline, the
  structurally-dead offline buffer, and the absence of wiring-level tests.
  Documentation status was corrected in commit `1a3c52a` (K2a vs K2b split);
  this spec does **not** touch `.ai` state tracking.

---

## 1. Executive Summary & Problem Statement

### 1.1 Problem Statement

The production `EventBus` has exactly **one** subscriber. In
`backend/app/websocket/endpoint.py:72` the application subscribes a single
handler (`MetricsBridgeHandler`) to a single event type
(`"MetricCollectedEvent"`). Every other domain event published via
`UnitOfWork(event_bus)` in command handlers — `ServerStartedEvent`,
`ServerStoppedEvent`, `ServerCrashedEvent`, `Backup*`, `Plugin*`,
`ServerExposure*`, health classifications — is silently dropped at
`backend/app/core/event_bus.py:98-100` (`if not subscribers: return`).

Three distinct production defects share this single root cause:

1. **No domain-event WebSocket delivery anywhere.** `EventDispatcher`
   (`backend/app/websocket/dispatcher.py:16-113`) is fully implemented and
   unit-tested in isolation (`backend/tests/test_websocket.py:429-499`) but is
   never instantiated or subscribed during application startup. The frontend
   `server:*` subscription (`frontend/src/components/WebSocketManager.tsx:81`)
   and the WS event→cache-invalidation bridge
   (`frontend/src/websocket/handler.ts:120-152`) therefore never receive
   anything; state updates depend entirely on HTTP mutation-invalidation and
   polling.
2. **The crash→health pipeline is fully dormant.** `HandleServerCrashHandler`
   (`backend/app/modules/health/application/event_handlers/server_crashed_handler.py:17`)
   and `HealthSignalHandler`
   (`backend/app/modules/health/application/event_handlers/health_signal_handler.py:26`)
   are `EventHandler` implementations that are **never constructed or
   subscribed anywhere** in the codebase. `ServerCrashedEvent` reaches neither
   the WebSocket layer nor the health/evidence/classification/recovery pipeline.
3. **The offline reconnect buffer is structurally unreachable.** Even after
   wiring, `OfflineMessageBuffer` (`backend/app/websocket/buffer.py:17`) can
   never be fed by `EventDispatcher.handle` (`dispatcher.py:59-68`) because
   `_find_disconnected_user_ids` (`dispatcher.py:75-87`) can only find users
   who still hold a live connection — full trace in Decision 3.

### 1.2 End-User Symptoms

1. **Stale server states / delayed visibility.** Server start/stop/crash are
   only visible after the next REST poll (`useServerRuntime` polls at 10 s:
   `frontend/src/server_manager/hooks/useServers.ts:75`; console at 3 s;
   metrics at 5 s). Other sessions' changes never appear live.
2. **Crash diagnostics silently never run.** A crashed server raises
   `ServerCrashedEvent` (published through UoW commit in command handlers,
   e.g. `start_server.py:99-102`), which is dropped. No evidence collection,
   no classification, no health re-evaluation, no recovery trigger.
3. **RecentActivity widget is empty in production.** The activity feed
   (`frontend/src/stores/activityStore.ts`, rendered by `RecentActivity.tsx`)
   is fed exclusively by WS `event`/`state_sync` frames
   (`WebSocketManager.tsx:57-69`); there is no REST events endpoint. Since no
   event ever reaches the WS, the feed never renders anything.
4. **Reconnection loses state-change history.** The built
   `state_sync`/offline-buffer path (`handlers.py:82-91`,
   `handler.ts:75-82,154-160`) has never carried real data.

### 1.3 Scope

**In scope:**
- Wire `EventDispatcher` into `start_websocket_services()` /
  `stop_websocket_services()` and define an explicit subscribed-event-type
  allowlist.
- Wire `HandleServerCrashHandler` and `HealthSignalHandler` into the event bus.
- Make the offline reconnect buffer feedable (registry-level persistent
  user↔channel bindings) and verify the drain path end-to-end.
- New tests that exercise **real** startup wiring (the gap no current test
  covers).
- Incidental fix: `MetricsBatcher` flush-window bootstrap from persisted
  settings (Decision 5).

**Out of scope:**
- Any REST/API change, schema change, or migration.
- Frontend UX polish for activity-feed verb mapping (see OQ-2).
- WS support for the `server:{server_id}:console` channel (declared
  `authorization.py:6`, validated `authorization.py:91-92`, the frontend's
  channel validator rejects 3-part shapes at `channels.ts:131-136`). It stays
  dead by design.
- The event-store module and all metrics-intake behavior other than Decision 5.

---

## 2. Root Cause Analysis (Verified with Codebase Evidence)

1. **Single-subscriber EventBus.**
   - Bus created once: `backend/app/main.py:99` `event_bus = EventBus()`.
   - Same instance flows to DI (`main.py:101` →
     `backend/app/api/deps.py:47-50`, resolved by `deps.py:65-69`) and to the
     WebSocket layer (`main.py:105` `init_websocket(event_bus)`).
   - Production subscriptions today: exactly **one** — `endpoint.py:72`
     `_event_bus.subscribe("MetricCollectedEvent", _bridge)`. Repo-wide
     `.subscribe(` grep in `backend/app` yields only `endpoint.py:72`,
     `dispatcher.py:31` (EventDispatcher, never invoked), and
     `handlers.py:131` (registry channel membership, unrelated to the bus).
   - `EventBus.publish` returns early on empty subscribers:
     `event_bus.py:98-100`.
2. **Wiring functions omit EventDispatcher.**
   - `init_websocket` (`endpoint.py:53-61`) builds registry/auth/authz/buffer/
     rate-limiter/handler only.
   - `start_websocket_services` (`endpoint.py:64-75`) instantiates only
     `MetricsBatcher` + `MetricsBridgeHandler`; `stop_websocket_services`
     (`endpoint.py:77-81`) stops only the batcher.
   - No code path imports or instantiates `EventDispatcher` outside its
     definition (`dispatcher.py:16`) and the tests.
3. **Dormant EventHandlers.** `HandleServerCrashHandler` and
   `HealthSignalHandler` are referenced only by their own files;
   `registration.py` (`_register_command_handlers` `:170-222`,
   `_register_query_handlers` `:225-252`) registers commands and queries, but
   has **no event-handler registration block and no `.subscribe` call** for
   any domain event.
4. **Structurally unreachable offline buffer.**
   - `_find_disconnected_user_ids` (`dispatcher.py:75-87`) iterates
     `ConnectionRegistry._user_connections`, but `manager.deregister`
     (`manager.py:22-33`) deletes a user's entry once their last connection
     drops, so an exclusively-offline user is invisible to the loop.
   - The send loop (`dispatcher.py:45-51`) already delivers to every connected
     subscriber of a routed channel and dedupes via `sent`, so
     `conns.intersection(sent_connections)` is never empty for a connected
     subscriber — `buffer.add` is unreachable in the synchronized design.
   - Existing tests unit-test only `OfflineMessageBuffer` add/get/clear
     (`test_websocket.py:382-426`) and the dispatcher **sent** path
     (`test_websocket.py:442-458`); none exercise the buffering path.

---

## 3. Design Decisions & Architecture

### Decision 1 — Wire EventDispatcher to the EventBus with an explicit event-type allowlist

**Location.** Extend the two existing service functions:
- `start_websocket_services()` (`endpoint.py:64-75`) to also instantiate
  `EventDispatcher(_registry, _buffer, _event_bus)` and call
  `await dispatcher.start(event_types=ALLOWLIST)`.
- `stop_websocket_services()` (`endpoint.py:77-81`) to also
  `await dispatcher.stop()`.
- Add a module global `_dispatcher: EventDispatcher | None` alongside the
  existing globals (`endpoint.py:23-31`).

This is the correct locality: the dispatcher depends on WebSocket-layer
collaborators (`_registry`, `_buffer`) exactly like the already-wired
`MetricsBatcher` (`endpoint.py:70`).

**Startup sequence (verified, no `main.py` change required):**
`main.py:105` `init_websocket(event_bus)` → `main.py:106`
`await start_websocket_services()`. The lazy fallback for a first `/ws`
connection without a lifespan run (`endpoint.py:95-96`) already calls
`init_websocket` and is unaffected.

**EventDispatcher API needs no modification.** `start(event_types: list[str] | None)`
(`dispatcher.py:28-33`) already subscribes per event-type string and no-ops on
`None`; `stop()` (`dispatcher.py:35-38`) unsubscribes tracked subscriptions.
Subscription keying matches publish keying because `EventBus.publish` fills
`event_type` with the class name when empty (`event_bus.py:94-96`).

**Allowlist decision (explicit allowlist, NOT "all subtypes").** The channel
router has a catch-all default: `_resolve_channels` (`dispatcher.py:89-113`)
falls through to `server:*` for any event with no `server_id` that does not
match the `Backup`/`Plugin`/`Alert`/`Metric` substrings (`dispatcher.py:110-111`).
Every authenticated session with `server:read` subscribes to `server:*`
(`WebSocketManager.tsx:81`). Subscribing all 52 `DomainEvent` subtypes would
therefore broadcast cross-user auth events (`UserLoggedInEvent`,
`ApiKeyCreatedEvent`, … — `backend/app/modules/auth/domain/events.py:8-46`,
none carry `server_id`) and instance/agent operations
(`AgentClaimGeneratedEvent`, `PanelExposureChangedEvent`, … —
`backend/app/modules/exposure/domain/events.py:28-57`) to every client on
`server:*` — a privacy leak and noise.

**Chosen allowlist** (31 event-type names, declared once as a module constant
co-located with the dispatcher in `dispatcher.py`, imported by `endpoint.py`):

| Family | Event types | Routing today (`dispatcher.py:89-113`) |
|---|---|---|
| Server | `ServerCreatedEvent, ServerStartingEvent, ServerStartedEvent, ServerStoppingEvent, ServerStoppedEvent, ServerCrashedEvent, ServerConfigChangedEvent, ServerDeletedEvent, ServerDiscoveredEvent, ServerVanishedEvent` | `server:{id}` + `server:*` (discovery events carry no `server_id` → default `server:*`, semantically correct) |
| Backup | `BackupStartedEvent, BackupCompletedEvent, BackupFailedEvent, BackupRestoredEvent, BackupDeletedEvent` | `backup:*` + server channels |
| Plugin | `PluginInstalledEvent, PluginEnabledEvent, PluginDisabledEvent, PluginUninstalledEvent, PluginUpdatedEvent` | `plugin:*` + server channels |
| Exposure (server-scoped) | `ServerExposureEnabledEvent, ServerExposureDisabledEvent, ServerExposureRemovedEvent` | server channels |
| Monitoring | `AlertTriggeredEvent, AlertResolvedEvent` | monitoring channels + server channels |
| Health/crash pipeline products | `EvidenceCollectedEvent, CrashClassifiedEvent, RecoveryTriggeredEvent, RecoveryFailedEvent, RecoverySucceededEvent, HealthStatusChangedEvent` | server channels (`server_id` present) |

**Name-collision note (settled, no action).** Subscriptions are string-keyed
on the class name (`event_bus.py:94-96`). Both
`monitoring/domain/events.py:17` and `health/domain/events.py:113` define a
class named `AlertTriggeredEvent` — the single allowlist entry
`"AlertTriggeredEvent"` therefore covers **both** classes. Both carry
`server_id` and route identically through the `"Alert"` branch
(`dispatcher.py:105-108`). Acceptable; the health variant has no producer
today, so only `monitoring/domain/aggregate.py:155` actually fires.

**Excluded (each citing code):**
- **auth family** (`auth/domain/events.py:8-46`) — cross-user; would land on
  the `server:*` default.
- **instance/agent & panel exposure** (`exposure/domain/events.py:28-57`;
  the three server-scoped events above ARE included) — no `server_id`, no
  user-facing server context.
- **metrics** (`MetricCollectedEvent`, `MetricRecordedEvent`) — already
  delivered at 5 Hz via `metrics_batch` (`dispatcher.py:148-155`); an `event`
  frame per sample would double-broadcast and flood.
- **health infra/source signals** (`RuntimeHealthSignalEvent`,
  `IntegrityCheckFailedEvent`, `EnvironmentDegradedEvent`, `StartupValidation*`,
  `HealthReportGeneratedEvent`) — no producers exist in `backend/app` today
  (repo-wide construction grep). Excluded from WS broadcast for now;
  `HealthSignalHandler` still subscribes to the first two (Decision 2).

**Rationale.** The allowlist is exactly the set of events whose broadcast
(1) is scoped to a server the viewer already has `server:read` on, or an
existing `backup:*`/`plugin:*`/`monitoring:*` channel surface
(`authorization.py:3-17`), and (2) has a real producer today. It matches the
frontend's existing cache-invalidation semantics (`handler.ts:124-151`) and
activity-feed vocabulary (`RecentActivity.tsx` verb map), so it activates
behavior the UI was already built to consume — no frontend change required.

### Decision 2 — Wire the crash→health event pipeline

**Location.** `registration.py` — add `_register_event_handlers(event_bus)`
invoked from `register_handlers` (`registration.py:160-167`). This is
domain/application wiring, not WebSocket-layer wiring; it belongs next to
command/query registration, in the same module that constructs the handlers.

**Subscriptions:**
- `HandleServerCrashHandler(event_bus)` → subscribe `"ServerCrashedEvent"`.
  The handler guards on `isinstance(event, ServerCrashedEvent)`
  (`server_crashed_handler.py:24-26`), so a scoped subscription is exact.
- `HealthSignalHandler(event_bus)` → subscribe `"RuntimeHealthSignalEvent"`,
  `"IntegrityCheckFailedEvent"`, `"CrashClassifiedEvent"` (matching its
  `handle()` dispatch switch at `health_signal_handler.py:31-37`).
  `"CrashClassifiedEvent"` is the only one with a producer today (emitted by
  `HandleServerCrashHandler` at `server_crashed_handler.py:48-56`); the other
  two complete the handler's designed surface at negligible cost.

**Coupling with Decision 1 — explicitly NOT subsumed by it.**
- Wiring EventDispatcher alone **leaves both handlers dormant**: they are
  domain `EventHandler`s, not part of the WS dispatch path, and nothing else
  constructs or subscribes them (repo-wide grep). Both wiring operations are
  required — the three gaps share a root cause but not a single fix.
- The reverse dependency also holds: wiring the crash pipeline alone would
  produce `CrashClassifiedEvent` / `HealthStatusChangedEvent` / `Recovery*`
  events that are still dropped (`event_bus.py:98-100`) unless Decision 1's
  allowlist includes them — which it does (health/crash products row).
- **Ordering is non-blocking.** `EventBus.publish` runs subscribers
  concurrently via `asyncio.gather` (`event_bus.py:106-110`). On a crash the
  raw `ServerCrashedEvent` may reach the client before the classification
  frame. Acceptable (eventual consistency — the UI renders both); **do not
  add ordering guarantees.**

**Per-subscriber timeout override (Decision 2a — owner-decided, root-cause fix).**
The bus subscriber timeout is global at 10 s (`event_bus.py:58`) with up to
`retry_attempts` retries before dead-lettering (`event_bus.py:112-151`).
`HandleServerCrashHandler` performs log-based evidence collection
(`server_crashed_handler.py:31-32`) that can exceed 10 s on large logs,
dead-lettering the classification. **Do not ship-and-monitor** — Mohamed
decided the root-cause fix up front:

- Add an optional **per-subscription timeout override** to the bus — additive
  and backward compatible (all existing `subscribe` call sites unchanged:
  `endpoint.py:72`, `dispatcher.py:31`): extend `Subscription`
  (`event_bus.py:39-43`) with an optional `timeout` field defaulting to `None`
  (use the global `_subscriber_timeout`), expose an optional `timeout` param on
  `EventBus.subscribe()` (`event_bus.py:60-71`), and have
  `_dispatch_with_retry` (`event_bus.py:112-122`) use the per-subscription
  timeout when present, else the global. Retry/dead-letter semantics unchanged.
- `_register_event_handlers` subscribes `HandleServerCrashHandler` with an
  explicit **60 s per-attempt override** — evidence collection is local
  disk-bound log reading; 60 s bounds even large logs while leaving ample
  headroom over the 10 s default. `HealthSignalHandler` is DB-bound and keeps
  the global default.
- `dead_letter_count` (`event_bus.py:77-78`) remains a servicability signal
  (log/expose it), but is no longer the mitigation.

### Decision 3 — Make the offline reconnect buffer feedable and verify the drain path

**Structural finding (deepens the RECON).** Two independent reasons make
`buffer.add` unreachable:
1. `_find_disconnected_user_ids` (`dispatcher.py:75-87`) only scans
   `_user_connections`, which `manager.deregister` clears on disconnect
   (`manager.py:30-33`); a fully-offline user is invisible.
2. Every connected subscriber already received the event via the send loop
   (`dispatcher.py:45-51` + `sent` dedupe), so
   `conns.intersection(sent)` is non-empty and the buffering condition fails
   (`dispatcher.py:85`).

**Fix — persistent "user↔channel intent" bindings in the registry.** The
registry must remember, across disconnect, which channels a user subscribed
to:
- Add `_user_channel_bindings: dict[str, set[str]]` to `ConnectionRegistry`
  (`manager.py:10-16`). `deregister` (`manager.py:22-33`) must NOT clear these
  bindings — only the live maps (`_connections`, `_user_connections`,
  `_channel_connections`, `_connection_channels`).
- Recording: in the `subscribe` branch (`handlers.py:99-131`, `user_id` in
  scope) also bind `user_id → channel`; mirror removal in the `unsubscribe`
  branch (`handlers.py:133-142`). Expose this as new registry methods
  (`bind_user_channel` / `unbind_user_channel`, or user-aware subscribe
  semantics) — Build picks the smallest shape that keeps `WSConnectionHandler`
  unchanged in behavior.
- Consumption: `_find_disconnected_user_ids` (`dispatcher.py:75-87`) switches
  from `_user_connections` to the persistent bindings. A user is
  "disconnected but interested" when their bound channels intersect the
event's channels **and** they hold no live connection. `buffer.add`
   (`dispatcher.py:59-68`) becomes reachable.

**Eviction / leak guard (required, not optional).** Bindings survive across
connections by design, so they persist for users who disconnect permanently —
unlike every other registry structure they have no TTL
(`manager.py:12-15`). Without eviction a long-lived process accrues one
binding set per ever-seen user ID. Minimal correct policy for Build: a binding
whose owner holds **no live connection** is eligible for eviction once its
matching `OfflineMessageBuffer` bucket is empty/expired (buffer TTL is 300 s,
`buffer.py:18`) — or simply evicted on the next dispatch where the user holds
no connection and has no buffered entries; Build picks the smallest
implementation that roots the cleanup to the existing buffer TTL.

**Bind/unbind symmetry (required).** Bindings are recorded only for
authorized, validated channel subscriptions (`handlers.py:116-131`, after both
`validate_channel` and `can_subscribe` pass — a failed authorization or a
`CHANNEL_LIMIT` rejection therefore never creates a partial binding, because
the loop returns before binding). A matching unbind **must** be issued from
the `unsubscribe` branch (`handlers.py:133-142`), so a user who explicitly
leaves a channel while online is never buffered for it afterwards.

**Drain path needs no additional wiring.** Backend `_send_pending_events`
(`handlers.py:82-91`) is invoked once at connect (`handlers.py:45`), sends one
`state_sync` frame, then clears the buffer. It already runs **after** the new
token's authorizer permissions are set (`handlers.py:41-42`) and is order-
independent of channel re-subscription. Frontend `handler.ts:75-82` routes
`state_sync` → `onStateSync` (store replace via `activityStore.setEvents`) plus
per-event cache invalidation. No frontend change required on the happy path.

**Disconnect→connect race closes naturally.** Under the new bindings logic,
once a user holds any live connection the dispatcher stops buffering for them,
so the get-pending-then-clear bucket race (`handlers.py:83-91`) loses its
window: events arriving mid-drain are delivered live, not appended to a bucket
that `clear()` would then pop.

**Security requirement (permission revocation while offline).** `state_sync`
is currently sent to the user's buffer bucket without re-checking the current
token's permissions. Each `BufferedMessage` carries its `channels`
(`buffer.py:11-14`) and the authorizer is fresh per connection
(`handlers.py:42`), so the drain should filter per channel: drop events whose
channels the current permissions no longer authorize (`authorization.py:41-58`).
Prevents buffered-data leakage on permission downgrade.

### Decision 4 — Test plan: scenarios that would have caught the gap

`TestEventDispatcher` (`test_websocket.py:429-499`) and
`TestMetricsBridgeHandler` (`test_websocket.py:567-630`) manually wire
components; `test_ws_console_integration.py:18-26` swaps in a `_noop_lifespan`.
None exercise the production wiring functions. The tests below call
`init_websocket` + `start_websocket_services` directly (mirroring
`main.py:105-106`), or run the real lifespan; **each fails against current
code.**

Backend (pytest):

| ID | Scenario | Expected | Fails pre-fix because |
|---|---|---|---|
| T-WS-01 | After `init_websocket(eb)` + `start_websocket_services()`, assert the bus has a subscriber for ≥1 allowlisted type (`"ServerStartedEvent"`). | Dispatcher present in `eb._subscribers`. | `start_websocket_services` never subscribes it. |
| T-WS-02 | Real wiring + TestClient WS at `/ws?token=…`, subscribe `server:*`, publish `ServerStartedEvent`. | Client receives an `event` frame with `event_type == "ServerStartedEvent"`. | Dispatcher not subscribed → `event_bus.py:98` no-op. |
| T-WS-03 | Same pattern, publish `ServerCrashedEvent`. | Client receives `ServerCrashedEvent`. | Same. |
| T-WS-04 | With `LogBasedEvidenceCollector` / `PatternCrashAnalyzer` mocked, publish `ServerCrashedEvent`. | `save_evidence`/`save_classification` invoked (or `EvidenceCollectedEvent` + `CrashClassifiedEvent` re-published). | Crash handler never constructed/subscribed. |
| T-WS-05 | Chain: publish `ServerCrashedEvent` (mocked collector/classifier/recovery) → `HealthSignalHandler` recomputes (`SQLHealthRepository.save`) **and** WS client on `server:*` receives `CrashClassifiedEvent` + `HealthStatusChangedEvent`. | Full end-to-end chain. | Pipeline dormant + dispatcher unwired. |
| T-WS-06 | Offline buffer: connect+subscribe `server:*`, disconnect, publish `ServerStartedEvent`, reconnect. | First frame is `state_sync` containing the event; buffer cleared. | Buffer structurally unreachable (Decision 3). |
| T-WS-07 | `stop_websocket_services()` after start, then restart. | Subscriptions cleared (`.stop()`), batcher stopped; no subscription leak on restart. | Guards restart symmetry. |
| T-WS-08 | Publish `MetricCollectedEvent` with batcher running. | Only a `metrics_batch` frame; **no** `event` frame. | Guards Decision 1 metrics exclusion. |
| T-WS-09 | Publish `UserCreatedEvent` (auth). | No client frame delivered on `server:*`. | Guards Decision 1 privacy exclusion. |
| T-WS-10 | Buffer an event offline under perms A; reconnect with a token lacking `server:read`. | Event filtered from `state_sync`. | Guards Decision 3 security requirement. |
| T-WS-13 | Persist `metrics_interval_seconds=1.5`; run `start_websocket_services()`. | `MetricsBatcher._window_seconds == 1.5`. | `endpoint.py:70` hardcodes 0.2. |
| T-WS-14 | Run real `_register_event_handlers`; assert the `HandleServerCrashHandler` `Subscription.timeout == 60.0` while the bus global stays 10.0. Unit-assert `_dispatch_with_retry` honors a tiny per-sub override (dead-letter only after the override, not the global, expires). | Decision 2a per-subscriber timeout mechanism proven. | No per-sub mechanism exists today (`event_bus.py:121` hardcodes the global). |

Frontend (Vitest):

| ID | Scenario | Expected |
|---|---|---|
| T-WS-11 | Feed `WSStateSyncMessage` into `WSHandler`; assert `onStateSync` fired, `reconnectBuffer` set, and `server:{id}`/`servers:list` cache updates fire per event type (`handler.ts:120-152`). | Drain-path contract; add the reconnect-drain sequencing assertion. |
| T-WS-12 | Feed the crash chain (`ServerCrashedEvent` → `CrashClassifiedEvent` → `HealthStatusChangedEvent`) into the activity store via `toActivityEvent`. | `RecentActivity` renders ≥1 red crash row (`RecentActivity.tsx` verb map). |

### Decision 5 — MetricsBatcher flush-window bootstrap from persisted settings (IN SCOPE, incidental)

**Include as a minor in-scope item.** Rationale: one-line change inside the
exact function this spec modifies (`start_websocket_services`,
`endpoint.py:64-75`), using only existing API (`get_live_settings` at
`settings_store.py:131-140`; `set_window_seconds` at `dispatcher.py:124-125`),
and it closes a live inconsistency — a persisted non-default
`metrics_interval_seconds` is honored by the scheduler cron (`main.py:282-284`,
`scheduler.py:137-144`) but ignored by the batcher until a PATCH
(`settings.py:45-59`). Leaving it would ship the new wiring with a latent
half-honored setting. Coverage: T-WS-13.

### Decision 6 — Rollout behavior change (dormant → active)

1. **No deploy-time backlog or flood.** The bus is in-memory and per-process
   (`main.py:99`); no persisted event queue, no startup replay. First deploy
   delivers only events occurring after boot.
2. **Duplicate/conflicting invalidation is benign.** State changes currently
   invalidate via mutation `onSuccess` (`useServers.ts:42-55,84-86,97-100`).
   Once WS events flow, the same cache keys are also invalidated by
   `WebSocketManager.onCacheUpdate` (`WebSocketManager.tsx:33-55` via
   `handler.ts:124-151`). TanStack Query coalesces concurrent invalidations;
   worst case is one redundant refetch. **No frontend change required.**
3. **Behavioral surface changes:** RecentActivity starts rendering (it is
   currently empty in production), and cache invalidation becomes cross-session
   live for the event families the frontend maps. The activity store caps at 20
   entries (`activityStore.ts:19`), and the WS event rate is bounded by the
   allowlist (metrics excluded, auth excluded). **Known residual:** a
   `ServerCrashedEvent` invalidates **no** TanStack query — `handler.ts:124-151`
   only maps `Server*Created/Started/Stopped/Restarted`, `Backup*`, `Plugin*`.
   The crash lands in the activity feed only (`RecentActivity.tsx:11-13` red
   `crashed` row); the degraded server state is re-fetched on the next 10 s
   runtime poll (`useServers.ts:75`). Accepted: optional follow-up (OUT of
   scope) adds a `ServerCrashed` branch to `_updateCacheFromEvent`.
4. **Crash-chain latency:** classifier output may trail the raw crash frame by
   seconds and could dead-letter under evidence collection >10 s
   (`event_bus.py:58,112-151`) — monitored via `dead_letter_count` (OQ-1).
5. **Permission downgrade while offline:** addressed by Decision 3's
   per-channel reauthorization on drain (cannot ship without that filter).

---

## 4. Architecture & Execution Flow

```
Startup (main.py:99-106)
├── EventBus()                        ── single instance, all subscribers below
├── init_buses(...)                   → dep injection (deps.py:47-50)
├── register_handlers(...)            → Decision 2: _register_event_handlers
│     ├── HandleServerCrashHandler ── subscribes "ServerCrashedEvent"
│     └── HealthSignalHandler ────── subscribes "RuntimeHealthSignalEvent",
│                                    "IntegrityCheckFailedEvent",
│                                    "CrashClassifiedEvent"
└── init_websocket(event_bus)         (endpoint.py:53-61)
    └── start_websocket_services()    (endpoint.py:64-75) [Decision 1 + 5]
          ├── MetricsBatcher + MetricsBridgeHandler → "MetricCollectedEvent"
          ├── MetricsBatcher window ← live_settings.metrics_interval_seconds
          └── EventDispatcher(_registry,_buffer,_event_bus)
                └── start(31 allowlisted types)

Runtime event flow (crash example)
ServerCrashedEvent (UoW commit, start_server.py:99-102)
 ├── EventBus.publish (event_bus.py:94-110, concurrent gather)
 │     ├── HandleServerCrashHandler → evidence + classify + recovery
 │     │     └── publishes CrashClassifiedEvent → HealthSignalHandler
 │     │           └── HealthStatusChangedEvent (health aggregate)
 │     └── EventDispatcher
 │           ├── live: route → server:{id}/server:* → registry.broadcast
 │           └── offline: bindings ∩ channels, no live conn → buffer.add
Reconnect (handlers.py:36-45)
 └── _send_pending_events → state_sync (filtered by current perms) → client
```

---

## 5. Acceptance Criteria & Test Matrix

**Acceptance criteria:** the build passes when (a) all T-WS tests in this
section are green against the *new* wiring, (b) each test is **known to fail
against current code** (regression proof, per Decision 4), and (c) no
pre-existing backend/frontend suite regresses.

### 5.1 Backend acceptance matrix (detailed scenarios: Decision 4)

| ID | Acceptance criterion (must be true post-fix) |
|---|---|
| T-WS-01 | `EventBus` has a `"ServerStartedEvent"` subscriber immediately after `start_websocket_services()`. |
| T-WS-02 / T-WS-03 | WS client on `server:*` receives `event` frames for server lifecycle events (`ServerStartedEvent`, `ServerCrashedEvent`). |
| T-WS-04 / T-WS-05 | Crash chain executes end-to-end: evidence collected, crash classified, health recomputed, and WS client receives `CrashClassifiedEvent` + `HealthStatusChangedEvent`. |
| T-WS-06 / T-WS-07 | Offline reconnect delivers a `state_sync` frame containing the buffered event then clears the bucket; restarts leak zero subscriptions. |
| T-WS-08 | Metrics produce `metrics_batch` only — never an `event` frame. |
| T-WS-09 | Auth/instance events never reach `server:*` subscribers (privacy guard). |
| T-WS-10 | Permission-downgraded reconnect drains a permission-filtered `state_sync`. |
| T-WS-13 | `MetricsBatcher` window equals persisted `metrics_interval_seconds` at boot. |
| T-WS-14 | Per-subscriber timeout override applied: `HandleServerCrashHandler` subscription carries 60 s, bus global stays 10 s; a slow subscriber is bounded by its own override, not the global window. |

### 5.2 Frontend acceptance matrix (detailed scenarios: Decision 4)

| ID | Acceptance criterion (must hold for the existing WS runtime) |
|---|---|
| T-WS-11 | `state_sync` drain → `onStateSync` fired + per-type cache invalidation with correct reconnect-buffer sequencing (`handler.ts:120-152`). |
| T-WS-12 | Crash-chain frames render a red crash row in `RecentActivity` (verb map). |

### 5.3 Non-regression constraints

- Existing suites (`test_websocket.py`, `test_ws_console_integration.py`,
  auth/health suites) stay green; additions only.
- No `.ai` state / K2 tracking edits (aligned with commit `1a3c52a`).
- No schema, migration, or REST contract changes.

---

## 6. Findings Ledger

| ID | Finding | Type | Date | Disposition |
|---|---|---|---|---|
| F-WS-01 | EventBus has exactly one production subscriber (`"MetricCollectedEvent"`, `endpoint.py:72`); all other domain events dropped at `event_bus.py:98-100`. | Confirmed defect | 2026-08-18 | Decision 1 (allowlist wiring) |
| F-WS-02 | `EventDispatcher` never instantiated or subscribed in any startup path (`endpoint.py:53-81`; only usage is its own tests). | Confirmed defect | 2026-08-18 | Decision 1 |
| F-WS-03 | `HandleServerCrashHandler` + `HealthSignalHandler` never constructed/subscribed (`registration.py` lacks an event-handler block). | Confirmed defect | 2026-08-18 | Decision 2 |
| F-WS-04 | `OfflineMessageBuffer` structurally unreachable — `_find_disconnected_user_ids` (`dispatcher.py:75-87`) vs `manager.deregister` clearing `_user_connections` (`manager.py:30-33`). | Confirmed defect (deepened during design) | 2026-08-18 | Decision 3 |
| F-WS-05 | No test exercises real startup wiring for WS delivery or the crash pipeline (`test_ws_console_integration.py:18-26` uses a noop lifespan). | Test gap | 2026-08-18 | Decision 4 (T-WS-01..13) |
| F-WS-06 | `MetricsBatcher` window hardcoded 0.2 at boot (`endpoint.py:70`) while the scheduler honors persisted `metrics_interval_seconds` (`main.py:283`). | Confirmed inconsistency | 2026-08-18 | Decision 5 (T-WS-13) |
| F-WS-07 | Documentation previously claimed K2 WebSocket delivery "Fixed"; split into K2a/K2b in commit `1a3c52a`. | Documentation | 2026-08-18 | Aligned — no further action in this spec |
| F-WS-08 | EventBus has no per-subscriber timeout mechanism — `Subscription` (`event_bus.py:39-43`) carries only handler/priority/cancelled, and `_dispatch_with_retry` hardcodes the global `_subscriber_timeout` (`event_bus.py:121`). Confirms Decision 2a needs an additive override. | Confirmed gap | 2026-08-18 | Decision 2a (per-subscriber timeout) |

---

## 7. Open Questions (for Owner / Review)

| ID | Question | Impact | Decision point |
|---|---|---|---|
| OQ-1 | **RESOLVED — owner decided root-cause fix (Decision 2a).** Explicit per-subscriber timeout override added to `EventBus.subscribe()`; `HandleServerCrashHandler` subscribes with a 60 s per-attempt override; `HealthSignalHandler` and all other subscribers keep the 10 s global default. `event_bus.py` gains only the additive override (backward compatible); `dead_letter_count` demoted to servicability signal. | Resolved up front | 2026-08-18 | Resolved before Build — no ship-and-monitor |
| OQ-2 | New WS event types (crash chain, health) map onto `RecentActivity` verb icons — confirm desired copy/visuals for `CrashClassified`/`HealthStatusChanged` rows or accept current defaults. | Cosmetic (activity feed only). | During Build; functional mapping already exists. |
| OQ-3 | Decision 3 registry API shape: Build to choose between explicit `bind_user_channel`/`unbind_user_channel` methods vs. recording inside the subscribe/unsubscribe flow. | Internal API only. | Build decision; no Owner required. |

---

## 8. Implementation Boundary

1. **Files to modify:** `backend/app/websocket/endpoint.py` (wire dispatcher
   + batcher window), `backend/app/websocket/dispatcher.py` (allowlist constant
   + bindings consumption in `_find_disconnected_user_ids`),
   `backend/app/websocket/manager.py` (persistent `_user_channel_bindings` +
   eviction), `backend/app/websocket/handlers.py` (bind/unbind recording + drain
   permission filter), `backend/app/core/event_bus.py` (additive per-subscriber
   timeout override, Decision 2a), `backend/app/registration.py`
   (`_register_event_handlers`), plus additive tests in `backend/tests/` and
   the frontend test suite.
2. **Core bus scope (additive only, Decision 2a):** `core/event_bus.py` gains
   two backward-compatible affordances — an optional `timeout` field on
   `Subscription` (default `None` = global) and an optional `timeout` param on
   `subscribe()`, consumed by `_dispatch_with_retry`. The global
   `_subscriber_timeout`, retry and dead-letter semantics are unchanged. No
   other bus internals are modified.
3. **Do NOT touch:** any schema/migration, REST `settings` API, and the
   frontend WS runtime (`WebSocketManager`, `handler.ts`, `activityStore`) on
   the happy path.
4. **Verification order:** full backend suite → targeted T-WS tests (each must
   reproduce the pre-fix failure) → frontend vitest → manual smoke: two
   clients, one mutating one observing; force `server_crashed` via
   `docker stop` to observe the crash chain and offline→reconnect buffering.
5. **Commit scope:** spec + implementation + T-WS tests + documentation/state
   updates in the same batch (traceability gate). Do **not** commit by default;
   await explicit instruction.

---

_End of SPEC-WS-DELIVERY-001._