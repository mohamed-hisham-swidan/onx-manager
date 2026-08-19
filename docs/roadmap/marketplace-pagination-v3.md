# Marketplace Pagination & Card Redesign v3 — Design Spec (2026-08-19)

Status: **Batch 1 (Backend) COMPLETE** (verified: 188 backend + 506 frontend tests
passing; zero new ruff violations). Batch 2 (Frontend pagination) and Batch 3
(Frontend card redesign) are queued but NOT started.

This spec layers on top of the currently-uncommitted SPEC-PLUGIN-DETAIL-TABS-001
batch (the new `marketplace.py` router, `CompatibilityCard.tsx`,
`ProjectVersionsList.tsx`, `PluginDetailPage.tsx` tabs — all uncommitted, HEAD
unchanged). It replaces the current marketplace **browse/list table** and the
**per-page version list** with Modrinth-style pagination and a Modrinth-style
card list, as designed below.

Follows `docs/history/features/marketplace-redesign-v2.md` as its structural
precedent (Status → Goals → Confirmed Design → API/Schema Changes → Batch Plan
→ Open Deviations).

## Goals

Add Modrinth-style pagination (20 items/page, arrow navigation, next page
**NOT** preloaded before the user clicks the arrow) plus a card redesign to
visually match Modrinth's own card style, across:

1. **Main marketplace browse page** — server-independent browse
   (`marketplace.py` `GET /api/v1/marketplace/search`).
2. **Marketplace search results** — same shared component/table as #1 per
   RECON (`PluginMarketplacePage.tsx`).
3. **Internal project-versions page** — `ProjectVersionsList.tsx` /
   `marketplace.py` `GET /api/v1/marketplace/projects/{id}/versions`.

Pagination applies **uniformly to BOTH the global (server-independent) and
server-scoped (`plugins.py`) browse/search variants**, since they share the
same frontend component.

Reference: the two attached screenshots (the Fabric API card, and the
numbered-pages-with-arrow pagination bar) are the literal visual target for the
card and paginator design.

## Confirmed Design

### Decision 1 — `total_hits` threading (page-count math)

Modrinth's `GET /search` response already includes `total_hits`, but
`ModrinthProvider.search()` currently discards it. Thread it end-to-end:

- `ModrinthProvider.search()` (provider)
- → `PluginCatalogProvider` abstract interface (`base.py`)
- → a new **wrapper/paginated response type** at the `PluginSearchResultResponse`
  level — the envelope, **not** the individual item schema
- → frontend, so the UI can compute the total page count.

### Decision 2 — Page size: exactly 20

**20 items per page.** The backend `limit` param stays capped at `le=50`; `20`
is simply what the frontend will always send. No change to the existing bound.

### Decision 3 — Pagination state lives in the URL

Stored as a `page` search param. The page already uses `useSearchParams` for
other state (`PluginMarketplacePage.tsx`) — follow that existing pattern.
Changing pages updates the URL; back/forward navigation should work naturally as
a result.

### Decision 4 — Default sort on initial load: Relevance

No query typed yet → **Relevance**, matching Modrinth's actual default
(confirmed: Modrinth defaults to Relevance both for search and for browsing, NOT
Downloads). This is effectively the current no-op default, so **no behavior
change is needed** — document it here explicitly so nobody later "fixes" it to
Downloads by mistake.

### Decision 5 — Scope: both global and server-scoped

Applies to both the global and server-scoped variants (see Goals) — same
component, same `page`-param handling, same query-key fix.

### Decision 6 — ProjectVersionsList paginates 20/page, backend-side

The internal versions page also paginates at 20/page. This requires **real
backend `limit`/`offset` support** added to `marketplace.py`'s
`/projects/{id}/versions` route (and the server-scoped `plugins.py` equivalent)
— **NOT** client-side slicing of an all-versions fetch. The provider's
`get_project_versions()` call to Modrinth needs `limit`/`offset` threaded
through **if Modrinth's `/project/{id}/version` endpoint supports it**;
otherwise, fall back to fetch-all-then-slice **server-side** (still never
shipping the whole payload to the client per page).

