# Plugins & Marketplace — Current Implementation

**Status:** ✅ **IMPLEMENTED** (backend + first-class `/marketplace` frontend + P5.5 modpacks).
**Cross-references:** `docs/architecture/SPECS.md` · `docs/API.md`

---

## 1. Two distinct concepts

This project has **two separate things** that are easy to confuse:

| Concept | What it is | State |
|---------|-----------|-------|
| **Plugin management** | Managing the plugins already on a server — list, enable, disable, uninstall | Implemented; filesystem-reconciled |
| **Marketplace** | Browsing/searching the Modrinth catalog and installing plugins/mods from it | Implemented (backend + `/marketplace` frontend) |

They are deliberately separated in this document: plugin management operates on what's on disk; the marketplace operates on what's available to install. (Full `.mrpack` and CurseForge modpack archive installation & 1-click safe upgrades are implemented under `backend/app/modules/versioning/`.)

---

## 2. Filesystem is the source of truth

`ReconcilePluginsHandler` (`backend/app/modules/plugin/application/commands/reconcile_plugins.py`)
makes the `plugins` DB table reflect the actual filesystem state:

- The **filesystem** (`<server_dir>/plugins/*.jar`) is the source of truth for
  which plugins exist.
- The **DB is a metadata cache** on top of it.
- Every `GET /api/v1/servers/{server_id}/plugins` triggers a
  `ReconcilePluginsCommand` before listing:
  - `.jar` files on disk with no DB row → new `source="detected"` rows.
  - DB rows whose file was removed from disk → pruned (unless pending deletion).
- Rows track per-plugin `filename` and `source` (`detected` | `modrinth`).
  These columns come from migrations `3a42d373bb05` (Modrinth source columns)
  and `c4d5e6f7a8b9` (plugin filesystem-tracking columns).
- Plugin deletion is **deferred**: a `pending_deletion` flag is set so a
  running JVM never has its `.jar` removed out from under it; the file is
  removed on the next server start/restart.

### DB columns relevant to the plugin registry

| Column | Meaning |
|--------|---------|
| `filename` | On-disk `.jar` filename (reconciliation key) |
| `source` | `detected` (found on disk) or `modrinth` (installed via marketplace) |
| `external_project_id` / `external_version_id` | Modrinth IDs for marketplace-installed plugins |
| `external_url` / `checksum` | Download URL + SHA-1/SHA-512 used at install |
| `pending_deletion` | Set by uninstall; consumed on next server start/restart |

---

## 3. Marketplace backend

### 3.1 Provider abstraction

`PluginCatalogProvider` ABC (`backend/app/modules/plugin/infrastructure/providers/base.py`)
mirrors the `StorageBackend` pattern:

| Method | Purpose |
|--------|---------|
| `search(query, limit, offset)` | Catalog search |
| `get_project(project_id)` | Project detail |
| `get_project_versions(project_id)` | All versions of a project |
| `get_version(version_id)` | Single version |
| `download(url, expected_sha1, expected_sha512)` | Download + checksum-verify |

Factory: `build_plugin_catalog_provider(name=None, settings=None)` — provider selection is
**configuration-driven** via `ONX_PLUGIN_PROVIDERS` (or legacy `MCS_PLUGIN_PROVIDERS`, default `modrinth`); a value is validated at
startup so an unknown, empty, **or multiple** configured providers fail fast.
The only registered plugin-catalog provider today is `ModrinthProvider` (`api.modrinth.com/v2`), while CurseForge modpack archives and API lookups are handled by `curseforge_adapter.py` in P5.5.

### 3.2 Modrinth quirks handled

- Search hits report `project_type: "mod"` even for real plugins — the provider
  filters on `all_project_types` and uses bukkit-family loader facets
  (`bukkit`, `paper`, `purpur`, `spigot`, `folia`), not the top-level field.
- Download/API calls retry with exponential backoff (2 retries, 30s timeout)
  and verify SHA-1/SHA-512 hashes when the provider returns them.

### 3.3 Best-version selection

`select_best_version()` (`backend/app/modules/plugin/application/services/version_selector.py`)
ranks versions for a given server:

1. **Exact game version + exact loader** — preferred.
2. **Exact game version on the nearest compatible parent loader**
   (purpur → paper → spigot → bukkit) — emits a `loader_fallback` notice.
3. **Closest available game version** on a compatible loader — emits a
   `version_mismatch` warning (**never blocks** the choice; the user can
   override from the full list).

Always returns the full version list sorted newest-first for manual override.

### 3.4 Install flow

