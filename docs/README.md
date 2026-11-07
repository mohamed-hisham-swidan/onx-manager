# Documentation Index

This is the authoritative index for ONX Manager documentation. Documents are
listed with their status so it is always clear what is implemented vs planned.

---

## Start Here

| Document | Status | Purpose |
|---|---|---|
| [Current State](current-state.md) | ✅ **CURRENT** | Verified snapshot of the codebase (version 0.1.0, 3,510 backend tests collected, 1,113 frontend tests, 42 DB migrations). |
| [Canonical Roadmap](roadmap/ROADMAP_v1.1.md) | ✅ **CANONICAL** | Authoritative living roadmap governing Phase 5 (Containers — CLOSED), Phase 4 (Community Features — CLOSED), Enterprise Branch Runtime (Stages A–G & Frontend UI — CLOSED), Phase 5.5 (Pre-Beta Reliability — CLOSED), Phase 6 (UP NEXT). |
| [Versioning Policy](VERSIONING.md) | ✅ **ADOPTED** | SemVer 2.0.0 rules, version single source of truth (`0.1.0`), compatibility floor (`b1e2100000022`). |
| [API Reference](API.md) | ✅ **CURRENT** | REST API reference (18 routers, 155 live routes) & WebSocket protocols. |

---

## Architecture & Design

| Document | Status | Purpose |
|---|---|---|
| [System Architecture](architecture/ARCHITECTURE.md) | ✅ **CURRENT** | Modular monolith design, 13 DDD bounded contexts, CQRS buses, outbox, supervisor. |
| [Technical Specs](architecture/SPECS.md) | ✅ **CURRENT** | Tech stack, repository metrics, directory layouts, feature matrices. |
| [Database Architecture](architecture/DATABASE.md) | ✅ **CURRENT** | SQLite (`backend/data/onx.db`) & PostgreSQL models, 42 Alembic migrations (`b1e2100000022`), pre-backend reconciler. |
| [Security Architecture](architecture/SECURITY.md) | ✅ **CURRENT** | RS256 JWT auth, RBAC/ABAC route permissions, API keys, path sandboxing. |
| [Frontend Architecture](architecture/FRONTEND.md) | ✅ **CURRENT** | React 19, Tailwind CSS v4, TanStack Query, WebSocket store. |
| [Forge/NeoForge Provisioning Spec](architecture/SPEC-FORGE-PROVISIONING-001.md) | ✅ **CURRENT** | Unified InstallerProvisioner, non-destructive retry, failure classification. |
| [Plugins & Marketplace](architecture/plugins-and-marketplace.md) | ✅ **CURRENT** | Modrinth catalog integration, markdown descriptions, platform metadata. |
| [Server Provisioning](architecture/PROVISIONING.md) | ✅ **CURRENT** | Server creation engine, JAR validation, supported software types. |
| [Bug 3 Server Identity Loss Spec](design/BUG_3_SERVER_IDENTITY_LOSS_DESIGN_SPEC.md) | ✅ **ADOPTED** | Authoritative identity stamping, reconciliation adopt-vs-heal scoring, broadened container cleanup. |

---

## Runtime & Subsystems

| Document | Status | Purpose |
|---|---|---|
| [Server Lifecycle State Machine](runtime/lifecycle.md) | ✅ **CURRENT** | 8 `ServerStatus` states, transition matrices, recovery workflows. |
| [Server Providers](runtime/providers.md) | ✅ **CURRENT** | `LocalLinuxProvider` (tmux), `LocalWindowsProvider` (Win32), and `DockerProvider` (Phase 5 complete, dynamic IP, broadened cleanup). |
| [Reconciliation Engine](runtime/reconciliation.md) | ✅ **CURRENT** | Runtime server state reconciliation, Filesystem Reconciliation & Identity Healing (`identity_writer.py`), and Pre-Backend Database Reconciler (`reconciler.py`). |
| [Supervision Engine](runtime/supervision.md) | ✅ **CURRENT** | `RuntimeSupervisor` heartbeats, process PID recovery, zombie pruning. |

---

## Reference & Registries

| Document | Status | Purpose |
|---|---|---|
| [Domain Event Catalog](reference/event-catalog.md) | ✅ **CURRENT** | 61 domain event classes across 8 bounded contexts with payload schemas. |
| [System Module Map](reference/module-map.md) | ✅ **CURRENT** | 13 DDD modules, 18 REST routers, 22 frontend pages. |
| [Dependency Graph](reference/dependency-graph.md) | ✅ **CURRENT** | Layering rules, bounded context communication, hexagonal boundaries. |
| [Contract Registry](reference/contract-registry.md) | ✅ **CURRENT** | RBAC route contracts (`contracts/permissions.yaml`, 155 live routes), schemas. |

---

## Historical & Archival

| Document | Status | Purpose |
|---|---|---|
| [Project History Index](project-history/README.md) | ✅ **RECORD** | Index of preserved feature design reviews and engineering notes. |
| [K5 Marketplace Design Review](project-history/features/2026-08-07-k5-marketplace-review.md) | ⏸️ **ARCHIVED** | First-class marketplace section design review. |
| [Marketplace UX & Theming Findings](project-history/features/marketplace-ux-findings.md) | ⏸️ **ARCHIVED** | Marketplace UX and theming findings. |
| [Dashboard & Server Management Redesign](project-history/features/dashboard-redesign-v1-findings.md) | ⏸️ **ARCHIVED** | Dashboard and server management redesign findings. |
| [Plugin Description Markdown Fast-Fix](project-history/post-phase-7/2026-08-20-plugin-description-markdown-fastfix.md) | ⏸️ **ARCHIVED** | Markdown rendering and sanitization notes for plugin descriptions. |
| [FakePlayer Verification Speedup Report](project-history/FIX2C-SPEED-2026-09-21.md) | ⏸️ **ARCHIVED** | Test execution optimization record for FakePlayer verification. |
