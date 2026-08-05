# Roadmap

> ⏸️ **LEGACY / SUPERSEDED.** This document is preserved for history only. The
> single authoritative roadmap is **`docs/mcs-manager-roadmap-v2.md`** (4-phase:
> 1 = Stabilization & Completion, 2 = Identity & Auth, 3 = Network Access, 4 = AI).

## What Has Been Delivered

All 10 original implementation batches are complete, plus the health-engine and backup-pipeline batches that followed:

| Batch | Name | Status | Key Outputs |
|---|---|---|---|
| 01 | Core Foundation | Delivered | CommandBus, QueryBus, EventBus, UnitOfWork, ConfigFactory, CircuitBreaker, FeatureFlags, idempotency (102 tests) |
| 02 | Domain Model | Delivered | Server aggregate, value objects, repository interfaces, domain events (130 domain tests) |
| 03 | Infrastructure Providers | Delivered | Local provider, Docker provider, filesystem, storage, repository implementations (52 provider tests) |
| 04 | Application Layer | Delivered | Server command/query handlers, provisioning flow, backup handlers, sagas (48 handler tests) |
| 05 | API Layer | Delivered | REST endpoints (60+), request/response schemas, error handling, rate limiting (44 API tests) |
| 06 | WebSocket Layer | Delivered | Connection manager, event dispatcher, channel auth, frontend WS client (62 backend + 36 frontend WS tests) |
| 07 | Plugin System | Delivered | Plugin lifecycle, subprocess sandbox, manifest parser, dependency resolver, JSON-RPC protocol (60 tests) |
| 08 | User & Auth System | Delivered | JWT RS256 auth, refresh token rotation, RBAC+ABAC permissions, audit hash chain, API keys (37 auth tests) |
| 09 | Monitoring & Tasks | Delivered | TaskQueue dual impl, event store hash chain, metrics collection, DLQ, rollup pipeline (48 tests) |
| 10 | Frontend UI | Delivered | React 19 app, TanStack Query, Zustand, WebSocket bridge, 11 pages, 236 frontend tests |

**Total test count**: 1068 backend passing (pytest; 1070 collected) + 236 frontend (vitest) = 1304 tests passing (2026-08-04).

## Current State

The project is in **hardening and documentation** phase:

- All features are implemented and tested
- Code quality gates pass (ruff, pyright, eslint, tsc --noEmit)
- This documentation suite is being completed
- Remaining global checklist items:

| Item | Status |
|---|---|
| Integration testing | Not started |
| Performance benchmarks | Not started |
| Security audit | Not started |
| Documentation | In progress |
| Production deployment verification | Not started |

## Future Directions

### Short-term

1. **Integration testing** — End-to-end tests that exercise the full stack (backend → DB → Redis → frontend). Framework: pytest with Docker Compose for external dependencies.

2. **Security audit** — External review of: JWT key management, refresh token rotation, audit chain integrity, subprocess isolation, rate limiting effectiveness, dependency vulnerabilities.

3. **Docker optimization** — Multi-stage Dockerfiles, image size reduction, healthcheck endpoints, graceful shutdown improvements, Docker Compose production profile.

### Medium-term

4. **CI/CD pipeline** — GitHub Actions for lint → typecheck → test → build → deploy. Automated releases with semantic versioning. Container registry publishing.

5. **Monitoring dashboard** — Prometheus integration (already exporting metrics at `/monitor/metrics`), Grafana dashboards for server operators, alerting rules for production.

6. **Performance tuning** — Database query optimization (N+1 detection, index tuning), WebSocket memory profiling under 1000+ concurrent connections, caching strategy review.

### Long-term

7. **Mobile companion app** — React Native or Flutter app for server monitoring on mobile. Push notifications for server events (crash, low TPS, backup completion).

8. **Plugin marketplace** — Community plugin registry with version management, dependency resolution across plugins, sandboxed plugin execution with resource quotas.

9. **Multi-host orchestration** — Support for managing servers across multiple physical hosts with provider-agnostic deployment targets.

## Key Milestones

| Milestone | Target | Description |
|---|---|---|
| M1 | Completed | Aggregate roots and event bus operational |
| M2 | Completed | CLI can start/stop a Minecraft server |
| M3 | Completed | REST API + WebSocket operational |
| M4 | Completed | Plugin system + auth protecting all endpoints |
| M5 | Completed | Real-time dashboard + backup scheduler |
| M6 | Completed | All batches delivered, all tests passing |
| M7 | Next | E2E integration tests passing |
| M8 | Next | Security audit clean |
| M9 | Future | Production deployment verified |

## Risk Items

- SQLite ↔ PostgreSQL compatibility may surface edge cases under load
- WebSocket reconnection + state sync under network interruption needs production testing
- Plugin subprocess isolation requires ongoing security review
- Metrics rollup tasks are pending implementation (raw data accumulates)
