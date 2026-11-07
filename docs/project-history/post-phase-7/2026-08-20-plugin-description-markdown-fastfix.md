# FAST-FIX: Render plugin Description as Markdown (images + GFM)

- **Document ID**: `FASTFIX-PLUGIN-DESCRIPTION-MARKDOWN-001`
- **Date**: 2026-08-20
- **Status**: `VERIFIED` (frontend-only; awaiting review/gate, NOT committed)
- **Supersedes**: the "About" card raw-text rendering in
  `SPEC-PLUGIN-DETAIL-TABS-001` §4.3 (§4.3's "moves under the Description tab
  unchanged" is amended: it now renders through ReactMarkdown).
- **Finding ID**: F-17

## Problem

Modrinth project `body` is raw GFM Markdown
(`backend/app/modules/plugin/infrastructure/providers/modrinth.py:120` →
`body=data.get("body", "")`), but `PluginDetailPage.tsx` rendered it as
escaped plain text with `whitespace-pre-wrap`. Result: images showed as
literal `![alt](...)` markdown syntax, headers/bullets/tables displayed as raw
markdown. User observed broken images on a plugin description page.

## Decision (Option A — frontend-only, no backend change)

Render `project.body` with `react-markdown@^10.1.0` + `remark-gfm@^4.0.1`,
styled via `@tailwindcss/typography@^0.5.20` (Tailwind v4 CSS-first:
registered with `@plugin "@tailwindcss/typography";` in
`frontend/src/index.css` — no `tailwind.config`, `vite.config.ts` uses
`@tailwindcss/vite`).

Key implementation points:
- **No `rehype-raw`** — raw HTML is escaped, never executed (react-markdown
  v10 default). Verified default `urlTransform` sanitizes URLs:
  `safeProtocol = /^(https?|ircs?|mailto|xmpp)$/i`; `javascript:` URLs
  collapse to empty `href`. No transform override shipped.
- react-markdown v10 **rejects a `className` prop** at runtime; typography
  classes (`.prose .prose-sm .max-w-none .dark\:prose-invert`) live on the
  wrapping `div` instead.
- `img` override in a module-scope `markdownComponents: Components`:
  `loading="lazy"`, `className="my-4 max-w-full rounded-lg border …"`,
  destructures `node: _node`.
- Changelog tab remains disabled/stubbed; a comment marks it for the same
  ReactMarkdown treatment when its content ships (SPEC-PLUGIN-DETAIL-TABS-001
  §7).

## Files touched (all frontend, uncommitted)

- `frontend/package.json` (+ `react-markdown@^10.1.0`, `remark-gfm@^4.0.1`;
  dev: `@tailwindcss/typography@^0.5.20`) / `frontend/package-lock.json`
- `frontend/src/index.css` — `@plugin "@tailwindcss/typography";` added
- `frontend/src/server_manager/pages/PluginDetailPage.tsx` — ReactMarkdown
  rendering (+4 new component lines, Changelog comment)
- `frontend/src/server_manager/pages/PluginDetailPage.test.tsx` — 4 new tests
  (9 total): markdown image → real `img` with `loading="lazy"`; GFM table +
  task-list checkboxes; raw HTML `<script>`/`<img onerror>` escaped; no
  `a[href^="javascript:"]` after rendering a `javascript:alert(1)` link.

## Verification

- `PluginDetailPage.test.tsx`: 9/9 pass. Note: `getByRole("link", …)` does
  NOT match `<a href="">` (empty-href anchors aren't exposed as links by
  jsdom/dom-accessibility-api) — the javascript: test asserts absence of
  `a[href^="javascript:"]` instead.
- Related: `PluginMarketplacePage.test.tsx` + `ProjectCard.test.tsx` +
  `ProjectVersionsList.test.tsx`: 31/31 pass.
- `npx tsc --noEmit`: no new errors beyond the 4 pre-existing baseline files.
- `eslint` PluginDetailPage.tsx + test: clean.

---

## ADDENDUM — Compatibility card game-version bucketing (F-18)

- **Finding**: F-18 — ships the deferred RV1-04/RP-04 item from
  SPEC-PLUGIN-DETAIL-TABS-001 §7 ("Game-version bucketing/range display").
  User-specified target: group by `major.minor` line; show the bare release
  as exact, cover the base release with `major.minor.x`, render a gap-free
  contiguous patch run as a range (`1.16.3–1.16.5`), otherwise `major.minor.x`.
  Follow-up: consecutive base-covered lines of the same major collapse into a
  line range (`1.17.x/1.18.x/1.19.x` → `1.17–1.19`); gap-covered lines
  (`1.20.x` from sparse patches) or exact single lines are never merged, so a
  range only asserts full line coverage.
- **Implementation** (`frontend/src/server_manager/components/CompatibilityCard.tsx`):
  new exported pure functions `parseGameVersion()` + `groupGameVersions()`.
  Verified against live Modrinth data (`/v2/project/sodium`,
  `/v2/project/appleskin`): `groupGameVersions(sodium.game_versions)` returns
  `["26.2","26.1.x","1.17–1.21","1.16.3–1.16.5"]` (the 1.17–1.21 lines merge;
  26.2 stays exact, 26.1.x stays a lone `x` line).
  Snapshots/pre-releases (e.g. `24w14potato`, `26.2-rc-1`) are non-numeric →
  kept raw and listed after the numeric lines. Pills sort newest-first.
- **Platforms section**: dropped the loader `<Icon>` inside each pill — every
  `LOADER_DISPLAY` icon currently resolves to the generic `download` fallback,
  so the icon added noise; label pills ("Fabric", "NeoForge", …) remain.
- **Information sidebar**: the "Game Versions" row in the detail page's
  `DetailSection Information` (`PluginDetailPage.tsx`) also joined
  `game_versions` flat — now rendered through the same `groupGameVersions()`
  (e.g. `1.19.x, 1.18.x, 1.17.x, 1.16.3–1.16.5`). Companion test added to
  `PluginDetailPage.test.tsx`.
- **Tests** (`CompatibilityCard.test.tsx`): 7 new `groupGameVersions` cases
  (12 total in file) incl. the full sodium-style wide-support reproduction.
- **Verification (F-18)**: CompatibilityCard 12/12, PluginDetailPage +
  Marketplace + ProjectCard + ProjectVersionsList 40/40, `tsc --noEmit` no
  new errors, eslint 0 errors (4 pre-existing react-refresh warnings on
  exported helpers).

## Out of scope (unchanged)

- Backend / Modrinth provider — untouched.
- Changelog tab content — per SPEC-PLUGIN-DETAIL-TABS-001 §7.
- Committing → pending review gate (per AI_RULES DESIGN COMPLETION GATE);
  batch must NOT commit without explicit approval.

---

## ADDENDUM — Clickable platform tags → marketplace search (F-19)

- **Finding**: F-19 — platform pills in the Compatibility card are now search
  tags: clicking one navigates to the marketplace with that platform as a
  search facet (`?loader=paper`), with a removable "Platform: <name>" tag and
  a single-platform Modrinth facet filter.
- **Backend** (`modrinth.py` `search()`): new `loader: str | None` kwarg.
  A validated loader token (`^[a-z0-9-]{1,50}$`) replaces the default
  loader OR-list with `["categories:<loader>"]`; invalid tokens are ignored
  (can never inject facet-syntax). Both search routes
  (`/api/v1/marketplace/search`, `/api/v1/servers/{id}/plugins/marketplace/search`)
  accept `loader` (max_length 50) and pass `loader or None`.
- **Frontend**: `api.ts` passes `loader` (undefined dropped by `buildUrl`);
  `usePlugins.ts` + `queryClient.ts` thread it through options and query keys
  (`loader ?? "all"`); `PluginMarketplacePage` reads `?loader=`, shows the
  removable filter tag (clear resets `page`); `CompatibilityCard` renders
  platform pills as `<Link>` when a `buildPlatformHref` is provided (still
  plain spans otherwise); new `platformProjectType()` maps server loaders →
  `plugin`, mod-loaders → `mod`; `PluginDetailPage` builds the href from the
  current URL (preserving `server`/`type`/`q`, forcing `type` from the loader
  knowledge, dropping `page`).
- **Tests**: backend — provider single-loader-facet (plugin + mod, replaces
  not combines the OR-list) + invalid-loader-ignored + route passthrough
  (`loader` omitted → `None`); frontend — api loader param, CompatibilityCard
  link-vs-span pills, `platformProjectType` map, detail-page pill
  hrefs, marketplace `?loader=` tag render + clear.
- **Verification**: backend 37 passed (providers/API marketplace) + 30 route
  contract; frontend 44 (detail/marketplace/compat) + 13 api + 21
  cards/versions; `tsc` clean; eslint 0 errors; ruff baseline unchanged for
  touched files (only ARG001/B008 FastAPI-pattern pre-existing violations,
  line numbers shifted).
---

## ADDENDUM — Real brand platform icons (F-19 icon pass)

- **Finding**: platform pills were showing generic `download` glyphs for every
  loader, and the in-app `modrinth`/`curseforge` marks were hand-drawn
  placeholders, not the real brand logos.
- **Icons (frontend `Icon.tsx`)**: swapped `modrinth` and `curseforge` for the
  real marks (official Modrinth logo 512×514 from
  `modrinth/code/packages/assets/branding/logo.svg`; official CurseForge
  C-mark 260×256 via svgl). Added the 12 official loader marks verbatim from
  Modrinth's own tag set (`modrinth/code/packages/assets/icons/tags/loaders/*.svg`):
  paper, spigot, purpur, bukkit, folia, fabric, forge, neoforge, quilt,
  velocity, bungeecord, waterfall. Because several use non-24×24
  viewBoxes (spigot 332×284, bukkit 292×319, velocity 500×500, neoforge
  100×100), `Icon` gained a per-name `VIEWBOX` override map; stroke-based
  loaders keep `currentColor`, filled marks pin `stroke="none"` so they color
  via CSS like every other icon.
- **Pills**: `CompatibilityCard` `LOADER_DISPLAY` now maps each loader to its
  real icon (plus velocity/bungeecord/waterfall, previously missing) and
  renders `<Icon size={11}>` inside both the plain-span and the link pill;
  `ProjectCard` (which already consumed `getLoaderDisplay`) picks up the real
  icons automatically; the marketplace `?loader=` filter tag also shows the
  loader icon.
- **Tests**: `Icon.test.tsx` covers all 12 loader icons rendering;
  `CompatibilityCard.test.tsx` asserts the pill's inner `<svg>` (including
  `aria-hidden`). Full suite: 553 frontend tests passing; `tsc` clean for
  touched files; eslint 0 errors (only pre-existing react-refresh warnings).

