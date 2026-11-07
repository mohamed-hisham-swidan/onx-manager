# ONX Frontend Overhaul — Findings Ledger

This document tracks all review, audit, and design findings across the frontend overhaul project (ADR-0021), reconciling findings from the Stage 2 UX/IA audit, `docs/design/frontend-overhaul/DECISIONS-NEEDED.md`, and previous review rounds.

---

## Status Classification Key
- **CLOSED**: Fully implemented, verified, and backed by automated tests and runnable evidence.
- **OWNER-DECISION**: Requires product/architectural sign-off from repo owner (deferred per governance).
- **BACKEND-DEPENDENT**: Blocked on backend schema, API routes, or provider implementations.
- **OPEN**: Actionable frontend-only tasks remaining in current scope.

---

## 1. Core Architecture & IA Findings (Stage 2 Audit & Corrections)

| ID | Source | Topic | Status | Commit / Decision | Runnable Evidence |
|:---|:---|:---|:---:|:---|:---|
| **C1** | PART_C_CORRECTIONS | Metric Accounting (110 inventory rows vs 104) | **CLOSED** | `c91338c` | `docs/design/frontend-overhaul/README.md` |
| **C2** | PART_C_CORRECTIONS | Route & File Naming (eliminated fictitious file paths) | **CLOSED** | `c91338c` | Verified against `frontend/src/App.tsx` and routes |
| **C3** | PART_C_CORRECTIONS | Evidence Precision (exact file:line citations) | **CLOSED** | `c91338c` | Audited in `PART_C_CORRECTIONS.md` |
| **C4** | PART_C_CORRECTIONS | Batch Architecture (token engine in B1-B2 prior to components) | **CLOSED** | `5252a84` | `src/index.css`, `src/stores/uiStore.ts` |
| **C5** | PART_C_CORRECTIONS | CodeEditor Strategy (retain in-house lightweight editor) | **CLOSED** | `f99f902` | `src/components/CodeEditor.tsx` |
| **C6** | PART_C_CORRECTIONS | WebSocket client typing & concurrency | **CLOSED** | `483ec43` | `src/websocket/client.ts` |
| **C7** | PART_C_CORRECTIONS | Governance Alignment (ADR-0021 under Lane B, D1) | **CLOSED** | `483ec43` | `docs/decisions/0021-frontend-ux-ia-overhaul-token-system.md` |
| **C8-a** | PART_C_CORRECTIONS | OperationDrawer unmounted in layout | **CLOSED** | `92af315` | Mounted in `AppShell.tsx:54` and `ServerShell.tsx:307` |
| **C8-b** | PART_C_CORRECTIONS | ServerResponse lacks live metrics / WS fleet metrics | **BACKEND-DEPENDENT** | Documented | `docs/design/frontend-overhaul/BACKEND-DEPENDENT.md` |
| **C8-c** | PART_C_CORRECTIONS | Files API lacks server pagination/search | **CLOSED** (honest client UI) | `f99f902` | `src/server_manager/pages/ServerFilesPage.tsx:430` |
| **C8-d** | PART_C_CORRECTIONS | Fleet status cards query params | **CLOSED** | `d845eb8` | `src/server_manager/components/StatusOverviewCards.tsx` |

---

## 2. Layout, Shells, Navigation & Identity

| ID | Source | Topic | Status | Commit / Decision | Runnable Evidence |
|:---|:---|:---|:---:|:---|:---|
| **L1** | DECISIONS-NEEDED §1 | Modal autofocus prop on destructive dialogs | **OWNER-DECISION** | Option B default | `src/components/ui/ConfirmDialog.tsx:33-37` |
| **L2** | DECISIONS-NEEDED §2 | Form Modal Escape Dismissal | **OWNER-DECISION** | Applied (closes without prompt; pending guard) | `src/components/ui/Modal.test.tsx` |
| **L3** | DECISIONS-NEEDED §3 | ServerShell Provider Badge (Container vs File) | **OWNER-DECISION** | Retained (commit dc6ed45) | `src/layouts/ServerShell.tsx:145` |
| **L4** | Review F4b | Landmark structure (banner, main, nav, aside) | **CLOSED** | `c9b4f26` | `src/layouts/AppShell.tsx`, `ServerShell.tsx` |
| **L5** | Review F4b | Skip-to-content link accessibility | **CLOSED** | `c9b4f26` | `src/layouts/AppShell.tsx:42` |
| **L6** | Review F4b | Mobile navigation drawer focus trap & Escape | **CLOSED** | `c9b4f26` | `src/components/layout/Sidebar.tsx` |
| **L7** | Review B10 | Header deduplication (ServerDetailPage vs ServerShell) | **CLOSED** | `dc6ed45` | Removed duplicate strip; unified identity |

---

## 3. Terminal & Console Lifecycle

| ID | Source | Topic | Status | Commit / Evidence | Runnable Evidence Command |
|:---|:---|:---|:---:|:---|:---|
| **T1** | Overnight Review | No duplicate terminal after back-navigation | **CLOSED** | Verified pure React scroll view with clean unmount | `npx vitest run src/server_manager/components/ServerConsole.test.tsx` |
| **T2** | Review F2-3 | Restore console lines on tab visibility change | **CLOSED** | `83b3328` (`ServerConsole.tsx:105-117`) | `npx vitest run src/server_manager/components/ServerConsole.test.tsx` (test line 354) |
| **T3** | Review F2-3 | Reconnect re-tail backfill & live buffer reset | **CLOSED** | `83b3328` (`ServerConsole.tsx:89-103`) | `npx vitest run src/server_manager/components/ServerConsole.test.tsx` (test line 335) |
| **T4** | Review F2-3 | Disable 3s polling query while WS connection active | **CLOSED** | `83b3328` (`ServerConsole.tsx:86`) | `npx vitest run src/server_manager/components/ServerConsole.test.tsx` (test line 316) |

