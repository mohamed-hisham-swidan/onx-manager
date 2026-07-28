# Architecture Overview

**Last updated**: 2026-07-27  
**Cross-references**: [ADR-0001](decisions/0001-modular-monolith.md), [ADR-0002](decisions/0002-command-query-event-buses.md), [ADR-0007](decisions/0007-core-persistence-rename.md)

---

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

Three client types (browser, CLI, plugin subprocesses) interact with a FastAPI backend. The backend dispatches through Command, Query, and Event buses backed by PostgreSQL (primary), Redis (cache + WebSocket), and subprocess-isolated plugins. SQLite is supported as an embedded/development fallback.

---

## Module Architecture

### Layered Structure

```
backend/app/
├── main.py                    # FastAPI app factory + startup
├── registration.py            # Module registration
├── api/                       # Interface layer (REST + WebSocket)
│   ├── deps.py                # FastAPI dependency injection
│   ├── errors.py              # Global exception handlers
│   └── v1/
│       ├── middleware/        # Auth, audit, rate-limit, request-id
│       ├── routers/           # 9 endpoint groups
│       └── schemas/           # Pydantic request/response schemas
├── core/                      # Foundation layer
│   ├── command_bus.py         # CQRS command bus
│   ├── query_bus.py           # CQRS query bus
│   ├── event_bus.py           # Async event bus with retry + DLQ
│   ├── persistence/           # Database engine, Base ORM, UoW ← ADR-0007
│   ├── saga.py                # Saga orchestrator
│   ├── circuit_breaker.py     # Circuit breaker pattern
│   ├── idempotency.py         # Idempotency keys
│   ├── feature_flags.py       # Feature flag system
│   ├── config.py              # Configuration (AppSettings)
│   ├── exceptions.py          # MCSError hierarchy
│   └── logging.py             # Structured logging
├── modules/                   # 8 DDD modules
│   ├── server/                # Minecraft server domain
│   ├── backup/                # Backup/restore domain
│   ├── auth/                  # User & auth domain
│   ├── health/                # Health monitoring & diagnostics
│   ├── plugin/                # Plugin system domain
│   ├── monitoring/            # Health & metrics domain
│   ├── event_store/           # Event store module
│   └── storage/               # File storage backends (S3/local)
├── services/                  # Cross-module orchestration
├── tasks/                     # Task queue + scheduling
└── websocket/                 # WebSocket connection manager
```

### Dependency Direction

Hexagonal (ports/adapters) architecture — verified clean in Batch 4 audit:

```
api/ ──► application/ ──► domain/
  │                          │
  └──────────────────────► infrastructure/
                                │
core/ ──────────────────────────┘
```

- **Domain** never imports from infrastructure, application, or API
- **Application** never imports from API
- **Infrastructure** never imports from API
- Cross-module communication happens only through domain events (EventBus) or shared value objects (`app/modules/shared/`)
- The `core/` layer provides reusable infrastructure consumed by all layers

### Each DDD Module

```
module/
├── domain/              # Core business logic
│   ├── aggregate.py     # Aggregate roots, entities
│   ├── events.py        # Domain events
│   └── repository.py    # Repository interfaces (ports)
├── application/         # Use cases
│   ├── commands/        # Command handlers
│   └── queries/         # Query handlers
└── infrastructure/      # Adapters
    ├── models.py        # SQLAlchemy ORM models
    └── repository.py    # SQL repository implementations
```

---

## Key Patterns

### CQRS (ADR-0002)

Commands and queries are segregated at the bus level:

```
CommandBus          QueryBus           EventBus
──────────          ────────           ────────
Synchronous         Synchronous        Asynchronous
Returns result      Returns data       Fire-and-forget
With transaction    With cache         With retry + DLQ
Idempotency keys    No idempotency     No idempotency
```

Every command handler returns `CommandResult(success, data, error, error_code)`. Every query handler returns `QueryResult(data, total)` for paginated queries.

### Unit of Work

All mutations run inside a `UnitOfWork` context (`core/persistence/unit_of_work.py`). The UoW collects domain events during a transaction and publishes them to the EventBus after a successful commit. On failure, the session is rolled back and no events are published.

### Event Bus

Modules communicate exclusively via domain events dispatched through an in-process async event bus (ADR-0002). Events are delivered concurrently with retry (exponential backoff, 3 attempts) and overflow to a dead letter queue.

### Saga Orchestration

Multi-step operations (server provisioning, backup workflows) are managed by saga process managers with compensation actions. The `SagaOrchestrator` coordinates long-running workflows across bounded contexts.

### Repository Pattern