---

## ADDENDUM — Detail page cleanups (2026-08-20)

- **Game Versions row removed**: the "Game Versions" DetailRow was dropped from
  the Information sidebar in `PluginDetailPage.tsx` (`groupGameVersions`
  import tidied; the CompatibilityCard's own "Minecraft: Java Edition" pills
  are untouched). Test replaced with a "does not render Game Versions row"
  assertion.
- **Author now actually populated**: Modrinth's API no longer returns
  `author` on the project payload — it returns a `team` id. The provider's
  `get_project` was mapping `data.get("author", "")`, so the Author row always
  rendered empty. Now `get_project` falls back to the team endpoint
  (`/team/{id}/members`), picks the Owner's `user.username`, and degrades to
  `""` if the team lookup fails. Search hits already carried `author`, so
  cards were unaffected. Two new provider tests cover the owner resolution and
  the failure fallback.

---

## ADDENDUM — Platform single source of truth + safe HTML rendering (2026-08-20)

- **New `frontend/src/server_manager/data/platforms.ts`** is the one source of
  truth for every platform/loader the app displays: `label`, real `icon`,
  brand `color`, marketplace `projectType`, picker `description` and `kind`.
  Consumers (`CompatibilityCard`, `PluginDetailPage`, the software picker,
  tests) all read from it instead of each keeping their own map.
  `CompatibilityCard`'s `LOADER_DISPLAY`/`PLATFORM_PROJECT_TYPE` maps were
  removed; `getLoaderDisplay` now reads `getPlatformInfo`; `platformProjectType`
  lives in the data module and is imported directly by `PluginDetailPage`.
