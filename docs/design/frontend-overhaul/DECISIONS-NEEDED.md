# Frontend Overhaul: Decisions Needed

This document records non-blocking decisions, conservative choices made during autonomous execution, and architectural items logged for future owner review.

---

## 1. RegisterPage vs InvitePage Token Verification Consolidation
- **Status**: SPEC-WORTHY ITEM / LOGGED & DEFERRED
- **Context**: The Stage 2 audit suggested merging invite-token redemption in `RegisterPage.tsx` into `InvitePage.tsx`.
- **Finding**: Merging invite-token redemption alters the public-facing authentication and invitation registration flow.
- **Decision Taken**: Per prompt non-negotiables, this flow is **NOT merged** during this overhaul. Both `RegisterPage.tsx` and `InvitePage.tsx` retain their existing routing and registration contracts. A dedicated spec is recommended before altering auth behaviors.

---

## 2. Default Density for Application Routes
- **Status**: CONSERVATIVE CHOICE TAKEN
- **Decision**: Per D8, density is mapped per-template:
  - Tables & high-throughput explorers (Servers Fleet, File Explorer, Activity Log): **Compact** (`--density-padding-row: 0.375rem`, 32px height).
  - Forms, Wizards, and Editors (Settings, Create Server Wizard, Auth): **Comfortable** (`--density-padding-card: 1.25rem`, 40px input height).
  - Global default at root: `comfortable`, with component templates overriding via CSS variables or `data-density` contexts without mixing densities on a single action surface.
- **Alternative**: Global toggle in user menu allowing user preference override. The architecture provides the `data-density` attribute on `<html>` to support this seamlessly.

---

## 3. Monaco Editor vs In-House CodeEditor
- **Status**: RESOLVED PER ADR-0021 D3
- **Decision**: Keep the lightweight in-house `CodeEditor.tsx` (syntax-highlighted textarea overlay, ~332 LOC) instead of adding Monaco Editor. Monaco adds ~2.5–4.5MB uncompressed payload, requiring complex Web Worker bundling and breaking the zero-new-dependencies rule.

---

## 4. System Font Stacks vs External Fonts
- **Status**: CONSERVATIVE CHOICE TAKEN
- **Decision**: Use robust modern system font stacks behind tokens (`font-sans`: `system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`, `font-mono`: `'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace`). Avoid external runtime downloads to ensure zero external network calls and 100% offline self-hosted operation.

---

## 5. Border Contrast Policy & Token Calibrations
- **Status**: CONSERVATIVE CHOICE TAKEN / LOGGED FOR OWNER DECISION
- **Context**: Non-text contrast compliance (WCAG AA 2.1 SC 1.4.11) requires a minimum 3.0:1 contrast ratio between functional boundaries and adjacent background surfaces.
- **Decision Taken**: Enforced a strict minimum 3.0:1 contrast ratio for all structural border tokens (`--border-default`, `--border-strong`, `--border-focus`) against all structural background surfaces (`--surface-page`, `--surface-card`, `--surface-elevated`, `--surface-muted`) across all skin (`graphite`, `azure`) and mode (`dark`, `light`) combinations. Calibrated `--border-default` in dark mode:
  - Graphite dark `--border-default`: adjusted from `#686868` (2.72:1 vs elevated) to `#707070` (3.06:1 vs elevated, preserving pure neutral $R=G=B=112$).
  - Azure dark `--border-default`: adjusted from `#606b7d` (2.71:1 vs elevated) to `#687385` (3.05:1 vs elevated).
  - Explicitly excluded decorative `--border-subtle` (low-contrast dividers to prevent visual noise) and transient `--surface-hover` / `--surface-active` surfaces (where interactive luminosity shifts provide feedback).
- **Alternative for Owner**: The owner may opt to leave borders as is (restoring `#686868` / `#606b7d`) if softer visual outlines are preferred, or adjust the dark surface elevation ladder instead of the border tokens.

---

## 6. Palette Ratchet Allowlist Cap Adjustments (F2-2)
- **Status**: CONSERVATIVE CHOICE TAKEN / LOGGED FOR OWNER DECISION
- **Context**: In review fix F2-2, `paletteRatchet.test.ts` was expanded to inspect all CSS property prefixes (`bg|text|border|ring|fill|stroke|outline|divide|from|via|to|shadow|accent|caret|decoration`) across all 22 Tailwind color families (gray, slate, zinc, neutral, stone, red, orange, amber, yellow, lime, green, emerald, teal, cyan, sky, blue, indigo, violet, purple, fuchsia, pink, rose).
- **Decision Taken**: The expanded regex captured pre-existing raw color classes that previous scans did not detect (e.g. gradient stops `to-gray-900`, `from-stone-900`, SVG fill `fill-gray-400`). To keep the ratchet passing without altering UI visuals or raising caps silently, caps were adjusted in `ALLOWLIST`:
  - `LoaderBadge.tsx`: 45 -> 60 (SVG animation spinner and multi-stop gradient classes).
  - `StartingMonitorBanner.tsx`: 35 -> 55 (multi-stage progress bar gradient stops and markers).
  - `ServerModsPage.tsx`: 15 -> 25 (mod-type badge color accents and category tag indicators).
