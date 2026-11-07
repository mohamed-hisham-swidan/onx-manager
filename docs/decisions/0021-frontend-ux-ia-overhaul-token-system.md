# ADR-0021: Frontend UX/IA Overhaul and Design Token System

**Status**: Accepted by owner (decisions D1-D10 recorded 2026-11-04)  
**Date**: 2026-11-04  
**Author**: Project Maintainers (recording owner decisions)  
**Roadmap drift**: Controlled Drift  
**Spec Reference**: [`docs/design/frontend-overhaul/README.md`](../design/frontend-overhaul/README.md)

## Context

ONX Manager is preparing to go public as an open-source project. An architectural audit of the frontend (`frontend/`, React 19 + TypeScript + Vite + Tailwind CSS v4) revealed that while functional capabilities are extensive, the user interface reads as an unrefined, generic template:

- **Aesthetic Immaturity**: Relies on default system fonts, a single monochrome gray/blue palette, repetitive identical rounded cards, emoji icons mixed inconsistently with SVGs, and a 10-card rainbow status grid on the dashboard where over 80% of cards display zeros in typical deployments.
- **Monolithic Pages**: High-complexity pages have grown into unmaintainable monoliths, notably `ServerVersioningPage.tsx` (1,280 LOC, 6 inline dialogs) and `CreateServerPage.tsx` (811 LOC).
- **Code Duplication & Lack of Primitives**: 14 modal files exist across the codebase without a shared modal primitive; 8 pages construct raw `<table>` elements with inconsistent styling and layout; `ServerShell.tsx:83-131` duplicates 50 lines of sidebar navigation code.
- **Absence of Skin/Atmosphere Mechanism**: The application only supports a binary light/dark CSS class toggle on `<html>`. There is no design token abstraction to support visual skins, themes, or variable densities.

The owner requires a structured, layout-first and token-first overhaul to establish a clean, production-grade, skin-ready user experience before open-source release.

## Evidence

The following empirical facts were verified directly against the codebase:

1. **Codebase Scale**: `frontend/src` comprises about 41.8k lines across 220 files (count varies slightly by method).
2. **CSS Engine**: Built on Tailwind CSS v4.3.3 (`frontend/package.json`), utilizing `@theme` directives without a `tailwind.config.js`.
3. **Routing Topology**: `frontend/src/App.tsx:33-80` defines 22 unique page components.
4. **Unmounted Drawer**: `OperationDrawer.tsx` exists at `frontend/src/operations/components/OperationDrawer.tsx:35`, but is completely unmounted across all application layouts and pages (referenced solely in its own unit test).
5. **Backend List Schema**: The `GET /api/v1/servers` endpoint (`backend/app/api/v1/routers/servers.py:84-92`) returns `ServerResponse` (`backend/app/api/v1/schemas/server.py:61-78`), which omits server `address` (provides only `port`), live `players` count (provides only configuration limit `max_players`), `CPU`, and `memory`.
6. **Fleet WebSocket Subscriptions**: `frontend/src/components/WebSocketManager.tsx:94` subscribes globally to `server:*`, delivering lifecycle and provisioning progression events, but pushes zero live telemetry metrics (CPU, RAM, player count) to the server list. Live vitals stream strictly on channel `metrics:${serverId}` mounted in `ServerDetailPage.tsx:102`.
7. **Files API Limitations**: The file listing endpoint (`backend/app/api/v1/routers/files.py:75-109`) accepts only `server_id: str` and `path: str = Query(default="")`. It supports no pagination (`skip`/`offset`/`page`), no `limit`, and no `search` parameters, transferring directories in single unpaginated payloads.
8. **WebSocket Client Typing**: `frontend/src/websocket/client.ts:180` contains an `as any` type assertion in method `sendExecInput`, triggering `@typescript-eslint/no-explicit-any` because `exec_input` is missing from `WSClientMessage` in `types.ts`.
9. **Vitest Runner Contention**: The project uses Vitest 2.1.9 (`frontend/package-lock.json`). High-core parallel test runs encounter worker thread contention resulting in timeouts in `RegisterPage.test.tsx`. (In Vitest 2.x, `maxConcurrency` only controls concurrency within a single file; file-level concurrency is governed by worker pool settings).

## Options

1. **Option A: Incremental Restyle in Place**  
   Apply piecemeal visual tweaks and CSS utility updates across existing components without changing component hierarchy or establishing design tokens.  
   *Rejected*: Leaves monolithic orchestrators (`ServerVersioningPage.tsx`, `CreateServerPage.tsx`) intact, perpetuates 14 duplicated modals and 8 raw tables, fails to address accessibility contrast failures, and requires repeated migrations as new features land.

