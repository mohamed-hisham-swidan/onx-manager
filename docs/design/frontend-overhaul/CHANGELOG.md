# Frontend Overhaul Changelog & Execution Record

This document records the full chronological history of changes implemented during the ONX Manager Frontend Overhaul.

---

## Batch Summary & Commits

| Batch ID | Phase | Commit | Primary Scope |
|---|---|---|---|
| **B0-Bootstrap** | Phase 0 | `483ec43` | Recorded ADR-0021 in repository HEAD and updated decisions index. |
| **B1-P1-Tokens** | Phase 1 | `5252a84` | Established semantic CSS custom property layer, Tailwind v4 `@theme`, and `uiStore` skin/density engine. |
| **B2-P2-Primitives** | Phase 2 | `3565755` | Created 18 token-driven shared UI primitives in `src/components/ui/` with unit test suites. |
| **B3-P3-Shells** | Phase 3 | `92af315` | Unified layout shells (`AppShell`, `ServerShell`, `TopBar`, `Sidebar`) and mounted global `OperationDrawer`. |
| **B4a-Fleet** | Phase 4 | `d845eb8` | Redesigned dashboard fleet status bar, table filtering with URL sync, and console tab re-tailing. |
| **B4b-Files** | Phase 4 | `f99f902` | Added client-side search filtering, directory pagination, and compact table styling to `ServerFilesPage`. |
| **B4c-Versioning** | Phase 4 | `b621907` | Decomposed 1,280 LOC `ServerVersioningPage` monolith into 5 modular components under `versioning/`. |
| **B4d-Wizard** | Phase 4 | `bd94068` | Decomposed 811 LOC `CreateServerPage` wizard monolith into 5 step components under `wizard/`. |
| **B4e-Addons-Auth** | Phase 4 | `4a84aa1` | Unified Add-ons views (`PluginListPage`, `ServerModsPage`), tokenized `SettingsPage`, `LoginPage`, and `RegisterPage`. |
| **B5-Ratchet** | Phase 5 | `8a8d677` | Migrated lingering components to semantic tokens and added automated palette ratchet test (`paletteRatchet.test.ts`). |
| **B6-Skins** | Phase 6 | `6ca0503` | Implemented full Graphite and Azure skins, pre-paint DOM attribute initialization, WCAG AA contrast verifier, and custom skin validator. |
| **B7-Brand** | Phase 7 | `27afa46` | Designed original vortex logo, isometric voxel banners, custom domain icons, and mounted legal disclaimers. |
| **B8-Motion** | Phase 8 | `737ea42` | Added restrained motion tokens, density controls, focus-visible outline, and accessibility verification (`accessibilityMotion.test.tsx`). |
| **B9-Perf-Docs** | Phase 9 | *In-Progress* | Route-level code-splitting with `React.lazy`, comprehensive design docs, and CI gate verification. |

---

## Detailed Batch Log

### Batch 0: Bootstrap & ADR-0021 (`483ec43`)
- Integrated Architecture Decision Record `0021-frontend-ux-ia-overhaul-token-system.md` into repository tree.
- Baseline verification established: 97 test files, 797 unit tests passing.

### Batch 1: Semantic Token Foundation (`5252a84`)
- Created semantic token structure in `src/index.css` covering surfaces, text, borders, accents, and status triplets.
- Registered all tokens in Tailwind CSS v4 `@theme` block.
- Implemented `uiStore.ts` managing `skin` (`graphite` | `azure`), `mode` (`dark` | `light`), and `density` (`compact` | `comfortable`), writing directly to `<html>` data attributes.

### Batch 2: UI Primitives Suite (`3565755`)
- Built and tested 18 reusable design system primitives:
  - Navigation & Dialogs: `Modal`, `ConfirmDialog`, `Tabs`, `Pagination`, `PageHeader`.
  - Content Presentation: `Table`, `Banner`, `Chip`, `StatusBadge`, `LoaderBadge`, `StatCard`.
  - Feedback & States: `EmptyState`, `ErrorState`, `Skeleton`, `ForbiddenState`, `LoadingBar`, `Toaster`.
  - Actions: `Button`, `IconButton`.