- **Missing platform tags fixed**: `datapack` and `vanilla` loaders now have
  real icons in `Icon.tsx` (official Modrinth datapack/vanilla pickaxe glyph,
  20×20 viewBox), so no known platform renders with the generic fallback glyph.
  `minestom` has no official loader mark, so it keeps the neutrally-colored
  fallback and is excluded from the "real icon" assertion accordingly.
- **Unloaded photos / leaked HTML in Modrinth descriptions**: the description
  bodies are raw HTML, and `react-markdown` strips raw HTML unless
  `rehype-raw` is present — which is why inline `<img>` screenshots never
  loaded and markup like `<details>`/`<br>` leaked or vanished. Installed
  `rehype-raw` + `rehype-sanitize`, and wired both into the description
  `ReactMarkdown` in `PluginDetailPage.tsx`. `rehype-sanitize`'s default
  schema keeps the safe content (`img`, `details`, `summary`, tables, code)
  while stripping scripts, event handlers and `style` attributes.
- **"Choose Server Software" picker now uses brand icons**: `SoftwareStep` in
  `CreateServerPage.tsx` renders each software card with a large (24px) colored
  brand icon in a tinted square plus a platform-kind badge, sourced from the
  same `platforms.ts` data — no per-card hardcoding.
- **Tests**: new `platforms.test.ts` locks the invariants (every backend
  software key and marketplace loader resolves to a known label + real icon +
  valid color; project-type mapping; graceful fallback). `CreateServerPage` and
  `CompatibilityCard` tests updated/passing. Full frontend suite 554/554
  (553 + 1 new file bundling 4 tests) passing; eslint 0 errors.
