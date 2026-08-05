# Documentation Index

This is the authoritative index for MCS Manager documentation. Documents are
listed with their status so it is always clear what is implemented vs planned.

> **State of the docs (2026-08-04):** this index and the documents it points to
> have been reconciled against the verified codebase state in
> `docs/current-state.md`. Older documents (`docs/roadmap.md`,
> `docs/mcs-manager-roadmap-v1.md`) are kept for history and are labeled
> `LEGACY`. Where any document disagrees with `docs/current-state.md`, the
> current-state doc wins.

---

## Start here

| Document | Status | Purpose |
|----------|--------|---------|
| [Current State](current-state.md) | ✅ **IMPLEMENTED** | Verified, evidence-based snapshot of the codebase (version, tests, DB, known issues). Read this first. |
| [Roadmap v2](mcs-manager-roadmap-v2.md) | ✅ **IMPLEMENTED** | The only authoritative roadmap — 10 dependency-ordered phases. Phase 1 (Plugins/Marketplace separation, current), Phase 2 (UI stabilization), Phase 3 (bug fixing & reliability), Phase 4 (Authorization), Phase 5 (Versioning), Phase 6 (Testing/CI/docs), Phase 7 (Network Access), Phase 8 (Dynamic endpoint + DNS), Phase 9 (Final stabilization), Phase 10 (AI — last, deferred). |
| [Versioning](VERSIONING.md) | 🟡 **PLANNED** | Single source-of-truth versioning strategy (currently `4.0.0` across code; stale `7.1.0` only in history/server data). Roadmap Phase 5. |
| [Roadmap v1](mcs-manager-roadmap-v1.md) | ⏸️ **LEGACY** | Superseded by v2. Historical phase plan (9 phases) kept for reference. |
| [Roadmap v0](roadmap.md) | ⏸️ **LEGACY** | Original batch-delivery roadmap. Historical only. |

---

## Design & architecture

| Document | Status | Purpose |
|----------|--------|---------|
| [Architecture](ARCHITECTURE.md) | ✅ **IMPLEMENTED** | System context, module structure, CQRS/hexagonal patterns, task wiring, reconciliation. |
| [Database](DATABASE.md) | ✅ **IMPLEMENTED** | Schema design, migration chain (16 revisions), query patterns, migration guide. |
| [Security](SECURITY.md) | ✅ **IMPLEMENTED** | Authentication, authorization (with known gaps), audit chain, data protection, rate limiting, sessions. |
| [Plugins & Marketplace](plugins-and-marketplace.md) | ✅ **IMPLEMENTED** | Plugin registry (filesystem source of truth) + Modrinth marketplace implementation. |
| [Network Access Design](network-access-design.md) | 🟡 **PLANNED** | Phases 7–8 design reference: TunnelProvider vs DnsProvider, dynamic endpoints, game vs management exposure, Tunnel ≠ Authentication. |
| [Frontend](FRONTEND.md) | ✅ **IMPLEMENTED** | React 19 app structure, state management, WebSocket integration, API client, testing. |
| [Provisioning](PROVISIONING.md) | ✅ **IMPLEMENTED** | Server creation flow, JAR validation, supported server types. |

---

## Reference

| Document | Status | Purpose |
|----------|--------|---------|
| [API](API.md) | ✅ **IMPLEMENTED** | REST endpoint reference + WebSocket protocol, verified against router code. |
| [Testing](testing.md) | ✅ **IMPLEMENTED** | Test suites, structure, mocking strategy, quality gates. |
| [Development](DEVELOPMENT.md) | ✅ **IMPLEMENTED** | Dev setup, sandbox isolation, scripts, debugging. |
| [Deployment](DEPLOYMENT.md) | ✅ **IMPLEMENTED** | Docker-based deployment guide. |
| [Getting Started](getting-started.md) | ✅ **IMPLEMENTED** | 5-minute quickstart. |
| [Status](STATUS.md) | ✅ **IMPLEMENTED** | Full project history (Batch 1–10) and session changelog. Historical narrative; factual counts live in `current-state.md`. |

---

## Planning & parking lot

| Document | Status | Purpose |
|----------|--------|---------|
| [Feature Ideas](FEATURE_IDEAS.md) | 🟡 **BACKLOG** | Deferred feature requests and the marketplace exception record. |
| [Permissions Future Ideas](PERMISSIONS_FUTURE_IDEAS.md) | 🟡 **BACKLOG** | Permission-model proposals and deferred decisions (WS trace, `/metrics`, registration bootstrap). |

---

## Sub-collections

| Directory | Status | Purpose |
|-----------|--------|---------|
| [Decisions (ADRs)](decisions/README.md) | ✅ **IMPLEMENTED** | 12 Architecture Decision Records (ADR-0001 … ADR-0012). |
| [Runtime](runtime/README.md) | ✅ **IMPLEMENTED** | Runtime subsystem deep-dives (reconciliation, ownership, supervision, recovery). |
| [Reference](reference/) | ✅ **IMPLEMENTED** | Module map, dependency graph, event catalog, contract registry, file ownership. |

---

## Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ **IMPLEMENTED** | Describes current, verified behavior |
| 🟡 **PLANNED** | Design reference for a future phase; nothing implemented |
| ⏸️ **LEGACY** | Historical; superseded; kept for reference only |
| 🟡 **BACKLOG** | Parking-lot; nothing committed |

---

## Cross-cutting claims (verified 2026-08-04)

- **Version:** `4.0.0` (code) — planning docs that mention "7.1.0" are stale.
- **Backend tests:** 1070 collected / 1068 passing / 2 pre-existing failures.
- **Frontend tests:** 236 passing across 41 files.
- **Routers:** 10 · **Migrations:** 16 · **ADRs:** 12 · **Contracts:** 6.
- **Authorization:** 24 routes gated by `require_permission` (22 mutating + 2 read-only marketplace; `contracts/permissions.yaml` v1.4).
- **Production DB:** `backend/data/servers/mcs.db`, 3 revisions behind head, 0 servers.
- **CI:** frontend workflow only (no backend CI yet).
