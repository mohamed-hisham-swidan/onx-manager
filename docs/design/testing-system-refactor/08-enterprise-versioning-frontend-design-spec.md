# Design Spec — Enterprise Versioning Frontend UI Batch (Stages B, C, F, G)

**Status:** BUILT & VERIFIED (Commit `8b219ba`, 2026-09-18)
**Author:** AI Agent (Antigravity)  
**Date:** 2026-09-18  
**Verification:** 730 passed / 0 failed frontend across 83 test files (100% green), 0 TypeScript errors, 2,906 passed / 6 skipped backend, 6/6 CI quality gates PASS.
**Scope:** Frontend UI implementation covering all 4 completed backend refactor stages:
- **Stage G:** Protected Branches UI & Policy Configuration
- **Stage F:** Test Definition Profiles, Run Selector & Crash Evidence Viewer
- **Stage C:** Worktree Materialization Browser & Live Import Review Flow
- **Stage B:** Branch Management, Tags, Commit DAG & History Diffing

---

## 1. Goal

Close the frontend delivery gap across the Enterprise Branch Runtime refactor. All backend services, database migrations (`b1e2100000019`), and CQRS handlers for Stages B, C, F, and G are built, tested, and passing with 150/150 live API routes green. This design spec establishes the complete, production-grade frontend user interface within [`frontend/src/server_manager/`](file:///mnt/D/files/onx-manager/frontend/src/server_manager/) to expose these capabilities without regressions to existing Phase 4 versioning workflows.

---

## 2. Current Behavior

1. **Branch Protection (Stage G):**
   - [`ServerVersioningPage.tsx:334-362`](file:///mnt/D/files/onx-manager/frontend/src/server_manager/pages/ServerVersioningPage.tsx#L334-L362) renders an unstyled `<select>` dropdown. There is no visual badge or lock indicator indicating whether a branch is protected.
   - Creating a commit on a protected branch fails with an uncaught HTTP 409 error in the New Commit modal without offering administrative force bypass or policy inspection.
2. **Test Platform & Evidence (Stage F):**
   - [`TestRunModal.tsx:21-26`](file:///mnt/D/files/onx-manager/frontend/src/server_manager/components/TestRunModal.tsx#L21-L26) requires manual input of bot counts, duration, tech, and placement every run. There is no selector for saved `TestDefinition` profiles.
   - Failed test runs in [`ServerVersioningPage.tsx:448-545`](file:///mnt/D/files/onx-manager/frontend/src/server_manager/pages/ServerVersioningPage.tsx#L448-L545) only display raw text from `failure_reason`. The structured `EvidenceBundle` (culprit mod blame, boot outcome, container exit code, crash analysis) cannot be viewed.
3. **Materialization & Import Review (Stage C):**
   - There is no file browser to inspect `.onx/worktrees/<mat_id>` commit snapshots or toggle edit mode.
   - Live changes detected on server disk outside version control cannot be reviewed, confirmed, dismissed, or reverted from the web UI.
4. **Branch Lifecycle, Tags & DAG (Stage B):**
   - Branches cannot be archived from the UI. Commits cannot be tagged.
   - Commit history is a flat chronological list lacking multi-parent indicators and diff viewing between parent and child commits.

---

## 3. Proposed Change

We will implement a cohesive, modular UI expansion divided into 5 clear slices:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 ServerVersioningPage                                   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Toolbar: [Branch Select ▾] [🔒 Protected] [Manage Branches] [New Branch] [Materializations]│
├──────────────────────────────────────┬─────────────────────────────────────────────────┤
│         Commit History Timeline      │               Isolated Test Runs                │
│  • Tag Badges (v1.0.0)               │  • Reusable Profiles Drawer [Test Profiles]     │
│  • Multi-parent DAG markers          │  • [Logs] [Evidence Viewer] [Promote to Live]   │
│  • [Inspect Manifest] [Diff Changes] │  • [Run Test] ──> TestRunModal (Profile Picker) │
└──────────────────────────────────────┴─────────────────────────────────────────────────┘
```

### Slice 0: TypeScript Types & API Client Service Layer
- **`frontend/src/server_manager/types.ts`**:
  - `MaterializationMode`: `"readonly" | "editable"`.
  - `CreateMaterializationRequest`: `{ revision_type: "commit" | "branch" | "tag"; ref: string; mode?: MaterializationMode }`.
  - `MaterializationCreateResponse`: `{ materialization_id: string; revision: string; mode: MaterializationMode; status: string; root: string }`.
  - `MaterializationListItemResponse`: `{ id: string; revision: string; mode: MaterializationMode; status: string; stale: boolean; created_at: string }`.
  - `MaterializationTreeEntry`: `{ path: string; classification: string; size_bytes: number; origin: string }`.
  - `MaterializationTreeResponse`: `{ entries: MaterializationTreeEntry[] }`.
  - `MaterializationFileResponse`: `{ content: string; encoding: string; path: string; size_bytes: number }`.
  - `SetEditModeRequest`: `{ enabled: boolean }`.
  - `SetEditModeResponse`: `{ mode: string }`.
  - `LiveChangeEntry`: `{ path: string; classification: string; change_type: string }`.
  - `ScanLiveChangesResponse`: `{ changes: LiveChangeEntry[]; auto_commit?: string | null }`.
  - `AutoCommitLiveChangesResponse`: `{ commit_id?: string | null; review_id?: string | null; changes: LiveChangeEntry[] }`.
  - `ImportReviewActionResponse`: `{ status: string; revert_commit_id?: string | null }`.
  - `ServerTag`: `{ id: string; server_id: string; name: string; commit_id: string; created_at: string }`.
  - `CreateTagRequest`: `{ name: string; commit_id: string }`.
  - `DiffResponse`:
    ```typescript
    export interface DiffResponse {
      from_commit_id: string;
      to_commit_id: string;
      has_changes: boolean;
      server_type: Record<string, string> | null;
      minecraft_version: Record<string, string> | null;
      java_args: Record<string, string> | null;
      configs: Record<string, unknown>;
      env_vars: Record<string, unknown>;
      mods: Record<string, unknown>;
    }
    ```
  - Update `ServerCommit` to include `parent_commit_ids: string[]` alongside `parent_commit_id: string | null`.
  - Update `CreateCommitRequest` to include `force?: boolean`, `force_reason?: string | null`.
- **`frontend/src/services/api.ts`**:
  - Expose typed methods for all 22 live versioning endpoints across the 4 stages.

### Slice 1: Area A — Stage G: Protected Branches UI
- **Toolbar Lock Indicator**:
  - In `ServerVersioningPage.tsx`, render a shield/lock badge (`Icon name="lock"`) next to the active branch name when `branch.is_protected === true`.
  - Add a "Branch Protection" button opening `BranchProtectionModal.tsx`.
- **`BranchProtectionModal.tsx`**:
  - Query current protection state via `api.getBranchProtection(serverId, branchName)`.
  - Toggle switch for enabling/disabling protection.
  - Granular policy switches:
    - *Require passing test run before promotion* (`require_test_pass`)
    - *Allow direct commits without test/promotion* (`allow_direct_commit`)
    - *Allow admins to force bypass protection* (`allow_force_bypass`)
    - *Prevent branch deletion or archival* (`prevent_deletion`)
  - Submits via `PUT` / `DELETE` to `/versioning/branches/{branch_name}/protection`.
- **Commit Creation Protection Guard**:
  - In `ServerVersioningPage.tsx` (`isNewCommitOpen` modal):
  - When the selected branch is protected and `!policy.allow_direct_commit`:
    - Display an amber callout: *"Direct commits to this protected branch are blocked. Verification must occur via an isolated test run and promotion."*
    - Reveal an administrative bypass checkbox: *"Emergency Force Bypass"* with required `force_reason` input field.

### Slice 2: Area B — Stage F: Test Definitions, Selector & Evidence Viewer
- **`TestDefinitionsModal.tsx`**:
  - Reusable test profile management dialog accessible from the "Isolated Test Runs" header.
  - Lists existing `TestDefinition` profiles with details: bot count, duration, placement mode, memory limits, and custom options.
  - Inline creation form (`POST .../test-definitions`) and deletion button (`DELETE .../test-definitions/{id}`).
- **Profile Selector in `TestRunModal.tsx`**:
  - Add a "Test Profile" select dropdown at top of modal.
  - Default: *"Custom Settings (Manual)"*.
  - Selecting a profile automatically sets `botCount`, `durationMinutes`, `placementMode`, `botTech` and passes `test_definition_id` into `api.runIsolatedTest()`.
- **`TestEvidenceModal.tsx`**:
  - Dedicated viewer for test failure diagnostics consuming `GET .../tests/{test_id}/evidence`.
  - Displays:
    - Exit Code & Boot Status badges (`boot_passed: true/false`, `exit_code: 0/1/137`)
    - Root Cause Analysis & Exception Stack Trace
    - Suspected Culprit Mods blaming tags (highlighted with mod blame pills)
    - Artifact retention status banner (whether 24h debug test root is retained or purged)
    - Copy Evidence Bundle to clipboard button.

### Slice 3: Area C — Stage C: Worktree Materialization Browser & Import Review
- **`MaterializationBrowserModal.tsx`**:
  - Modal or sub-panel enabling operators to explore materialized commit trees in `.onx/worktrees/`.
  - Tree browser patterned after [`ServerFilesPage.tsx`](file:///mnt/D/files/onx-manager/frontend/src/server_manager/pages/ServerFilesPage.tsx) with breadcrumbs, file sizes, and binary-detection guards.
  - **Read-Only by default** with an explicit "Enable Edit Mode" toggle (`PATCH .../materializations/{id}/mode` with `{ enabled: true }`, transitioning to `"editable"` mode).
  - Integrates [`CodeEditor.tsx`](file:///mnt/D/files/onx-manager/frontend/src/components/CodeEditor.tsx) for viewing and editing materialized files.
- **`ImportReviewModal.tsx`**:
  - Triggered by a banner on `ServerVersioningPage.tsx` when uncommitted live changes are detected (`GET .../changes/live`).
  - Displays categorized change list: Added files, Modified files, Removed files.
  - Actions:
    - *Confirm & Commit*: Commits live changes to branch (`POST .../import-reviews/{id}/confirm`).
    - *Dismiss*: Acknowledges changes without creating commit (`POST .../import-reviews/{id}/dismiss`).
    - *Revert*: Destructively resets live filesystem back to branch head (`POST .../import-reviews/{id}/revert`).

### Slice 4: Area D — Stage B: Branch Management, Tags & Commit DAG Diffing
- **`ManageBranchesModal.tsx`**:
  - Lists all server branches with lifecycle status badges (`created`, `active`, `archived`) and protection badges.
  - Provides an "Archive Branch" button (`POST .../branches/{name}/archive`) with confirmation guard.
  - When selected branch is archived, disables commit creation and displays a gray banner in `ServerVersioningPage.tsx`.
- **`CreateTagModal.tsx`**:
  - Allows tagging any historical commit with an immutable version tag (`POST /tags`).
  - Renders tag pills (e.g., `v1.2.0`, `release-purpur`) next to commit IDs in the timeline.
- **`CommitDiffModal.tsx` & DAG Visualization**:
  - Renders multi-parent indicators on commits that have `parent_commit_ids.length > 1` (merge commits).
  - "Diff Changes" button on each commit opening `CommitDiffModal.tsx` (`GET /commits/diff?from={parent}&to={commit}`).
  - Summarizes configuration diffs, added/removed mods, and environment variables.

---

## 4. Affected Components

| File Path | Nature of Change | Description |
|---|---|---|
| [`frontend/src/server_manager/types.ts`](file:///mnt/D/files/onx-manager/frontend/src/server_manager/types.ts) | Modified | Add Stage B/C/F/G interfaces (`Materialization`, `ImportReview`, `ServerTag`, `DiffResponse`, `EvidenceBundle`, etc.) |
| [`frontend/src/services/api.ts`](file:///mnt/D/files/onx-manager/frontend/src/services/api.ts) | Modified | Add typed client functions for all 22 versioning routes |
| [`frontend/src/server_manager/pages/ServerVersioningPage.tsx`](file:///mnt/D/files/onx-manager/frontend/src/server_manager/pages/ServerVersioningPage.tsx) | Modified | Integrate branch protection indicator, tag badges, DAG markers, action buttons, and modal controllers |
| [`frontend/src/server_manager/components/TestRunModal.tsx`](file:///mnt/D/files/onx-manager/frontend/src/server_manager/components/TestRunModal.tsx) | Modified | Add Test Definition profile selector dropdown and auto-populate logic |
| `frontend/src/server_manager/components/BranchProtectionModal.tsx` | New | Policy editor dialog for Stage G protected branches |
| `frontend/src/server_manager/components/TestDefinitionsModal.tsx` | New | CRUD management dialog for Stage F reusable test definitions |
| `frontend/src/server_manager/components/TestEvidenceModal.tsx` | New | Diagnostic evidence viewer for Stage F test failures and culprit mods |
| `frontend/src/server_manager/components/MaterializationBrowserModal.tsx` | New | File explorer for Stage C worktree snapshots with edit mode toggle |
| `frontend/src/server_manager/components/ImportReviewModal.tsx` | New | Review modal for Stage C uncommitted live changes (confirm/dismiss/revert) |
| `frontend/src/server_manager/components/ManageBranchesModal.tsx` | New | Branch management dialog with archiving action |
| `frontend/src/server_manager/components/CreateTagModal.tsx` | New | Tag creation dialog for immutable commit tagging |
| `frontend/src/server_manager/components/CommitDiffModal.tsx` | New | Visual diff inspector for configuration, mod, and env var changes |

---

## 5. Interfaces & Contracts

### A. TypeScript API Service Additions (`frontend/src/services/api.ts`)

```typescript
// Branch Protection (Stage G)
getBranchProtection: (serverId: string, branchName: string) =>
  request<BranchProtectionResponse>(`/api/v1/servers/${serverId}/versioning/branches/${branchName}/protection`),
setBranchProtection: (serverId: string, branchName: string, body: SetBranchProtectionRequest) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/branches/${branchName}/protection`, {
    method: "PUT",
    body,
  }),
removeBranchProtection: (serverId: string, branchName: string) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/branches/${branchName}/protection`, {
    method: "DELETE",
  }),

// Test Definitions & Evidence (Stage F)
getTestDefinitions: (serverId: string) =>
  request<TestDefinition[]>(`/api/v1/servers/${serverId}/versioning/test-definitions`),
createTestDefinition: (serverId: string, body: CreateTestDefinitionRequest) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/test-definitions`, {
    method: "POST",
    body,
  }),
updateTestDefinition: (serverId: string, definitionId: string, body: Partial<CreateTestDefinitionRequest>) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/test-definitions/${definitionId}`, {
    method: "PUT",
    body,
  }),
deleteTestDefinition: (serverId: string, definitionId: string) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/test-definitions/${definitionId}`, {
    method: "DELETE",
  }),
getTestEvidence: (serverId: string, testId: string) =>
  request<EvidenceBundle>(`/api/v1/servers/${serverId}/versioning/tests/${testId}/evidence`),

// Materializations & Import Reviews (Stage C)
getMaterializations: (serverId: string) =>
  request<MaterializationListItemResponse[]>(`/api/v1/servers/${serverId}/versioning/materializations`),
createMaterialization: (serverId: string, body: CreateMaterializationRequest) =>
  request<MaterializationCreateResponse>(`/api/v1/servers/${serverId}/versioning/materializations`, {
    method: "POST",
    body,
  }),
deleteMaterialization: (serverId: string, matId: string) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/materializations/${matId}`, {
    method: "DELETE",
  }),
setMaterializationMode: (serverId: string, matId: string, enabled: boolean) =>
  request<SetEditModeResponse>(`/api/v1/servers/${serverId}/versioning/materializations/${matId}/mode`, {
    method: "PATCH",
    body: { enabled },
  }),
getMaterializationTree: (serverId: string, matId: string) =>
  request<MaterializationTreeResponse>(`/api/v1/servers/${serverId}/versioning/materializations/${matId}/tree`),
getMaterializationFile: (serverId: string, matId: string, path: string) =>
  request<MaterializationFileResponse>(`/api/v1/servers/${serverId}/versioning/materializations/${matId}/files`, {
    params: { path },
  }),
writeMaterializationFile: (serverId: string, matId: string, path: string, content: string) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/materializations/${matId}/files`, {
    method: "PUT",
    body: { path, content },
  }),
getLiveChanges: (serverId: string) =>
  request<ScanLiveChangesResponse>(`/api/v1/servers/${serverId}/versioning/changes/live`),
confirmImportReview: (serverId: string, reviewId: string) =>
  request<ImportReviewActionResponse>(`/api/v1/servers/${serverId}/versioning/import-reviews/${reviewId}/confirm`, {
    method: "POST",
  }),
dismissImportReview: (serverId: string, reviewId: string) =>
  request<ImportReviewActionResponse>(`/api/v1/servers/${serverId}/versioning/import-reviews/${reviewId}/dismiss`, {
    method: "POST",
  }),
revertImportReview: (serverId: string, reviewId: string) =>
  request<ImportReviewActionResponse>(`/api/v1/servers/${serverId}/versioning/import-reviews/${reviewId}/revert`, {
    method: "POST",
  }),

// Branch Management, Tags & Diffing (Stage B)
archiveBranch: (serverId: string, branchName: string) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/branches/${branchName}/archive`, {
    method: "POST",
  }),