- **Alternative for Owner**: The owner may choose to lower these caps by refactoring the inline SVG gradients, complex spinner animations, and mod badges to use tokenized CSS variables or SVGs referencing CSS custom properties.

---

## 7. Modal Portal Deferred
- **Status**: CONSERVATIVE CHOICE TAKEN / LOGGED FOR OWNER DECISION
- **Context**: Portaling dialogs into `document.body` via `createPortal` decouples modal rendering from ancestor CSS transforms and local stacking contexts.
- **Decision Taken**: Deferred introducing `createPortal` in `Modal.tsx`. `Modal.tsx` currently renders in-place using `fixed inset-0 z-50` with high z-index and module-level body scroll locking (`lockBodyScroll`). Introducing React portals across the application shifts DOM event delegation and changes container queries across existing Vitest/JSDOM test suites.
- **Alternative for Owner**: The owner can choose to adopt `createPortal` in a dedicated batch if stacking context bugs emerge in complex layouts.

---

## 8. ConfirmDialog Initial Focus on Cancel for Danger Variant
- **Status**: CONSERVATIVE CHOICE TAKEN / LOGGED FOR OWNER DECISION
- **Context**: Destructive operations (such as server deletion or resetting configuration) carry high penalty if executed unintentionally via an accidental Enter/Space keypress.
- **Decision Taken**: In `ConfirmDialog.tsx`, when `variant="danger"`, initial focus automatically shifts to the Cancel button (`cancelButtonRef.current?.focus()`). Non-danger variants (`warning`, `info`) continue to focus the Confirm button by default.
- **Alternative for Owner**: The owner may configure explicit autofocus props per dialog instance if specific destructive dialogs require confirm-first keyboard workflows.

---

## 9. Overlay Migration to Modal Primitive (Batch F5 / N-02)
- **Status**: IN PROGRESS (16 overlays migrated across F5a, F5b, F5c-A, and N-02; remaining 10 overlays logged for triage/migration)
- **Context**: An initial audit revealed 28 `fixed inset-0` overlay implementations across 21 files that bypassed the shared `Modal.tsx` primitive, managing their own backdrops and key listeners independently.
- **Progress in Batch F5a, F5b, F5c-A & N-02 (16 Overlays Migrated)**:
  - **Batch F5a (6 overlays in `VersioningModals.tsx`)**: `CreateBranchModal`, `CreateCommitModal`, `PromoteModal`, `InspectCommitModal`, `ViewLogsModal`, `BotSettingsModal` (commit `8d1f127`). Added `closeOnBackdrop` prop.
  - **Batch F5b-1 (Close Guard on Form Modals)**: Added `closeOnEscape` prop to `Modal.tsx`. Guarded `CreateBranchModal`, `CreateCommitModal`, `PromoteModal`, and `BotSettingsModal` with `closeOnEscape={!isPending}` and disabled dismissal actions while in-flight (commit `c09e288`).
  - **Batch F5b-2 (4 overlays migrated)**:
    1. `frontend/src/server_manager/components/CreateTagModal.tsx` (commit `3774648`)
    2. `frontend/src/server_manager/components/BranchProtectionModal.tsx` (commit `3774648`)
    3. `frontend/src/server_manager/components/ManageBranchesModal.tsx` (commit `3774648`)
    4. `frontend/src/server_manager/components/CommitDiffModal.tsx` (commit `3774648`)
  - **Batch F5b-4 (Backdrop Dismissal Tests)**: Added backdrop dismissal tests for the 4 F5b-2 modals with mutation proof (commit `652fa2d`).
  - **Batch F5c-A (3 Versioning overlays migrated)**:
    1. `frontend/src/server_manager/components/TestRunModal.tsx` (commit `274135b`)
    2. `frontend/src/server_manager/components/TestEvidenceModal.tsx` (commit `274135b`)
    3. `frontend/src/server_manager/components/TestDefinitionsModal.tsx` (commit `274135b`)
  - **Batch N-02 / F5c-B (3 overlays migrated)**:
    1. `frontend/src/server_manager/components/ImportReviewModal.tsx`
    2. `frontend/src/server_manager/components/CrashReportViewerModal.tsx`
    3. `frontend/src/server_manager/components/MaterializationBrowserModal.tsx`
  - **Batch N-03 / F5d-1 (3 overlays migrated)**:
    1. `frontend/src/server_manager/components/InstallModal.tsx`
    2. `frontend/src/server_manager/components/AddCompanionTargetModal.tsx`
    3. `frontend/src/server_manager/components/EditPublicAddressModal.tsx`
  - **Batch N-04 / F5d-2 (7 inline overlays migrated)**:
    1. `frontend/src/server_manager/components/AccessModeCard.tsx` (Access mode switch confirm dialog)
    2. `frontend/src/server_manager/components/GlobalExposureActionsCard.tsx` (Emergency stop/reset typed confirmation dialog)
    3. `frontend/src/server_manager/components/InvitationsSection.tsx` (Generate invitation form dialog)
    4. `frontend/src/server_manager/components/PanelExposureSection.tsx` (Disable panel exposure confirm dialog)
    5. `frontend/src/server_manager/components/ServerExposureMethodSelector.tsx` (Exposure method switch typed confirmation dialog)
    6. `frontend/src/server_manager/components/TargetCard.tsx` (Remove companion target confirm dialog)
    7. `frontend/src/server_manager/pages/ServerExposurePage.tsx` (Disable server exposure confirm dialog)
