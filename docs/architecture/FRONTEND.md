# Frontend Architecture

## Tech Stack

| Layer | Choice |
|---|---|
| Framework | React 19 |
| Language | TypeScript 5 (strict mode) |
| Build tool | Vite 5 |
| Styling | TailwindCSS 4 (via `@tailwindcss/vite` plugin) |
| Server state | TanStack Query 5 |
| Global state | Zustand 5 |
| Routing | React Router v7 |
| Forms | Native React controlled components |
| Charts | Custom components (Sparkline, ServerMetricsCharts) — no chart library |
| Testing | Vitest + jsdom + @testing-library/react |

UI primitives are raw Tailwind components — shadcn/ui is not used (intentional decision to avoid dependency overhead). See `frontend/package.json` for exact versions.

## Project Structure

```
frontend/src/
├── App.tsx                      # Router + providers + WS manager
├── main.tsx                     # Entry point
├── index.css                    # Tailwind imports
├── test-setup.ts                # Vitest setup (jsdom, mocks)
├── components/
│   ├── layout/
│   │   ├── Sidebar.tsx          # Navigation drawer
│   │   └── TopNav.tsx           # Top bar (theme toggle, auth)
│   ├── guards/
│   │   ├── AuthGuard.tsx          # Route protection → /login
│   │   └── SystemStatusGuard.tsx  # Redirects uninitialized instances → /setup, blocks guest routes
│   ├── EmptyState.tsx           # Empty state placeholder
│   ├── ErrorBoundary.tsx        # Error boundary with retry
│   ├── Skeleton.tsx             # Loading skeletons + table skeleton
│   └── WebSocketManager.tsx     # WS lifecycle + cache bridge
├── server_manager/
│   ├── types.ts                 # Server-specific types
│   ├── hooks/                   # Server-specific hooks
│   ├── components/              # Server-specific components
│   └── pages/                   # Feature pages
│       ├── DashboardPage.tsx
│       ├── ServersPage.tsx
│       ├── CreateServerPage.tsx
│       ├── ImportServerPage.tsx
│       ├── ServerDetailPage.tsx
│       ├── ServerFilesPage.tsx
│       ├── ServerModsPage.tsx
│       ├── BackupListPage.tsx
│       ├── PluginListPage.tsx
│       ├── PluginMarketplacePage.tsx   # Modrinth marketplace (2026-08-04)
│       ├── PluginDetailPage.tsx
│       ├── SettingsPage.tsx
│       └── ApiKeysPage.tsx
├── pages/
│   ├── LoginPage.tsx
│   ├── RegisterPage.tsx
│   ├── SetupPage.tsx             # First-run Owner bootstrap wizard
│   └── InvitePage.tsx            # Token-based registration (/invite/:token)
├── stores/
│   ├── authStore.ts             # JWT + refresh token persistence
│   ├── uiStore.ts               # Theme + sidebar state
│   └── wsStore.ts               # WebSocket connection state
├── hooks/
│   └── useWebSocket.ts          # WS client + handler lifecycle
├── services/
│   ├── api.ts                   # Typed fetch API client (35+ endpoints)
│   └── queryClient.ts           # TanStack Query client + query keys
├── websocket/
│   ├── types.ts                 # Message protocol types + enums
│   ├── client.ts                # WS connection with auto-reconnect
│   ├── handler.ts               # Message routing + cache updates
│   └── channels.ts              # Channel subscription manager
└── types/
    └── index.ts                 # Shared API response types
```

## State Management

Three layers, each with a distinct responsibility:

### TanStack Query — Server Data

All server-mutated data flows through TanStack Query. Query keys are defined centrally in `frontend/src/services/queryClient.ts:13`:

```typescript
queryKeys = {
  servers: { all: ["servers"], list: () => ["servers", "list"], detail: (id) => ["servers", "detail", id] },
  backups: { all: ["backups"], list: (serverId?) => ["backups", "list", serverId] },
  plugins: { all: ["plugins"], list: (serverId) => ["plugins", "list", serverId] },
  auth:    { me: ["auth", "me"], apiKeys: ["auth", "api-keys"] },
  users:   { all: ["users"], list: () => ["users", "list"], detail: (id) => ["users", "detail", id] },
  monitoring: { metrics: (serverId?) => ["monitoring", "metrics", serverId] },
  console: { history: (serverId) => ["console", "history", serverId] },
  settings: { all: ["settings"] },
}
```

Default options: `staleTime: 10s`, `retry: 1`, `refetchOnWindowFocus: false`.

### Zustand — Client-Only State

Three stores, all accessed via selector functions for optimal re-render:

