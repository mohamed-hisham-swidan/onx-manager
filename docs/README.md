# Documentation Index

Welcome to the ONX Manager documentation (`v0.1.0`). Every active guide, architectural spec, runtime manual, and reference catalog is indexed below.

---

## Getting Started & Operations

| Document | Purpose |
|---|---|
| [Getting Started](getting-started.md) | 5-minute quickstart via Docker Compose, `install.sh` / `install.ps1`, Desktop app, or manual dev setup. |
| [Deployment Guide](DEPLOYMENT.md) | Docker Compose deployment, DooD profile, bare-metal VPS `systemd`, `ONX_DEPLOYMENT_PROFILE` & DB migration floor. |
| [Desktop App Wrapper](../desktop/README.md) | Thin Electron shell (`desktop/`) supporting Local auto-supervisor and Remote VPS/tunnel panels. |
| [Development Guide](DEVELOPMENT.md) | Local development workflow, `launcher.py`, preflight scripts, and troubleshooting. |
| [Testing Guide](testing.md) | Backend (`pytest`) & frontend (`vitest`) suites and the 6 CI quality gates. |
| [REST & WebSocket API](API.md) | API reference across 19 router files (215 live routes) and `/ws` WebSocket protocols. |
| [Versioning Policy](VERSIONING.md) | SemVer 2.0.0 rules, single source of truth (`0.1.0`), and fail-closed DB compatibility floor (`b1e2100000033`). |
| [Roadmap](roadmap/ROADMAP.md) | Public post-launch roadmap placeholder. |

---

## Architecture & Design (`architecture/` & `design/`)

| Document | Purpose |
|---|---|
| [Architecture Portal](architecture/README.md) | Index of architecture specifications. |
| [System Architecture](architecture/ARCHITECTURE.md) | Modular monolith, 13 DDD bounded contexts, CQRS buses, and Simple/Advanced architecture. |
| [Technical Specs](architecture/SPECS.md) | Tech stack, repository shape, code/test metrics, and complete feature inventory. |
| [Database Architecture](architecture/DATABASE.md) | SQLite & PostgreSQL schema, 56 ORM tables (`62` SQLite tables), 53 Alembic migrations (`b1e2100000033`), and pre-backend reconciler. |
| [Security Architecture](architecture/SECURITY.md) | RS256 JWT auth, RBAC/ABAC route permissions, API keys, and path-traversal sandboxing. |
| [Frontend Architecture](architecture/FRONTEND.md) | React 19, Tailwind CSS v4, TanStack Query, Zustand, and WebSocket cache bridge. |
| [Server Provisioning](architecture/PROVISIONING.md) | Server creation engine, JAR validation, supported software types (incl. Quilt & modpacks). |
| [Forge/NeoForge Provisioning](architecture/SPEC-FORGE-PROVISIONING-001.md) | Unified installer provisioner, non-destructive retry, and failure classification. |
| [Plugins & Marketplace](architecture/plugins-and-marketplace.md) | Plugin lifecycle, disk reconciliation, and Modrinth catalog integration. |
| [Health Engine Design](architecture/health-engine-design.md) | Multi-factor server health evaluation engine and crash classification. |
| [Simple & Advanced Modes Spec](design/SPEC-2026-11-09-SIMPLE-ADVANCED-MODES-02.md) | Normative specification (v8.7) for Simple/Advanced modes, Allow-list v2.3, vaults, branch runtimes, GitHub sync, and safe upgrades. |
| [Frontend Design System](design/frontend-overhaul/README.md) | Design system index ([BRAND.md](design/frontend-overhaul/BRAND.md), [TOKENS.md](design/frontend-overhaul/TOKENS.md), [SKINS.md](design/frontend-overhaul/SKINS.md), [PRIMITIVES.md](design/frontend-overhaul/PRIMITIVES.md), [TEMPLATES.md](design/frontend-overhaul/TEMPLATES.md), [MINECRAFT-FLAVOR-GUARDRAILS.md](design/frontend-overhaul/MINECRAFT-FLAVOR-GUARDRAILS.md)). |

---

## Runtime & Subsystems (`runtime/`)

| Document | Purpose |
|---|---|
| [Runtime Overview](runtime/README.md) | Supervision, reconciliation, and ownership feedback loop. |
| [Server Lifecycle State Machine](runtime/lifecycle.md) | Server status transitions and recovery workflows. |
| [Server Providers](runtime/providers.md) | Docker-only runtime provider (`DockerProvider`) and remote/cloud provider stubs. |
| [Runtime Reconciliation](runtime/reconciliation.md) | DB ↔ OS state reconciliation and orphan cleanup. |
| [Filesystem Reconciliation](runtime/filesystem-reconciliation.md) | Disk-as-truth directory scanner and `.onx-manager/server.json` identity healing. |
| [Ownership Verification](runtime/ownership.md) | Multi-factor process ownership checks and port claiming. |
| [Supervision Engine](runtime/supervision.md) | `RuntimeSupervisor` heartbeats, startup deadlines, and crash handling. |
| [Recovery Procedures](runtime/recovery.md) | Startup and crash recovery playbooks. |

---

## Reference & Decisions (`reference/`, `decisions/`, `governance/`)

| Document | Purpose |
|---|---|
| [Reference Portal](reference/README.md) | Index of live subsystem registries. |
| [System Module Map](reference/module-map.md) | Directory map of 13 DDD modules, 19 REST router files (215 routes), and 23 routed frontend pages. |
| [Domain Event Catalog](reference/event-catalog.md) | 87 domain event classes across 9 bounded contexts. |
| [Dependency Graph](reference/dependency-graph.md) | Layering rules and hexagonal boundary constraints. |
| [Contract Registry](reference/contract-registry.md) | Route permission contracts (`contracts/permissions.yaml`) and JSON/YAML schemas. |
| [Architecture Decision Records](decisions/README.md) | Index of ADRs `0001`–`0023`. |
| [Contributing & Governance](../CONTRIBUTING.md) | Development workflow, quality gates, and project decision/PR process. |
