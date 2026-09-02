# Feature Ideas — Deferred / Parking-Lot Document

**Status:** Not started — backlog / parking-lot document.
**Purpose:** Captures feature ideas Mohamed has raised and decisions explicitly
deferred to a later roadmap phase. This is **not** a spec and nothing here is
committed work.
**Last updated:** 2026-08-04

---

## 1. Reveal server / backup directory in the OS file manager

**Requested:** 2026-08-03

A direct link/button in the server and backup UI sections to open that server's
or backup's directory in the OS file manager — e.g. from the server detail page
or the backups list. Mohamed confirmed this is useful for his own testing
workflow (quick access to world files, logs, backups on disk).

**Why deferred (not implemented now):**

- This is **new feature work**, and the project is currently in **Phase 1
  (Plugins / Marketplace separation)** per `docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md`, which
  gates new capability behind its exit criteria.
- It also carries real security surface: opening a filesystem path from a web UI
  typically means the backend either shells out to something like
  `xdg-open` / `explorer`, or returns a path for a client-side file-manager
  integration. Either way, if the path isn't strictly validated against the real
  server/backup `root_path`, it becomes a path-traversal or command-injection
  vector (user-controllable path segments, traversal, or unsanitized input
  reaching a shell command).

**Security constraints any future implementation MUST satisfy:**

1. **Strict server-side path resolution** against the DB's `root_path` field
   only — no client-supplied path fragments may be accepted or resolved.
2. **No shell string interpolation.** If a command must be spawned (e.g.
   `xdg-open` / `explorer`), invoke it with a fixed argv and pass the resolved
   absolute path as a single, non-interpolated argument.
3. **Read-only "reveal in file manager" action**, scoped to a single
   already-authorized `resource_id` (server id / backup id) rather than an
   arbitrary path parameter.

**Suggested target phase:** **Phase 4 (Frontend Redesign & Parity)** — the
roadmap phase for UI/UX feature work.

---

## 2. Plugin marketplace — browse / search / install plugins from Modrinth

**Requested:** 2026-08-04

> ✅ **IMPLEMENTED (2026-08-04).** This feature is now delivered and marked
> **IMPLEMENTED** in `docs/README.md`. Implementation summary:
>
> - Backend: `GET /api/v1/servers/{server_id}/plugins/marketplace/search`, `GET /api/v1/servers/{server_id}/plugins/marketplace/projects/{project_id}/versions`, `POST /api/v1/servers/{server_id}/plugins/marketplace/install` — Modrinth provider (`app/modules/plugin/infrastructure/providers/modrinth.py`), version selection ranking (`select_best_version`), install flow downloading the `.jar` into the server's `plugins/` directory.
> - Filesystem reconciliation: the filesystem is the source of truth — on-disk `.jar` files are reconciled into the DB on every list (`source="detected"`), rows whose file was removed directly from disk are pruned, deletion is deferred via `pending_deletion`.
> - Frontend: `PluginMarketplacePage` at route `/plugins/marketplace` (search, version picker, install) — **no sidebar entry yet** (known gap K5).
> - Docs: full detail in `docs/architecture/plugins-and-marketplace.md`.
>
> The investigation findings below remain accurate reference material.

Browsing, searching, and installing server plugins directly from ONX Manager,
sourcing them from the Modrinth catalog (`api.modrinth.com`) and potentially
other providers later.

**Why deferred (originally):**

- This is **new feature work**, and the project is currently in **Phase 1
  (Plugins / Marketplace separation)** per `docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md`, which
  gates new capability behind its exit criteria.
- The investigation confirmed the feature is feasible with minimal new
  foundations — nothing about it depends on a Phase 1 decision, so it was
  gated purely by roadmap sequencing, not by design risk.

**Key findings from the investigation (2026-08-04):**

- **HTTP client:** `aiohttp` is already a runtime dependency (`pyproject.toml`,
  `requirements.txt`) — no new HTTP library is needed.
- **Download pattern to follow:** `app/modules/server/application/services/jar_service.py`
  already implements download + typed timeouts + retry with exponential backoff
  + atomic write (`write_binary_atomic`) for server jars — a close template for
  downloading a `.jar` into a server's `plugins/` folder.
- **Provider-abstraction convention:** `app/modules/storage/base.py`'s abstract
  `StorageBackend` ABC (with `LocalStorageBackend` / `S3StorageBackend` behind a
  factory) is the established pattern for interchangeable backends — a future
  `ModrinthProvider` should follow it, and the same ABC + factory pattern should
  be preferred over building a multi-provider abstraction upfront.
- **Modrinth API reachable:** `api.modrinth.com` returned HTTP 200; no API key
  required for search/browse; rate limit 300 requests/window
  (`x-ratelimit-limit` header).
- **API quirk to design around:** plugin search hits report
  `project_type: "mod"` even for actual plugins — filtering/display must rely on
  `all_project_types` or category facets (bukkit/paper/spigot), not the
  top-level `project_type` field.
- **Current plugin system is DB-metadata only:** the `plugins` table is empty;
  `InstallPluginCommand` only writes a DB row (no real `.jar` placement); the
  frontend Install button is a stub ("Install coming soon").

> ⚠️ **Note (2026-08-04):** the two findings above predate the marketplace
> implementation and are now **stale**. The plugin system was extended so the
> filesystem is the source of truth for plugin existence (on-disk `.jar` files
> reconciled into the DB on every list, `source="detected"`), and marketplace
> installs place real `.jar` files with **download-integrity verification**
> against Modrinth's sha1/sha512 hashes (`_verify_checksum`, raising
> `CorruptedDownloadError` on mismatch).

**Gaps to close before implementing:**

1. **Shared outbound HTTP client** — no centralized session/timeout/retry policy
   exists for app-level outbound calls; `jar_service.py`'s pattern is per-call,
   not pooled.
2. **Download-integrity verification** — no sha1/sha512 verification exists
   anywhere yet, even though Modrinth provides both hashes per version file.

> ✅ **Note (2026-08-04):** both gaps are now **resolved** in the marketplace
> implementation. The shared HTTP client is `get_http_client()` in
> `backend/app/core/http_client.py`; download-integrity verification is
> `_verify_checksum` in `backend/app/modules/plugin/infrastructure/providers/modrinth.py`.
> See `docs/architecture/plugins-and-marketplace.md`.

**Suggested implementation start:** single provider (Modrinth only), matching
the existing `StorageBackend`-style ABC + factory pattern, rather than a
multi-provider abstraction built upfront.

**Suggested target phase:** ✅ **Implemented as of 2026-08-04** (see
`docs/architecture/plugins-and-marketplace.md`); originally targeted the roadmap's
plugin-system phase.