getServerTags: (serverId: string) =>
  request<ServerTag[]>(`/api/v1/servers/${serverId}/versioning/tags`),
createTag: (serverId: string, body: CreateTagRequest) =>
  request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/tags`, {
    method: "POST",
    body,
  }),
diffCommits: (serverId: string, fromCommitId: string, toCommitId: string) =>
  request<DiffResponse>(`/api/v1/servers/${serverId}/versioning/commits/diff`, {
    params: { from: fromCommitId, to: toCommitId },
  }),
```

---

## 6. Failure Cases & Edge Cases

1. **Direct Commit to Protected Branch via UI:**
   - *Handling*: When `selectedBranch.is_protected` is true and policy restricts direct commits, standard commit submission displays an inline validation message before dispatching. If the operator selects "Emergency Force Bypass", the modal requires a non-empty `force_reason` and submits `force: true`. If the caller lacks `server:version:branch:bypass_protection`, the backend 403 error is cleanly surfaced in an alert banner.
2. **Archived Branch Operations:**
   - *Handling*: If a branch has `status === "archived"`, the "Create Snapshot Commit" and "Protection Settings" buttons are disabled with tooltip *"Cannot modify archived branch"*.
3. **Empty / Missing Crash Evidence:**
   - *Handling*: For test runs that completed without error or where test logs were purged (`artifacts_purged === true`), `TestEvidenceModal` displays a clean empty state: *"No crash evidence recorded for this run"* or *"Artifacts have been pruned after the 24-hour retention window."*