### Batch 3: Shell Architecture & Navigation (`92af315`)
- Unified page wrappers into `AppShell` and `ServerShell`.
- Implemented `TopBar` with live WebSocket status pill, operations drawer toggle, and skin/density menu.
- Standardized `Sidebar` to serve as both global and server-scoped navigation, eliminating duplicate sidebar logic.
- Mounted `OperationDrawer` with cached selector optimization.

### Batch 4a: Dashboard & Fleet Management (`d845eb8`)
- Replaced the 10-card rainbow grid on the dashboard with a clean, density-aware Fleet Status Bar (`StatusOverviewCards.tsx`).
- Updated `ServersPage.tsx` table to adhere to ADR-0021 D2 columns: Status, Server Name, Software/Version, Port, and Quick Actions.
- Synced status filter pills with URL query parameters (`?status=...`).
- Added visibility change listener to `ServerConsole.tsx` to automatically re-fetch missed log lines upon tab reactivation.

### Batch 4b: File Browser UX Improvements (`f99f902`)
- Implemented real-time client-side filename filtering in `ServerFilesPage.tsx`.
- Added client-side directory pagination for directories with large file counts.
- Applied compact table density and token styling while preserving slide-over `CodeEditor.tsx`.

### Batch 4c: Server Versioning Decomposition (`b621907`)
- Decomposed monolithic 1,280 LOC `ServerVersioningPage.tsx` into 5 single-responsibility sub-components:
  - `StorageHealthBanner.tsx`
  - `BranchToolbar.tsx`
  - `CommitTimeline.tsx`
  - `TestRunList.tsx`
  - `VersioningModals.tsx`
- Reduced main page orchestrator to 607 LOC.

### Batch 4d: Create Server Wizard Decomposition (`bd94068`)
- Decomposed monolithic 811 LOC `CreateServerPage.tsx` into 5 modular step components:
  - `SoftwareStep.tsx`
  - `VersionStep.tsx`
  - `ConfigStep.tsx`
  - `PropertiesStep.tsx` (advanced server properties collapsed by default)
  - `ReviewStep.tsx`
- Reduced main wizard orchestrator to 273 LOC.

### Batch 4e: Unified Add-ons, Settings & Auth (`4a84aa1`)
- Standardized `PluginListPage.tsx` and `ServerModsPage.tsx` onto the shared Fleet/List template with `EmptyState`, `ErrorState`, and `Pagination`.
- Tokenized all 6 sections of `SettingsPage.tsx` (`Profile`, `Appearance`, `Security`, etc.).
- Tokenized `LoginPage.tsx` and `RegisterPage.tsx`.

### Batch 5: Color Migration & Palette Ratchet (`8a8d677`)
- Migrated all remaining UI components away from raw Tailwind color utilities (`bg-gray-800`, `text-blue-400`) to semantic design tokens.
- Implemented `paletteRatchet.test.ts` scanning `frontend/src/` to ensure zero unallowlisted hardcoded hex or raw color classes.

### Batch 6: Multi-Skin Engine & Contrast Verification (`6ca0503`)
- Implemented pure neutral black **Graphite** skin (0% blue chroma on all neutral tokens) and classic **Azure** slate-blue skin.
- Added synchronous pre-paint DOM attribute initialization in `main.tsx` using shared storage keys to eliminate theme flash safely without inline scripts.
- Created programmatic WCAG AA contrast ratio test (`contrast.test.ts`) that parses real token definitions directly from `frontend/src/index.css` and computes WCAG 2.x relative luminance ratios (not Euclidean distances) across all skin/mode pairs, with an explicit documented exclusion for `--border-subtle` decorative separators.
- Implemented zero-dependency JSON custom skin validator contract (`skinValidator.ts` & `skinValidator.test.ts`) with prototype-pollution guards, root-key allowlists, and size capping.

### Batch 7: Brand Identity & Domain Icons (`27afa46`)
- Created original vector brand lockup (`BrandLogo.tsx`) featuring an abstract geometric vortex swirl.
- Designed abstract isometric voxel banners (`VoxelBanner.tsx`) and application splash screen (`SplashScreen.tsx`).
- Created themed domain icon set in `Icon.tsx` (`server`, `world`, `plugin`, `mod`, `backup`, `console`, `files`, `network`, `version-branch`).
- Added official non-Mojang affiliation legal disclaimer to `Sidebar.tsx` and auth pages.

