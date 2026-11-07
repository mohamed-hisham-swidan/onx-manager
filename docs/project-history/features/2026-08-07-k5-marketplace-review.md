# K5 — Marketplace as a First-Class Frontend Section (Design Review)

**Status:** DRAFT — awaiting approval. No code written.
**Roadmap:** Phase 1 (§3), Workstream 1 (K5) — frontend nav restructure.
**Scope boundary:** Do not pre-empt Workstream 2 (D4 route/namespace decision) beyond the minimal
enabler described below. Do not touch Workstream 3 (K16 provider list) — already done (K16A).

---

## 1. Current architecture

**Frontend routing** — `frontend/src/App.tsx`
- `/plugins` → `PluginListPage` (server-scoped management).
- `/plugins/marketplace` → `PluginMarketplacePage` — **no top-level standalone route**.
- Both share the `/plugins` namespace. Sidebar (`frontend/src/components/layout/Sidebar.tsx`)
  has `NAV_ITEMS = [Dashboard, Servers, Backups, Plugins, Settings]` — **no Marketplace entry**.

**Marketplace page coupling to a server** — `PluginMarketplacePage.tsx`
- Reads `server` from URL search params: `searchParams.get("server")`.
- Calls `useMarketplaceSearch(serverId, submitted)` → `GET /api/v1/servers/{server}/plugins/marketplace/search`.
- Without a `server` param, the search input is **disabled** and the page shows
  "Select a server to search plugins..." — you cannot browse the catalog at all without a server.
- `useProjectVersions(serverId, projectId)` and `useInstallFromMarketplace(serverId)` are also
  server-scoped. Best-version recommendation (`select_best_version`, `PluginMarketplacePage.tsx`
  → backend `plugins.py:96`) depends on the server's type + Minecraft version.
- "Back to Plugins" (line 110) navigates to `/plugins`, which resets `PluginListPage`'s
  in-component `selectedServerId` — the selection is lost.

**Entry point** — `PluginListPage.tsx` `handleInstall()` (line 51) navigates
`/plugins/marketplace?server=<id>`. Marketplace is reachable *only* through Plugins → select a
server → "Install Plugin".

**Backend** — single router `backend/app/api/v1/routers/plugins.py`, prefix
`/api/v1/servers/{server_id}/plugins`. It handles **both** plugin management and marketplace
(search/versions/install). Key detail: the marketplace **search handler ignores `server_id`
entirely** (`plugins.py:67-77` — it just calls `provider.search(query, limit, offset)`). Only
`versions` and `install` genuinely need the server. Provider is config-driven via
`build_plugin_catalog_provider()` (K16A).

**Hooks / API client / query keys**
- `usePlugins.ts` — `useMarketplaceSearch`, `useProjectVersions`, `useInstallFromMarketplace` all
  take `serverId`.
- `services/api.ts` — `searchMarketplace(serverId, …)` (lines 259-262).
- `services/queryClient.ts` — `queryKeys.plugins.marketplace.search(serverId, query)`.

**Tests**
- `PluginMarketplacePage.test.tsx` (115 lines) — entire first screen is served by these mocks; a
  marketplace surface with no `server` param is impossible today.
- `PluginListPage.test.tsx` (196) — asserts `mockNavigate("/plugins/marketplace?server=srv LunchPlugin`.
- No test asserts behavior occurs with `undefined/''` inputs — none asserts these inputs disabled.

**Icon** — all icons are declared inline in `Icon.tsx` and used on both `PageHeader` and the
`PluginMarketplacePage` (no shared icon component interface changes needed — it reuses `PageHeader`
and `Icon`).

---

## 2. Problems with the current UX / navigation

1. **Marketplace is undiscoverable.** No sidebar entry, no top-level route. A user lands on it only
   by Plugins → choose server → Install → search.
2. **Not independently navigable (violates acceptance criteria).** Schema requires a
   server-prefixed path to reach search; no server in the URL = a dead, disabled page.