- **`authStore`** (`frontend/src/stores/authStore.ts`) — Access token, refresh token, `isAuthenticated`. Persisted to `localStorage` under `mcs_auth`. Auto-detects expiry on load. Provides `login`, `logout`, `setTokens`, and `getAccessToken`.
- **`uiStore`** (`frontend/src/stores/uiStore.ts`) — Theme (`light`/`dark`, persisted to `localStorage` under `mcs_theme`, respects `prefers-color-scheme`), sidebar open/close state.
- **`wsStore`** (`frontend/src/stores/wsStore.ts`) — WebSocket `connectionState` and `connected` boolean.

### Forms

All forms use native React controlled components through TanStack Query mutations.

## Key Pages & Routes

| Route | Page Component | Description |
|---|---|---|
| `/setup` | `SetupPage` | First-run Owner bootstrap wizard (shown while the instance is uninitialized) |
| `/login` | `LoginPage` | Email/password + "Remember me" → redirect to `/` |
| `/register` | `RegisterPage` | User registration (direct open registration in `LOCAL` mode) |
| `/invite/:token` | `InvitePage` | Invitation-token registration (required in `GLOBAL` mode) |
| `/` (index) | `DashboardPage` | Overview cards (total/online/offline), recent servers, alerts |
| `/servers` | `ServersPage` | Server list table, inline create, start/stop/delete |
| `/servers/create` | `CreateServerPage` | Server creation form |
| `/servers/import` | `ImportServerPage` | Import existing server from filesystem |
| `/servers/:serverId` | `ServerShell` → `ServerDetailPage` | Console, metrics, actions, config editor |
| `/servers/:serverId/files` | `ServerFilesPage` | File browser (list/content/edit/delete/upload/mkdir) |
| `/servers/:serverId/mods` | `ServerModsPage` | Mod management |
| `/backups` | `BackupListPage` | Backup table, create/restore/schedule |
| `/plugins` | `PluginListPage` | Plugin table, install/enable/disable; Install → marketplace |
| `/plugins/marketplace` | `PluginMarketplacePage` | Modrinth catalog: search, versions, install (reached with `?server=<id>`) |
| `/marketplace` | `PluginMarketplacePage` | Alias for `/plugins/marketplace` (added for K5); renders the same catalog |
| `/settings` | `SettingsPage` | Global application settings; hosts `AccessSection` (access-mode control) and `InvitationsSection` (invite management) |
| `/settings/api-keys` | `ApiKeysPage` | API key management |

Guest routes (`/setup`, `/login`, `/register`, `/invite/:token`) are wrapped in
`SystemStatusGuard` (`frontend/src/components/guards/SystemStatusGuard.tsx`),
which consults `GET /api/v1/setup/status` and:
- shows `SetupPage` while the instance is **uninitialized**;
- directs invitations to `InvitePage` when the token is valid;
- otherwise lets users proceed to login/register.

All authenticated routes are wrapped in `AuthGuard` (`frontend/src/components/guards/AuthGuard.tsx`) which redirects to `/login` if `isAuthenticated` is false. Each page is wrapped in `ErrorBoundary` for isolated error handling.

### Route-by-Route State Matrix

| Route | Loading | Error | Empty | Stale/Refetch | Notes |
|---|---|---|---|---|---|
| `/login` | N/A — inline "Signing in..." button state | Inline red div (form submit) | N/A — static form | N/A | Inline error is an in-form submit error, not a full-page fetch error — intentional, not ErrorState |
| `/register` | N/A — inline "Creating account..." button | Inline red div (form submit) | N/A — static form | N/A | Same intentional in-form pattern as `/login` |
| `/` (index) | `Skeleton` header + dashboard cards | `ErrorState` | `EmptyState` (no servers) | Polls/refetches on navigation | Recent Activity section uses `EmptyState` when no events |
| `/servers` | `TableSkeleton` (inside body, after PageHeader) | `ErrorState` | `EmptyState` (no servers yet) | TanStack Query refetch | PageHeader rendered unconditionally (reference pattern) |
| `/servers/create` | Inline "Loading versions..." text for version step | `ErrorState` (failed to load versions) | "No versions available." inline text | N/A — wizard state | Multi-step wizard; loading/empty for versions step use inline text, not skeletons |
| `/servers/import` | Inline "Scanning..."/"Importing..." button text | Inline red div (scan/import submit) | N/A — static form | N/A | Console-style form; inline errors only, no ErrorState/EmptyState |
| `/servers/:serverId` | `Skeleton` header + detail cards | `ErrorState` (non-404) | Inline "Server not found" block (404) | Refetch on tab switch | 404 distinguishes a missing record from a backend failure; no EmptyState used |
| `/backups` | `TableSkeleton` (after PageHeader) | `ErrorState` | `EmptyState` (no backups) | TanStack Query refetch | Filter that matches nothing also falls back to `EmptyState` |
| `/plugins` | `TableSkeleton` (after server selected) | `ErrorState` | Two `EmptyState` variants: no server selected / no plugins installed | Refetch on server change | Server-gated; empty before a server is chosen |
| `/plugins/marketplace` | `TableSkeleton` (search + versions) | `ErrorState` (search / versions) | Multiple `EmptyState` (search prompt, zero results, no versions, no servers) | Manual search submit | Multi-stage catalog (search → versions → target server) |
| `/marketplace` | Same as `/plugins/marketplace` | Same as `/plugins/marketplace` | Same as `/plugins/marketplace` | Same as `/plugins/marketplace` | K5 alias; identical component and behavior |
| `/settings` | `Skeleton` header + cards | `ErrorState` | `ErrorState` for `!settings` (post-fix `9c4e934`) | TanStack Query refetch | Missing/null payload now renders `ErrorState` — no legitimate empty state for a singleton config |
| `/settings/api-keys` | `TableSkeleton` (inside body, after PageHeader) | `ErrorState` | `EmptyState` (no API keys) | TanStack Query refetch | PageHeader kept visible during loading (post-fix `564fc0a`) |