Each aggregate root has a dedicated repository interface in its domain layer with a SQLAlchemy implementation in its infrastructure layer. The generic `BaseRepository[T]` (`core/persistence/base.py`) provides common CRUD operations.

---

## Validation Strategy (ADR-0009)

Input validation follows a two-layer defense:

1. **Pydantic schema layer** (HTTP boundary): `@field_validator` on request schemas in `api/v1/schemas/` ensures invalid input is rejected at HTTP 422 with a structured error detail list.
2. **Handler safety-net** (domain boundary): Try/except around domain value-object constructors catches `ValueError` and raises `InvalidValueError` (MCSError subclass) for a consistent `VALIDATION_ERROR` code.

This pattern was applied to `minecraft_version` (Batch 2.5) and `email` (Batch 4). Any future domain value object that validates input must have a matching Pydantic validator.

---

## Sandbox Isolation (ADR-0008)

Testing and development are isolated from production via environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `MCS_DATABASE_URL` | Database connection | `sqlite+aiosqlite:///data/mcs.db` |
| `MCS_SERVERS_DATA_DIR` | Server file directory | `data/servers` |

Both must be set together when running test/development backends. Because `setsid` drops environment variables, they must be passed in the same command invocation as the uvicorn process.

---

## Technology Stack

### Backend

| Component | Choice |
|-----------|--------|
| Language | Python 3.14+ |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic (9 revisions) |
| Validation | Pydantic v2 |
| Logging | structlog |
| Message Queue | InProcessQueue (dev), Arq/Redis (production) |
| Event Bus | In-process async bus + dead letter queue |
| WebSocket | FastAPI WebSocket + custom connection manager |

### Frontend

| Component | Choice |
|-----------|--------|
| Language | TypeScript 5+ |
| Framework | React 19+ (Vite) |
| Styling | TailwindCSS 4+, shadcn/ui |
| Data Fetching | TanStack Query |
| State | Zustand |

### Data Stores

| Store | Purpose |
|-------|---------|
| PostgreSQL 16 | Primary database |
| SQLite 3 | Dev/test fallback |
| Redis 7 | Cache, WebSocket pub/sub, production task queue |

### Containerization

| Component | Details |
|-----------|---------|
| Dockerfile (backend) | Multi-stage: deps → app → runtime |
| Dockerfile (frontend) | Build → nginx static serving |
| docker-compose.yml | Backend + frontend services, health checks, volumes |

---

## Production Deployment

### Docker

```
docker compose up --build    # Full stack
docker compose build         # Rebuild images
```

Both Dockerfiles and `docker-compose.yml` are at the repository root. The backend exposes port 8000; the frontend nginx proxy serves on port 80 and proxies `/api`, `/ws`, `/health`, `/docs` to the backend.

### Environment Variables (production)

| Variable | Required | Description |
|----------|----------|-------------|
| `MCS_DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection for production |
| `JWT_PRIVATE_KEY` | Yes* | RSA private key PEM (*auto-generated if absent) |
| `JWT_PUBLIC_KEY` | Yes* | RSA public key PEM (*auto-generated if absent) |
| `STORAGE_BACKEND` | No | `local` or `s3` (default: `local`) |

---

## File Ownership & Conventions (ADR-0010)

Every source file belongs to exactly one batch. No shared ownership. Changes are committed one logical step at a time — each commit is independently verifiable and has a clear message explaining the change, rationale, and verification results.

---

## Testing

```bash
pytest                          # All tests (781 passing)
pytest tests/ -x -q             # Quick run, stop on first failure
```

Test isolation: sandbox database + sandbox server directory, set via `MCS_DATABASE_URL` and `MCS_SERVERS_DATA_DIR`.

---

## Architectural Decision Records

| ADR | Date | Title |
|-----|------|-------|
| 0001 | 2026-07-22 | Modular Monolith with Hexagonal Boundaries |
| 0002 | 2026-07-22 | Separate Command, Query, and Event Buses |
| 0003 | 2026-07-22 | All Plugins Run as Subprocesses |
| 0004 | 2026-07-22 | WebSocket — asyncio.Lock, EventDispatcher, Channel Permissions |
| 0005 | 2026-07-22 | JWT RS256 Authentication |
| 0006 | 2026-07-23 | Task Queue — Dual Implementation, Event Store Chain, DLQ |
| 0007 | 2026-07-27 | Rename app/storage/ to app/core/persistence/ |
| 0008 | 2026-07-27 | Environment-Variable-Driven Sandbox Isolation |
| 0009 | 2026-07-27 | Pydantic Field Validators for Domain Value-Object Inputs |
| 0010 | 2026-07-27 | Commit-per-Step Discipline for Structural Changes |
