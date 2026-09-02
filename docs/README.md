# Documentation Index

This is the authoritative index for ONX Manager documentation. Documents are
listed with their status so it is always clear what is implemented vs planned.

---

## Start Here

| Document | Status | Purpose |
|---|---|---|
| [Current State](current-state.md) | ✅ **CURRENT** | Verified snapshot of the codebase (version 0.1.0, 2149 backend tests, 574 frontend tests, 29 DB migrations). |
| [Canonical Roadmap](roadmap/ROADMAP.md) | ✅ **CANONICAL** | Authoritative living roadmap governing Phase 8+ (Dynamic DNS & Custom Domains). |
| [Versioning Policy](VERSIONING.md) | ✅ **ADOPTED** | SemVer 2.0.0 rules, version single source of truth (`0.1.0`), compatibility floor. |
| [API Reference](API.md) | ✅ **CURRENT** | REST API reference (15 routers, 105 endpoints) & WebSocket protocols. |

---

## Architecture & Design

| Document | Status | Purpose |
|---|---|---|
| [System Architecture](architecture/ARCHITECTURE.md) | ✅ **CURRENT** | Modular monolith design, 10 DDD bounded contexts, CQRS buses, outbox, supervisor. |
| [Technical Specs](architecture/SPECS.md) | ✅ **CURRENT** | Tech stack, repository metrics, directory layouts, feature matrices. |
| [Database Architecture](architecture/DATABASE.md) | ✅ **CURRENT** | SQLite (`backend/data/onx.db`) & PostgreSQL models, 29 Alembic migrations (`b1e2100000009`), pre-backend reconciler. |
| [Security Architecture](architecture/SECURITY.md) | ✅ **CURRENT** | RS256 JWT auth, RBAC/ABAC route permissions, API keys, path sandboxing. |
| [Frontend Architecture](architecture/FRONTEND.md) | ✅ **CURRENT** | React 19, Tailwind CSS v4, TanStack Query, WebSocket store. |
| [Forge/NeoForge Provisioning Spec](architecture/SPEC-FORGE-PROVISIONING-001.md) | ✅ **CURRENT** | Unified InstallerProvisioner, non-destructive retry, failure classification. |
| [Plugins & Marketplace](architecture/plugins-and-marketplace.md) | ✅ **CURRENT** | Modrinth catalog integration, markdown descriptions, platform metadata. |
| [Server Provisioning](architecture/PROVISIONING.md) | ✅ **CURRENT** | Server creation engine, JAR validation, supported software types. |

---

## Runtime & Subsystems

| Document | Status | Purpose |
|---|---|---|
| [Server Lifecycle State Machine](runtime/lifecycle.md) | ✅ **CURRENT** | 8 `ServerStatus` states, transition matrices, recovery workflows. |
| [Server Providers](runtime/providers.md) | ✅ **CURRENT** | `LocalLinuxProvider` (tmux execution) & `LocalWindowsProvider` (native Win32 process tracking). |
| [Reconciliation Engine](runtime/reconciliation.md) | ✅ **CURRENT** | Runtime server state reconciliation and Pre-Backend Database Reconciler (`reconciler.py`). |
| [Supervision Engine](runtime/supervision.md) | ✅ **CURRENT** | `RuntimeSupervisor` heartbeats, process PID recovery, zombie pruning. |

---

## Reference & Registries

| Document | Status | Purpose |
|---|---|---|
| [Domain Event Catalog](reference/event-catalog.md) | ✅ **CURRENT** | 52 domain event classes across all 10 DDD modules with payload schemas. |
| [System Module Map](reference/module-map.md) | ✅ **CURRENT** | 10 DDD modules, 15 REST routers, 19 frontend pages. |
| [Dependency Graph](reference/dependency-graph.md) | ✅ **CURRENT** | Layering rules, bounded context communication, hexagonal boundaries. |
| [Contract Registry](reference/contract-registry.md) | ✅ **CURRENT** | RBAC route contracts (`contracts/permissions.yaml`), schemas. |

---

## Historical & Archival

| Document | Status | Purpose |
|---|---|---|
| [Archived Roadmap Generations](history/archive/legacy-roadmaps/) | ⏸️ **ARCHIVED** | Historical roadmap monoliths (v1–v4), volume splits (vol2–vol6-8), and Blueprint v4 series. |
| [Archived Blueprint V5](history/archive/blueprint-v5-2026-08-07.md) | ⏸️ **ARCHIVED** | Superseded blueprint (Phases 0–7 completed). |
| [Docs Reconnaissance Report](history/2026-08-23-docs-recon-report.md) | ⏸️ **AUDIT** | 107-file inventory and health assessment report. |
| [Redoc Execution Plan](history/2026-08-23-redoc-execution-plan.md) | ⏸️ **PLAN** | 7-batch documentation reorganization plan. |
| [Status Journal](history/status-journal-2026.md) | ⏸️ **ARCHIVED** | Historical narrative log of project milestones. |
