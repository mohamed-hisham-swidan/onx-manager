# System Module Map & Route Inventory

**Status:** Living Reference (Synchronized with live codebase)  
**Backend Architecture:** Modular Monolith with 13 DDD Bounded Contexts & Hexagonal Architecture  
**Frontend Architecture:** React 19 / Vite / TanStack Query with 23 routed pages (`App.tsx`)

---

## 1. Backend Bounded Contexts (`backend/app/modules/`)

| Module Name | Domain Responsibilities | Key Aggregates & Value Objects | Physical Path |
|---|---|---|---|
| **`server`** | Server aggregate root, lifecycle transitions, provisioning engine, launch config, process supervision, import scanner, filesystem reconciliation | `Server`, `ServerId`, `ServerStatus`, `ServerProperties`, `LaunchConfiguration` | `backend/app/modules/server/` |
| **`versioning`** | Git-native server version control, commit DAG, tags, materializations, import reviews, test definitions, admission-scheduled test runs, branch protection, AES-256-GCM Class-C/secret vaults, structured merge, branch runtimes, GitHub sync, modpacks, LEC & 1-click safe upgrades | `ServerBranch`, `ServerCommit`, `ServerTag`, `Materialization`, `ImportReview`, `TestDefinition`, `Runtime`, `TestRun`, `BranchProtectionPolicy`, `LockfileV21`, `RefreshJournalRecord`, `HostPortSet` | `backend/app/modules/versioning/` |
| **`operations`** | Multi-step operation state machine, step execution tracking, cooperative cancellation, idempotency, WebSocket projection | `Operation`, `OperationStep`, `OperationStatus` | `backend/app/modules/operations/` |
| **`activity`** | Persistent per-server activity and audit logs | `ServerActivityLog` | `backend/app/modules/activity/` |
| **`auth`** | User entity, password hashing (Argon2id/bcrypt), RS256 JWT tokens, RBAC/ABAC permissions, invite codes, API keys | `User`, `UserId`, `Role`, `Permission`, `ApiKey`, `InviteCode` | `backend/app/modules/auth/` |
| **`backup`** | Backup saga, tar/gzip archiving, restoration orchestrator, S3/local storage strategies, checksum verification | `Backup`, `BackupId`, `BackupType`, `BackupStatus` | `backend/app/modules/backup/` |
| **`health`** | System & server health classification, filesystem integrity guard, crash analyzer, automated recovery sagas | `HealthReport`, `IntegrityCheck`, `CrashClassification`, `RecoveryAction` | `backend/app/modules/health/` |
| **`monitoring`** | Host & process CPU/RAM metrics collection, RCON client & TPS parsing, Prometheus metrics endpoint | `MetricPoint`, `MetricsSnapshot`, `AlertRule` | `backend/app/modules/monitoring/` |
| **`plugin`** | Plugin entity, Modrinth & CurseForge catalog providers, subprocess isolation runner, JSON-RPC SDK bridge | `Plugin`, `PluginProject`, `PluginVersion`, `CatalogProvider` | `backend/app/modules/plugin/` |
| **`exposure`** | Network access subsystem, Cloudflare Named Tunnels, Playit.gg agent daemon control plane, UPnP port forwarding | `ExposureConfig`, `TunnelMapping`, `PlayitAgent`, `PortForward` | `backend/app/modules/exposure/` |
| **`event_store`** | Append-only event store persistence, event stream replaying, aggregate event auditing | `EventStoreEntry`, `StreamSnapshot` | `backend/app/modules/event_store/` |
| **`storage`** | Local & remote storage providers, atomic file writes, same-filesystem staging directory management | `StorageProvider`, `LocalStorageProvider`, `S3StorageProvider` | `backend/app/modules/storage/` |
| **`shared`** | Shared domain primitives, base aggregate root, entity ID generators, event abstractions | `AggregateRoot`, `Entity`, `ValueObject`, `DomainEvent` | `backend/app/modules/shared/` |

---

## 2. API Routers (`backend/app/api/v1/routers/` — 19 Router Files)