2. **Option B: Layout-and-Token-First Structural Overhaul (Adopted)**  
   Establish a semantic design token skeleton (`data-skin`, `data-mode`, `data-density`) in `frontend/src/index.css` in Batches 1–2 using neutral fallback values that preserve today's visual styling. Build foundational UI and data display primitives first, modularize monoliths, and refactor pages to consume tokens from inception. Specific skin palettes (Graphite and Azure) land in later batches with zero duplicate class rewrites.

3. **Option C: Full Frontend Rewrite**  
   Rebuild the frontend from scratch or migrate to an alternate framework.  
   *Rejected*: Severe roadmap drift, immense regression risk, discards 90 test files (767 passing tests), and violates the 15% drift budget.

## Decision (Owner Decisions D1–D10)

The repository owner made the following binding architectural decisions on 2026-11-04:

- **D1 (Strict Scope Boundary)**: Frontend-only overhaul. Zero new backend features.
- **D2 (Fleet Table Columns)**: Fleet table (`ServersPage.tsx`) columns are strictly limited to `status`, `name`, `software/version`, `port`, and `actions`. Additional metrics (live players, CPU, memory) are deferred to a separate backend follow-up task.
- **D3 (File Manager & Editor)**: File manager (`ServerFilesPage.tsx`) uses client-side search, client-side virtualization, and a slide-over drawer housing the existing 332-LOC in-house `CodeEditor.tsx`. Monaco Editor is not adopted.
- **D4 (Server Identity Strip)**: After removing the collapsible info container, the top Server Identity Strip displays `version`, `loader`, `port`, `address`, and `uptime`.
- **D5 (Server Contextual Sidebar)**: Navigation in `ServerShell.tsx` is structured into 3 non-collapsible group headings:
  1. *Core Workspace*: Console & Telemetry, Files & Editor, Settings
  2. *Add-ons & Content*: Mods & Plugins (unified view)
  3. *Operations & DevOps*: Network & Tunnels, Versions & Testing, Change History
- **D6 (Mobile Navigation)**: On mobile viewports (<1024px), server navigation collapses into a dedicated vertical slide-out drawer, avoiding overflowing horizontal pill bars.
- **D7 (Versioning & Audit Placement)**: "Versions & Testing" remains a primary signature item in the `ServerShell` sidebar. "Audit History" remains strictly scoped inside the server workspace (`/servers/:serverId/activity`); no global audit route is added.
- **D8 (UI Density Contract)**: Density is defined per-template rather than globally: compact (32px row height) for index and table pages (Servers, Files, Activity), and comfortable for forms and wizards (Settings, Create Server). Density is never mixed within a single action surface.
- **D9 (Marketplace IA)**: Retain the global `/marketplace` route for general catalog browsing, and add a contextual "Browse for [server]" deep link inside `ServerShell` to initiate targeted server installations.
- **D10 (Roadmap placement)**: No new phase is created. This work is recorded under Phase 7 (Visual / Brand Polish) of ROADMAP_v1.1 as a controlled scope amendment (D2) that adds structural UX/layout and the token architecture.

### Visual Skins Strategy
- Planned skins:
  1. **Graphite**: Neutral deep black/graphite foundation, free of blue undertones, featuring an intentional surface elevation ladder, avoiding harsh `#000000` / `#FFFFFF` pure pairings.
  2. **Azure**: Clean modern blue accent palette (aligned with the current product direction).
- Custom skins: The architecture must support future custom skins strictly as validated, sandboxed JSON token-value mappings; no custom CSS injections.

## Scope Contract

### In Scope
- Information architecture refactoring, page re-layouts, and five reusable layout templates (`FleetListTemplate`, `OperationalHudTemplate`, `MasterDetailTemplate`, `TabbedSettingsTemplate`, `GuidedWizardTemplate`).
- Shared UI primitives: `ModalPrimitive`, `Button`, `Badge`, `Card`, `DropdownMenu`, `DataTable<T>`, `PaginationBar`, `FilterBar`.
- Design token skeleton in `frontend/src/index.css` (`@theme`) with runtime `data-skin`, `data-mode`, and `data-density` hooks on `<html>` (neutral fallbacks in B1–B2).
- Theme palettes: Graphite and Azure definitions under `[data-skin]`.
- Accessibility standards: WCAG AA compliance (text contrast >= 4.5:1, UI boundaries >= 3:1, verified via computation script).
- Console stability criteria: terminal must repaint missed lines upon reconnect or returning from background tabs; terminal must not mount duplicate instances upon back-navigation.
- URL query parameter synchronization (`?status=`) for server fleet filtering.
- Unified Add-ons interface integrating Plugins and Mods.

