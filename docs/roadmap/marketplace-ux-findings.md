# Marketplace UX & Theming Findings (2026-08-07)

Source: live user testing session + independent code investigation.
Status: DOCUMENTED, NOT YET PLANNED. No batches scoped yet — this file
is ground truth for future Phase 3+ frontend planning.

## Issue 1 — Marketplace opens empty, no default browse content
**Severity: Low complexity**

- `PluginMarketplacePage.tsx`: query starts as `""`, and
  `usePlugins.ts`'s search hooks set `enabled: query.trim().length > 0`
  — zero API calls fire until the user types something.
- Page renders a plain "Search the marketplace" EmptyState on load;
  search button disabled until query is non-empty.
- No "featured"/"popular"/"trending"/"hot" concept exists anywhere in
  frontend or backend (confirmed via exhaustive grep).
- Backend CAN support this: Modrinth's `/v2/search` API returns popular
  results when queried with an empty string — the backend passes query
  through as-is (`modrinth.py`). The frontend is the only thing
  blocking this.
- Fix shape: allow `usePlugins.ts` hooks to fire on empty query (or a
  dedicated "browse" mode), update EmptyState logic accordingly.

## Issue 2 — Recommendation system: two different things, one missing entirely, one built-but-unwired
**Severity: Low-Medium complexity**