| Router | Prefix | Responsibility |
|---|---|---|
| `activity.py` | `/api/v1/servers/{id}/activity` | Per-server and branch-scoped activity and audit log queries |
| `auth.py` | `/api/v1/auth` | User authentication, token issuance, refresh, logout, session inspection |
| `users.py` | `/api/v1/users` | User management, role assignment, password updates, deactivation |
| `invites.py` | `/api/v1/invites` | User invitation creation, token redemption, invite revocation |
| `setup.py` | `/api/v1/setup` | First-run owner bootstrap, system initialization guard |
| `servers.py` | `/api/v1/servers` | Server CRUD, mode, start/stop/restart/kill, console tail, command execution, retry-provisioning |
| `software.py` | `/api/v1/software` | Minecraft server software list, version discovery, download metadata |
| `plugins.py` | `/api/v1/servers/{id}/plugins` & `/api/v1/plugins` | Installed plugin management, enable/disable, local JAR install/uninstall |
| `marketplace.py` | `/api/v1/marketplace` | Global & server-scoped plugin search, project details, version listing, Modrinth install |
| `modpacks_upgrades.py` | `/api/v1/servers/{id}/{modpacks,upgrades,p55-settings}` & `/api/v1/lec` | Modpack inspect/install (`.mrpack`/CurseForge), 1-click safe upgrade workflow, P5.5 settings, and host LEC management |
| `backups.py` | `/api/v1/backups` | Backup creation, listing, restoration, deletion, verification |
| `exposure.py` | `/api/v1/exposure` & `/servers/{id}/exposure` | Cloudflare/Playit panel access, server tunnel mapping, UPnP forwarding, agent claim |
| `files.py` | `/api/v1/servers/{id}/files` | Server filesystem browser, live-state inspection, file read/write, directory listing, upload/delete |
| `health.py` | `/api/v1/health` & `/servers/{id}/health` | System health checks, server integrity validation, crash reports, recovery triggers |
| `monitoring.py` | `/api/v1/monitoring` | Host metrics, server CPU/RAM/TPS timeseries, resource alerts |
| `operations.py` | `/api/v1/operations` | Multi-step operation creation, status inspection, cooperative cancel, and retry |
| `schedules.py` | `/api/v1/schedules` | Automated scheduled tasks (backups, restarts, commands) |
| `settings.py` | `/api/v1/settings` | Live application settings inspection, runtime config updates, encrypted panel integration secrets |
| `versioning.py` | `/api/v1/servers/{id}/versioning`, `/api/v1/servers/{id}/convert/*` & `/api/v1/webhooks/github` | Branches, protection, commits, merge, diff, tags, refresh/rollback, vaults, branch runtimes, data templates, Simple ↔ Advanced conversion, GitHub sync & webhook ingress, tests |

*Total live routes: 215 across all routers + system/app routes (`/ws`, `/health`, `/metrics`, `/.well-known/jwks.json`, OpenAPI). Verified by `./scripts/check-route-contract` (215/215 PASS).*

---

## 3. Frontend Page Inventory (`frontend/src/` — 23 Routed Pages)

| Page Component | Route Path | Purpose |
|---|---|---|
| `LoginPage.tsx` | `/login` | User login form with JWT authentication |
| `RegisterPage.tsx` | `/register` | User registration via invite code |
| `SetupPage.tsx` | `/setup` | First-run owner account setup wizard |
| `InvitePage.tsx` | `/invite/:code` | Invite code landing and account creation |
| `DashboardPage.tsx` | `/` | System overview, active server cards, quick actions |
| `ServersPage.tsx` | `/servers` | Filterable list of all Minecraft servers with status badges |
| `CreateServerPage.tsx` | `/servers/new` | Multi-step server creation wizard (Software, Version, Config, Properties, Review) |
| `ImportServerPage.tsx` | `/servers/import` | Unmanaged server import wizard from filesystem scanner |
| `ServerDetailPage.tsx` | `/servers/:id` | Server management hub (Console, Controls, Status, Metrics overview) |
| `ServerFilesPage.tsx` | `/servers/:id/files` | In-browser file explorer, text editor, file uploader |
| `ServerModsPage.tsx` | `/servers/:id/mods` | Mod & plugin manager for Forge, Fabric, NeoForge, Paper |
| `ServerExposurePage.tsx` | `/servers/:id/exposure` | Game server network exposure configuration (Playit, Cloudflare, UPnP) |
| `ServerVersioningPage.tsx` | `/servers/:id/versioning` | Enterprise versioning hub (Branches, Tags, Commits, Diffs, Worktrees, Tests, Reviews) |
| `ServerActivityPage.tsx` | `/servers/:id/activity` | Server activity and audit log |
| `ServerSettingsPage.tsx` | `/servers/:id/settings` | Per-server configuration and tuning |
| `PluginListPage.tsx` | `/servers/:id/plugins` | Installed plugins table with toggle switch and uninstall |
| `PluginMarketplacePage.tsx` | `/marketplace` | Modrinth plugin/mod marketplace browser with search, filters, pagination |
| `PluginDetailPage.tsx` | `/marketplace/:id` | Rich plugin details with ReactMarkdown descriptions, version picker, install modal |
| `BackupListPage.tsx` | `/servers/:id/backups` | Backup management, manual trigger, download, restore actions |
| `SettingsPage.tsx` | `/settings` | System configuration, network access, auth policies, live settings |
| `ApiKeysPage.tsx` | `/settings/api-keys` | User API key generation, permissions, revocation |
| `NotFoundPage.tsx` | `*` | 404 error page with navigation fallback |