- **Owner Decision (Escape Close Behavior on Form Modals)**:
  - **Applied Behavior**: "Escape now closes form modals; typed text is discarded (no dirty-form prompt); guard only while pending".
  - **Rationale**: Keeps modal UX predictable and accessible per WCAG dialog patterns without intrusive multi-step discard prompts, while protecting data integrity by blocking Escape dismissal while mutations are actively in-flight.
- **Remaining Bypassing Overlays (0 files, 0 occurrences)**:
  *(Computed by `grep -rl "fixed inset-0" frontend/src --include='*.tsx' | grep -v '\.test\.'`, excluding primitives `Modal.tsx` and `ConfirmDialog.tsx`, `SplashScreen.tsx`, and `Sidebar.tsx` mobile backdrop)*:
  - **Result: 0 bypassing overlays remain.** Every modal dialog in the application now utilizes the canonical `Modal` and `ConfirmDialog` primitives with scroll locking, accessible roles, and focus traps. Ratchet locked via `overlayRatchet.test.ts` (N-05).

---

## 10. CurseForge Marketplace Integration & Navigation Flow
- **Status**: RESOLVED (Option B applied by default in F5a; owner may revert)
- **Context**: Commit `c9b4f26` simplified the primary Sidebar by removing nested "Modrinth" and "CurseForge" sub-links under "Marketplace", directing the root item directly to `/marketplace` with default source `modrinth`.
- **Finding (Task 5 Investigation)**:
  1. The backend catalog infrastructure (`backend/app/infrastructure/plugin_catalog/`) currently implements only `ModrinthProvider`. `backend/tests/infrastructure/test_plugin_catalog_providers.py:54` explicitly asserts that `build_plugin_catalog_provider(name="curseforge")` raises `ValueError("Unknown plugin catalog provider")`.
  2. In the frontend, `PluginMarketplacePage.tsx` previously provided a segmented control in the `PageHeader` actions allowing users to switch between "Modrinth" and "CurseForge (Soon)".
  3. When "CurseForge" was selected, the page rendered `ComingSoonState` with title `"CurseForge Integration Coming Soon"`, badge `"Coming Soon"`, and a `"Switch to Modrinth"` button.
  4. In `Sidebar.tsx`, clicking the primary "Marketplace" nav link resets the store to `setSource("modrinth")`, ensuring entering the marketplace always shows active browseable Modrinth content.
  5. In task F5a, Option B was applied as the owner default: the segmented source switch on `PluginMarketplacePage.tsx` was removed so the marketplace defaults cleanly to Modrinth without dead-end switches. The owner may revert if desired.
- **Alternatives for Owner**:
  - **Option A (Keep Current State)**: Retain the segmented "CurseForge (Soon)" toggle on `PluginMarketplacePage` with the `ComingSoonState` placeholder until backend CurseForge API adapter (or CurseForge API key integration) is built.
  - **Option B (Hide Until Backend Ready - Applied by default)**: Remove the segmented toggle button on `PluginMarketplacePage` entirely until the backend CurseForge catalog provider is implemented, presenting `/marketplace` exclusively as Modrinth.
  - **Option C (Backend Adapter Implementation)**: Spec and implement `CurseForgeProvider` with API key configuration in backend and connect `PluginMarketplacePage` search to the CurseForge endpoint.