`InstallModrinthPluginHandler`
(`backend/app/modules/plugin/application/commands/install_modrinth_plugin.py`):

1. Resolves the server's deployment root; rejects servers that don't support
   plugin installs from a catalog (`vanilla`, `fabric`, `forge` are manual-only).
2. Resolves the version (explicit `version_id`, or best-version selection).
3. Downloads the primary file with SHA-1/SHA-512 verification.
4. Writes the `.jar` atomically into `<server_dir>/plugins/` (existing filename
   → `FILE_CONFLICT`).
5. Creates the `modrinth` plugin row and commits.

### 3.5 Routes

Two route namespaces — a server-scoped one under
`/api/v1/servers/{server_id}/plugins`, and a server-independent global catalog
one under `/api/v1/marketplace` (K5 + SPEC-PLUGIN-DETAIL-TABS-001). See
`docs/API.md` for the full reference.

Server-scoped (all under `/api/v1/servers/{server_id}/plugins`):

| Method | Path | Permission | Notes |
|--------|------|-----------|-------|
| `GET` | `/plugins` | auth (list) | Triggers filesystem reconciliation first |
| `GET` | `/plugins/marketplace/search` | `plugin:manage` | Modrinth catalog search |
| `GET` | `/plugins/marketplace/projects/{project_id}/versions` | `plugin:manage` | Versions + best-version selection for the server |
| `POST` | `/plugins/marketplace/install` | `plugin:manage` | Download + verify + atomic install |
| `GET` | `/plugins/{plugin_id}` | auth (read) | |
| `DELETE` | `/plugins/{plugin_id}` | `plugin:manage` | Sets `pending_deletion` |
| `POST` | `/plugins/{plugin_id}/enable` | auth-only (K4) | **No `require_permission`** — Phase 4 gap |
| `POST` | `/plugins/{plugin_id}/disable` | auth-only (K4) | **No `require_permission`** — Phase 4 gap |

Server-independent (under `/api/v1/marketplace`, all `plugin:manage`):

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/marketplace/search` | Global catalog search (K5, `useMarketplaceSearchGlobal`) |
| `GET` | `/marketplace/projects/{project_id}` | Full project detail; nullable `wiki_url`/`source_url`; `client_side`/`server_side` (SPEC-PLUGIN-DETAIL-TABS-001) |
| `GET` | `/marketplace/projects/{project_id}/versions` | All versions raw, `selected=null` always; Recommended computed client-side (2026-08-19) |

---

## 4. Frontend

### 4.1 Plugin management page

`PluginListPage` (`frontend/src/server_manager/pages/PluginListPage.tsx`):

- Requires a selected server (`?server=` / dropdown).
- Lists the reconciled plugins.
- Enable / disable / uninstall (with deferred-deletion toast).
- The **Install** button navigates to `/plugins/marketplace?server=<id>`.

### 4.2 Marketplace page

`PluginMarketplacePage` (`frontend/src/server_manager/pages/PluginMarketplacePage.tsx`):

- Server selector, search box, results table (downloads, follows, icon).
- Project detail → versions table with the best-version highlight and
  loader-fallback / version-mismatch notices.
- Install with confirmation dialog; toast on success/failure.

### 4.3 Routing

- `App.tsx`: `<Route path="plugins/marketplace" element={<PluginMarketplacePage />} />` (kept) plus
  top-level `<Route path="marketplace" element={<PluginMarketplacePage />} />` — the same page now
  serves both, using the global search when not deep-linked with `?server=`.
- Sidebar (`components/layout/Sidebar.tsx`): **Marketplace entry added (K5, 2026-08-06)** — now
  Dashboard / Servers / Backups / Plugins / **Marketplace** / Settings, with a `store` glyph from
  `components/ui/Icon.tsx`.

**Net frontend gap (K5): ✅ CLOSED (2026-08-06).** The marketplace is now a first-class section:
its own sidebar entry and top-level `/marketplace` route, a global search endpoint
(`GET /api/v1/marketplace/search`) separate from the server-scoped one, and a reworked install
flow that lets the user pick a server at install time (pre-selecting by deep link → last-used
server → first compatible → any server). Server-scoped `/plugins/marketplace` remains for
installing within a specific server's context.

---

## 5. Known items

| ID | Item | Notes |
|----|------|-------|
| K16 | Multi-provider plugin catalog selection | `ONX_PLUGIN_PROVIDERS` currently validates a single plugin catalog provider (`modrinth`); CurseForge modpack installs are supported separately via `curseforge_adapter.py`. |