4. **Materialization Inactive / Missing Directory:**
   - *Handling*: If a materialization directory was reaped or deleted on disk, `getMaterializationTree` surfaces a 404. The UI captures this gracefully and provides a "Re-materialize Commit" action.
5. **Editing Read-Only Materialization:**
   - *Handling*: In `MaterializationBrowserModal`, the file editor is set to `readOnly={mode !== "edit"}`. Attempting to write without switching modes is prevented client-side; server-side 409 responses are surfaced via `toast.error()`.
6. **Concurrent Branch Protection Changes:**
   - *Handling*: If protection policy changes in the background, TanStack Query invalidation (`refresh()`) ensures toolbar badges and modal forms reload fresh data immediately after mutation.

---

## 7. Tests & Verification

### A. Frontend Component Tests (`Vitest` + React Testing Library)
1. **`BranchProtectionModal.test.tsx`**:
   - Verify loading policy via `getBranchProtection`.
   - Verify enabling protection dispatches `PUT` with selected policy.
   - Verify disabling protection dispatches `DELETE`.
   - Verify error alert on 403 / 409 response.
2. **`TestRunModal.test.tsx` (Extended)**:
   - Verify test definitions load into dropdown.
   - Verify selecting a definition locks/updates bot count and passes `test_definition_id`.
