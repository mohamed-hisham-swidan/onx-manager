# Contract Registry

> Cross-references: [Dependency Graph](dependency-graph.md), [Event Catalog](event-catalog.md), [Module Map](module-map.md), [Architecture](../ARCHITECTURE.md)

Source: `contracts/`

---

## Contract IDs

| ID | Interface | Provider | Consumer(s) | Since |
|---|---|---|---|---|
| C-001 | `CommandBus` | Batch 01 | All batches | v4.0 |
| C-002 | `EventBus` | Batch 01 | All batches | v4.0 |
| C-003 | `QueryBus` | Batch 01 | All batches | v4.0 |
| C-004 | `UnitOfWork` | Batch 01 | All batches | v4.0 |
| C-005 | `MCSError` hierarchy | Batch 01 | All batches | v4.0 |
| C-006 | `ServerProvider` | Batch 03 | Batch 04, 05, 06 | v4.0 |
| C-007 | `Server` aggregate | Batch 02 | Batch 03, 04, 05, 09 | v4.0 |
| C-008 | `JWTProvider` | Batch 08 | Batch 05, 06 | v4.0 |
| C-009 | `PermissionEvaluator` | Batch 08 | Batch 05, 06 | v4.0 |
| C-010 | `AuditLogger` | Batch 08 | Batch 05 | v4.0 |
| C-011 | `TaskQueue` | Batch 09 | Batch 04, 05 | v4.0 |
| C-012 | `EventStore` | Batch 09 | All batches | v4.0 |

## Contract Files

### `config.schema.json` — Server Configuration Schema

- **Version:** Draft-07
- **Scope:** Server module
- **Path:** `contracts/config.schema.json`

Top-level schema for immutable server configuration. Validates Minecraft version (semver pattern), memory allocation (1024 MB min), port range (1024–65535), JVM args, provider type, stop timeout. Conditional requirement: `provider_type: "remote"` requires `ssh_host`, `ssh_user`, `ssh_key_path`.

### `plugin.yaml` — Plugin Contract

- **Version:** 1.0
- **Scope:** Plugin system
- **Path:** `contracts/plugin.yaml`

Defines the plugin manifest schema (name, version, author, isolation mode, permissions for filesystem/network/events/system) and the plugin lifecycle state machine with nine states (INSTALLED → DISABLED → ENABLING → ENABLED → DISABLING → UNINSTALLING → UNINSTALLED, +FAILED) and valid transitions.

### `permissions.yaml` — Permission Contract

- **Version:** 1.0
- **Scope:** Auth system
- **Path:** `contracts/permissions.yaml`

Defines every permission string and its scoping (`server_id` or `global`). Covers server CRUD + start/stop, backup CRUD, plugin management, user management, settings, and `admin:full`. Defines three built-in roles:
- **viewer:** read-only on servers, backups, plugins
- **operator:** server write/start/stop, backup create, plugin install/manage
- **admin:** unrestricted

### `events.yaml` — Event Contract

- **Version:** 1.0
- **Scope:** All modules
- **Path:** `contracts/events.yaml`

Standard event envelope schema (id, type, version, timestamp, source, correlation_id, payload) plus schemas for every domain event. See [Event Catalog](event-catalog.md) for full list.

### `api.yaml` — API Contract

- **Version:** 1.0
- **Scope:** REST API
- **Path:** `contracts/api.yaml`

Cross-batch agreement on REST API behavior:
- **Base path:** `/api/v1`
- **Content type:** `application/json`
- **Auth:** Bearer JWT in `Authorization` header
- **Error format:** `{ code, message, details, request_id, retryable, documentation_url }`
- **Pagination:** 1-indexed, `page`/`per_page` (default 20, max 100), `total`, `total_pages`
- **Response envelope:** `{ data, pagination? }`

## Breaking Changes

| Contract | Impact |
|---|---|
| C-001 (`CommandBus`) | All handler registrations must update |
| C-006 (`ServerProvider`) | All provider implementations must update |

---

The concrete abstract classes / protocol stubs live in each module's `domain/` (ports) and `infrastructure/` (adapters) layers — see the [Module Map](module-map.md) for locations.