### Batch 8: Motion, Density & Accessibility Polish (`737ea42`)
- Introduced motion tokens (`--motion-duration-*`, `--motion-ease-standard`) and global `prefers-reduced-motion` override.
- Enforced density hierarchy tokens (`compact` vs `comfortable`).
- Standardized global `:focus-visible` outline rings with `--border-focus`.
- Added accessibility verification test suite (`accessibilityMotion.test.tsx`).

---

## Overnight Closure Run Batches (N-01 to N-18)

| Batch ID | Commit | Description | Verification |
|:---|:---|:---|:---|
| **N-01** | `a1ee645` | Gate React Query Devtools floating button behind `VITE_QUERY_DEVTOOLS === 'true'`. | Clean dev bundle, devtools opt-in |
| **N-02** | `0944f8f` | Migrate `ImportReviewModal`, `CrashReportViewerModal`, `MaterializationBrowserModal` to `Modal`. | 11/11 tests pass, pending guards wired |
| **N-03** | `8d9ecbd` | Migrate `InstallModal`, `AddCompanionTargetModal`, `EditPublicAddressModal` to `Modal`. | 29/29 tests pass across 3 suites |
| **N-04** | `f2ea87e` | Migrate all 7 remaining inline dialogs (`AccessModeCard`, `GlobalExposureActionsCard`, `InvitationsSection`, `PanelExposureSection`, `ServerExposureMethodSelector`, `TargetCard`, `ServerExposurePage`) to `Modal`. | 0 bypassing raw overlays remaining |
| **N-05** | `d3adaa2` | Implement automated `overlayRatchet.test.ts` enforcing zero raw `fixed inset-0` dialogs repo-wide. | 3/3 overlay ratchet tests pass |
| **N-06** | `bd42b68` | Eliminate native `window.confirm` calls; replace with `<ConfirmDialog>` in Versioning modals. | 0 native dialogs remaining |
| **N-07** | `4af5441` | Document comprehensive `FINDINGS-LEDGER.md` reconciling all 33 audit and review items. | 26 CLOSED, 5 OWNER-DECISION, 2 BACKEND-DEPENDENT |
| **N-08** | Verified | Audit WCAG AA contrast computation and prove mutant kill in `/tmp`; report 0 channel spread on Graphite surfaces. | Mutation proof verified, test fails on mutant |
| **N-09** | `6913c6c` | Audit palette ratchet allowlist and ratchet down 5 caps by -115 total allowance. | 5/5 palette ratchet tests pass |
| **N-10** | `acfd0a4` | Add unmount/remount navigation test proving zero duplicate console viewports. | 21/21 console tests pass |
| **N-11** | `720ba9d` | Update files filter label to "Filter files in folder..." and clarify client pagination in docs. | 12/12 files tests pass |
| **N-12** | `7991d28` | Standardize `ApiKeysPage`, `BackupListPage`, `PluginMarketplacePage`, `PluginDetailPage` on `States` primitives. | 51/51 tests pass, 6/6 CI gates PASS |
| **N-13** | `d36a45c` | Add ARIA live regions to `Toaster` and accessible labels to file inputs. | 13/13 accessibility tests pass |
| **N-14** | `e5b4b33` | Add modal focus restoration, Tab/Shift+Tab cycling, and stacked dialog unit tests. | 15/15 Modal tests pass |
| **N-15** | `4de3431` | Remove unused `CardSkeleton` and ratchet down `Skeleton.tsx` cap from 25 to 15. | 4/4 Skeleton tests pass |
| **N-16** | `bcdeb61` | Safely resolve all ESLint warnings with strict typing and clean dependencies. | 0 ESLint errors, 0 warnings |
| **N-17** | Verified | Measure production bundle: 39 JS chunks, largest chunk 396.68 kB. | Build clean in 5.28s |
| **N-18** | (current) | Comprehensive docs truth pass across design docs, primitives specification, and consolidated decision summary. | All identifiers and numbers verified |

