# Architecture Overview

## System Context

```
┌─────────┐     ┌──────────────┐     ┌──────────────┐
│ Browser ├────►│  FastAPI      │────►│  PostgreSQL  │
│         │     │  (Backend)    │     │              │
└─────────┘     │              │     └──────────────┘
                │  ┌──────────┐│
┌─────────┐     │  │ Command  ││     ┌──────────────┐
│  CLI    ├────►│  │  Bus     ││────►│  Redis       │
│         │     │  ├──────────┤│     │  (Cache+WS)  │
└─────────┘     │  │ Query    ││     └──────────────┘
                │  │  Bus     ││
┌─────────┐     │  ├──────────┤│     ┌──────────────┐
│ Plugins ├────►│  │ Event    ││────►│  Subprocess  │
│ (proc)  │     │  │  Bus     ││     │  Plugins     │
└─────────┘     │  └──────────┘│     └──────────────┘
                └──────────────┘
```

The system is a **modular monolith** with hexagonal architecture per module. Three client types (browser, CLI, plugin subprocesses) interact with a FastAPI backend. The backend dispatches through Command, Query, and Event buses backed by PostgreSQL (primary), Redis (cache + WebSocket), and subprocess-isolated plugins.

## Bounded Contexts

| Context | Responsibility | Aggregate Roots |
|---|---|---|
| Server Management | Server lifecycle, configuration, deployment | `Server`, `ServerGroup` |
| Plugin Engine | Plugin lifecycle, sandboxing, dependency resolution | `Plugin`, `PluginRegistry` |
| Backup | Backup scheduling, execution, restoration | `BackupJob`, `BackupPolicy` |
| Monitoring | Metrics, health checks, alert rules | `MetricSeries`, `AlertRule` |
| Notification | Alert delivery (Discord, Telegram, Email) | `NotificationChannel` |
| User & Auth | Users, roles, permissions, API keys | `User`, `Role`, `ApiKey` |
| Storage | File storage abstraction | `StoredFile` |
| Event Store | Immutable event log | `StoredEvent` |
| Configuration | Config templates and snapshots | `ConfigurationProfile` |

## Module Map

```
mcs_manager/
├── core/               # CommandBus, QueryBus, EventBus, UoW
├── server/             # Minecraft server domain
├── backup/             # Backup/restore domain
├── plugin/             # Plugin system (subprocess-isolated)
├── user/               # Auth + RBAC/ABAC
├── monitor/            # Health checks, metrics
├── task/               # Scheduled tasks
└── api/                # REST + WebSocket
```

Each module follows a consistent internal structure:

```
module/
├── domain/             # Aggregates, value objects, repository interfaces
├── application/        # Command/query handlers, sagas
└── infrastructure/     # Repository implementations, external adapters
```

