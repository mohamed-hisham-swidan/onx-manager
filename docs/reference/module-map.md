# System Module Map & Route Inventory

**Status:** Living Reference (Synchronized with live codebase)  
**Backend Architecture:** Modular Monolith with 10 DDD Bounded Contexts & Hexagonal Architecture  
**Frontend Architecture:** React 19 / Vite / TanStack Query with 19 pages

---

## 1. Backend Bounded Contexts (`backend/app/modules/`)

| Module Name | Domain Responsibilities | Key Aggregates & Value Objects | Physical Path |
|---|---|---|---|
| **`server`** | Server aggregate root, lifecycle transitions, provisioning engine, launch config, process supervision, import scanner, filesystem reconciliation | `Server`, `ServerId`, `ServerStatus`, `ServerProperties`, `LaunchConfiguration` | `backend/app/modules/server/` |
| **`auth`** | User entity, password hashing (bcrypt), RS256 JWT tokens, RBAC/ABAC permissions, invite codes, API keys | `User`, `UserId`, `Role`, `Permission`, `ApiKey`, `InviteCode` | `backend/app/modules/auth/` |
| **`backup`** | Backup saga, tar/gzip archiving, restoration orchestrator, S3/local storage strategies, checksum verification | `Backup`, `BackupId`, `BackupType`, `BackupStatus` | `backend/app/modules/backup/` |
| **`health`** | System & server health classification, filesystem integrity guard, crash analyzer, automated recovery sagas | `HealthReport`, `IntegrityCheck`, `CrashClassification`, `RecoveryAction` | `backend/app/modules/health/` |
| **`monitoring`** | Host & process CPU/RAM metrics collection, RCON client & TPS parsing, Prometheus metrics endpoint | `MetricPoint`, `MetricsSnapshot`, `AlertRule` | `backend/app/modules/monitoring/` |
| **`plugin`** | Plugin entity, Modrinth & CurseForge catalog providers, subprocess isolation runner, JSON-RPC SDK bridge | `Plugin`, `PluginProject`, `PluginVersion`, `CatalogProvider` | `backend/app/modules/plugin/` |
| **`exposure`** | Network access subsystem, Cloudflare Named Tunnels, Playit.gg agent daemon control plane, UPnP port forwarding | `ExposureConfig`, `TunnelMapping`, `PlayitAgent`, `PortForward` | `backend/app/modules/exposure/` |
| **`event_store`** | Append-only event store persistence, event stream replaying, aggregate event auditing | `EventStoreEntry`, `StreamSnapshot` | `backend/app/modules/event_store/` |
| **`storage`** | Local & remote storage providers, atomic file writes, same-filesystem staging directory management | `StorageProvider`, `LocalStorageProvider`, `S3StorageProvider` | `backend/app/modules/storage/` |
| **`shared`** | Shared domain primitives, base aggregate root, entity ID generators, event abstractions | `AggregateRoot`, `Entity`, `ValueObject`, `DomainEvent` | `backend/app/modules/shared/` |

---

## 2. API Routers (`backend/app/api/v1/routers/` — 15 Routers)

| Router | Prefix | Responsibility | Endpoint Count |
|---|---|---|---|
| `auth.py` | `/api/v1/auth` | User authentication, token issuance, refresh, logout, session inspection | 5 |
| `users.py` | `/api/v1/users` | User management, role assignment, password updates, deactivation | 6 |
| `invites.py` | `/api/v1/invites` | User invitation creation, token redemption, invite revocation | 4 |
| `setup.py` | `/api/v1/setup` | First-run owner bootstrap, system initialization guard | 3 |
| `servers.py` | `/api/v1/servers` | Server CRUD, start/stop/restart/kill, console tail, command execution, retry-provisioning | 14 |
| `software.py` | `/api/v1/software` | Minecraft server software list, version discovery, download metadata | 4 |
| `plugins.py` | `/api/v1/servers/{id}/plugins` | Installed plugin management, enable/disable, local JAR install/uninstall | 6 |
| `marketplace.py` | `/api/v1/marketplace` | Global & server-scoped plugin search, project details, version listing, Modrinth install | 6 |
| `backups.py` | `/api/v1/backups` | Backup creation, listing, restoration, deletion, download stream | 7 |
| `exposure.py` | `/api/v1/exposure` & `/servers/{id}/exposure` | Cloudflare/Playit panel access, server tunnel mapping, UPnP forwarding, agent claim | 10 |
| `files.py` | `/api/v1/servers/{id}/files` | Server filesystem browser, file read/write, directory listing, upload/delete | 8 |
| `health.py` | `/api/v1/health` & `/servers/{id}/health` | System health checks, server integrity validation, crash reports, recovery triggers | 6 |
| `monitoring.py` | `/api/v1/monitoring` | Host metrics, server CPU/RAM/TPS timeseries, resource alerts | 5 |
| `schedules.py` | `/api/v1/schedules` | Automated scheduled tasks (backups, restarts, commands) | 6 |
| `settings.py` | `/api/v1/settings` | Live application settings inspection, runtime config updates | 5 |

---

## 3. Frontend Page Inventory (`frontend/src/` — 19 Pages)

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
| `PluginListPage.tsx` | `/servers/:id/plugins` | Installed plugins table with toggle switch and uninstall |
| `PluginMarketplacePage.tsx` | `/marketplace` | Modrinth plugin/mod marketplace browser with search, filters, pagination |
| `PluginDetailPage.tsx` | `/marketplace/:id` | Rich plugin details with ReactMarkdown descriptions, version picker, install modal |
| `BackupListPage.tsx` | `/servers/:id/backups` | Backup management, manual trigger, download, restore actions |
| `SettingsPage.tsx` | `/settings` | System configuration, network access, auth policies, live settings |
| `ApiKeysPage.tsx` | `/settings/api-keys` | User API key generation, permissions, revocation |
| `NotFoundPage.tsx` | `*` | 404 error page with navigation fallback |
