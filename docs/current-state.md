# Current System State (`onx-manager` v0.1.0)

Updated: 2026-11-26 (Release **`v0.1.0`**, Alembic head **`b1e2100000034`**, **`217`** live HTTP routes)

## Database & Migrations

- **Head Revision:** `b1e2100000034` (`b1e2100000034_branch_exposure_and_pending_settings.py`, 54 total revisions)
- **Previous Head:** `b1e2100000033`
- **`RELEASE_MINIMUM_DB_REVISION` / `EXPECTED_ALEMBIC_HEAD`:** `b1e2100000034` (`backend/app/core/persistence/db_revision.py`)
- **Latest Schema Highlights (`b1e2100000034`):**
  - `server_exposure`: adds `branch_name` (default `"main"`), `cloudflare_mode`, `subdomain_prefix`, `base_domain`, `srv_record_enabled`, and `ephemeral`; replaces the unique `server_id` index with composite unique constraint `uq_server_exposure_server_branch`.
  - `server_branches`: adds `pending_merge_on_restart`, `pending_merge_status`, and `pending_merge_error`.

## Network Exposure & Tunneling

- **Startup Bind Resolution (`launcher.py`, `backend/app/core/settings_store.py`):** Loads host/port precedence (`CLI/env override > config/settings.yaml > 127.0.0.1:8000`) so `BIND_MISMATCH` clears after restart on `0.0.0.0` while Cloudflare and `playit.gg` remain loopback-bound.
- **UPnP IGD & CGNAT Detection (`backend/app/modules/exposure/infrastructure/upnp.py`):** Queries `GetExternalIPAddress`, rejects RFC1918/RFC6598/loopback/link-local addresses with `CGNAT_DETECTED`, validates port range `1..65535`, and cleans up port mappings on teardown.
- **Cloudflare Panel & Branch Tunnels (`cloudflared.py`, `commands.py`):** Injects permanent tunnel tokens exclusively via `TUNNEL_TOKEN` environment variable (never CLI argv or `GET` responses), supports zero-config ephemeral `*.trycloudflare.com` previews, and terminates child processes cleanly.
- **Live Reachability Probe (`?probe=true`):** Performs an SSRF-protected live Minecraft Server List Ping (SLP) probe with DNS resolution checks blocking loopback, private, link-local, and cloud-metadata IP ranges.

## Multi-Tab Branch Isolation & Lifecycle (Advanced Mode)

- **Shared Branch Context (`frontend/src/layouts/ServerShell.tsx`, `ServerBranchContext.tsx`, `Sidebar.tsx`):** Persists per-server active branch, preserves `?branch=` across server tabs, and scopes header status badges and Start/Stop/Restart actions to the active branch container when `branch != "main"`.
- **Persistent-Stop / Explicit-Destroy Branch Containers:** Stopping a branch runtime halts the Docker container, tears down branch exposure, and unlocks the worktree while retaining its export directory and port allocation for log inspection and fast resume. Destroying removes the container, wipes the export tree, and frees ports.
- **Branch-Aware Console, Plugins, Settings & Exposure:**
  - **Console:** `GET /console?branch=` and `POST /command?branch=` isolate logs and RCON execution per branch.
  - **Plugins & Mods:** Working branches manage branch-scoped addon lockfiles with uncommitted-change indicators while protecting `main` from direct mutation.
  - **Settings:** Separates branch-scoped properties/runtime from server-wide settings; `main` edits queue onto `settings/...` branches and auto-merge on next server restart (`DELETE /settings/pending` to discard).
  - **Exposure:** Per-branch `(server_id, branch_name)` exposure targeting each branch container's host port set, with automatic teardown on branch stop/destroy/delete.
  - **Change History & Files:** Branch mutations record branch-attributed events in `server_activity_logs`; non-`main` live runtime state files are clearly marked `main`-owned and read-only.
- **Simple Mode Invariant:** Simple Mode remains completely Git-free (`/versioning/*` returns HTTP 409).

## Core Safety Invariants

- **Route/Permission Contract:** `217` live FastAPI routes matched 1:1 against `contracts/permissions.yaml`.
- **Path & File Safety:** `backend/app/core/allowlist.py` enforces canonical relative paths (`validate_canonical_relpath`), symlink-safe file descriptor opens (`open_safe_path_fd`), and root containment (`resolve_safe_disk_path`).