### Out of Scope (Deferred to Future Product track)
- Bulk server power actions (multi-select start/stop/restart).
- Dedicated players management panel (in-browser kick, ban, message).
- Global command palette (`Cmd+K`).
- Table vs. card grid view toggles on fleet list.
- Real-time directory/folder size calculation.
- Multi-file archive/extract operations in file browser.
- Global administrative audit log route.
- Custom skin visual builder or file import UI.
- Monaco Editor or third-party editor libraries.

### Backend Follow-ups (Separate Items, Outside This ADR)
- Fleet list enrichment in `ServerResponse` (`address`, live `players`, `CPU`, `memory`).
- Server Files API pagination, limit, and search parameters.

### Functional Items Separated Outside Visual Batches
The following items are isolated into separate functional tasks outside visual layout batches:
1. Mounting `OperationDrawer` (gated by verifying the operation store is actively fed).
2. TopBar WebSocket latency and diagnostics popover.
3. `client.ts:180` typing fix (`exec_input` shape in `WSClientMessage`).
4. Merging the invitation token redemption flow of `RegisterPage.tsx` into `InvitePage.tsx`.
5. Route-level code splitting (`React.lazy` / dynamic imports in `App.tsx`).
6. Vitest test runner stabilization via worker pool configuration (`Tech Debt track`).

## Execution Constraints & Governance

- **API Invariance**: Backend API contracts and route URLs remain strictly unchanged.
- **Zero Unapproved Dependencies**: No new runtime npm libraries are introduced without explicit owner approval.
- **Atmosphere & Trademark Safety**: Absolutely zero Mojang/Minecraft trademarks, brand logos, proprietary textures, or look-alike lettering. Original voxel/pixel artistic touches are deferred to Stage 3.
- **Batch Cadence**: Work is executed in approximately 19 small, focused batches. Every batch begins with a targeted targeted code audit of the exact file lines it modifies and must fit within a 30-minute agent execution window.
- **Peer Review & Commits**: Every batch must be independently reviewed by a separate agent before completion. Per project engineering policies, only the repository owner commits changes.

## Why

This decision satisfies the governance requirements of project governance standards:
1. It eliminates significant technical debt (monolith components, modal duplication, unvirtualized lists) while respecting the 15% pre-launch controlled drift budget.
2. It decouples visual design from component logic through semantic tokens, allowing brand customization without ongoing code churn.
3. It strictly contains blast radius by enforcing frontend-only boundaries, neutral token fallbacks, and single-batch reversibility.

## Impact

- **Product / User**: Delivers a cohesive, professional Minecraft server administration cockpit. Eliminates confusing dead placeholders ("Coming soon" cards) and useless zero-state dashboard grids. Provides non-overflowing mobile navigation and fast virtualized file browsing.
- **Stability**: Eliminates fragile inline modal dialogs, fixes terminal unmount/remount glitches, and prevents browser tab crashes on massive directory listings.
- **Performance**: Keeps vendor bundle lean (rejects Monaco's ~2.5–4.5MB uncompressed payload) and introduces route-level code splitting.
- **Architecture**: Transitions the frontend from hardcoded Tailwind utility classes to a formal three-tier design token architecture (`data-skin`, `data-mode`, `data-density`).
- **Operations**: Zero impact on backend deployment, database schema, or infrastructure.

## Effort

Estimated at approximately 19 small, sequential batches (<=30 minutes each):
- Batches 1–2: Foundational token skeleton & core shared primitives.
- Batches 3–4: AppShell, TopBar, and ServerShell layout unification.
- Batches 5–12: Template implementation and page modularization.
- Batches 13–14: Skin theme palettes (Graphite & Azure), switcher controls, and regression testing.
- Standalone functional specs: Code splitting, operation drawer, invite consolidation, Vitest tuning.

## Reversibility

**Easy to Moderate**. Each batch is isolated and covered by atomic git checkpoints. Because the token skeleton in B1–B2 uses neutral fallback values matching the current interface, layout changes and primitive extractions can be rolled back individually without breaking styling across unaffected pages.

## Roadmap Impact

**Controlled Drift**. Remains within the 15% pre-launch capacity budget. Work is strictly frontend-contained and advances the project toward release readiness. The work is recorded under Phase 7 (Visual / Brand Polish) of ROADMAP_v1.1 as noted in decision D10.

## Verification

Every batch must satisfy the following automated and visual verification gates:
1. `npm run typecheck` passes with 0 errors.
2. `npm run lint` passes with 0 warnings/errors.
3. `npm run test` passes (all 90 test files / 767+ unit tests).
4. `npm run build` succeeds; vendor and page bundle chunks remain within size budgets (<500 kB per async chunk).
5. WCAG AA color contrast verified programmatically for all theme token combinations.

## Outcome

Pending execution.