3. **Marketplace does not read as "global."** It automatically fails to render a search when the
   server param is missing. The intended model (roadmap §3) is a distinct global store.
4. **Server selection is forced up-front** instead of at install time. The desired model: browse
   the catalog globally → choose a target server only when installing.
5. **Deep-linking is broken.** There's no way to bookmark/share a marketplace search or a project
   page; no `/marketplace` URL exists.
6. **Back-navigation loses server context.** Back to Plugins discards the selected server (local
   component state), so the user must re-select it.

---

## 3. Proposed design

### 3.1 Frontend IA
- Add a top-level route `/marketplace` → `PluginMarketplacePage` (page becomes the global store).
- Add a **Marketplace** entry to the sidebar `NAV_ITEMS`, with a new icon.
  - New icon key `icon-store` (a storefront glyph) added to `Icon.tsx` union +
    `PATHS`.
- `/plugins` remains the server-scoped "Plugins" management surface.
- Preserve the existing deep-link `/marketplace?server=<id>` so the Plugins page's "Install
  Plugin" button, and any saved links, still work (param **preselects** the target server,
  it's **not required**).

### 3.2 Global search (server-independent)
- Add a minimal **global** marketplace route `GET /api/v1/marketplace/search`
  mirroring the existing handler but without `server_id`. It already ignores
  `server_id` in the typed handler, so this is a thin, non-breaking addition. Keep the existing
  server-scoped routes intact (no removal; D4 decides their future).
- Frontend: new API method `searchMarketplaceGlobal(query, limit, offset)`, new hook
  `useMarketplaceSearchGlobal`, new query key `queryKeys.plugins.marketplace.global(query)`.

### 3.3 Install flow (server chosen at install time)
- Keep `versions` + `install` **server-scoped** — best-version recommendation and jar placement are inherently per-server.
- `PluginMarketplacePage` becomes a 2 Phase view:
  1. Global search (no server needed).
  2. On "Install" on a project → **Choose target server** dropdown (preseed `?server=`; server is
     required to proceed) → load `useProjectVersions(server, project)` → pick a version → confirm
     (existing `ConfirmDialog` → `useInstallFromMarketplace(server)`).
- `PluginListPage` "Install Plugin" → `navigate(\`/marketplace?server=${serverId}\`)` (keeps the
  existing UX path, now landing on the global page with server preselected).

### 3.4 State management
- Local component state for the selected server within `PluginMarketplacePage` (pre-seeded from
  `?server=`). No new global store needed. Server choice need not be a React Router param — local
  state suffices (matches current pattern; params stay for preseed only).

### 3.5 Tests
- Sidebar test: assert a Marketplace `NavLink` exists.
- App route test (or use the existing suites): `/marketplace` renders without a `server` param.
- `PluginMarketplacePage` tests: global search enabled with no server; server picker required at
  install; preset preserved; back to Plugins behavior.
- `PluginListPage` test: update expected navigate target to `/marketplace?server=…`.
- Backend test: global search endpoint returns the same results as `plugins.py` search (mirror
  `test_marketplace_search`).

---

## 4. Files to modify

**Backend**
- `backend/app/api/v1/routers/plugins.py` — add global `GET /marketplace/search` (keep old).
- `backend/app/main.py` — mount the new router (or add the route to the plugins router; register in
  `include_router`).
- `backend/tests/...` — new test for the global endpoint.

**Frontend**
- `frontend/src/components/ui/Icon.tsx` — add `store` icon.
- `frontend/src/components/layout/Sidebar.tsx` — add Marketplace `NAV_ITEMS` entry.
- `frontend/src/App.tsx` — add `<Route path="marketplace" …/>`.
- `frontend/src/services/api.ts` — add `searchMarketplaceGlobal`.
- `frontend/src/services/queryClient.ts` — add global marketplace key.
- `frontend/src/server_manager/hooks/usePlugins.ts` — add `useMarketplaceSearchGlobal`.
- `frontend/src/server_manager/pages/PluginMarketplacePage.tsx` — global browse + server picker at
  install.
