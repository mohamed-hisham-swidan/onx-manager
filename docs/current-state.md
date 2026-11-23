# Current System State (`onx-manager`)

Updated: 2026-11-23 (SPEC **v8.8**, Alembic head **`b1e2100000034`**)

## Database & Migrations
- **Head Revision:** `b1e2100000034` (`b1e2100000034_branch_exposure_and_pending_settings.py`)
- **Previous Head:** `a9d8100000033`
- **`RELEASE_MINIMUM_DB_REVISION` / `EXPECTED_ALEMBIC_HEAD`:** `b1e2100000034` (`backend/app/core/persistence/db_revision.py`)
- **Schema Highlights (`b1e2100000034`):**
  - `server_exposure`: adds `branch_name` (default `"main"`), `cloudflare_mode`, `subdomain_prefix`, `base_domain`, `srv_record_enabled`, `ephemeral`; replaces unique `server_id` index with composite unique constraint `uq_server_exposure_server_branch`.
  - `server_branches`: adds `pending_merge_on_restart`, `pending_merge_status`, `pending_merge_error`.

## Track A — Network Exposure & Tunneling Architecture
- **Startup Bind Resolution (`launcher.py`, `backend/app/core/settings_store.py`):** Loads host/port cleanly (`CLI/env override > config/settings.yaml > 127.0.0.1:8000`) so `BIND_MISMATCH` clears after restart on `0.0.0.0` while Cloudflare and `playit.gg` continue operating strictly bound to `127.0.0.1`.
- **UPnP IGD & CGNAT Detection (`backend/app/modules/exposure/infrastructure/upnp.py`):** Queries `GetExternalIPAddress`, validates returned IP against RFC1918, RFC6598 (`100.64.0.0/10`), loopback, and link-local ranges, refuses false-positive active status with `CGNAT_DETECTED`, enforces strict `int` port validation (`1..65535`), and performs clean `DeletePortMapping` teardown.
- **Cloudflare Panel & Branch Tunnels (`cloudflared.py`, `commands.py`):** Injects permanent Tunnel Tokens exclusively via `TUNNEL_TOKEN` environment variable (never CLI argv, never returned on `GET`), supports zero-config `quick` ephemeral `*.trycloudflare.com` previews, checks binary presence, and terminates child processes gracefully without orphans.

## Track B — Multi-Tab Branch Isolation & Lifecycle (`ServerMode.ADVANCED`)
- **Shared Branch Context (`frontend/src/layouts/ServerShell.tsx`, `ServerBranchContext.tsx`, `Sidebar.tsx`):** Persists per-server active branch, synchronizes `?branch=` across all 7 navigation tabs, and scopes top-header status badges and Start/Stop/Restart power actions strictly to the active branch container when `branch != "main"`.
- **Persistent-Stop / Explicit-Destroy Branch Containers:** `stop_branch_runtime` stops the Docker container (`status="stopped"`), tears down branch exposure, and unlocks the worktree while retaining `.onx/branch-exports/<runtime_id>` and `port_set_json` for log inspection and fast resume. `POST /api/v1/servers/{server_id}/versioning/branches/{name}/destroy` destroys the container, wipes the export directory, and releases ports.
- **Branch-Aware Console, Plugins, Settings & Exposure:**
  - **Console:** `GET /console?branch=` & `POST /command?branch=` isolate logs and RCON execution per branch; unprovisioned branches offer Data Template selection and **Create & Start Branch Container**.
  - **Plugins/Mods:** `?branch=` manages `ArtifactCas` + worktree `onx-jars.lock.json` on working branches with `is_committed` status while protecting `main` from direct mutation.
  - **Settings:** Separates branch-scoped properties/runtime (`config/onx-runtime.json`, `server.properties`) from server-wide settings; `main` edits queue onto `settings/...` branches and auto-merge cleanly on next server restart (`DELETE /settings/pending` to discard).
  - **Exposure:** Per-branch `(server_id, branch_name)` exposure targeting each branch container's Host Port Set (`game_port`), with automatic teardown on branch stop/destroy/delete.
  - **Activity & Files:** All branch mutations record branch-attributed events (`branch_name`) in `server_activity_logs`; non-`main` `Live State (Class C)` view in Files is clearly marked `main`-owned and read-only.
- **Simple Mode Invariant:** `ServerMode.SIMPLE` remains completely Git-free (`/versioning/*` returns HTTP 409) and uses host-only `onx-jars.lock.json`.

## Core Safety Invariants
- **Allow-list v2.3 Freeze:** `backend/app/core/allowlist.py` preserved unmodified (`sha256: 6b0cf099c779064150f67323fe6b400cd5b3894ad29fefe7e1114136a1541e4c`).
- **Path Safety:** All worktree, export, and staging reads/writes enforce `validate_canonical_relpath()`, `open_safe_path_fd()`, and `resolve_safe_disk_path()`.
