# onx-manager Frontend

React 19 + TypeScript + Vite + Tailwind CSS v4 single-page application for managing Minecraft servers. Dark-theme-first with a consistent design system.

## Commands

| Command | Purpose |
|---------|---------|
| `npm run dev` | Start Vite dev server |
| `npm run build` | Type-check + production build |
| `npm run test` | Run Vitest test suite once |
| `npm run test:watch` | Run tests in watch mode |
| `npm run lint` | ESLint over `src/` |
| `npm run typecheck` | `tsc --noEmit` |

## Routing (`src/App.tsx`)

Public routes wrap `AuthGuard`, then the `AppShell` layout for all authenticated pages:

- `/` — Dashboard
- `/servers` — Servers list
- `/servers/create` — Create server wizard
- `/servers/import` — Import server from directory
- `/servers/:serverId` — Server detail (info/config/console/metrics tabs)
- `/backups` — Backups list + create
- `/plugins` — Plugins list + install
- `/settings` — Global settings
- `/settings/api-keys` — API keys
- `/login`, `/register` — Auth (outside `AuthGuard`)
- `*` — `NotFoundPage`

## Layout

- `src/layouts/AppShell.tsx` — Responsive shell: fixed `TopBar`, collapsible `Sidebar` (mobile drawer), and a `max-w-7xl` content container.
- `src/components/layout/TopBar.tsx` — Mobile menu toggle, page search, theme toggle, user menu.
- `src/components/layout/Sidebar.tsx` — Nav links (Dashboard, Servers, Backups, Plugins, Settings), collapsed state on desktop, slide-over on mobile.
- `src/components/guards/AuthGuard.tsx` — Redirects unauthenticated users to `/login`.

## UI kit (`src/components/ui/`)

Shared, theme-consistent primitives:

- `Icon.tsx` — Inline SVG icon set; renders `aria-hidden`.
- `PageHeader.tsx` — Title + description + optional back link + actions slot.
- `StatusBadge.tsx` — Colored status dot + label (driven by `STATUS_MAP`).
- `StatCard.tsx` — Icon + label + value summary card.
- `ConfirmDialog.tsx` — Accessible confirm modal (Escape / backdrop close) for destructive actions.
- `Toaster.tsx` — Renders notifications from `toastStore`.
- `LoadingBar.tsx` — Top-of-page progress bar.
- `Skeleton.tsx` / `TableSkeleton` — Loading placeholders.
- `EmptyState.tsx` — Consistent empty-state block.
- `ErrorBoundary.tsx` — Top-level error catcher.

## Pages (`src/server_manager/pages/`)

All list/detail pages follow one pattern: `PageHeader` → loading `TableSkeleton` → error card → `EmptyState` → data table. Icon action buttons are color-coded with `aria-label` + `title`, and destructive actions go through `ConfirmDialog`.

- `DashboardPage` — Status overview cards, recent activity fed by live WebSocket events.
- `ServersPage` — Search/filter/sort server list with start/stop/restart/delete actions.
- `ServerDetailPage` — Header actions + tabbed sections.
- `BackupListPage` — Summary `StatCard`s, filters, create/restore/verify/delete.
- `PluginListPage` — Server selector, enable/disable/uninstall.
- `CreateServerPage`, `ImportServerPage`, `SettingsPage`, `ApiKeysPage`, `LoginPage`, `RegisterPage`, `NotFoundPage`.

## Stores (`src/stores/`)

Zustand stores, each with a unit test:

- `toastStore.ts` — Toast queue; `toast(type, title, description)` helper.
- `authStore.ts` — Session/token state.
- `uiStore.ts` — UI prefs (sidebar open, theme).
- `activityStore.ts` — Recent activity log, fed by WebSocket events.
- `wsStore.ts` — WebSocket connection state.

## Data & Live Events

- `src/services/api.ts` — Authenticated API client (single source of endpoint types).
- `src/services/queryClient.ts` — TanStack Query client + `queryKeys`.
- `src/hooks/useWebSocket.ts` — Reconnecting WebSocket hook (`onEvent` / `onStateSync`).
- `src/components/WebSocketManager.tsx` — Mounts the socket once and normalizes events into `activityStore` via `toActivityEvent`.
- `src/server_manager/hooks/` — Per-resource query/mutation hooks (`useServers`, `useBackups`, `usePlugins`, `useApiKeys`, `useSettings`).

## Utilities

- `src/server_manager/utils/format.ts` — `formatBytes`, `formatDateTime`, etc.
- `src/server_manager/utils/motd.ts` — Strips Minecraft MOTD formatting codes.

## Design conventions

- Dark-theme-first; every color has explicit light + `dark:` variants.
- Cards: `rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800`.
- Primary actions: `rounded-lg bg-blue-600 hover:bg-blue-700 text-white`.
- Icon buttons: `rounded-lg p-1.5` + color-matched hover state.
- Tables: `overflow-hidden rounded-xl border` wrapper; secondary columns hidden on mobile (`hidden sm:table-cell`).
- Keyboard: global `:focus-visible` outline in `src/index.css`; dialogs close on Escape.