- **Plugin recommendations (curated suggestions, e.g. "Recommended:
  EssentialsX, Vault")**: genuinely does not exist anywhere in the
  codebase. Would need a new backend service/curated list.
- **Best-version-for-server recommendation**: ALREADY IMPLEMENTED in
  the backend and currently discarded by the frontend:
  - `version_selector.py`: `select_best_version(server_type,
    minecraft_version, versions)` — maps loader compatibility chains
    (purpur → paper → spigot → bukkit), selects best match, generates
    notice text.
  - `plugins.py` router calls this and returns `PluginVersionsResponse`
    with `selected`, `notice`, `notice_kind` fields.
  - `PluginMarketplacePage.tsx` receives this response as
    `selectedVersionResponse`, maps over `.versions` for a flat table,
    but **never reads `.selected` or `.notice`** — no highlight, no
    banner, nothing.
  - Fix shape: this is primarily a frontend consumption fix — wire the
    already-computed `selected`/`notice` fields into the version table
    UI. No new backend logic needed for this half.

## Issue 3 — Install flow is inverted and has no server-first auto-select
**Severity: Medium complexity (UI/UX restructuring)**

Current actual flow in `PluginMarketplacePage.tsx` (confirmed, not a
modal — inline state swap within the page):
1. Search results table → click "Install" on a plugin row
2. Flat table of ALL versions (unfiltered by Minecraft version or
   loader) → click "Install" on a version row
3. Radio list of ALL servers → click "Continue"
4. `ConfirmDialog` confirmation modal

What exists toward the desired flow:
- `serverMatchesVersion()`: after a version is picked, does a naive
  string match (`loader.toLowerCase() === server.server_type.toLowerCase()`)
  to sort/pre-select a likely target server — but this runs AFTER
  version selection, not before, so it can't drive filtering.
- No Minecraft-version filtering exists on the version table at all —
  every version from Modrinth renders regardless of compatibility.
- No server-first flow exists — user picks version blind before server
  context is established.

Desired flow (per user testing): Select server first → auto-detect
loader from server's `server_type` → auto-suggest best-compatible
version (using Issue 2's already-built backend selector) → optional
manual override via a full version list.

Fix shape: state machine restructure in the install flow — server
selection first, loader inferred, version auto-suggested via existing
backend `selected` field, manual version list as secondary/expandable
option rather than the primary view.

**Screenshot evidence (2026-08-07):** live testing on the global
marketplace view (`/marketplace`, no server context —
"Browse the global marketplace without a server — you'll pick a
destination when installing") confirmed this in practice. The version
table for a single plugin showed an unsorted, mixed-loader list in
one flat view with no visual grouping or compatibility indicator:

| Version | Game versions | Loaders |
|---|---|---|
| fabric-2.6.21+26.3-snapshot-7 | 26.3-snapshot-7 | fabric |
| fabric-2.6.21+26.3-snapshot-6 | 26.3-snapshot-6 | fabric |
| fabric-2.6.21+26.3-snapshot-5 | 26.3-snapshot-5 | fabric |
| fabric-2.6.21+26.3-snapshot-4 | 26.3-snapshot-4 | fabric |
| fabric-2.6.21+26.2 | 26.2 | fabric |
| neoforge-2.6.21+26.2 | 26.2 | neoforge |
| forge-2.6.21+26.2 | 26.2 | forge |
| bukkit-2.6.21 | 1.8.8, 1.12, 1.12.1 +40 | bukkit, folia, paper, purpur, spigot |
| fabric-2.6.21+26.1.2 | 26.1, 26.1.1, 26.1.2 | fabric |
| neoforge-2.6.21+26.1.2 | 26.1, 26.1.1, 26.1.2 | neoforge |
| forge-2.6.21+26.1.2 | 26.1, 26.1.1, 26.1.2 | forge |

Observations from this concrete example:
- Fabric, NeoForge, Forge, and Bukkit-family builds are all
  interleaved in one list with no grouping by loader.
- Version strings encode the PLUGIN's own version
  (`fabric-2.6.21+26.3-snapshot-7`), not a clear "compatible with
  your server" signal — a user has no fast way to identify which row
  matches their server's Minecraft version without reading every
  "Game versions" cell individually.
- This was viewed from the GLOBAL marketplace (no server selected),
  which explains why no compatibility highlighting appears at all —
  there is no server context yet for the backend's
  `select_best_version()` (documented in Issue 2) to compare against.
  This reinforces Issue 3's "Fix shape": a server-first flow would
  give this comparison a chance to work; the current version-first
  flow structurally prevents it even when accessed from a
  server-scoped entry point.
- User assessment from this session: "version recommendation trash,
  ~60% doesn't even work" — i.e. even where a server context IS
  available (server-scoped marketplace entry), the recommendation
  signal documented as unwired in Issue 2 was not visibly helping in
  practice.

## Issue 4 — No Mods support (Fabric/Forge) — marketplace is Bukkit-only
**Severity: Medium-High complexity**

- `ServerType` enum (`value_objects.py`) and `ServerResponse.server_type`
  (`types.ts`) already support "fabric", "forge", "paper", "purpur",
  "spigot", "bukkit", "vanilla" — the data model isn't the blocker.
- The marketplace provider layer IS the blocker:
  `modrinth.py` hardcodes:

_PLUGIN_CATEGORIES = ("bukkit", "paper", "purpur", "spigot", "folia")
_PLUGIN_FACET = '["project_type:plugin"]'
_PLUGIN_LOADER_FACETS = ('["categories:bukkit","categories:paper",'
'"categories:purpur","categories:spigot","categories:folia"]')

  This makes it structurally impossible to query Fabric/Forge/Quilt/
  NeoForge mods — every search forces `project_type:plugin` with
  Bukkit-family category facets.
- `Server.server_type` (`read_models.py`, `types.ts`) already stores
  the loader per-server — available, just unused by the marketplace
  layer.

Fix shape: parameterize `ModrinthProvider.search()` to accept project
type (plugin vs. mod) and loader category dynamically; add a Mods/
Plugins tab or filter in the UI; wire server's `server_type` to
pre-select the correct project type when installing to a specific
server.

## Issue 5 — Light mode is broken (Tailwind v4 config gap)
**Severity: Very low complexity — single CSS line**

- `TopBar.tsx` → `toggleTheme()` in `uiStore.ts` correctly toggles a
  `.dark` class on `<html>` and persists the choice to `localStorage`
  (`mcs_theme`). The React/state layer works correctly.
- Root cause (confirmed, high confidence): project uses Tailwind CSS
  v4 (`@tailwindcss/vite` 4.3.3). In v4, `@import "tailwindcss";` alone
  defaults `dark:` variants to `prefers-color-scheme` media-query mode
  UNLESS a custom dark variant selector is declared.
- `frontend/src/index.css` contains only `@import "tailwindcss";` —
  no `@custom-variant dark (&:where(.dark, .dark *));` declaration.
- Result: Tailwind ignores the manually-toggled `.dark` class entirely;
  theme follows OS preference only, regardless of user's in-app choice.
- Fix shape: add one line to `frontend/src/index.css`:
  `@custom-variant dark (&:where(.dark, .dark *));`

## Summary table

| # | Issue | Severity | Backend work needed? | Frontend work needed? |
|---|---|---|---|---|
| 1 | Empty marketplace on load | Low | No (already supports empty query) | Yes — enable empty-query fetch |
| 2 | Version recommendation unused | Low-Med | No (already built) | Yes — consume `selected`/`notice` |
| 2b | No plugin recommendation engine | — | Yes (new) | Yes (new) — not scoped yet |
| 3 | Inverted install flow | Medium | No | Yes — restructure state machine |
| 4 | No Mods/Forge support | Med-High | Yes — provider parameterization | Yes — UI tabs/filters |
| 5 | Light mode broken | Very Low | No | Yes — 1 CSS line |

## Not yet planned
This document is findings only. No batch breakdown, no sequencing, no
architectural decisions have been made yet. Batch planning for these
items happens in a future session, likely alongside or after Phase 3.
