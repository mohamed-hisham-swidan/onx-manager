# Marketplace Redesign v2 — Architecture & Decisions (2026-08-09)

Status: DESIGN CONFIRMED, RECON COMPLETE, NOT YET BATCHED. This
document supersedes standalone Issues #2 (version recommendation
unused), #3 (inverted install flow), and the Modrinth half of #4 (no
mods support) from `docs/roadmap/marketplace-ux-findings.md`. Those
three issues are no longer separate patches — they are one combined
redesign. CurseForge backend integration (the other half of #4) is
explicitly deferred to a future phase and is NOT part of this
document's scope beyond a UI placeholder.

Issues #1 and #5 from the original findings doc are already shipped
and are NOT part of this redesign:
- Issue #5 (light mode): shipped, commit confirmed in prior session.
- Issue #1 (empty marketplace on load): shipped, commit
  `472ca526ee1e4148dca6d18c6a66fbaa064881a8`.

## Approved design

### 1. Source selection (sidebar)
Two source icons in the sidebar: **Modrinth** and **CurseForge**.
- Modrinth: fully functional.
- CurseForge: visible, selectable icon, but shows a "Coming soon" /
  disabled state. Backend integration for CurseForge is out of scope
  for this phase — deferred entirely to a future phase.
- One source is selected by default, or the app remembers the user's
  last-selected source.

### 2. Within a selected source (Modrinth, for now)
- On open, immediately shows trending/popular results (mods +
  plugins mixed) with no user action required (this reuses the
  already-shipped Issue #1 empty-query fix).
- A **"Discover"** dropdown control (top-left of content area, with a
  down-arrow) lets the user narrow the view to either **Mods** or
  **Plugins**.
- A search box is available at all times.
- The browse/result list itself is a plain list/table — no blur, no
  modal.

### 3. Product entry points (two distinct paths)
- Clicking a product's **name or image** opens a **detail view**
  (image + description + an Install button).
- Clicking **"Install" directly** from the browse list skips the
  detail view and goes straight to the install modal.

### 4. Install modal
- Centered modal, background blurs slightly, has a way to
  cancel/go back.
- **Server selection is automatic and hidden** from the user as a
  manual primary step — the system auto-selects the last-used server
  (or last server the user tried installing to). No visible
  server-picker as the primary UI.
- Platform/loader is inferred automatically from the auto-selected
  server's `server_type`.
- If the auto-selected server doesn't support the product type
  (e.g. installing a mod to a Bukkit-only server), the system
  suggests a different server that does.
- **Version list: simple, flat, vertically-ordered list**
  (e.g. 1.1, 1.2, 1.3, 1.4, 1.5 stacked top-to-bottom), ordered
  **numerically by version_number** (semantic-version-aware — 1.10
  must sort after 1.9, not as a plain string sort), **regardless of
  published date**. This is a confirmed decision that changes prior
  RECON's assumption — `select_best_version`'s current output is
  sorted by published date, NOT version number, so backend work is
  required here (see Gaps).
- Best-compatible version pre-selected automatically (reusing
  `select_best_version` / `selected`/`notice` fields), small warning
  shown if compatibility isn't 100% certain. User can still manually
  override from the ordered list.

### 5. Data model — explicit project_type field
- Confirmed decision: the `Plugin` aggregate gets a new **explicit
  `project_type` field** (`mod` | `plugin`), set at install time —
  NOT inferred solely from the host server's `ServerType`. This is a
  deliberate flexibility choice (a server could in principle host
  both in the future) and changes prior RECON's assumption that
  ServerType-based inference was sufficient.
- Each server's plugin/mod lists should be filterable/separable by
  this explicit field going forward.

## RECON findings (current state, verified 2026-08-09)

### Frontend
- `PluginMarketplacePage.tsx` is currently monolithic — search
  listing and version selection both handled inline (no modal), via
  a `selectedProject` / `chosenVersion` ternary chain.
- `Sidebar.tsx` has no existing source-switcher pattern — a new
  pattern is needed for Modrinth/CurseForge.
- `ConfirmDialog.tsx` (`components/ui/`) is the existing modal
  pattern (`open`, `title`, `description?`, `confirmLabel?`,
  `cancelLabel?`, `onConfirm`, `onCancel`) — a good foundation, but
  the install modal needs a richer body (server auto-select display,
  version list) beyond a description string.
- `ServerDetailPage.tsx` has a usable detail-view pattern
  (`DetailSection`/`DetailRow` components) that the product detail
  view can follow.
- No route for a product detail view exists yet
  (e.g. `/marketplace/:projectId`) — needs to be added to `App.tsx`.
- No "coming soon" / disabled-feature visual pattern exists anywhere
  in the codebase — needs to be introduced new.
- `Icon.tsx` has no Modrinth or CurseForge brand SVGs yet — need to
  be sourced/added.

### Backend
- `ModrinthProvider.search()` hardcodes Bukkit-family plugin facets
  (`_PLUGIN_FACET`, `_PLUGIN_LOADER_FACETS` module constants) — needs
  to be parameterized to accept `project_type` (mod vs plugin) and
  pass correct loader facets dynamically.
- `ServerType` enum already includes FABRIC and FORGE alongside
  PAPER/PURPUR/SPIGOT/BUKKIT/VANILLA — sufficient to infer mod vs
  plugin support at the server level for the auto-suggest-different-
  server behavior in point 4 above.
- `Plugin` aggregate (`plugin/domain/aggregate.py`) is tied to
  `server_id` but has **no `project_type` field today** — confirmed
  gap, to be added per the point-5 decision above.
- `select_best_version()` in `version_selector.py` already returns a
  `VersionSelection` dataclass with `selected`, `available` (a sorted
  tuple), `notice`, `notice_kind`. **Currently sorted by published
  date, not version number** — needs a sort-key change to satisfy the
  point-4 decision above (numeric/semver-aware version_number sort).
  This is a backend code change, contrary to original RECON's
  "no additional backend work needed" finding — that finding assumed
  published-date sort was acceptable; it is not, per the confirmed
  decision.

## Gaps summary (needs to be newly built)

**Frontend:**
1. Source switcher UI (Modrinth/CurseForge) in sidebar or marketplace
   header.
2. Modrinth + CurseForge brand SVGs in `Icon.tsx`.
3. "Coming soon" visual pattern for the CurseForge placeholder.
4. "Discover" dropdown (Mods vs Plugins) in the marketplace view.
5. Product detail view (`/marketplace/:projectId` route + UI).
6. Install modal component (extends `ConfirmDialog` pattern, richer
   body: hidden auto-server-select display, ordered version list).
7. Simple flat ordered version-list UI component.

**Backend:**
8. Parameterize `ModrinthProvider.search()` for dynamic `project_type`
   (mod/plugin) + corresponding loader facets.
9. Add explicit `project_type` field to `Plugin` aggregate + a DB
   migration (Alembic, per project convention) + set it at install
   time.
10. Change `select_best_version()`'s sort key from published-date to
    numeric/semver-aware `version_number` ordering.
11. Confirm/update `PluginVersionsResponse` and related API response
    models if the sort-key change affects response shape.

**Cross-cutting:**
12. Decide (separate design question, not yet asked) how "last-used
    server" is tracked for the install modal's auto-select — is this
    new state, or does existing state (e.g. Zustand persistence
    mentioned in project history for K5 marketplace work) already
    cover it? Needs its own RECON before batching the install modal.

## Batching guidance (not yet executed)

This is a multi-batch effort. Suggested logical groupings (order and
assignment not yet decided — needs orchestrator sign-off before any
BUILD prompt is written):
- Batch A (backend, foundational): version_number sort-key change
  (gap 10-11), project_type field + migration (gap 9).
- Batch B (backend): ModrinthProvider mod/plugin parameterization
  (gap 8).
- Batch C (frontend, foundational): source switcher + brand icons +
  coming-soon pattern (gaps 1-3).
- Batch D (frontend): Discover dropdown + simple ordered version list
  UI (gaps 4, 7).
- Batch E (frontend): product detail view + route (gap 5).
- Batch F (frontend, most complex): install modal with hidden
  auto-server-select (gap 6) — depends on gap 12 being resolved first.

Do not start implementing any batch without explicit go-ahead and the
same RECON → design decision → build → review → commit cycle used for
Issues #1 and #5.
