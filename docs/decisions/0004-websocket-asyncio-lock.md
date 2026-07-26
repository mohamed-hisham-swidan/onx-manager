# ADR-0004: WebSocket — asyncio.Lock, EventDispatcher, Channel Permissions, Cache Callbacks

**Status**: Accepted
**Date**: 2026-07-22
**Author**: Architecture Review Board

## Context

Batch 06 added WebSocket support to the system. Four design decisions were made during implementation to ensure correct concurrent behavior, clean event routing, consistent authorization, and loose coupling with the frontend state layer.

---

### Decision 1: ConnectionRegistry uses asyncio.Lock

Multiple coroutines may register, deregister, or subscribe simultaneously during WebSocket connects and disconnects. Threading primitives would block the event loop; no lock at all would allow race conditions on the connection registry.

**Chosen Approach**: `asyncio.Lock` — all registry access is guarded by an async lock, providing mutual exclusion without blocking the event loop.

**Consequences**: All ConnectionRegistry access must be async and use a context manager. Slightly more overhead than no lock, but correct under concurrent connect/disconnect load.

---

### Decision 2: EventDispatcher subscribes per event type, not wildcard

The EventBus (owned by Batch 01) publishes events matched by exact `event_type` string — it has no wildcard or pattern support. Modifying the EventBus would violate the architecture rule that batches do not modify each other's code.

**Chosen Approach**: Subscribe per event type via `start(event_types=[...])`. The dispatcher receives an explicit list of event types it cares about at startup.

**Consequences**: The dispatcher must know which event types to subscribe to at startup. New domain event types must be explicitly registered with the dispatcher. Integration code passes the relevant event types when calling `dispatcher.start()`.

---

### Decision 3: Channel permission model mirrors REST API scopes

WebSocket channels need authorization that aligns with the existing REST endpoint permission model. Introducing a separate permission namespace would duplicate the RBAC/ABAC logic.

**Chosen Approach**: Reuse REST scopes (`servers:read`, `servers:write`, etc.) mapped to channel patterns in a single `CHANNEL_PATTERNS` dictionary within `authorization.py`.

**Consequences**: Auth stays consistent across the stack — REST and WebSocket use the same permission strings. Channel-to-permission mappings are hardcoded in a patterns dict. New channel types require adding an entry to `CHANNEL_PATTERNS`.

---

### Decision 4: Frontend WS handler uses callback pattern for cache updates

The WebSocket handler on the frontend must integrate with TanStack Query for automatic cache invalidation, but should remain framework-agnostic and testable without React.

**Chosen Approach**: Callback pattern — the handler accepts an `onCacheUpdate` callback. The consumer (WebSocketManager component) wires the callback to the TanStack QueryClient.

**Consequences**: The websocket package stays independent of React and TanStack Query. The consumer must implement the callback. Frontend features (Batch 10) wire the callbacks to the QueryClient for automatic cache invalidation. The handler can be unit-tested without rendering React components.