3. **`TestEvidenceModal.test.tsx`**:
   - Verify rendering of culprit mods blaming pills, stack trace, and boot outcome.
   - Verify copy to clipboard button.
4. **`MaterializationBrowserModal.test.tsx`**:
   - Verify tree navigation and file selection.
   - Verify toggle from read-only to edit mode invokes `setMaterializationMode`.
5. **`ImportReviewModal.test.tsx`**:
   - Verify display of added/modified/removed files.
   - Verify confirm, dismiss, and revert mutation triggers.
6. **`CommitDiffModal.test.tsx`**:
   - Verify visual diff display of changed configs, mods, and environment variables.
7. **`ServerVersioningPage.test.tsx` (Extended)**:
   - Verify lock icon appears on protected branches.
   - Verify force bypass controls appear in commit modal when on protected branch.
   - Verify tag badges appear on commits.

### B. CI Quality Gates & System Verification
- `npm run build -- --noEmit` / `npx tsc --noEmit` (Zero TypeScript compiler errors).
- `npm run test` (Frontend test suite passes without introducing regressions).
- All 6/6 CI backend quality gates preserved (`check-db-revision`, `check-route-contract`, `check-ruff-baseline`, etc.).

---

## 8. Out of Scope

- **Multi-tenant cloud storage provisioning**: Out of scope per Stage G baseline.
- **Full visual 2D Git DAG graph renderer (like GitKraken/GitGraph canvas)**: Out of scope. Clean topological parent-node connectors and commit ancestry list meet all enterprise requirements without bloating bundle size.
- **Direct live filesystem modifications inside Materialization Browser**: Materialization browser only inspects and edits `.onx/worktrees/<mat_id>`, not the live server directory. Live server edits remain governed by `ServerFilesPage.tsx`.

---

## 9. Next Steps

Upon user approval of this Design Spec:
1. Advance directly to **BUILD TASK** for the Frontend UI Batch.
2. Implement Slice 0 (Types & API client).
3. Implement Slice 1 (Protected Branches UI).
4. Implement Slice 2 (Test Definitions & Evidence Viewer).
5. Implement Slice 3 (Materialization Browser & Import Review).
6. Implement Slice 4 (Branch Archiving, Tags & Commit Diffing).
7. Run complete Vitest suite, TypeScript verification, and CI quality gates.
