# Minecraft Server Manager — Documentation

## Architecture

| Document | Description |
|---|---|
| [Architecture Overview](ARCHITECTURE.md) | System context, modular monolith structure, bounded contexts, key patterns (CQRS, Event Bus, Saga), technology stack |
| [API Reference](API.md) | REST endpoints, WebSocket protocol, error codes, rate limiting, pagination |
| [Database Architecture](DATABASE.md) | Schema design, key tables, migration strategy, audit log implementation, query patterns |
| [Security Architecture](SECURITY.md) | JWT RS256 auth, RBAC+ABAC permissions, audit hash chain, rate limiting, session management |
| [Decisions Index](decisions/README.md) | All Architecture Decision Records (10 ADRs covering the key architectural choices) |
| [Project Status](STATUS.md) | Complete session history, repository tree, test matrix, known limitations |

## Backend

| Document | Description |
|---|---|
| [Development Guide](DEVELOPMENT.md) | Setup, virtual environment, migration commands, testing strategy, debugging tips |
| [Database Architecture](DATABASE.md) | PostgreSQL/SQLite schemas, migration history, query patterns, audit log implementation |
| [Security Architecture](SECURITY.md) | Authentication, authorization, cryptographic audit chain, rate limiting |

## Frontend

| Document | Description |
|---|---|
| [Frontend Architecture](FRONTEND.md) | React 19 app structure, TanStack Query integration, Zustand stores, WebSocket client, routing, UI conventions |
| [API Reference](API.md) | REST endpoints consumed by the frontend, WebSocket event types |

## Runtime

| Document | Description |
|---|---|
| [Server Lifecycle](runtime/lifecycle.md) | Server state machine, transitions, provisioning flow |
| [Server Ownership](runtime/ownership.md) | Resource ownership model, user-server relationships |
| [Server Provisioning](runtime/providers.md) | Provider architecture, local/Docker/remote providers |
| [Runtime Reconciliation](runtime/reconciliation.md) | State reconciliation between DB and actual process state |
| [Runtime Supervision](runtime/supervision.md) | Process supervision, health checks, auto-restart |
| [Runtime Recovery](runtime/recovery.md) | Crash recovery, startup validation, cleanup routines |
| [Runtime README](runtime/README.md) | Overview of runtime subsystem |

## Operations

| Document | Description |
|---|---|
| [Provisioning Guide](PROVISIONING.md) | Server creation flow, JAR validation, supported server types |
| [Deployment Guide](DEPLOYMENT.md) | Docker setup, environment variables, production deployment |
| [Getting Started](getting-started.md) | 5-minute quickstart — clone to first running server |

## Development

| Document | Description |
|---|---|
| [Getting Started](getting-started.md) | Quickstart for new developers |
| [Development Guide](DEVELOPMENT.md) | Full setup, scripts, development loop, code conventions |
| [Testing Guide](testing.md) | How to run and write tests (backend pytest + frontend Vitest) |
| [Contributing](CONTRIBUTING.md) | Contribution workflow, code conventions, git conventions, cross-batch protocol |
| [Roadmap](roadmap.md) | Delivered batches, current state, future directions |

## Reference

| Document | Description |
|---|---|
| [Module Map](reference/module-map.md) | All backend modules with their responsibilities and file ownership |
| [File Ownership](reference/file-ownership.md) | Every source file and which batch owns it |
| [Dependency Graph](reference/dependency-graph.md) | Inter-batch dependencies and interface contracts |
| [Event Catalog](reference/event-catalog.md) | All domain events with their producers and consumers |
| [Contract Registry](reference/contract-registry.md) | Shared interfaces and data contracts across batches |

## Decisions

| Document | Description |
|---|---|
| [Decisions Index](decisions/README.md) | Index of all 10 Architecture Decision Records |
| [ADR-0001](decisions/0001-modular-monolith.md) | Modular monolith with hexagonal boundaries |
| [ADR-0002](decisions/0002-command-query-event-buses.md) | Separate command, query, and event buses |
| [ADR-0003](decisions/0003-plugin-subprocess-isolation.md) | All plugins run as subprocesses |
| [ADR-0004](decisions/0004-websocket-asyncio-lock.md) | WebSocket concurrent patterns |
| [ADR-0005](decisions/0005-jwt-rs256-auth.md) | JWT RS256 authentication and audit chain |
| [ADR-0006](decisions/0006-task-queue-dual-impl.md) | Task queue, event store, DLQ, metrics retention |
| [ADR-0007](decisions/0007-persistence-layer-rename.md) | Rename app/storage to app/core/persistence |
| [ADR-0008](decisions/0008-commit-per-step-discipline.md) | One concern per commit, no batch commits |
| [ADR-0009](decisions/0009-pydantic-field-validators.md) | Pydantic field validators for domain boundary defense |
| [ADR-0010](decisions/0010-doc-index-cross-ref.md) | All docs listed in README index, cross-checked |
