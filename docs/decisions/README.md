# Architecture Decision Records

This directory captures significant architectural decisions made during the project. Each ADR describes the context, options considered, chosen approach, trade-offs, and consequences.

| ID | Title | Date | Status | Summary |
|---|---|---|---|---|
| 0001 | [Modular Monolith with Hexagonal Boundaries](0001-modular-monolith.md) | 2026-07-22 | Accepted | Single deployable with module boundaries enforced by ports/adapters; enables future microservice extraction. |
| 0002 | [Separate Command, Query, and Event Buses](0002-command-query-event-buses.md) | 2026-07-22 | Accepted | CQRS at the bus level: CommandBus (sync+tx), QueryBus (sync+cache), EventBus (async+DLQ). |
| 0003 | [All Plugins Run as Subprocesses](0003-plugin-subprocess-isolation.md) | 2026-07-22 | Accepted | No in-process plugins; JSON-RPC over Unix sockets prevents GIL blocking and host crashes. |
| 0004 | [WebSocket — asyncio.Lock, EventDispatcher, Channel Permissions, Cache Callbacks](0004-websocket-asyncio-lock.md) | 2026-07-22 | Accepted | asyncio.Lock for connection registry, per-type EventDispatcher, REST scope reuse for WS auth, callback pattern for TanStack Query bridge. |
| 0005 | [JWT RS256 Authentication — Refresh Tokens, Audit Chain, Permissions, Timestamps](0005-jwt-rs256-auth.md) | 2026-07-22 | Accepted | RS256 asymmetric JWTs, opaque DB-stored refresh tokens, SHA-256 audit chain, RBAC+ABAC hybrid, ISO 8601 timestamps. |
| 0006 | [Task Queue — Dual Implementation, Event Store Chain, DLQ, Metrics Retention](0006-task-queue-dual-impl.md) | 2026-07-23 | Accepted | Abstract TaskQueue (InProcess/Arq), app-level hash chain, store-then-replay DLQ, four-tier metrics rollup tables. |

## New ADRs

To propose a new ADR, copy an existing template and add it to this table. ADRs are numbered sequentially and never deleted — only superseded by a newer ADR.
