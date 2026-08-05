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
│   │   └── AuthGuard.tsx        # Route protection → /login
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
│       ├── BackupListPage.tsx
│       ├── PluginListPage.tsx
│       ├── PluginMarketplacePage.tsx   # Modrinth marketplace (2026-08-04)
│       ├── SettingsPage.tsx
│       └── ApiKeysPage.tsx
├── pages/
│   ├── LoginPage.tsx
│   └── RegisterPage.tsx
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
| `/login` | `LoginPage` | Email/password + "Remember me" → redirect to `/` |
| `/register` | `RegisterPage` | User registration |
| `/` (index) | `DashboardPage` | Overview cards (total/online/offline), recent servers, alerts |
| `/servers` | `ServersPage` | Server list table, inline create, start/stop/delete |
| `/servers/create` | `CreateServerPage` | Server creation form |
| `/servers/import` | `ImportServerPage` | Import existing server from filesystem |
| `/servers/:serverId` | `ServerDetailPage` | Console, metrics, actions, config editor |
| `/backups` | `BackupListPage` | Backup table, create/restore/schedule |
| `/plugins` | `PluginListPage` | Plugin table, install/enable/disable; Install → marketplace |
| `/plugins/marketplace` | `PluginMarketplacePage` | Modrinth catalog: search, versions, install (reached with `?server=<id>`) |
| `/settings` | `SettingsPage` | Global application settings |
| `/settings/api-keys` | `ApiKeysPage` | API key management |

All authenticated routes are wrapped in `AuthGuard` (`frontend/src/components/guards/AuthGuard.tsx`) which redirects to `/login` if `isAuthenticated` is false. Each page is wrapped in `ErrorBoundary` for isolated error handling.

### UI Conventions

- **Loading**: Skeleton screens (`Skeleton.tsx`, `TableSkeleton`) — no spinners
- **Empty**: Helpful message + suggested action (`EmptyState.tsx`)
- **Error**: Error message + retry button (`ErrorBoundary.tsx`)
- **Mutations**: Toast on success/failure (via TanStack Query callbacks)
- **Destructive actions**: Confirmation dialog before execution
- **Responsive**: Sidebar collapses on mobile (`ml-56` ↔ `ml-0`)
- **Theme**: Dark/light toggle persisted in localStorage, respects system preference

## WebSocket Integration

> ⚠️ **Backend status note:** the frontend WebSocket client is fully
> implemented, but the backend currently rejects every channel subscription
> (plural/singular permission mismatch) and never dispatches events
> (`EventDispatcher` not wired). The client connects, pings, and keepalives,
> but will not receive server-push data until backend gaps K1/K2 are closed
> (see `docs/mcs-manager-roadmap-v2.md` Phase 3 §5.1).

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

- Valid prefix list: `server`, `backup`, `plugin`, `monitoring`, `metrics`, `health`, `auth`, `user`
- Max 50 simultaneous channels
- Channel format: `<prefix>:<id>` or `<prefix>:*` for wildcard
- Wildcard, server, backup, plugin, and monitoring helpers for type checking

## API Client

`frontend/src/services/api.ts` — `createApiClient` returns a typed fetch wrapper with:

- Automatic Bearer token injection from `authStore`
- Auto-refresh on 401 responses (deduplicated via `refreshing` promise guard)
- Structured error handling: `ApiError` with status, code, message, detail
- Covers 35+ endpoints across auth, servers, backups, plugins, monitoring, users, settings, software catalog, and schedules

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

236 frontend tests across 41 files (measured 2026-08-04). Test infrastructure:
- `vitest.config.ts` — jsdom environment, `@/` path alias, globals enabled
- `test-setup.ts` — jsdom, localStorage mock, matchMedia mock
- Testing libraries: `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`

Key test areas: `authStore` (9), `uiStore` (9), `api.ts` (11), `wsStore` (4), `AuthGuard` (2), `LoginPage` (5), `Sidebar` (4), `TopNav` (4), `AppLayout` (2), `WebSocketManager` (3), `ServersPage` (8), `DashboardPage` (7).

## Cross-References

- [Architecture](ARCHITECTURE.md) — system context, backend module map
- [API docs](API.md) — REST endpoints and WebSocket protocol reference
- [Development guide](DEVELOPMENT.md) — full setup instructions
