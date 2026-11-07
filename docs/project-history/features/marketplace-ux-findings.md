# Marketplace UX & Theming Findings (2026-08-07)

Source: live user testing session + independent code investigation.
Status: HISTORICAL / CLOSED (2026-08-09). Issues #1 and #5 were shipped directly. Issues #2, #3, and the Modrinth half of #4 were SUPERSEDED by `docs/history/marketplace-redesign-v2.md` and completed across Batches A–F. The CurseForge backend integration (other half of #4) remains open/deferred.

## Issue 1 — Marketplace opens empty, no default browse content [CLOSED]
**Status: CLOSED (Commit `472ca526ee1e4148dca6d18c6a66fbaa064881a8`)**

- `PluginMarketplacePage.tsx`: empty query fetch enabled. Modrinth search API returns default popular/trending items on initial load.

## Issue 2 — Recommendation system: two different things, one missing entirely, one built-but-unwired [SUPERSEDED]
**Status: SUPERSEDED by `docs/history/marketplace-redesign-v2.md` (Completed in Batches A & F)**

- Best-version recommendation wired into `InstallModal.tsx` and version sorting updated to semver-aware `version_number` ordering.

## Issue 3 — Install flow is inverted and has no server-first auto-select [SUPERSEDED]
**Status: SUPERSEDED by `docs/history/marketplace-redesign-v2.md` (Completed in Batch F — Commit `5a207a9ef14a5568efce40313d6f2c1886d4f1ef`)**

- Replaced inline install flow with `InstallModal.tsx`: server resolved/auto-selected first, version list fetched for that server, closed-by-default version dropdown.

## Issue 4 — No Mods support (Fabric/Forge) — marketplace is Bukkit-only [PARTIALLY SUPERSEDED / OPEN]
**Status: Modrinth Mod Support COMPLETE (Batches B, C, D — Commit `a192656`, `a5c3917`, `14c2f96`). CurseForge Backend Integration OPEN / DEFERRED.**

- Modrinth provider parameterized to query mods and plugins dynamically (`projectType`).
- "Discover" dropdown added to select Mods vs Plugins.
- **CurseForge Backend Integration:** Remains unaddressed/open as a deferred feature. UI placeholder ("Coming Soon") added in Batch C.

## Issue 5 — Light mode is broken (Tailwind v4 config gap) [CLOSED]
**Status: CLOSED (Commit `8240c1c28b8af2de1e57a09171671b3dcd8212bb`)**

- Added `@custom-variant dark (&:where(.dark, .dark *));` to `frontend/src/index.css`.

## Summary table

| # | Issue | Status | Resolution / Commit Hash |
|---|---|---|---|
| 1 | Empty marketplace on load | CLOSED | Commit `472ca526ee1e4148dca6d18c6a66fbaa064881a8` |
| 2 | Version recommendation unused | SUPERSEDED | Redesign v2 (Batches A & F) |
| 2b | No plugin recommendation engine | DEFERRED | Future scope |
| 3 | Inverted install flow | SUPERSEDED | Redesign v2 Batch F (`5a207a9ef14a5568efce40313d6f2c1886d4f1ef`) |
| 4a | Modrinth Mod Support | CLOSED | Redesign v2 Batches B/C/D |
| 4b | CurseForge Backend Integration | OPEN / DEFERRED | UI placeholder in Batch C; backend deferred |
| 5 | Light mode broken | CLOSED | Commit `8240c1c28b8af2de1e57a09171671b3dcd8212bb` |