- `frontend/src/server_manager/pages/PluginListPage.tsx` — update `handleInstall` target.
- `frontend/src/{pages,hooks}/Sidebar*` / `App.test` tests for the nav surface.
- Tests for `Sidebar`, `PluginMarketplacePage`, `PluginListPage`.

**Docs (only when K5 lands)** — update STATUS.md / current-state.md / roadmap §3 acceptance criteria entries and
"Net frontend gap" note in `plugins-and-marketplace.md:165`; mark roadmap §3 Workstream 1 (K5) done.

**No changes expected**: backend command/provider query logic, `getProjectVersions` handler logic, `InstallModrinthCommandHandler`, plugin schema.

---

## 5. Risks

1. **Scope creep into D4.** Mitigate: global search only; keep every existing server-scoped route;
   leave explicit D4 out of this slice.
2. **Behavior change for saved deep-links** (old `/plugins/marketplace`). Old URL still works
   at this stage of the plan's work.
3. **Version/install still requires a server** — if the user has no servers, installing is
   impossible. Add an explicit empty-state message ("You need a server to install into") rather than
   silently disabling. The **browse/search** remains usable in that case.
4. **Icon/component changes ripple.** Adding a new `IconName` is additive; the Icon union is
   string-strong, so TypeScript will catch any missed usage.
5. **Query cache.** Add a distinct `global` key so global search does not collide with the
   server-scoped search cache (different `query` content).

---

## 6. Proposed implementation plan (small independent commits)

Each commit is independently verifiable (tests + build/lint). Order chosen so each PR's tests
remain green.

1. **[backend] Add global marketplace search endpoint**
   `GET /api/v1/marketplace/search` (no `server_id`); keep the existing server-scoped search.
   Add a test mirroring the existing search test. *(Backend + tests green, no frontend change.)*

2. **[frontend] Add API/hook/query-key for global marketplace search**
   `searchMarketplaceGlobal` in `api.ts`, `useMarketplaceSearchGlobal` in `usePlugins.ts`, new
   global key set. Add small API/hook tests.

3. **[frontend] Add `store` icon + Marketplace sidebar entry + `/marketplace` route**
   Icon.tsx key, Sidebar.tsx `NAV_ITEMS`, App.tsx route. Sidebar test asserts the entry; an App
   render smoke test for `/marketplace` (independent of server). *(Marketplace still server-gated
   until step 4 — but already navigable via the new top-level route.)*

4. **[frontend] Rework Marketplace to global browse + install-time server picker**
   Rework `PluginMarketplacePage`; update `PluginListPage.handleInstall` target to
   `/marketplace?server=…`; add/refresh tests for global search (no server), server picker flow,
   and `PluginListPage` navigation. *(The acceptance criterion "independently navigable" is met
   here.)*

5. **[chore] Docs & roadmap update**
   Mark K5 done in roadmap §3; update acceptance criteria + the "net frontend gap" (K5) line in
   `plugins-and-marketplace.md`; optionally the `current-state.md`/`STATUS.md` entry. *(Docs
   only; describes the manual UX walk + frontend tests.)*

**Verification for the whole change**
- Backend suite: `python -m pytest backend` (existing baseline green; 1084 passed, 2 pre-existing
  env failures).
- Frontend: `npm test` (vitest) for the touched suites + `npm run build` + `tsc`.
- Manual walk: `/marketplace` loads global search with no server selected; search works with no
  server; install flow requires a chosen server; `Plugins → Install Plugin` deep-link preselects
  the server; Marketplace sidebar entry navigates correctly.

---

## 7. Approval gate

This document is a design review only. Implementation is intentionally **not** started. Awaiting
approval to proceed with the plan in §6 (or requested modifications) before writing any code.
</content>