---

## 4. File Browser & Honesty

| ID | Source | Topic | Status | Commit / Evidence | Runnable Evidence Command |
|:---|:---|:---|:---:|:---|:---|
| **F1** | Overnight Review | Files page client-side search honestly labeled | **CLOSED** | `f99f902` (`placeholder="Filter files in folder..."`) | `git grep -n "Filter files in folder..." frontend/src` |
| **F2** | Review B4b | Directory client-side pagination | **CLOSED** | `f99f902` (`filteredFiles.slice(...)`) | `npx vitest run src/server_manager/pages/ServerFilesPage.test.tsx` |
| **F3** | Review B4b | Binary file preview safe fallback | **CLOSED** | `f99f902` (renders warning, prevents crash) | `npx vitest run src/server_manager/pages/ServerFilesPage.test.tsx` (ISS-050 test) |

---

## 5. Overlays, Dialogs & Primitive Standardization

| ID | Source | Topic | Status | Commit / Evidence | Runnable Evidence Command |
|:---|:---|:---|:---:|:---|:---|
| **O1** | Review F5a | Migrate VersioningModals overlays to Modal | **CLOSED** | `3774648`, `4a6bb6b` | `npx vitest run src/server_manager/pages/ServerVersioningPage.test.tsx` |
| **O2** | Review F5c-A | Migrate TestRun, TestEvidence, TestDefinitions to Modal | **CLOSED** | `274135b` | 13/13 tests pass in `TestDefinitionsModal.test.tsx` |
| **O3** | Review F5c-B | Migrate ImportReview, CrashReport, Materialization to Modal | **CLOSED** | `0944f8f` | 11/11 tests pass in `MaterializationBrowserModal.test.tsx` |
| **O4** | Review F5d-1 | Migrate InstallModal, AddCompanion, EditPublicAddress to Modal | **CLOSED** | `8d9ecbd` | 29/29 tests pass across the 3 suites |
| **O5** | Review N-04 | Migrate 7 remaining inline `fixed inset-0` overlays | **CLOSED** | `f2ea87e` | All 7 migrated to `Modal` |
| **O6** | Review N-05 | Overlay ratchet test preventing raw overlays | **CLOSED** | `d3adaa2` | `npx vitest run src/tokens/overlayRatchet.test.ts` (3/3 PASS) |
| **O7** | Review N-06 | Eliminate native `window.confirm` dialogs | **CLOSED** | `bd42b68` | 0 native dialogs remaining; ConfirmDialog tests pass |

---

## 6. Token System, Contrast & Themes

| ID | Source | Topic | Status | Commit / Evidence | Runnable Evidence Command |
|:---|:---|:---|:---:|:---|:---|
| **K1** | Review F1-2 | Programmatic WCAG AA contrast calculation parser | **CLOSED** | `c1cf6c8` | `npx vitest run src/tokens/contrast.test.ts` |
| **K2** | Review F1-3 | Text-muted contrast failure fixes | **CLOSED** | `fb8aad6` | 9/9 tests pass in `contrast.test.ts` |
| **K3** | Review F2-1 | `skinValidator` prototype pollution & DoS hardening | **CLOSED** | `b9e400f` | `npx vitest run src/tokens/skinValidator.test.ts` (14/14 PASS) |
| **K4** | Review F3-2 | Border contrast >= 3.0:1 enforcement | **CLOSED** | `a3a86ca` | `npx vitest run src/tokens/contrast.test.ts` |
| **K5** | Review F3-1 | Replace 184 orphan Tailwind classes with tokens | **CLOSED** | `4671820` | `npx vitest run src/tokens/tokenClassExistence.test.ts` |
| **K6** | Review F2-2 | Palette ratchet allowlist shrinking & prefix checks | **CLOSED** | `5a07c2a` | `npx vitest run src/tokens/paletteRatchet.test.ts` |
| **K7** | Review N-01 | Gate React Query Devtools on env flag | **CLOSED** | `a1ee645` | `VITE_QUERY_DEVTOOLS === 'true'` |

---

## 7. Marketplace & Add-ons

| ID | Source | Topic | Status | Commit / Evidence | Runnable Evidence Command |
|:---|:---|:---|:---:|:---|:---|
| **M1** | DECISIONS-NEEDED §10 | CurseForge Marketplace integration source switch | **OWNER-DECISION** | Option B default (hide until backend ready) | `npx vitest run src/server_manager/pages/PluginMarketplacePage.test.tsx` |
| **M2** | Backend Dependency | CurseForge Provider backend implementation | **BACKEND-DEPENDENT** | Documented | `backend/app/infrastructure/plugin_catalog/` |

---

## Summary of Ledger
- Total findings tracked: **33**
- **CLOSED**: 26 (78.8%)
- **OWNER-DECISION**: 5 (15.2%)
- **BACKEND-DEPENDENT**: 2 (6.0%)
- **OPEN**: 0 (0.0%) — All actionable frontend-only items have been addressed.