- **Styled tables in description bodies**: markdown and raw-HTML `<table>`s in
  plugin descriptions previously rendered as bare, unstyled `prose` tables.
  `markdownComponents` in `PluginDetailPage.tsx` now overrides `table`, `thead`,
  `th`, `tr`, `td` to render a responsive card-style table — rounded border,
  uppercase header band, zebra striping, padded cells, horizontal scroll wrapper
  on narrow screens, dark-mode aware. GFM tables and raw-HTML `<table>` bodies
  (e.g. Veinminer's command/settings tables) both get the treatment. Two new
  tests cover the styled GFM table and a raw-HTML `<table>` body.
- **Styled tables — revised (bolder)**: after user reported tables still read as
  unstyled, the markdown table overrides in `PluginDetailPage.tsx` were redone
  with a clearly visible card design: outer wrapper with visible `border` +
  `rounded-lg` + `overflow-x-auto`, slate header band (`bg-slate-100`) with
  `font-bold` uppercase `th` and a thick `border-b-2` divider, per-row
  `border-b` dividers, and generous `px-3.5 py-2.5` cell padding. Dropped the
  earlier `odd/even` zebra (it counted the thead row incorrectly). Verified via
  render-check that both GFM and raw-HTML `<table>` bodies emit the styled
  markup, and confirmed the old production `dist/` (built 2026-08-19, stale)
  was rebuilt with `vite build` so it no longer serves the pre-style bundle.
  Tests updated (13 passing) to assert the new classes; eslint clean.
