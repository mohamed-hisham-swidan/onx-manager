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
| 0007 | [Rename app/storage/ to app/core/persistence/](0007-core-persistence-rename.md) | 2026-07-27 | Accepted | Relocated database engine, base ORM, UoW under `core/persistence/`; all imports, ADRs, and docs updated in one commit. |
| 0008 | [Environment-Variable-Driven Sandbox Isolation](0008-env-var-sandbox-isolation.md) | 2026-07-27 | Accepted | Sandboxing driven by `MCS_*` env vars so tests never touch production data or servers. |
| 0009 | [Pydantic Field Validators for Domain Value-Object Inputs](0009-pydantic-field-validator-for-domain-values.md) | 2026-07-27 | Accepted | Schema-level `@field_validator`s enforce domain value-object invariants at the API boundary. |
| 0010 | [Commit-per-Step Discipline for Structural Changes](0010-commit-per-step-discipline.md) | 2026-07-27 | Accepted | One concern per commit during refactors so each step stays reviewable and revertible. |
| 0011 | [Orphan Reconciliation — Ownership Verification](0011-orphan-reconciliation-ownership-verification.md) | 2026-07-27 | Accepted | Orphan cleanup verifies a process truly belongs to the managed server set (MCS marker / cwd / start-time) before killing, with project-owned vs system-wide scopes. |
| 0012 | [Same-Filesystem Staging for Atomic File Swaps](0012-same-filesystem-staging-for-atomic-swaps.md) | 2026-08-04 | Accepted | Files staged for atomic swap onto live data must live on the same filesystem as the target — never the OS default temp dir (/tmp). |
| DECISION-2026-09-10-001 | [Build Phase 5 (Containers) before Phase 4 (Community Features)](DECISION-2026-09-10-001.md) | 2026-09-10 | Accepted | Build order reversed to execute Phase 5 before Phase 4 to avoid rework in Phase 4 Feature 2. |
| DECISION-2026-09-12-001 | [Redefine Phase 4 Feature 1 as Standalone Git/CI-CD-Inspired Versioning & Test System](DECISION-2026-09-12-001.md) | 2026-09-12 | Accepted | Redefine Feature 1 as a standalone subsystem with branch/commit tracking, isolated test containers, and multi-node groundwork. |

## New ADRs

To propose a new ADR, copy an existing template and add it to this table. ADRs are numbered sequentially and never deleted — only superseded by a newer ADR.
