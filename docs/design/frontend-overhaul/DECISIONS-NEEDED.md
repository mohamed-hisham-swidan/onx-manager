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

## 9. Overlay Migration to Modal Primitive (Planned Batch F5)
- **Status**: PLANNED FOR BATCH F5 / LOGGED FOR OWNER DECISION
- **Context**: An audit revealed 28 `fixed inset-0` overlay implementations across 21 files that currently bypass the shared `Modal.tsx` primitive, managing their own backdrops and key listeners independently.
- **Decision Taken**: Left these 28 overlays unmigrated in batch F4a (which focused strictly on primitive fixes and targeted accessible button fixes) to keep changes isolated and testable without risking modal regressions across major workflows. Logged for systematic consolidation in planned Batch F5.
- **Files with Bypassing Overlays (21 files, 28 occurrences)**:
  1. `frontend/src/server_manager/components/AccessModeCard.tsx`
  2. `frontend/src/server_manager/components/AddCompanionTargetModal.tsx`
  3. `frontend/src/server_manager/components/BranchProtectionModal.tsx`
  4. `frontend/src/server_manager/components/CommitDiffModal.tsx`
  5. `frontend/src/server_manager/components/CrashReportViewerModal.tsx`
  6. `frontend/src/server_manager/components/CreateTagModal.tsx`
  7. `frontend/src/server_manager/components/EditPublicAddressModal.tsx`
  8. `frontend/src/server_manager/components/GlobalExposureActionsCard.tsx`
  9. `frontend/src/server_manager/components/ImportReviewModal.tsx`
  10. `frontend/src/server_manager/components/InstallModal.tsx`
  11. `frontend/src/server_manager/components/InvitationsSection.tsx`
  12. `frontend/src/server_manager/components/ManageBranchesModal.tsx`
  13. `frontend/src/server_manager/components/MaterializationBrowserModal.tsx`
  14. `frontend/src/server_manager/components/PanelExposureSection.tsx`
  15. `frontend/src/server_manager/components/ServerExposureMethodSelector.tsx`
  16. `frontend/src/server_manager/components/TargetCard.tsx`
  17. `frontend/src/server_manager/components/TestDefinitionsModal.tsx`
  18. `frontend/src/server_manager/components/TestEvidenceModal.tsx`
  19. `frontend/src/server_manager/components/TestRunModal.tsx`
  20. `frontend/src/server_manager/components/versioning/VersioningModals.tsx` (6 overlays)
  21. `frontend/src/server_manager/pages/ServerExposurePage.tsx`
- **Alternative for Owner**: The owner may choose to migrate all 28 overlays to `Modal.tsx` in batch F5 or retain specialized full-screen diff and console inspection overlays as standalone components.

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