The table above covers the primary fetch-driven routes. Guest routes
(`/setup`, `/invite/:token`) and auth flows (`/login`, `/register`) use
inline submit forms rather than the shared primitives, as do the
wizard/console-style flows (`/servers/create`, `/servers/import`). The
routes covered above that use the shared `ErrorState`/`EmptyState`/
`TableSkeleton`/`Skeleton` primitives for their fetch-driven states are
`/`, `/servers`, `/servers/:serverId`, `/backups`, `/plugins`,
`/plugins/marketplace`, `/marketplace`, `/settings`, `/settings/api-keys`.
This split informs workstream 2 (shared primitives) but is recorded here as
an observation only, not a backlog item.

### UI Conventions

- **Loading**: Skeleton screens (`Skeleton.tsx`, `TableSkeleton`) — no spinners
- **Empty**: Helpful message + suggested action (`EmptyState.tsx`)
- **Error**: Error message + retry button (`ErrorBoundary.tsx`)
- **Mutations**: Toast on success/failure (via TanStack Query callbacks)
- **Destructive actions**: Confirmation dialog before execution
- **Responsive**: Sidebar collapses on mobile (`ml-56` ↔ `ml-0`)
- **Theme**: Dark/light toggle persisted in localStorage, respects system preference

## WebSocket Integration

> The frontend WebSocket client and the backend delivery pipeline are both
> **functional**. Backend gaps K1 (per-channel authorization) and K2 (event
> dispatch / real-time metrics push) were closed in Phase 3 (commits
> `b98da77`, `d096f75`, `db1889d`). The client connects, subscribes to active
> channels, and receives server-push data (state updates, domain events, and
> batched real-time metrics).

### Architecture

```
useWebSocket() hook
    └─ WSClient (connection, reconnect, ping, message queue)
         └─ WSHandler (message routing, state sync, cache bridge)
              └─ WebSocketManager (TanStack Query bridge)

Connection lifecycle: connect on login → subscribe to channels → disconnect on logout
```

### Client (`frontend/src/websocket/client.ts`)

- Connects via `wss://<host>/ws?token=<jwt>` with the access token as query parameter
- Auto-reconnect with exponential backoff: base 1s, max 30s, max 10 retries
- 30-second ping interval for keepalive
- `auth_expired` server message triggers immediate disconnect
- Message queue flushes on reconnect
- Channel subscriptions automatically re-sent on reconnect
- Binary type set to `arraybuffer` for binary frame support

### Message Protocol

**Server → Client:**

| Type | Purpose |
|---|---|
| `state_sync` | Full state replay on reconnect |
| `state` | Server state change (start/stop/restart) |
| `metrics` | Single metric sample (tps, players, ram_mb) |
| `metrics_batch` | Multiple metric samples for chart fill |
| `event` | Domain event (server created/deleted, backup progress, etc.) |
| `auth_expired` | Token expired, client must re-authenticate |
| `error` | Server-side error notification |
| `pong` | Keepalive response |

**Client → Server:**

| Type | Purpose |
|---|---|
| `subscribe` | Subscribe to channel(s) |
| `unsubscribe` | Unsubscribe from channel(s) |
| `refresh_token` | Update auth token mid-connection |
| `ping` | Keepalive |

### Cache Bridge

`WebSocketManager` (`frontend/src/components/WebSocketManager.tsx`) maps WS cache update keys to TanStack Query keys:

