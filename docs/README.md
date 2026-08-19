# Documentation Index

This is the authoritative index for MCS Manager documentation. Documents are
listed with their status so it is always clear what is implemented vs planned.

> **State of the docs (2026-08-12):** this index and the documents it points to
> have been reconciled against the verified codebase state in
> `docs/current-state.md`. Older documents (superseded roadmaps in `docs/history/`,
> the archived Blueprint v4 split set in `docs/history/blueprint-v4/`) are kept for
> history and are labeled `LEGACY`. Where any document disagrees with
> `docs/current-state.md`, the current-state doc wins. `current-state.md` is the
> **single** current-state source of truth — there is no `STATUS.md`, and one is
> not maintained (see `docs/current-state.md` §7.1). Its facts are kept honest by
> the weekly re-verification cadence (`.github/workflows/verification-cadence.yml`,
> `scripts/reverify`; §7.2).

---

## Start here

| Document | Status | Purpose |
|----------|--------|---------|
| [Current State](current-state.md) | ✅ **IMPLEMENTED** | Verified, evidence-based snapshot of the codebase (version, tests, DB, known issues). Read this first. |
| [Roadmap (Blueprint V5)](roadmap/MCS-Manager-Engineering-Blueprint-V5.md) | ✅ **IMPLEMENTED** | The only authoritative roadmap — 10 dependency-ordered phases. Phase 1 (CLOSED), Phase 2 (CLOSED), Phase 3 (CLOSED), Phase 4 (CLOSED — server-scoped authorization, owner/access-mode/invitations), Phase 5 (Versioning), Phase 6 (Testing/CI/docs), Phase 7 (Network Access), Phase 8 (Dynamic endpoint + DNS), Phase 9 (Final stabilization), Phase 10 (AI — last, deferred). |
| [Roadmap v2](history/mcs-manager-roadmap-v2.md) | ⏸️ **LEGACY** | Superseded by Blueprint v5. Historical phase plan kept in `history/`. |
| [Versioning](VERSIONING.md) | ✅ **ADOPTED** | Versioning policy: SemVer 2.0.0 semantics, `4.0.0` internal app version, `/api/v1` public API contract (independent), plugin `min_app_version` compatibility floor (separate). Policy adopted 2026-08-12 (Phase 5 WS 5.1); single-source mechanism implemented 2026-08-13 (WS 5.2–5.6). |
| [Roadmap v1](history/mcs-manager-roadmap-v1.md) | ⏸️ **LEGACY** | Superseded by v2. Historical phase plan (9 phases) kept for reference. |
| [Blueprint v4 (split set)](history/blueprint-v4/00-index-and-vision.md) | ⏸️ **LEGACY** | Superseded by Blueprint v5. Archived in `history/blueprint-v4/`. |

---

## Design & architecture

| Document | Status | Purpose |
|----------|--------|---------|
| [Architecture](architecture/ARCHITECTURE.md) | ✅ **IMPLEMENTED** | System context, module structure, CQRS/hexagonal patterns, task wiring, reconciliation. |
| [Database](architecture/DATABASE.md) | ✅ **IMPLEMENTED** | Schema design, migration chain (27 revisions), query patterns, migration guide. |
| [Security](architecture/SECURITY.md) | ✅ **IMPLEMENTED** | Authentication, authorization (Phase 4 enforced: global + server-scoped RBAC), audit chain, data protection, rate limiting, sessions. |
| [Plugins & Marketplace](architecture/plugins-and-marketplace.md) | ✅ **IMPLEMENTED** | Plugin registry (filesystem source of truth) + Modrinth marketplace implementation. |
| [Network Access Design](architecture/network-access-design.md) | 🟡 **PLANNED** | Phases 7–8 design reference: TunnelProvider vs DnsProvider, dynamic endpoints, game vs management exposure, Tunnel ≠ Authentication. |
| [Frontend](architecture/FRONTEND.md) | ✅ **IMPLEMENTED** | React 19 app structure, state management, WebSocket integration, API client, testing. |
| [Provisioning](architecture/PROVISIONING.md) | ✅ **IMPLEMENTED** | Server creation flow, JAR validation, supported server types. |

---

## Reference

| Document | Status | Purpose |
|----------|--------|---------|
| [API](API.md) | ✅ **IMPLEMENTED** | REST endpoint reference + WebSocket protocol, verified against router code. |
| [Testing](testing.md) | ✅ **IMPLEMENTED** | Test suites, structure, mocking strategy, quality gates. |
| [Development](DEVELOPMENT.md) | ✅ **IMPLEMENTED** | Dev setup, sandbox isolation, scripts, debugging. |
| [Deployment](DEPLOYMENT.md) | ✅ **IMPLEMENTED** | Docker-based deployment guide. |
| [Getting Started](getting-started.md) | ✅ **IMPLEMENTED** | 5-minute quickstart. |
| [Status & History](status/history.md) | ✅ **IMPLEMENTED** | Full project history (Batch 1–10) and session changelog. Historical narrative; factual counts live in `current-state.md`. |
| [Contributing](CONTRIBUTING.md) | ✅ **IMPLEMENTED** | Contribution workflow, code conventions, git conventions, cross-batch protocol. |

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
| [Reference](reference/README.md) | ✅ **IMPLEMENTED** | Module map, dependency graph, event catalog, contract registry, file ownership. |
| [Status & History](status/history.md) | ✅ **IMPLEMENTED** | Project history, batch/session changelog, known-limitations log. |
| [Architecture](architecture/README.md) | ✅ **IMPLEMENTED** | Architecture design deep-dives (design docs migrated from `docs/`). |

---

## Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ **IMPLEMENTED** | Describes current, verified behavior |
| ✅ **ADOPTED** | Policy/standard is decided and binding; its enforcement mechanism may still be pending implementation |
| 🟡 **PLANNED** | Design reference for a future phase; nothing implemented |
| ⏸️ **LEGACY** | Historical; superseded; kept for reference only |
| 🟡 **BACKLOG** | Parking-lot; nothing committed |

---

## Cross-cutting claims (verified 2026-08-19)

- **Version:** `4.0.0` (code) — single source `backend/pyproject.toml` → `backend/app/core/version.py:get_app_version()`; planning docs that mention "7.1.0" are stale.
- **Backend tests:** 1934 passed / 2 skipped (0 failures).
- **Frontend tests:** 506 passed across 65 files (`tsc` typecheck: 9 pre-existing errors, 0 new since HEAD `7c12d85`; `eslint` 2 pre-existing errors in `ServersPage.tsx`, 0 in current work).
- **Routers:** 15 · **Migrations:** 27 (head `b1e2100000007`) · **ADRs:** 12 · **Contracts:** 6.
- **Authorization:** enforced via `require_permission` (global), `require_server_permission` (server-scoped RBAC), and `require_owner` (access mode); `contracts/permissions.yaml` v1.5 documents 85 effective routes.
- **Production DB:** `backend/data/servers/mcs.db` is a **legacy file** at revision `a3b2c3d4e5f6`; the default configured DB is `backend/mcs.db` **at head** (`b1e2100000007`, with `system_state`, `invitations`, `server_memberships` + Phase-7 exposure tables). See `current-state.md` §3.
- **CI:** five workflows — `backend-tests.yml` (full pytest + DB-compat + Ruff-baseline gate), `backend-version-ci.yml` (version propagation), `route-permission-ci.yml` (route→permission contract), `frontend-ci.yml` (typecheck/lint/test/build), `verification-cadence.yml` (weekly re-verification; see `current-state.md` §7). Pyright is advisory/local only, not CI-gated.