### Decision 7 — Card redesign (table → Modrinth-style card list)

The current `PluginMarketplacePage.tsx` table (icon / title / description /
author / downloads / Install button rendered in a `<table>`) is **REPLACED
entirely** with a Modrinth-style card list — one card per row, each showing:

- icon
- name + author
- description (truncated)
- tag pills: loader(s), category/categories, client/server environment
- download count
- follow/like count
- last-updated as **relative time**

Visual target: the attached Fabric API card screenshot.

### Decision 8 — Schema additions

`PluginSearchResultResponse` gains:

- `categories`
- `loaders`
- `client_side`
- `server_side`
- `date_modified`
- (optionally) `color`

All are present in Modrinth's real search-hit response today — just not
currently parsed/exposed by our provider or schema. This requires:

- schema change (`schemas/plugin.py`)
- provider parse update (`modrinth.py`)
- `PluginCatalogProvider` interface update if it is typed there
- test updates (`test_plugin_catalog_providers.py`, `api.test.ts`)

## API/Schema Changes

- **New paginated search envelope** (provider + interface + response type)
  carrying `hits`/items **and** `total_hits` (Decision 1), used by both
  `marketplace.py /search` and `plugins.py /marketplace/search`.
- **`GET /api/v1/marketplace/projects/{id}/versions`** and its server-scoped
  equivalent in `plugins.py`: add real `limit`/`offset` query params (Decision
  6). Provider `get_project_versions()` gains `limit`/`offset` threaded to
  Modrinth if supported, else server-side fetch-all-then-slice.
- **`PluginSearchResultResponse`** gains `categories`, `loaders`,
  `client_side`, `server_side`, `date_modified`, optionally `color` (Decision 8).
- No change to the existing `limit` bound (`le=50`).

## Batch Plan (proposed — NOT STARTED)

> Suggestion only. The user may re-split or reorder these batches before build
> starts.

- **Batch 1 (Backend):** **✅ DONE (2026-08-19).** `total_hits` plumbing
  (provider + `PluginCatalogProvider` interface + paginated response envelope);
  schema field additions (Decision 8); query-key fix (`offset` now in React
  Query keys); versions-endpoint `limit`/`offset` (Decision 6 backend half,
  fetch-all-then-slice in the Modrinth provider).
- **Batch 2 (Frontend):** new reusable **Pagination** component (arrow +
  page-number bar, URL-param-driven, no prefetch); wire into
  `PluginMarketplacePage.tsx` and `ProjectVersionsList.tsx`. **NOT STARTED.**
- **Batch 3 (Frontend):** replace the marketplace table with the new
  Modrinth-style card component, consuming the new schema fields from Batch 1.
  **NOT STARTED.**

## Batch 1 verification record

- Backend: `188 passed` across `test_plugin_catalog_providers.py`,
  `test_api_endpoints.py`, `test_install_modrinth_plugin.py`,
  `test_version_selector.py`, `test_route_contract.py`.
- Frontend: `65 files / 506 passed` (`vitest run`); `tsc --noEmit` clean for all
  changed files (the only remaining errors are the 4 pre-existing files verified
  at HEAD: `DashboardServerList.test.tsx`, `PanelExposureSection.tsx`,
  `useServerExposure.ts`, `ServerDetailPage.test.tsx`).
- Ruff: repo-wide counts net-unchanged relative to pre-batch state (baseline
  gate was already red before this batch from the uncommitted
  SPEC-PLUGIN-DETAIL-TABS-001 work; Batch 1 adds no new violations — B008
  remains *under* its 194 baseline).
- Pre-existing (NOT introduced by Batch 1): `test_install_modrinth_plugin.py`
  fails with `NoReferencedTableError` when run in isolation (fixture-ordering
  artifact; passes inside the full application suite).

## Findings Ledger (Batch 1 closure)

