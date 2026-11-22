# Architecture Decision Records

This directory captures significant architectural decisions made during the project. Each ADR describes the context, options considered, chosen approach, trade-offs, and consequences.

| ID | Title | Date | Status | Summary |
|---|---|---|---|---|
| 0001 | [Modular Monolith with Hexagonal Boundaries](0001-modular-monolith.md) | 2026-07-22 | Accepted | Single deployable with module boundaries enforced by ports/adapters; enables future microservice extraction. |
| 0002 | [Separate Command, Query, and Event Buses](0002-command-query-event-buses.md) | 2026-07-22 | Accepted | CQRS at the bus level: CommandBus (sync+tx), QueryBus (sync+cache), EventBus (async+DLQ). |
| 0003 | [All Plugins Run as Subprocesses](0003-plugin-subprocess-isolation.md) | 2026-07-22 | Accepted | No in-process plugins; JSON-RPC over Unix sockets prevents GIL blocking and host crashes. |
| 0004 | [WebSocket — asyncio.Lock, EventDispatcher, Channel Permissions, Cache Callbacks](0004-websocket-asyncio-lock.md) | 2026-07-22 | Accepted | `asyncio.Lock` for connection registry, per-type EventDispatcher, REST scope reuse for WS auth, callback pattern for TanStack Query bridge. |
| 0005 | [JWT RS256 Authentication — Refresh Tokens, Audit Chain, Permissions, Timestamps](0005-jwt-rs256-auth.md) | 2026-07-22 | Accepted | RS256 asymmetric JWTs, opaque DB-stored refresh tokens, SHA-256 audit chain, RBAC+ABAC hybrid, ISO 8601 timestamps. |
| 0006 | [Task Queue — Dual Implementation, Event Store Chain, DLQ, Metrics Retention](0006-task-queue-dual-impl.md) | 2026-07-23 | Accepted | Abstract TaskQueue (`InProcessQueue`), app-level hash chain, store-then-replay DLQ, metrics collection pipeline. |
| 0007 | [Rename app/storage/ to app/core/persistence/](0007-core-persistence-rename.md) | 2026-07-27 | Accepted | Relocated database engine, base ORM, UoW under `core/persistence/`; all imports, ADRs, and docs updated in one commit. |
| 0008 | [Environment-Variable-Driven Sandbox Isolation](0008-env-var-sandbox-isolation.md) | 2026-07-27 | Accepted | Sandboxing driven by `ONX_*` / `MCS_*` env vars so tests never touch production data or servers. |
| 0009 | [Pydantic Field Validators for Domain Value-Object Inputs](0009-pydantic-field-validator-for-domain-values.md) | 2026-07-27 | Accepted | Schema-level `@field_validator`s enforce domain value-object invariants at the API boundary. |
| 0010 | [Commit-per-Step Discipline for Structural Changes](0010-commit-per-step-discipline.md) | 2026-07-27 | Accepted | One concern per commit during refactors so each step stays reviewable and revertible. |
| 0011 | [Orphan Reconciliation — Ownership Verification](0011-orphan-reconciliation-ownership-verification.md) | 2026-07-27 | Accepted | Orphan cleanup verifies a process truly belongs to the managed server set before killing, with project-owned vs system-wide scopes. |
| 0012 | [Same-Filesystem Staging for Atomic File Swaps](0012-same-filesystem-staging-for-atomic-swaps.md) | 2026-08-04 | Accepted | Files staged for atomic swap onto live data must live on the same filesystem as the target — never `/tmp`. |
| 0013 | [Domain-Model-First for Stage A Entities](0013-domain-model-first-for-stage-a-entities.md) | 2026-09-17 | Accepted | Formalize Revision, Materialization, PersistentDataset, and Runtime in domain layer first before schema extensions. |
| 0014 | [Shared Commit DAG Migration Strategy and Branch Lifecycle](0014-shared-commit-dag-migration-and-branch-lifecycle.md) | 2026-09-17 | Accepted | Branch state machine (`created`/`active`/`archived`) and additive transition path from linear history to shared DAG. |
| 0015 | [Runtime Domain Entity and ServerProvider Relationship](0015-runtime-entity-and-server-provider-relationship.md) | 2026-09-17 | Accepted | Runtime pins immutable Commit ID; wraps existing ServerProvider without breaking provider contracts; preserves per-server lock. |
| 0016 | [PersistentDataset Boundary and Non-Mutation Isolation](0016-persistent-dataset-boundary-and-isolation.md) | 2026-09-17 | Accepted | Mutable dataset writes cannot silently mutate versioned Tree/Commit or overwrite tracked configs. |
| 0017 | [Branch-Head Compare-and-Swap (CAS) for Versioning](0017-branch-head-cas.md) | 2026-10-20 | Accepted | CAS on `server_branches.head_commit_id` prevents lost updates on concurrent commits/merges. |
| 0018 | [Atomic Promote Config Writes and Durability](0018-promote-atomicity-stop-guard.md) | 2026-10-20 | Superseded | Atomic `write_binary_atomic`/`write_text_atomic` retained; `PromoteCommitHandler` later removed in favor of Clean Export & Live Refresh. |
| 0019 | [Dynamic Backend Port Selection](0019-dynamic-backend-port.md) | 2026-10-20 | Accepted | Preferred port precedence, bind-race retry, and active-port reuse in `.onx/backend.port`. |
| 0020 | [Installer and Launcher Pin Python to Exactly 3.12](0020-installer-python-312-pin.md) | 2026-11-02 | Accepted | Exact 3.12 probe in launcher/start scripts/bootstrap; versioned-only installs; safe venv recreation. |
| 0021 | [Frontend UX/IA Overhaul and Design Token System](0021-frontend-ux-ia-overhaul-token-system.md) | 2026-11-04 | Accepted | Layout/IA overhaul, semantic token engine (`data-skin`/`mode`/`density`), shared primitives, and code-splitting. |
| 0022 | [Brand Tokens and Favicon Architecture](0022-brand-tokens-and-favicon.md) | 2026-11-08 | Accepted | Three-token brand system (`--brand-mark-1/2`, `--brand-ink`), inline `BrandLogo`, and dynamic theme favicon. |
| 0023 | [Corner Style Setting and Radius Token Architecture](0023-corner-style-setting.md) | 2026-11-08 | Accepted | Configurable Rounded/Sharp corner styles mapped via Tailwind v4 `@theme` radius variables. |

## New ADRs

To propose a new ADR, copy an existing ADR and add it to this table. ADRs are numbered sequentially and never deleted — only superseded by a newer ADR.