```typescript
"servers:list"      → ["servers", "list"]
"server:{id}"       → ["servers", "detail", id]
"backups:list"      → ["backups", "list"]
"plugins:list"      → ["plugins", "list"]
"metrics:{id}"      → ["monitoring", "metrics", id]
"metrics_batch:{id}" → ["monitoring", "metrics", id]
```

Invalidation events are derived from domain event types: `ServerCreated`/`ServerDeleted` invalidates the server list; `ServerStarted`/`ServerStopped` invalidates the specific server detail; `Backup*` events invalidate backups; `Plugin*` events invalidate plugins.

### Channel Manager (`frontend/src/websocket/channels.ts`)

- Valid prefix list (`VALID_CHANNEL_PREFIXES`): `server`, `backup`, `plugin`, `monitoring`, `metrics`, `auth`, `user` (matches the backend `validate_channel` set — no `health` prefix exists)
- Max 50 simultaneous channels
- Channel format: `<prefix>:<id>` or `<prefix>:*` for wildcard
- Wildcard, server, backup, plugin, and monitoring helpers for type checking (`isMonitoringChannel` covers both `monitoring:` and `metrics:`)

## API Client

`frontend/src/services/api.ts` — `createApiClient` returns a typed fetch wrapper with:

- Automatic Bearer token injection from `authStore`
- Auto-refresh on 401 responses (deduplicated via `refreshing` promise guard)
- Structured error handling: `ApiError` with status, code, message, detail
- Covers 35+ endpoints across auth, servers, backups, plugins, monitoring, users, settings, software catalog, and schedules

### Metrics snapshot ordering contract

`GET /api/v1/monitoring/metrics?server_id=...` (`getMetrics`) returns points in
**newest-first** order — the backend query orders by `recorded_at DESC`
(`backend/app/modules/monitoring/infrastructure/repository.py:get_series`).

Consumers MUST NOT assume a fixed index (e.g. `[length - 1]`). The "current"
value shown in the metric cards is derived in
`ServerMetricsCharts.tsx` by selecting the point with the greatest `timestamp`
via `reduce`, which is robust to either ordering. A past bug read
`metrics[metrics.length - 1]` and displayed the *oldest* point in the window
(all-zero defaults) instead of the newest live values.

Regression coverage: `frontend/src/server_manager/components/ServerMetricsCharts.test.tsx`.

## Build Commands

```bash
npm run dev          # Vite dev server (port 5173, proxies /api and /ws to :8000)
npm run build        # tsc && vite build
npm run preview      # Vite preview server
npm run test         # Vitest run
npm run test:watch   # Vitest watch mode
npm run lint         # ESLint on src/
npm run typecheck    # tsc --noEmit
```

### Vite Proxy Configuration

In development, the Vite config proxies the following to `localhost:8000`:
- `/api` → HTTP
- `/ws` → WebSocket
- `/health`, `/docs`, `/openapi.json` → HTTP

Production builds use `window.location.host` for API and WS URLs.

## Testing

406 frontend tests across 56 files (measured 2026-08-13). Test infrastructure:
- `vitest.config.ts` — jsdom environment, `@/` path alias, globals enabled
- `test-setup.ts` — jsdom, localStorage mock, matchMedia mock
- Testing libraries: `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`

`npm run typecheck` (`tsc --noEmit`) is clean; `npm run lint` (`eslint src/`) is
clean (0 errors / 0 warnings, resolved 2026-08-13).

### CI

Frontend CI (`.github/workflows/frontend-ci.yml`) runs on every push/PR to
`master` and gates on: `npm run typecheck`, `npm run lint`, `npm test`
(406 / 56 files), and `npm run build`.

Key test areas: `authStore` (9), `uiStore` (9), `api.ts` (11), `wsStore` (4), `AuthGuard` (2), `LoginPage` (5), `Sidebar` (4), `TopNav` (4), `AppLayout` (2), `WebSocketManager` (3), `ServersPage` (8), `DashboardPage` (7).

### Version display source

The application version shown in `SettingsPage` (`{settings.app_name ?? "MCS Manager"} {settings.version}`)
is read from `GET /api/v1/settings` (`version` field), which the backend
resolves via `backend/app/core/version.py:get_app_version()` from
`backend/pyproject.toml`. `frontend/package.json` `version` is **build metadata
only** — it is not the displayed product version (see `docs/VERSIONING.md`).

## Cross-References

- [Architecture](../architecture/ARCHITECTURE.md) — system context, backend module map
- [API docs](../API.md) — REST endpoints and WebSocket protocol reference
- [Development guide](../DEVELOPMENT.md) — full setup instructions