---

## 11. Native Browser Dialog (`window.confirm`) Elimination (Batch N-06)
- **Status**: RESOLVED (Implemented, pending independent review)
- **Context**: Prior to Batch N-06, two native `confirm(...)` calls remained in user-facing flows:
  1. `frontend/src/server_manager/components/MaterializationBrowserModal.tsx:225` (`Delete worktree snapshot '${activeMat.id}'?`)
  2. `frontend/src/server_manager/components/TestDefinitionsModal.tsx:113` (`Delete test profile '${name}'?`)
- **Resolution**: Both components were migrated to use the accessible design system primitive `<ConfirmDialog>` with asynchronous pending guards (`isDeleting`), role="dialog", focus trapping, and keyboard cancellation.
- **Verification**:
  - `git grep -n -E "window\.(confirm|alert|prompt)|\b(confirm|alert|prompt)\(" frontend/src | grep -v "\.test\."` returns 0 matches across the entire codebase.
  - Test suites updated with explicit `ConfirmDialog` interaction tests in `MaterializationBrowserModal.test.tsx` and `TestDefinitionsModal.test.tsx`.

---

## 12. Consolidated & Prioritized Owner-Decision Summary

The following decisions are consolidated and prioritized for repo owner review. Safe defaults have been applied in the implementation so the platform is fully functional and hardened, but the owner retains final authority on each item:

| Priority | Decision Topic | Current Applied Default | Owner Alternative Options | Relevant File(s) |
|:---|:---|:---|:---|:---|
| **P1** | **Form Modal Escape Behavior** | Escape closes form modals; typed form data is discarded; Escape is strictly blocked during pending mutations. | Owner may choose to introduce a dirty-form prompt ("Discard unsaved changes?"). | `src/components/ui/Modal.tsx` |
| **P2** | **ServerShell Provider Badge** | Retained in header strip (shows "Container" for Docker, "File" for Host process). | Owner may choose to hide provider badge or move it to ServerSettings. | `src/layouts/ServerShell.tsx:145` |
| **P3** | **CurseForge Marketplace Source** | Option B: Segmented toggle hidden; `/marketplace` defaults exclusively to Modrinth until backend catalog provider is built. | Owner may choose Option A (re-enable toggle showing "Coming Soon" state) or Option C (implement backend provider). | `src/server_manager/pages/PluginMarketplacePage.tsx` |
| **P4** | **Destructive Dialog Initial Focus** | Danger variants focus "Cancel" button by default to prevent accidental confirmation. Non-danger variants focus "Confirm". | Owner may configure instance-level autofocus if specific workflows require confirm-first keyboard flow. | `src/components/ui/ConfirmDialog.tsx:33-37` |
| **P5** | **Multi-Skin Palette Scope** | Shipped with "Graphite" (100% neutral gray, 0 channel spread) and "Azure" (modern slate blue), plus `skinValidator` contract. | Owner may introduce additional built-in skins (e.g. high-contrast, emerald). | `src/index.css`, `src/tokens/skinValidator.ts` |
| **P6** | **Brand Visual Assets** | Vortex vector swirl mark (`BrandLogo.tsx`), abstract voxel banners (`VoxelBanner.tsx`), favicon.svg. | Owner may replace SVG artwork with custom product logos. | `src/components/brand/` |

---

## 13. N-04 NEW behavior: Escape Dismissal Standardization
- **Status**: CONSERVATIVE CHOICE TAKEN / LOGGED FOR OWNER DECISION
- **Context**: During batch N-04, 7 inline overlays in the Server Exposure workflow were migrated to the canonical `Modal` primitive.
- **Escape Dismissal Changes**:
  - Pre-migration, only 2 of the 7 components had Escape listeners (`GlobalExposureActionsCard.tsx` and `ServerExposureMethodSelector.tsx`).
  - Five components had NO Escape dismissal pre-migration (only internal Cancel/Close buttons):
    1. `AccessModeCard.tsx`
    2. `InvitationsSection.tsx`
    3. `PanelExposureSection.tsx`
    4. `TargetCard.tsx`
    5. `ServerExposurePage.tsx`
  - In batch N-04, all 5 components gained Escape dismissal by default via `<Modal closeOnEscape={...}>` (standard WCAG dialog keyboard pattern).
  - For all 5 components, Escape dismissal is strictly blocked while mutations are in-flight (`isPending` / `isUpdating` / `isSettingExposureState`).
  - Backdrop dismissal remains strictly disabled (`closeOnBackdrop={false}`) across all 7 components to preserve their pre-migration behavior and prevent accidental dismissal.