The **core/** module is foundational and owned by Batch 01. It provides the infrastructure consumed by all other modules: buses, Unit of Work, configuration factory, exception hierarchy, structured logging, and base repository class.

## Key Patterns

- **CQRS**: Commands and queries are segregated at the bus level. Commands mutate state; queries return data. Every command carries an idempotency key — duplicate commands return cached results. See [API docs](API.md) for endpoint conventions.
- **Event Bus**: Modules communicate exclusively via domain events dispatched through an in-process async event bus. Events are delivered concurrently with retry (backoff, 3 attempts) and overflow to a dead letter queue.
- **Repository**: Each aggregate root has a dedicated repository interface (domain layer) with infrastructure-level implementations. Persistence is abstracted behind ports.
- **Unit of Work**: Sessions collect domain events during a transaction. On commit, events are published after the database flush. See [Database docs](DATABASE.md) for transaction boundaries.
- **Domain Events & Audit Log**: All domain events are appended to an immutable event store with cryptographic chaining. The event store has no UPDATE/DELETE privileges.
- **Saga Orchestration**: Multi-step operations are managed by process managers with compensation actions (Saga pattern). The `SagaOrchestrator` coordinates long-running workflows across bounded contexts.
- **Hexagonal Architecture**: Every module defines ports (interfaces) in its domain layer and adapters (implementations) in its infrastructure layer. Adapters are swappable without affecting business logic.

## Technology Stack

### Backend

| Component | Choice |
|---|---|
| Language | Python 3.12+ |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Logging | structlog |
| Message Queue | InProcessQueue (dev), Arq/Redis (production) |
| Event Bus | In-process async bus + dead letter queue |
| WebSocket | FastAPI WebSocket + custom connection manager |

### Frontend

| Component | Choice |
|---|---|
| Language | TypeScript 5+ |
| Framework | React 19+ |
| Build | Vite |
| Styling | TailwindCSS 4+, shadcn/ui |
| Data Fetching | TanStack Query |
| State | Zustand |

### Data Stores

| Store | Purpose |
|---|---|
| PostgreSQL 16 | Primary database |
| SQLite 3 | Embedded/desktop mode |
| Redis | Cache, WebSocket pub/sub, production message queue |

## Core Infrastructure

All components below are provided by the **core/** module and used by every other module.

- **CommandBus**: Middleware pipeline — logging → idempotency → auth → validation → transaction → handler. Returns cached results for duplicate idempotency keys (24h expiry via `IdempotencyStore`).
- **QueryBus**: Middleware pipeline — logging → cache → handler. Read-only, no transaction wrapper.
- **EventBus**: Concurrent dispatch with retry (exponential backoff, 3 attempts), dead letter queue for failed events.
- **UnitOfWork**: Session manager that collects domain events during a transaction. On successful commit, publishes all collected events to the EventBus.
- **ConfigFactory**: Immutable configuration assembled from layered sources (defaults → config files → env → overrides).
- **CircuitBreaker**: Fail-fast wrapper for all infrastructure providers (database, Redis, external APIs). Prevents cascading failures.
- **FeatureFlags**: Boolean toggle, percentage rollout, and per-user override support. All new features are gated behind flags.
- **SagaOrchestrator**: Coordinates multi-step operations across bounded contexts. Each step has a forward action and a compensation action for rollback.

## Provisioning Flow

See [Provisioning docs](PROVISIONING.md) for the complete server provisioning flow:

1. **JAR Download** — type-specific URL resolution
2. **Validation** — magic bytes + minimum size checks
3. **Retry** — 2x exponential backoff on failure
4. **Cleanup** — filesystem cleanup on failure
5. **Server Type Support** — multiple Minecraft server types

## Key Design Decisions

1. **Idempotency** — Every command carries an idempotency key. Duplicate commands return cached results.
2. **Immutable Audit Log** — Event store is append-only with cryptographic chaining. No UPDATE/DELETE privileges.
3. **Saga Pattern** — Multi-step operations use a saga process manager with compensation actions.
4. **Circuit Breakers** — All infrastructure providers wrapped in circuit breakers.
5. **Feature Flags** — All new features behind toggles. Percentage rollouts supported.
6. **Zero-Downtime Deployment** — Expand-contract migration pattern. Connection draining before shutdown.
7. **Plugin Subprocess Isolation** — All plugins run as subprocesses. No in-process plugin execution.
8. **Configuration: Two-Layer Only** — Templates (snapshotted) + Server overrides (absolute). No inheritance chain.

## File Ownership

Every source file belongs to exactly one batch. No shared ownership. See [File Ownership](reference/file-ownership.md).

Cross-batch communication occurs through defined interfaces only. A batch that needs a feature from another batch creates a **Request**; the target batch implements the interface in its next session. No batch may modify files owned by another batch. See [Contributing Guide](CONTRIBUTING.md).

## Testing

```bash
pytest                          # All tests
pytest tests/unit/              # Unit tests (fast)
pytest tests/test_integration.py  # Core component interaction tests
pytest tests/e2e/               # E2E tests (with Docker)
pytest --cov=app                # Coverage report
```

See [Development guide](DEVELOPMENT.md) for contribution workflow and testing conventions.
