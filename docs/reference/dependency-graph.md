# Inter-Module Dependency Graph & Layering Rules

**Status:** Living Reference (Synchronized with live codebase)  
**Architectural Pattern:** Modular Monolith with Strict Hexagonal Boundaries (ADR 0001)

---

## 1. Module Layering Rules

Modules communicate across strict boundaries:
1. **Domain Layer (`domain/`):** Zero outbound dependencies on other modules or infrastructure. Contains entities, value objects, domain events, and repository interfaces.
2. **Application Layer (`application/`):** Depends only on own domain and core abstractions (Bus, Units of Work). Handles commands, queries, and event handlers.
3. **Infrastructure Layer (`infrastructure/`):** Implements domain interfaces (SQL repositories, providers, HTTP clients).
4. **API Layer (`api/v1/`):** Thin REST routing layer invoking Application Handlers via CommandBus / QueryBus.

```
┌─────────────────────────────────────────────────────────────┐
│                       API Routers (15)                      │
└──────────────────────────────┬──────────────────────────────┘
                               │ CommandBus / QueryBus
┌──────────────────────────────v──────────────────────────────┐
│                  Application Command/Query Handlers         │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
┌──────────────v──────────────┐┌──────────────v───────────────┐
│     Domain Aggregates       ││   Infrastructure Adapters    │
│  (Server, User, Backup...)  ││ (SQLAlchemy, LocalProvider)  │
└─────────────────────────────┘└──────────────────────────────┘
```

---

## 2. Bounded Context Dependency Map

| Module | Allowed Upstream Modules | Prohibited Direct Dependencies | Communication Mechanism |
|---|---|---|---|
| **`server`** | `shared`, `core` | `auth`, `plugin`, `backup`, `exposure` | Publishes domain events to EventBus |
| **`auth`** | `shared`, `core` | `server`, `plugin`, `exposure` | Self-contained identity & permission context |
| **`backup`** | `shared`, `core`, `server` (queries only) | `auth`, `plugin`, `exposure` | Subscribes to server events; executes sagas |
| **`health`** | `shared`, `core`, `server` (queries only) | `plugin`, `exposure` | Subscribes to server lifecycle events |
| **`monitoring`** | `shared`, `core`, `server` (queries only) | `auth`, `plugin`, `exposure` | Background collector polling runtime state |
| **`plugin`** | `shared`, `core`, `server` (queries only) | `auth`, `backup`, `exposure` | Manages server plugins directory |
| **`exposure`** | `shared`, `core`, `server` (queries only) | `plugin`, `backup` | Subscribes to server lifecycle for tunnel sync |
| **`event_store`** | `shared`, `core` | All business modules | Listens to all domain events via EventBus |
| **`storage`** | `shared`, `core` | All business modules | Pure filesystem & object storage provider |
