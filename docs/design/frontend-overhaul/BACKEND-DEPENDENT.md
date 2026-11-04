# Frontend Overhaul: Backend-Dependent Gaps

This document tracks UI features that require backend API enhancements before they can be fully realized in the frontend. Per D1 and project non-negotiables, no backend changes are made during this overhaul; the frontend renders only what the API currently returns.

---

## 1. Fleet Server List Live Telemetry & Vitals
- **Endpoint**: `GET /api/v1/servers` (`backend/app/api/v1/routers/servers.py`)
- **Current Response**: Returns `ServerResponse` (`backend/app/api/v1/schemas/server.py`), which includes `id`, `name`, `status`, `port`, `loader`, `version`, `max_players`, but omits:
  - `address` (only `port` is provided; host/address must be inferred or resolved)
  - `live_players` (active player count; only `max_players` configuration limit is present)
  - `cpu_percent` / `cpu_usage`
  - `memory_bytes` / `memory_usage`
- **WebSocket Broadcast**: Fleet WebSocket topic (`server:*`) transmits lifecycle and provisioning events, but zero live telemetry metrics. Telemetry streams strictly on `metrics:{serverId}`.
- **Frontend Mitigation**: Per D2, the fleet table displays strictly `status`, `name`, `software/version`, `port`, and `actions`. CPU, RAM, and live player columns are omitted rather than faked with placeholders or zeros.

---

## 2. Server Files API: Server-Side Pagination & Search
- **Endpoint**: `GET /api/v1/servers/{server_id}/files` (`backend/app/api/v1/routers/files.py`)
- **Current Parameters**: Accepts only `server_id: str` and `path: str = ""` query parameter.
- **Missing Parameters**:
  - `page` / `offset` / `skip`
  - `limit` / `page_size`
  - `search` / `filter` query
  - `recursive` directory size computation
- **Frontend Mitigation**:
  - The frontend performs client-side directory filtering/search over the current directory listing.
  - Client-side pagination/virtualization is applied to ensure smooth rendering of directories containing hundreds of files.
  - Full server-side recursive search and paginated streaming remain deferred to a dedicated backend task.

---

## 3. Operations Drawer Event Feeds
- **Component**: `OperationDrawer.tsx`
- **Current Backend Support**: Operations endpoints exist for async long-running tasks (`/api/v1/operations`), but not all background server tasks consistently register operation IDs.
- **Frontend Mitigation**: Mounted globally in AppShell behind the TopBar trigger, bound to `useOperationStore`. When operations exist, they are displayed; empty state informs the user when no background tasks are in progress.