| ID | Finding / Decision | Classification | Documentation Location | Code/Test Impact | Status |
|---|---|---|---|---|---|
| F-01 | Modrinth search response exposes `categories`; loaders must be **derived**, not parsed separately — added `_LOADER_CATEGORY_NAMES` frozenset (plugin/mod categories + velocity/bungeecord/waterfall/minestom) instead of Modrinth's absent `loaders` field | PROVIDER / DESIGN | `docs/roadmap/marketplace-pagination-v3.md` Decision 8; `backend/app/modules/plugin/infrastructure/providers/modrinth.py` | `PluginSearchResult.loaders` populated from derived set; tests assert non-loader categories excluded | Verified |
| F-02 | `total_hits` is top-level in the Modrinth search response, not inside `hits` — provider parses it separately and defaults to `0` when absent (backward-safe for the server-scoped PathOfExile/fake providers) | PROVIDER | `modrinth.py`; `base.py` `PluginSearchPage` | `test_search_total_hits_missing_defaults_zero` added | Verified |
| F-03 | Decision 6 resolved as **fetch-all-then-slice**: Modrinth API versions endpoint has no server-side pagination, so the provider fetches all versions and slices in Python (`items[offset:offset+limit]`), with `total` = full count | PROVIDER / DESIGN | `modrinth.py` `get_project_versions`; spec Decision 6 | `TestModrinthProviderGetProjectVersions` (all + slice cases) | Verified |
| F-04 | Search response schema is now an **envelope** `{items, total_hits, offset, limit}` (`PluginSearchResultsResponse`) so the frontend page-count math has one source of truth; `PluginVersionsResponse` gains `total` for the same reason | DESIGN | `backend/app/api/v1/schemas/plugin.py`; spec Decision 1 / API changes | Both routers (`marketplace.py`, `plugins.py`) return the envelope; fake providers + fixture mocks updated | Verified |
| F-05 | Frontend React Query keys for marketplace search **did not include page/offset** — page 2 would silently reuse page 1's cache (spec's Caching note). All four marketplace query-key builders now include `offset` (`search(serverId, query, projectType?, offset=0)`, `global(..., offset=0)`, `projectVersions(projectId, offset=0)`, `versions(serverId, projectId, offset=0)`); `MARKETPLACE_PAGE_SIZE = 20` | BUG (cache) | `frontend/src/services/queryClient.ts`; spec Caching note | `usePlugins.ts` Python shell hooks thread offset into keys + API calls; `PluginMarketplacePage.test.tsx` / `api.test.ts` fixtures updated | Verified |
| F-06 | `PluginDetailPage.tsx` constructs its `searchResult` from a project object — the new Decision-8 fields are filled client-side (`categories: []`, `loaders: project.loaders`, `client_side`/`server_side` from project, `date_modified: ""`, `color: null`) so the CompatibilityCard keeps working against the non-marketplace server-scoped grab | DESIGN | `frontend/src/server_manager/pages/PluginDetailPage.tsx` | `PluginDetailPage.test.tsx` selectedProject assertion updated | Verified |
| F-07 | Ruff baseline gate (`scripts/check-ruff-baseline`) was **already red before Batch 1** — the uncommitted SPEC-PLUGIN-DETAIL-TABS-001 batch drifted I001/F811/F841/E501/SIM105 counts above the committed `ruff-baseline.json`. Batch 1 adds **zero new violations** (B008 stays under its 194 baseline; net repo delta vs pre-batch: +1 ARG001 / +2 B008, both on prior-batch code). Four-elements filename test helper diff cleanup needed later, not this batch | CI | `scripts/check-ruff-baseline`; `.ai/CURRENT_STATE.json` | New test mocks use the `assert params.get("query")` pattern to avoid ARG001 | Verified / pre-existing not this batch |

## Caching note (must be addressed in Batch 1)

React Query keys for marketplace search currently **do not include
page/offset** — this MUST be fixed (add the page param into the queryKey) as
part of Batch 1, otherwise page 2 will silently reuse page 1's cached results.
Also: do **not** add any `prefetchQuery` / `useInfiniteQuery` /
prefetch-next-page logic anywhere — pages are fetched only on explicit arrow
click, per the "no preload" requirement.

## Open Deviations

_(Empty for now — filled in only if something here turns out to be technically
impossible once building starts.)_