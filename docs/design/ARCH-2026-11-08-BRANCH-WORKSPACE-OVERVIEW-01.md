# ARCH-2026-11-08-BRANCH-WORKSPACE-OVERVIEW-01

**Title:** Branch Workspace Architecture Overview — Server + Branch context, branch-aware pages, history operations, branch instances, and branch permissions

**Status:** Architecture overview / design input. This document is **not** build authorization and does not authorize schema, API, permission, or lifecycle changes. It records the target model, current evidence, options, and open owner decisions.

**Date:** 2026-11-08

**Scope:** The paper architecture for selecting a Server **and** a Branch, making the server workspace branch-aware, grouping working changes, performing stack-like history operations, running several branches simultaneously as isolated instances, and adding per-branch permissions.

**Evidence convention:**
- `[FACT]` — verified directly in the repository with `file:line` at the time of writing.
- `[ASSUMPTION]` — inferred behavior; requires owner confirmation.
- `[UNKNOWN]` — not verified or not present in the repository.
- `[NEW]` — a concept, identifier, route, column, or channel proposed by this document and not present in the repository.

The project's governing principle remains **"Branch != Server != Container != Test"** from `docs/design/testing-system-refactor/00-README.md:7`.

---

## 1. Owner Vision (faithful summary)

1. The top bar selects a **Server** and a **Branch**. The default branch is `main`, which holds the players.
2. Switching the branch changes the whole server workspace at once: Console, Files, Settings, Plugins, Network, Versioning, and Testing.
3. Testing is **not** tied to one branch. A test can run against any branch or any commit.
4. Settings changes **auto-commit by default**. The operator may disable auto-commit and commit manually after a group of changes.
5. History is clear and stack-like:
   - go back to a point and start a new line from there on the same branch;
   - move a commit from the middle of history to a new branch.
6. Several branches can run at the same time: the live branch, a branch being edited, and a branch under test.
7. Branches have permissions; for example, a developer role may be scoped to the test branch.

This document does not redesign that vision. It maps it onto the existing domain and identifies what is missing.

---

## 2. Glossary and Concept Model

### 2.1 Glossary

| Concept | Existing domain name and evidence | Meaning in this architecture |
|---|---|---|
| Project | `Project` at `backend/app/modules/versioning/domain/entities.py:29`; `Project.id` maps 1:1 to the server id (`docs/design/testing-system-refactor/01-stage-a-domain-reconstruction-design-spec.md`) | Logical Minecraft environment. Today it is the Server. |
| Repository | `Repository` at `entities.py:43` | Owns the commit history for a Project. |
| Server | `Server` aggregate at `backend/app/modules/server/domain/aggregate.py:99` | Operational unit: runtime, provider, ports, files, players. |
| Branch | `ServerBranch` at `entities.py:83`, alias `Branch` at `entities.py:148` | Mutable named pointer to a commit; lifecycle `CREATED → ACTIVE → ARCHIVED` (`backend/app/modules/versioning/domain/value_objects.py:27`). |
| Commit | `ServerCommit` at `entities.py:161` | Immutable desired-state snapshot with a manifest and one or more parents. |
| Tree / Manifest | `Tree` at `value_objects.py:241`; `CommitManifest` at `value_objects.py:91` | Tracked desired state: configs (`configs`), mods (`mods`), environment variables, Java arguments. World data is not in the Tree. |
| Working changes | No first-class entity. Live-disk comparison exists as `ScanLiveChangesQuery` at `backend/app/modules/versioning/application/queries/scan_live_changes.py:16` and `extract_classified_changes` at `scan_live_changes.py:21`; worktree edit state is computed in the Stage C design (`docs/design/testing-system-refactor/04-stage-c-filesystem-materialization-design-spec.md`) | Edits that are not yet a commit. This overview proposes an explicit grouping concept (see §5.1). |
| Materialization | `Materialization` at `entities.py:261` | Isolated working tree derived from a commit. Root must be under `.onx/tests` or `.onx/worktrees` (`entities.py:278-292`). Status `PENDING → READY → STALE → REMOVED` (`value_objects.py:33`). Mode `READONLY | EDITABLE` (`value_objects.py:40`). |
| Path classification | `PathClassification` at `value_objects.py:60` | `TRACKED`, `PERSISTENT`, `GENERATED`, `IGNORED`, `EPHEMERAL`. Writes to a materialization are TRACKED-only (`backend/app/modules/versioning/application/commands/write_materialized_file.py:97-115`). |
| Persistent data | `PersistentDataset` at `entities.py:562` | Mutable runtime state excluded from commits (worlds, player data, caches). |
| Runtime / Instance | `Runtime` at `entities.py:378`; persisted by `ServerRuntimeModel` at `backend/app/modules/versioning/infrastructure/models.py:145`; live-server registry `RuntimeSupervisor` at `backend/app/modules/server/application/supervisor.py:27` | An execution instance pinned to an immutable `commit_id` (`entities.py:387`) and optionally a `materialization_id` (`entities.py:388`). It must never bind to a mutable branch reference (`entities.py:411`). |
| Test run | `ServerTestRun` at `entities.py:608`; persisted by `ServerTestRunModel` at `models.py:90`; `TestDefinition` at `entities.py:472`; `TestSpec` at `backend/app/modules/versioning/infrastructure/test_runner.py:103`; `TestHandle` at `test_runner.py:119` | Execution of a revision with assertions and evidence. Test runs are bound to a commit, not to a branch. |
| Admission | `admit()` at `backend/app/modules/versioning/application/scheduling/admission.py:233` | Global cross-process gate for test runs (`admission.py:1-18`), with a global cap default of 3 (`admission.py:48`). |
| Branch protection | `BranchProtectionPolicy` at `entities.py:54`; `ServerBranch.is_protected` at `entities.py:95` | Per-branch policy fields for test-pass, direct commit, force bypass, and deletion prevention. |

**Naming correction:** The task input referred to a "RuntimeAdmissionScheduler". No such identifier exists in the repository (`[UNKNOWN]`). The implemented admission primitive is `admit()` in `admission.py:233`, and its persisted ledger is `server_admission_lease` (`models.py:174`). This overview uses the real name.

### 2.2 Relationships

```
Project 1 ─── 1 Server
Project 1 ─── 1 Repository
Repository 1 ─── N Branch
Branch 1 ─── N Commit            (head_commit_id points at one commit)
Commit N ─── N Commit            (parent_commit_ids; shared DAG)
Commit 1 ─── 1 Tree/CommitManifest
Commit 1 ─── N Materialization   (worktree or test staging)
Materialization 1 ─── N Runtime  (Runtime.materialization_id is optional)
Runtime 1 ─── N PersistentDataset
Commit 1 ─── N TestRun           (TestRun.runtime_id links to Runtime)
TestDefinition 1 ─── N TestRun
```

Key relationship facts:
- `ServerBranch.head_commit_id` is nullable and starts as `CREATED` (`entities.py:83-95`; `create_branch.py:102-103`).
- `ServerCommit.parent_commit_ids` already supports multi-parent commits (`entities.py:170`); merges are explicit-manifest operations (`merge_commits.py:20-26`, `:135-143`).
- `Materialization.commit_id` is mandatory (`entities.py:269`), so a materialization is always a concrete commit view, not a branch view.
- `Runtime.commit_id` is immutable and branch references are rejected (`entities.py:387`, `:407-413`).
- A test run may link to a `Runtime` (`models.py:110-118`), and the runtime is pinned to the commit under test.
- `PersistentDataset.runtime_id` is mandatory (`entities.py:570`), formalizing world/player state as runtime-owned.

---

## 3. Current State by Capability

### 3.1 Version control engine

| Capability | State | Evidence |
|---|---|---|
| Custom in-process VCS (no Git dependency) | Exists | `entities.py:29,43,83,161`; commands under `backend/app/modules/versioning/application/commands/` |
| Commit DAG with multiple parents | Exists | `entities.py:170`; `backend/app/modules/versioning/domain/dag.py:9` (`check_cycle`), `dag.py:43` (`traverse_history`) |
| Branch from any commit | Exists | `CreateBranchCommand.head_commit_id` at `create_branch.py:15-18`; validation at `create_branch.py:82-90` |
| Tags | Exists | `Tag` at `entities.py:237`; `create_tag.py` |
| Deterministic diff | Exists | `diff_commits.py`; `ScanLiveChangesQuery` at `scan_live_changes.py:16` |
| Merge commits | Partial | Explicit parent list and caller-supplied manifest; no auto-resolution (`merge_commits.py:20-26`, `:135-143`) |
| Ancestor / merge-base query | Missing | `dag.py` exposes only `check_cycle` (`:9`) and `traverse_history` (`:43`); no `is_ancestor` (`[UNKNOWN]`) |
| Three-way merge / conflict resolution | Missing | `merge_commits.py:139-143` raises `ConflictError` when parent manifests differ and no manifest is supplied |
| Restore / reset / cherry-pick | Missing as first-class commands | No such command files in `backend/app/modules/versioning/application/commands/`; only `revert_import_review.py` (revert of an auto-import) and `promote_commit.py` (live promotion) |
| Branch-head optimistic concurrency | Exists | `advance_branch_head_optimistic` at `backend/app/modules/versioning/infrastructure/repository.py:111`, used by `create_commit.py:207` |

### 3.2 Branch context and workspace

| Capability | State | Evidence |
|---|---|---|
| Top bar selects Server and Branch | Missing | `frontend/src/components/layout/TopBar.tsx` has no server or branch selector; the server switcher lives in `frontend/src/layouts/ServerShell.tsx:286-291` |
| Branch is a workspace-wide context | Missing | Branch state is local to the Versioning page: `frontend/src/server_manager/pages/ServerVersioningPage.tsx:39-40` (`branches`, `selectedBranch`) |
| Branch-aware routing | Missing | Routes are `/servers/:serverId/<section>` (`frontend/src/App.tsx:91-100`); no branch segment or query parameter |
| Branch-aware Files | Missing | Files router resolves only the live root (`backend/app/api/v1/routers/files.py:69-80`) and has no `source`/`ref` parameters (`files.py:118,166,191,212,236,300,323`) |
| Branch-aware Settings | Missing | Settings edits the server aggregate via `ServerSettingsSection` (`frontend/src/server_manager/components/ServerSettingsSection.tsx:431-432`) |
| Branch-aware Plugins | Missing | Plugin routes are server-scoped on the live directory; page uses `serverId` (`frontend/src/server_manager/pages/PluginListPage.tsx:160-161`) |
| Branch-aware Network | Missing | Exposure page is server-scoped (`frontend/src/server_manager/pages/ServerExposurePage.tsx:21-22`); no branch runtime network identity |
| Branch-aware Console | Partial (test only) | Live channel `server:{server_id}:console` (`backend/app/websocket/serializers.py:142`); test channel `test:{test_id}:console` (`serializers.py:150`); no branch-runtime channel |
| Branch-aware Testing | Partial | `RunIsolatedTestCommand.commit_id` is optional (`run_isolated_test.py:21`); when omitted it falls back to the latest commit of the server (`run_isolated_test.py:92-99`), not the branch head. Any commit can be tested, but the command is not branch-aware and the UI does not carry a branch workspace context |

### 3.3 Working changes and auto-commit

| Capability | State | Evidence |
|---|---|---|
| Live-change scan | Exists | `ScanLiveChangesQuery` (`scan_live_changes.py:16`) and `extract_classified_changes` (`scan_live_changes.py:21`) |
| Auto-commit of live changes | Exists | `AutoCommitLiveChangesCommand` (`auto_commit_live_changes.py:24-26`); message `[auto-import] N live change(s) imported` (`:139`); author `onx-auto-import` (`:140`) |
| Auto-commit default-on policy | Partial | The Stage C design defines auto-commit as the default for live import, but the current Settings page writes the server aggregate, not a commit (`ServerSettingsSection.tsx:431-432`) |
| Grouping a set of changes | Missing | No working-changes group/session entity exists; commits are whole live snapshots (`auto_commit_live_changes.py:109-140`) |
| Manual commit after a group | Partial | `CreateCommitCommand` exists (`create_commit.py:32`) but the UI exposes no grouped commit flow |

### 3.4 Instances and concurrency

| Capability | State | Evidence |
|---|---|---|
| Live server runtime | Exists, one per server | `RuntimeSupervisor._instances: dict[str, RuntimeSupervisor]` keyed by `server_id` (`supervisor.py:28`); container name `onx-{server_id}` (`backend/app/modules/server/infrastructure/providers/docker.py:369`) |
| Isolated test runtimes | Exists, concurrent | `onx-test-{test_id}` (`test_runner.py:296`, `:641`); admission global cap (`admission.py:48`); isolated bridge and unmapped ports (`docs/design/testing-system-refactor/05-stage-d-runtime-scheduling-design-spec.md`) |
| Domain `Runtime` wired to tests | Exists | `ServerRuntimeModel` (`models.py:145`); `runtime_id` FK on test runs (`models.py:110-118`) |
| Multiple branch instances per server | Missing | One supervisor instance per `server_id` (`supervisor.py:28`); no branch-runtime registry |
| Port allocation for additional runtimes | Partial | `GET /available-port` picks from 25565 upward (`backend/app/api/v1/routers/servers.py:71-80`); `ServerModel.port` (`backend/app/modules/server/infrastructure/models.py:36`); duplicate-port conflict is detected at runtime-ownership time (`backend/app/modules/server/application/runtime_ownership.py:384-388`), not at create/import time |
| Lifecycle serialization | Partial / in-flight | `ServerLifecycleLeaseManager` keyed by `server_id` (`backend/app/modules/server/application/lifecycle_lock.py`, untracked); migration `backend/alembic/versions/b1e2100000023_add_server_lifecycle_leases.py` (untracked) |
| Per-player isolation | Missing | `PersistentDataset` exists (`entities.py:562`) but branch instances have no player-facing routing; players are served by the live runtime |

### 3.5 Permissions

| Capability | State | Evidence |
|---|---|---|
| Server-scoped roles | Exists | `ServerMembershipModel` at `models.py:81`; role map `SERVER_ROLE_PERMISSIONS` at `backend/app/api/deps.py:128-153` (`admin`, `dev`, `viewer`) |
| Global role catalog | Exists | `roles: viewer, operator, admin` at `contracts/permissions.yaml:160-172` |
| Versioning permissions | Exists | `server:version:read`, `server:version:commit`, `server:test:execute`, `server:test:configure`, `server:version:promote`, `server:version:branch:protect`, `server:version:branch:bypass_protection` (`permissions.yaml:120-150`) |
| Branch-scoped role/grant | Missing | No branch id in any permission string or membership row; no branch grant table |
| Policy enforcement completeness | Partial | `can_commit_directly` (`entities.py:133`) and `can_archive` (`entities.py:141`) are enforced (`create_commit.py:136`, `auto_commit_live_changes.py:85`, `archive_branch.py:82`); `require_test_pass` and `allow_force_bypass` are stored/serialized (`entities.py:57-59`, `schemas/versioning.py:315-321`) but have no enforcement logic (`[FACT]` a repository search found only definitions and schema fields) |

---

## 4. Target Behavior per Page

The workspace has three modes: **stopped branch**, **running branch**, and **main**. In all modes the selected Server and Branch are explicit. `main` is special because it owns the live runtime, the production ports, and the players.

| Page | Stopped branch | Running branch | Main |
|---|---|---|---|
| **Console** | Shows an empty/idle state with the branch name and commit; no live process. Offers "Start branch instance" when Stage 3 exists. | Streams the branch runtime channel `runtime:{runtime_id}:console` `[NEW]`. Commands are sent to that runtime only. | Streams the existing live channel `server:{server_id}:console` (`serializers.py:142`). Commands target the production runtime. |
| **Files** | Browses the branch worktree materialization (`Materialization.root_path`, `entities.py:270`). Scope is pending owner decision (§8): Option A displays TRACKED paths only, while Option B displays the whole server directory with non-TRACKED paths read-only. Edits must remain within TRACKED paths and land in working changes (`write_materialized_file.py:97-115`). | Same worktree view; the running instance reads the materialized tree, not the live directory. | Browses the live server directory through the existing Files API default (`files.py:69-80`). Saves auto-commit by default or enter a working-changes group. |
| **Settings** | Edits the branch commit's tracked configuration (`CommitManifest.configs`, `value_objects.py:96`) through a worktree. Saves join the working-changes group. | Same, with a clear "affects this branch instance only" banner; world/player settings that are persistent are read-only or explicitly marked. | Edits the live desired state. Auto-commit by default; manual mode accumulates a group and commits once. |
| **Plugins** | Browses the branch's tracked mods (`CommitManifest.mods`, `value_objects.py:97`); installing/removing a plugin writes the worktree and joins working changes. Binary/JAR changes are materialization-level, not arbitrary file uploads (Stage C boundary). | Same branch view; changes apply to the next restart of that branch instance. | Manages the live `mods`/`plugins` directories. Auto-commit by default. |
| **Network** | No listener. Shows the reserved port that will be used if the branch instance starts. | Shows the branch runtime's reserved game port and its exposure status. Players do not connect here by default. | Shows the live public address, production port, and exposure targets. Players connect here. |
| **Versioning** | Branch-aware timeline: commits, tags, parents, working changes, restore/reset/cherry-pick entry points. | Same timeline, with a runtime badge for the running commit and a link to the test/evidence record. | Same timeline, plus promotion/merge-to-main controls and protected-main policy. |
| **Testing** | Can run a test against the branch head or any commit; `RunIsolatedTestCommand.commit_id` is optional (`run_isolated_test.py:21`) and currently falls back to the server's latest commit across history (`run_isolated_test.py:92-99`) rather than the selected branch head. | Can run a test against the running commit or another commit; the branch instance and the test container are separate runtimes. | Can run tests before promotion; promotion remains gated by test evidence (`promote_commit.py`). |

**Players only on main** follows from the owner vision and the current data model: world and player state are persistent (`PersistentDataset`, `entities.py:562`), commits exclude world data (Stage C design), and branch instances must use a snapshot/COW world rather than the live world. A branch instance is therefore not a production player endpoint unless the owner explicitly opens it.

---

## 5. Cross-Cutting Decisions

Each decision lists viable options and a recommendation. All recommendations preserve the existing domain invariants unless an owner decision changes them.

### 5.1 Auto-commit policy and "working changes" grouping

**Problem:** The current auto-commit path commits a whole live snapshot with a generated message (`auto_commit_live_changes.py:109-140`). That is acceptable for import review but too noisy for interactive Settings/Files edits, and it cannot represent "a group of changes."

**Options:**

| Option | Description | Trade-offs |
|---|---|---|
| **A. Per-write auto-commit** | Every successful save creates a commit immediately. | Simplest; maximum history noise; poor for a Settings form that changes many fields; races with the CAS path. |
| **B. Working-changes group with auto-commit on boundary (recommended)** | Edits accumulate in a `[NEW]` working-changes group per branch/materialization; auto-commit fires on an explicit boundary (form submit, navigation away, idle timeout, closing the branch) or when the operator presses Commit. A per-server/per-branch `[NEW]` auto-commit policy can disable the automatic boundary and require a manual commit. | Matches the owner's "group of changes" wording; one commit per intent; still safe because the group commits through `CreateCommitCommand` and the existing CAS (`create_commit.py:207`). |
| **C. Auto-commit plus amend/squash** | Commit each save, then amend or squash later. | Requires history rewriting semantics the engine does not have; conflicts with the immutable commit model (`entities.py:161`); not recommended. |

**Recommendation:** Option B. Introduce `[NEW]` `WorkingChangesGroup` (identity, server, branch, base commit, materialization, member paths, status) and `[NEW]` `AutoCommitPolicy` (mode `auto-on-boundary | manual`, idle boundary, optional message template). A working-changes group is a commit-preparation concept; it is not a new version-control object and does not change `ServerCommit`, `Tree`, or `Materialization` semantics.

**Open sub-decision:** whether the boundary is form submit, navigation, a debounce timer, or an explicit button. The owner should choose the default; all are implementable on the same group concept.

### 5.2 History operations (restore, reset with safety ref, cherry-pick/move)

**Current engine gaps:**
- No ancestor/merge-base primitive: `dag.py` has only `check_cycle` (`dag.py:9`) and `traverse_history` (`dag.py:43`).
- No three-way merge or conflict resolution: `merge_commits.py:139-143` requires an explicit manifest when parents differ.
- No restore, reset, or cherry-pick command files.
- Head movement is guarded by optimistic concurrency (`advance_branch_head_optimistic`, `repository.py:111`), which any new operation must reuse.

**Semantics and options:**

| Operation | Safe semantics | Options | Recommendation |
|---|---|---|---|
| **Restore** ("go back to a point") | Create a new commit whose Tree equals the target commit's Tree, parented to the current head. History is never rewritten. | (A) new commit on the same branch; (B) reset the branch pointer. | (A) Restore-as-new-commit. It preserves history, works with the immutable model, and needs no safety ref. |
| **Reset** ("start a new line from there") | Move the branch `head_commit_id` to an earlier commit, then commit forward. Requires a recoverable anchor. | (A) reset to target and create a `[NEW]` safety checkpoint before the move; (B) reset only if the target is an ancestor; (C) reset via a new branch then swap names. | (A) with a `[NEW]` safety checkpoint. Refuse non-ancestor reset. Reuse `Tag` (`entities.py:237`) only if a reserved, non-user-visible name space is acceptable; otherwise a dedicated checkpoint is cleaner. |
| **Cherry-pick / move a commit** | Create a new commit on the target branch containing the selected commit's change relative to its parent. | (A) apply the manifest diff and fail loudly on conflict; (B) require a caller-supplied resolved manifest, mirroring `merge_commits.py`; (C) full three-way merge (not present). | (A) for a first increment, with a hard failure and an explicit "resolve manually" path (B). Do not attempt automatic conflict resolution; the Stage B scope explicitly rejects invented resolution. |

**What the engine currently lacks and what Stage 2 must add:** `[NEW]` `is_ancestor`, `[NEW]` restore/reset/cherry-pick commands, `[NEW]` safety checkpoint semantics, and a deterministic manifest-diff application rule. Three-way merge remains out of scope until explicitly authorized.

**Stack-like UI consequence:** "starting a new line from there on the same branch" is reset-plus-forward, not history deletion. "Moving a commit from the middle to a new branch" is cherry-pick into a branch created at the current head, then optionally archiving the old line. The UI must show the safety checkpoint and require confirmation for reset.

### 5.3 Running branches as instances

**Problem:** The current live runtime is singular per server: `RuntimeSupervisor._instances` is keyed by `server_id` (`supervisor.py:28`) and the container is `onx-{server_id}` (`docker.py:369`). Tests are the only concurrent execution path (`test_runner.py:296`, `:641`; admission at `admission.py:233`). The owner wants live, editing, and testing branches running simultaneously.

**Options:**

| Concern | Option A | Option B | Option C | Recommendation |
|---|---|---|---|---|
| Runtime identity | Reuse `Runtime` (`entities.py:378`) pinned to commit + materialization, add a branch label only for display | New `[NEW]` `BranchInstance` aggregate separate from `Runtime` | Reuse test-run identity and extend `TestHandle` | Reuse `Runtime` (A). ADR-0015 already forbids binding `Runtime` to a mutable branch (`entities.py:411`); a display label is not a binding. |
| Registry key | Keep `server_id` key and disallow multiples | `[NEW]` key by `runtime_id` or `(server_id, runtime_id)` | A separate `[NEW]` branch-runtime registry | Key by `runtime_id` (B), because it matches the persisted identity (`models.py:145`) and the console channel. |
| Container name | Keep `onx-{server_id}` for all | `[NEW]` `onx-branch-{server_id}-{runtime_short}` | Reuse `onx-test-{test_id}` | `[NEW]` `onx-branch-...` (B). Live and test names stay unchanged. |
| Port allocation | Reuse `ServerModel.port` | `[NEW]` reserved port per runtime, allocated from a free range and persisted on the runtime | Publish no game port for branch instances | Reserved port per runtime (B). Branch instances need a connectable game port; tests deliberately use unmapped ports. |
| Lifecycle lease key | Use `server_id` (current lock) | `[NEW]` `runtime:{runtime_id}` lease key, while `main` keeps the server key | No lock | `[NEW]` runtime-scoped lease key (B). A server-scoped lock would serialize all branch instances and defeat the vision. |
| Console channel | `server:{server_id}:console` | `[NEW]` `runtime:{runtime_id}:console` | Reuse `test:{test_id}:console` | `[NEW]` runtime channel (B). Reusing the test channel would conflate test evidence with branch runtime output. |
| World data | Share the live world | COW/snapshot world per branch instance | No world | COW/snapshot per instance (B), using the existing snapshot driver (`test_runner.py:440`) and `PersistentDataset` (`entities.py:562`). Live world and players stay with `main`. |
| Resource caps | Ignore branch runtimes in admission | Count branch runtimes in the same global occupied set | Separate branch-instance cap | Count them in the same accounting (B) or a clearly separate `[NEW]` cap; either way, reservations must be persisted, not recomputed. Extend the existing admission vocabulary rather than inventing a second scheduler. |
| Player traffic | Allow players on any branch | Players only on `main`; branch ports are private or explicitly exposed | Route players by permission | Players only on `main` by default (B), matching the owner vision; exposing a branch instance is an explicit, audited action. |

**Important constraint:** Stage D explicitly avoided new "Runtime"-named concepts and kept admission vocabulary (`admission.py:1-18`). Stage 3 should reuse `Runtime` and the admission ledger rather than create a parallel scheduler, unless the owner authorizes a distinct concept.

### 5.4 Per-branch permissions

**Current state:** Permissions are server-scoped. `ServerMembershipModel` stores a role per user per server (`models.py:81-92`); `SERVER_ROLE_PERMISSIONS` maps `admin`, `dev`, `viewer` to server nodes (`deps.py:128-153`); the YAML catalog also defines global roles `viewer`, `operator`, `admin` (`permissions.yaml:160-172`). No permission string or row carries a branch id.

**Dependency on S4/S5:** The task refers to a "single-admin vs membership-scoping decision (S4/S5)" `[UNKNOWN]` (owner-supplied). No such decision label exists as an owner decision in the repository; an unrelated S4/S5 appears in `docs/design/SPEC-2026-10-02-DOCKER-STATUS-AND-DELETE-HONESTY-01.md` (referencing Docker crash exit scenarios). The decision matters because:
- If the product remains **single-admin** at the server level, branch permissions collapse to server permissions or a small additive branch grant.
- If **membership scoping** is adopted, branch permissions become a first-class dimension of membership and must coexist with the existing server roles.

**Options:**

| Option | Description | Trade-offs |
|---|---|---|
| **A. Branch grant table** `[NEW]` `branch_grants` | Rows of `(branch_id, user_id, role)` or `(branch_id, user_id, permission)`, evaluated in addition to server membership. | Clean branch dimension; needs migration, route guards, and a UI; avoids overloading server roles. |
| **B. Extend server membership roles** | Add branch-qualified roles to `server_memberships`, e.g. role `dev:branch-id`. | No new table, but pollutes the role vocabulary and complicates every existing guard. |
| **C. Branch id in permission strings** | Add `server.{server_id}.branch.{branch_id}.{action}` strings and a matching resolver. | Fine-grained but verbose; expands `contracts/permissions.yaml` heavily and requires every route to accept a branch id. |

**Recommendation:** Option A if membership scoping is chosen; if single-admin is chosen, defer Stage 4 and treat branch access as a server-level concern. Either way, do not fork the existing `require_server_permission` resolver (`deps.py:156-240`) into a second authorization engine; extend it with an optional branch dimension.

### 5.5 URL and routing model for the branch context

**Current state:** Routes are `/servers/:serverId/<section>` (`App.tsx:91-100`). The server switcher preserves the current subpath and search string (`ServerShell.tsx:286-291`). Branch state is local component state (`ServerVersioningPage.tsx:39-40`).

**Options:**

| Option | Description | Trade-offs |
|---|---|---|
| **A. Path segment** `[NEW]` `/servers/:serverId/b/:branch/<section>` | Branch is a first-class URL segment. `main` may be canonicalized to `/servers/:serverId/<section>`. | Bookmarkable, shareable, deep-linkable; requires nested routing and a redirect rule; conflicts with section names only if a reserved segment is not used. |
| **B. Query parameter** `?branch=<name>` | Branch is a query parameter on existing routes. | Minimal routing change; easy to lose on navigation; weaker semantics; awkward for server switching. |
| **C. Client store only** | Branch lives in a React context/store with no URL representation. | Smallest change; not shareable; refresh loses context; inconsistent with the server-switcher behavior. |

**Recommendation:** Option A with a reserved `b` segment and a canonical default of `main`. The server switcher must preserve both the branch segment and the section (`ServerShell.tsx:286-291` already preserves the subpath and search). Stage 1 introduces a `[NEW]` `BranchContext` provider that reads the URL and supplies the selected branch to all pages.

---

## 6. Stage Map

Each stage is independently reviewable. Stages are ordered by dependency, not by calendar. "Owner-modified" lists the relevant files that already carry uncommitted changes in the current working tree; any stage touching them must coordinate with the owner and preserve those changes.

### Stage 0 — Prerequisites

**Purpose:** Make lifecycle and port ownership safe enough that branch instances cannot corrupt the live server.

**Backend scope:**
- Land the multi-worker lifecycle lease: `lifecycle_lock.py` (untracked), migration `b1e2100000023_add_server_lifecycle_leases.py` (untracked), and the start/stop/restart/delete integration.
- Add a duplicate-port guard at server create/import time (currently only runtime-ownership detects conflicts: `runtime_ownership.py:384-388`; providers check a single port at start: `providers/local.py:75`, `providers/local_windows.py:101`).
- Decide the canonical runtime identity for the live server versus additional runtimes.

**Frontend scope:** None required.

**Dependencies:** None.

**Risks:** The lease and migration are already untracked but not committed; committing them is a release-critical action. Port allocation must not break existing servers that already share a port by configuration.

**Owner-modified files:** `backend/app/modules/server/application/lifecycle_lock.py` (untracked), `backend/alembic/versions/b1e2100000023_add_server_lifecycle_leases.py` (untracked), `backend/app/core/fs_utils.py` (untracked), `start_server.py`, `stop_server.py`, `restart_server.py`, `delete_server.py`, `supervisor.py`, `backend/app/modules/server/infrastructure/fs.py`, `providers/docker.py`, `providers/local.py`, `providers/local_windows.py`, `runtime_ownership.py`, `reconciliation.py`, `runtime_reconciliation.py`.

### Stage 1 — Branch context + Files/Settings + commit-from-worktree

**Purpose:** Deliver the top-bar Server+Branch selector and make Files and Settings branch-aware, with a safe way to turn worktree edits into a commit.

**Backend scope:**
- Extend the Files API with `[NEW]` `source=live|worktree` and `ref=<materialization_id>` parameters, keeping `source=live` as the default; resolve worktree roots from `Materialization.root_path` (`entities.py:270`); preserve the existing protected-directory guard (`files.py:25-64`). Branch Files scope is pending owner decision (§8): Option A exposes TRACKED paths only (current engine: `write_materialized_file.py:97-115`, `get_materialization_tree.py:90`, ADR-0016; `world/logs/PERSISTENT/GENERATED` not shown); Option B exposes the whole server directory with TRACKED editable and non-TRACKED read-only (requiring a new read semantic in `get_materialization_tree.py:90` and `get_materialization_file.py:77`). Under both options, mutations to non-TRACKED paths remain rejected.
- Add `[NEW]` `CommitFromWorktreeCommand` (named in the superseded spec but not implemented) that compiles a diff against the parent manifest and advances the branch head through `advance_branch_head_optimistic` (`repository.py:111`).
- Make Settings read/write the branch's tracked configuration through the materialization rather than the live aggregate; keep persistent fields read-only.
- Add a branch-context read model (branch, head commit, materialization, policy) so the frontend can render one context.

**Frontend scope:**
- Add the top-bar/branch selector and `[NEW]` `BranchContext`; implement the URL model from §5.5.
- Add branch mode to `ServerFilesPage` and `ServerSettingsPage`; shared context in `ServerVersioningPage`.
- Add the working-changes grouping UI from §5.1 (even if auto-commit remains manual in this stage).
- Extend `api.ts` with worktree file calls and commit-from-worktree calls.

**Dependencies:** Stage 0; existing materialization engine (`create_materialization.py`, `write_materialized_file.py`, `tree_writer.py`).

**Risks:**
- Regressing live Files behavior by changing the default resolution path.
- Writing outside the worktree root or into PERSISTENT/GENERATED paths.
- Divergence between the materialization's commit and the branch head; must fail stale-head loudly.
- Permission surface: worktree writes need the same or stricter rights than live writes.

**Owner-modified files:** `backend/app/api/v1/routers/files.py`, `backend/app/modules/versioning/domain/entities.py`, `promote_commit.py`, `remove_materialization.py`, `config_writer.py`, `frontend/src/layouts/ServerShell.tsx`, `frontend/src/server_manager/pages/ServerVersioningPage.tsx`, `frontend/src/server_manager/components/versioning/BranchToolbar.tsx`, `CommitTimeline.tsx`, `StorageHealthBanner.tsx`, `TestRunList.tsx`, `frontend/src/services/api.ts`.

### Stage 2 — History operations

**Purpose:** Make history stack-like: restore, reset with a safety checkpoint, and cherry-pick/move a commit.

**Backend scope:**
- Add `[NEW]` `is_ancestor` to `dag.py` (currently only `check_cycle` and `traverse_history` exist).
- Add `[NEW]` restore, reset, and cherry-pick commands.
- Add `[NEW]` safety-checkpoint semantics for reset; reuse `Tag` only if a reserved namespace is acceptable.
- Reuse the explicit-manifest merge path for cherry-pick conflict handling (`merge_commits.py:135-143`); do not invent automatic resolution.
- Preserve branch protection and the test gate; protected branches must reject destructive operations.
- **Note on prior art:** `docs/design/SPEC-2026-10-05-BRANCH-AWARE-FILES-AND-PROTECTED-MAIN-01.md:298-356,489-492` already contains an `is_ancestor` / commit-from-worktree design (superseded, never implemented); Stage 2 must reconcile with it, not duplicate it.

**Frontend scope:** History context menu, reset confirmation with checkpoint display, cherry-pick dialog, and a clear "new line from here" flow.

**Dependencies:** Stage 1 commit path; Stage 0 CAS guarantee.

**Risks:** History rewrite confusion, protected-branch bypass, and accidental loss of the current line. The safety checkpoint must be durable before the head moves.

**Owner-modified files:** `entities.py`, `promote_commit.py`, `create_commit.py` (not currently modified), `merge_commits.py` (not currently modified), `ServerVersioningPage.tsx`, `CommitTimeline.tsx`, `api.ts`.

### Stage 3 — Branch instances

**Purpose:** Run `main`, an editing branch, and a tested branch simultaneously as isolated runtimes.

**Backend scope:**
- Introduce `[NEW]` runtime-scoped identity and registry keyed by `runtime_id` (reusing `Runtime` and `ServerRuntimeModel`). Registry architecture constraint: the existing live `RuntimeSupervisor._instances` (`supervisor.py:28`) is in-process memory only. Per Constraint 15 and multi-worker safety, branch-runtime status, lifecycle leases, and port assignments must be DB-backed (`ServerRuntimeModel` at `models.py:145` and `server_lifecycle_leases`), while process supervision handles remain local to the active worker.
- Add `[NEW]` `onx-branch-{server_id}-{runtime_short}` container naming; keep `onx-{server_id}` and `onx-test-{test_id}` unchanged.
- Add `[NEW]` per-runtime port reservation and a create/import duplicate-port guard.
- Add `[NEW]` `runtime:{runtime_id}` lifecycle lease key; keep the server key for `main`.
- Add `[NEW]` `runtime:{runtime_id}:console` channel and teach `ConsoleStreamManager` (`console_stream.py:49`) to resolve it.
- Extend admission/accounting to include branch runtimes with persisted reservations; preserve the global cap concept (`admission.py:48`).
- Give each branch runtime a COW/snapshot world (`test_runner.py:440`) and a `PersistentDataset` (`entities.py:562`); never mount the live world.
- Keep players on `main` by default.

**Frontend scope:** Branch-instance status, start/stop, console, port/address display, resource usage, and an explicit "expose this instance" action if authorized.

**Dependencies:** Stage 0 (lease, ports), Stage 1 (materialization and branch context).

**Risks:** Port collisions, orphan containers, world corruption, resource exhaustion, and accidental player exposure. Container adoption must be verified by identity, not by name alone.

**Owner-modified files:** `supervisor.py`, `providers/docker.py`, `providers/local.py`, `providers/local_windows.py`, `start_server.py`, `stop_server.py`, `delete_server.py`, `runtime_ownership.py`, `admission.py` (not currently modified), `console_stream.py` (not currently modified), `serializers.py` (not currently modified), `ServerShell.tsx`, `ServerConsole.tsx` (not currently modified).

### Stage 4 — Branch permissions

**Purpose:** Scope roles/grants to a branch (for example, a developer role on a test branch).

**Backend scope:**
- Add a `[NEW]` branch permission dimension: grant table or branch-qualified membership, per the owner's S4/S5 ruling.
- Extend `require_server_permission` (`deps.py:156-240`) with an optional branch check; do not create a second auth engine.
- Add permissions to `contracts/permissions.yaml` and the route coverage matrix.
- Ensure protected-branch operations require both server-level and branch-level authority.

**Frontend scope:** Branch access editor, role display, and disabled states for unauthorized branches.

**Dependencies:** The S4/S5 owner decision; Stage 1 branch context.

**Risks:** Two existing role vocabularies (`SERVER_ROLE_PERMISSIONS` at `deps.py:128-153` and YAML roles at `permissions.yaml:160-172`) already diverge; adding a branch dimension without reconciling them will multiply the inconsistency.

**Owner-modified files:** `deps.py`, `contracts/permissions.yaml`, `ServerShell.tsx`, settings/member UI files.

### Stage 5 — Merge and promote to main

**Purpose:** Move a tested branch's changes into `main` safely.

**Backend scope:**
- Define the merge policy: fast-forward-only or explicit-manifest merge, with a pinned `PASSED` test run.
- Enforce protected-main policy (`BranchProtectionPolicy`, `entities.py:54`) including `require_test_pass` and `allow_force_bypass`, which are currently not enforced.
- Harden promotion: stop the live server, confirm the stop, swap configs/mods/worlds atomically with rollback, and restart (`promote_commit.py:220-345`; `keep_world_changes` at `:56`, `:333-338`).
- Decide whether `main` may receive direct commits; the current engine allows them when `allow_direct_commit` is true (`create_commit.py:136`).

**Frontend scope:** Merge dialog, pre-merge test evidence, promotion confirmation, and protected-main warnings.

**Dependencies:** Stages 1–4.

**Risks:** The Stage B hard stop forbids invented conflict resolution; promotion touches the live world and has the highest blast radius; the existing promote path is already owner-modified.

**Owner-modified files:** `promote_commit.py`, `start_server.py`, `stop_server.py`, `supervisor.py`, `providers/docker.py`, `entities.py`, `ServerVersioningPage.tsx`, `CommitTimeline.tsx`, `TestRunList.tsx`.

---

## 7. Constraints Stage 1 Must Respect

Stage 1 is the foundation for every later stage. It must not paint the architecture into a corner.

1. **Live is the default.** `source=live` must remain the default for every Files route; branch mode is additive (`files.py:69-80`).
2. **No live writes from worktrees.** `CommitFromWorktreeCommand` must never write into the live server directory; promotion is the only live-write path (`promote_commit.py`).
3. **Worktree mutation constraints (pending owner decision).** Worktree mutations must remain strictly within TRACKED paths (`write_materialized_file.py:97-115`); mutations to PERSISTENT (`world*`), GENERATED (`logs`, `crash-reports`), and IGNORED (`.onx`) paths are rejected. The browsing visibility of non-TRACKED paths in the Files interface is pending owner decision (§8): Option A displays TRACKED paths only, while Option B displays the whole server directory with non-TRACKED files as read-only.
4. **Respect the protected-directory guard.** `.onx`, `.onx-manager`, and `.mcsmanager` must remain inaccessible to mutation (`files.py:25-64`).
5. **Use the command bus.** Branch operations flow through commands and the existing repository; do not add cross-module imports that violate the `server` → `versioning` layering rule.
6. **Preserve CAS and stale-head detection.** Any head advance uses `advance_branch_head_optimistic` (`repository.py:111`) and fails loudly on conflict.
7. **Do not bind Runtime to Branch.** `Runtime.commit_id` remains immutable (`entities.py:411`); a branch label is display metadata only.
8. **Do not rename existing runtime identities.** Keep `onx-{server_id}` (`docker.py:369`) and `onx-test-{test_id}` (`test_runner.py:296`, `:641`) until Stage 3 deliberately adds a third form.
9. **Do not reuse test staging.** Branch worktrees live under `.onx/worktrees` (`entities.py:278-292`); `.onx/tests` remains test-owned.
10. **Do not change console channels in Stage 1.** Keep `server:{server_id}:console` and `test:{test_id}:console` unchanged (`serializers.py:142,150`); the runtime channel is Stage 3.
11. **Do not add branch permissions early.** Stage 1 authorization stays server-scoped; the branch dimension is Stage 4 and depends on the owner's S4/S5 decision.
12. **No silent background triggers.** Auto-commit boundaries are explicit (form submit, navigation, idle, or button); do not introduce a filesystem watcher or scheduler in Stage 1.
13. **Keep the permission catalog stable.** Reuse existing permission strings (`permissions.yaml:120-150`); new permissions require a contract update and route-matrix verification.
14. **Preserve materialization lifecycle.** Do not mark a materialization `READY` before verification; keep `STALE` handling lazy as designed (`docs/design/testing-system-refactor/04-stage-c-filesystem-materialization-design-spec.md`).
15. **Do not assume single-process.** Any new lock or reservation must be database-backed, matching the Stage D rationale (`admission.py:1-18`).

---

## 8. Open Decisions for the Owner

> **Out of scope note:** The server-icon feature (per-server icon display on server cards) is a separate UI item not covered by this branch workspace overview and is addressed in its own patch series.

1. **Default branch behavior:** Is `main` editable directly, or must all changes flow through a branch and a merge? The current engine permits direct commits when `allow_direct_commit` is true (`create_commit.py:136`).
2. **Auto-commit boundary:** What event closes a working-changes group — form submit, navigation, idle timeout, or an explicit Commit button? Is auto-commit on by default for Settings only, or for Files and Plugins too?
3. **Working-changes visibility:** Should grouped changes be visible to other users or sessions before commit, and should switching branches auto-commit or prompt?
4. **Reset safety:** Is a `Tag` with a reserved namespace acceptable as the recoverable anchor, or is a dedicated `[NEW]` safety checkpoint required?
5. **Cherry-pick conflict policy:** Fail loudly and require a manual resolved manifest, or block the operation until a three-way merge is authorized?
6. **Branch-instance identity:** Reuse `Runtime` with a display label, or create a distinct `[NEW]` branch-instance aggregate? The former is recommended by ADR-0015 and the Stage D vocabulary.
7. **Registry and lease keys:** Confirm `runtime_id` as the registry and lease key, with the live server retaining the `server_id` key.
8. **Port range:** What range may branch instances reserve, and must the reservation be visible in the server list?
9. **World handling:** Confirm COW/snapshot per branch instance and confirm that live world and players stay on `main`.
10. **Players:** Are branch instances always private, or may an authorized operator expose one to players?
11. **Resource accounting:** Should branch runtimes share the test admission cap, or have a separate cap? Are reservations persisted per runtime?
12. **Branch permissions:** Is the product single-admin or membership-scoped? No such decision label exists as an owner decision in the repository; an unrelated S4/S5 appears in `docs/design/SPEC-2026-10-02-DOCKER-STATUS-AND-DELETE-HONESTY-01.md:258-266` (describing Docker crash exit scenarios). The label is owner-supplied `[UNKNOWN]`. The answer determines whether Stage 4 is a grant table, an extended membership role, or deferred.
13. **Protected main:** Which policy fields become enforced (`require_test_pass`, `allow_force_bypass`), and who may bypass them?
14. **URL model:** Confirm `/servers/:serverId/b/:branch/<section>` with a canonical `main` default, or choose the query-parameter alternative.
15. **Test scope:** In the current implementation, `RunIsolatedTestCommand.commit_id` is optional (`run_isolated_test.py:21`); when omitted it falls back to the latest commit of the server, not the branch head (`run_isolated_test.py:92-99`). When testing in a branch workspace, should branch testing explicitly pass the branch head commit (and disable testing or prompt if the branch has no head commit), or fall back to the nearest ancestor/main commit?
16. **Retention:** How long do branch worktrees, safety checkpoints, and stopped branch instances persist? The current materialization lifecycle has no automatic expiry in Stage C.
17. **Branch Files scope (Stage 1):**
    - **Option A (Recommended for Stage 1):** Branch Files displays `TRACKED` paths only, editable. The current engine enforces this (`write_materialized_file.py:97,111`, ADR-0016); `PERSISTENT` (`world*`), `GENERATED` (`logs`), and `IGNORED` (`.onx`) paths are not displayed in the branch workspace.
    - **Option B:** Whole server directory shown in branch Files; `TRACKED` files remain editable while non-`TRACKED` files are displayed as read-only. This requires introducing a new read semantic in `get_materialization_tree.py:90` and `get_materialization_file.py:77` allowing reads of non-`TRACKED` paths while strictly blocking writes.
18. **Reconciliation lifecycle lease (F3):** Reconcile operations currently run without acquiring a lifecycle lease (`docs/design/SPEC-2026-11-08-SERVER-LIFECYCLE-HARDENING-01.md:180`).
    - **Option A:** Defer by a documented decision (reconciliation runs only at startup and via manual administrative API).
    - **Option B:** Treat as a launch blocker and require reconciliation to acquire a per-server lifecycle lease (`lifecycle_lock.py`).
19. **DeleteServer during provisioning/install (F4):** Deleting a server while it is in `PROVISIONING` status cancels the running install (`docs/design/SPEC-2026-11-08-SERVER-LIFECYCLE-HARDENING-01.md:81,174,200-202,659`).
    - **Option A:** Accept cancel-and-continue behavior and document it in the lifecycle spec (`delete_server.py:95-106`, `installer_provisioner.py`).
    - **Option B:** Refuse deletion requests while a server is actively provisioning.
20. **Branch-runtime registry persistence (Stage 3):** `RuntimeSupervisor._instances` (`supervisor.py:28`) is an in-process dictionary that cannot coordinate across multiple API worker processes.
    - **Option A (Recommended):** Multi-worker safety requires a DB-backed branch-runtime registry for runtime status, lifecycle leases, and port assignments (consistent with `ServerLifecycleLeaseModel` at `models.py:145` and `server_lifecycle_leases`).
    - **Option B:** Document a single-worker process limitation for Stage 3 branch runtimes.

---

## Appendix A — Identifier Verification

### A.1 Existing identifiers cited

| Identifier | Location | Status |
|---|---|---|
| `Project` | `backend/app/modules/versioning/domain/entities.py:29` | Verified |
| `Repository` | `entities.py:43` | Verified |
| `BranchProtectionPolicy` | `entities.py:54` | Verified |
| `ServerBranch` / `Branch` | `entities.py:83` / `entities.py:148` | Verified |
| `ServerCommit` | `entities.py:161` | Verified |
| `ServerWorldSnapshot` | `entities.py:152` | Verified |
| `Tag` | `entities.py:237` | Verified |
| `Materialization` | `entities.py:261` | Verified |
| `Runtime` | `entities.py:378` | Verified |
| `TestDefinition` | `entities.py:472` | Verified |
| `PersistentDataset` | `entities.py:562` | Verified |
| `ServerTestRun` | `entities.py:608` | Verified |
| `BranchStatus` | `backend/app/modules/versioning/domain/value_objects.py:27` | Verified |
| `MaterializationStatus` | `value_objects.py:33` | Verified |
| `MaterializationMode` | `value_objects.py:40` | Verified |
| `PathClassification` | `value_objects.py:60` | Verified |
| `CommitManifest` | `value_objects.py:91` | Verified |
| `Tree` | `value_objects.py:241` | Verified |
| `PortNumber` | `backend/app/modules/server/domain/value_objects.py:106` | Verified |
| `Server` aggregate | `backend/app/modules/server/domain/aggregate.py:99` | Verified |
| `ServerRuntimeModel` | `backend/app/modules/versioning/infrastructure/models.py:145` | Verified |
| `ServerTestRunModel` | `backend/app/modules/versioning/infrastructure/models.py:90` | Verified |
| `ServerMembershipModel` | `backend/app/modules/server/infrastructure/models.py:81` | Verified |
| `RuntimeSupervisor` | `backend/app/modules/server/application/supervisor.py:27` | Verified |
| `_instances` | `supervisor.py:28` | Verified |
| `ConsoleStreamManager` | `backend/app/modules/server/infrastructure/console_stream.py:49` | Verified |
| `admit()` | `backend/app/modules/versioning/application/scheduling/admission.py:233` | Verified |
| `advance_branch_head_optimistic` | `backend/app/modules/versioning/infrastructure/repository.py:111` | Verified |
| `check_cycle` | `backend/app/modules/versioning/domain/dag.py:9` | Verified |
| `traverse_history` | `dag.py:43` | Verified |
| `CreateBranchCommand` | `backend/app/modules/versioning/application/commands/create_branch.py:15` | Verified |
| `CreateCommitCommand` | `backend/app/modules/versioning/application/commands/create_commit.py:32` | Verified |
| `MergeCommitsCommand` | `backend/app/modules/versioning/application/commands/merge_commits.py:20` | Verified |
| `AutoCommitLiveChangesCommand` | `backend/app/modules/versioning/application/commands/auto_commit_live_changes.py:24` | Verified |
| `RevertImportReviewCommand` | `backend/app/modules/versioning/application/commands/revert_import_review.py:24` | Verified |
| `RunIsolatedTestCommand` | `backend/app/modules/versioning/application/commands/run_isolated_test.py:19` (optional `commit_id` at `:21`) | Verified |
| `ScanLiveChangesQuery` | `backend/app/modules/versioning/application/queries/scan_live_changes.py:16` | Verified |
| `TestSpec` / `TestHandle` | `backend/app/modules/versioning/infrastructure/test_runner.py:103` / `:119` | Verified |
| `Files` router path resolution | `backend/app/api/v1/routers/files.py:69-115` | Verified |
| `PROTECTED_DIRNAMES` | `files.py:25` | Verified |
| `GET /available-port` | `backend/app/api/v1/routers/servers.py:71-80` | Verified |
| `DUPLICATE_PORT` | `backend/app/modules/server/application/runtime_ownership.py:54` | Verified |
| `SERVER_ROLE_PERMISSIONS` | `backend/app/api/deps.py:128-153` | Verified |
| `require_server_permission` | `deps.py:156-240` | Verified |
| `permissions.yaml` versioning permissions | `contracts/permissions.yaml:120-150` | Verified |
| `permissions.yaml` roles | `contracts/permissions.yaml:160-172` | Verified |
| `server-switcher-select` | `frontend/src/layouts/ServerShell.tsx:286-291` | Verified |
| `selectedBranch` state | `frontend/src/server_manager/pages/ServerVersioningPage.tsx:39-40` | Verified |
| Routes | `frontend/src/App.tsx:91-100` | Verified |
| `ServerFilesPage` live API calls | `frontend/src/server_manager/pages/ServerFilesPage.tsx:139-240` | Verified |
| `ServerSettingsSection` | `frontend/src/server_manager/components/ServerSettingsSection.tsx:431-432` | Verified |
| `ServerExposurePage` | `frontend/src/server_manager/pages/ServerExposurePage.tsx:21-22` | Verified |
| `PluginListPage` | `frontend/src/server_manager/pages/PluginListPage.tsx:160-161` | Verified |
| Materialization API client | `frontend/src/services/api.ts:495-534` | Verified |
| Console channels | `backend/app/websocket/serializers.py:142` and `:150` | Verified |
| Live container name | `backend/app/modules/server/infrastructure/providers/docker.py:369` | Verified |
| Test container name | `backend/app/modules/versioning/infrastructure/test_runner.py:296` and `:641` | Verified |
| `server_lifecycle_leases` migration | `backend/alembic/versions/b1e2100000023_add_server_lifecycle_leases.py` | Verified (untracked) |
| `lifecycle_lock.py` | `backend/app/modules/server/application/lifecycle_lock.py` | Verified (untracked) |

### A.2 New identifiers proposed by this overview

| Identifier | Purpose | Status |
|---|---|---|
| `WorkingChangesGroup` | Group edits before a commit | `[NEW]` |
| `AutoCommitPolicy` | Per-branch/server auto-commit mode and boundary | `[NEW]` |
| `CommitFromWorktreeCommand` | Compile a worktree diff into a commit | `[NEW]` (named in the superseded spec, not in code) |
| `is_ancestor` | DAG ancestor/merge-base query | `[NEW]` (named in the superseded spec, not in code) |
| `SafetyCheckpoint` | Recoverable anchor before a reset | `[NEW]` |
| `BranchContext` | Frontend workspace context | `[NEW]` |
| `BranchInstance` | Alternative to reusing `Runtime` | `[NEW]` (not recommended) |
| `BranchRuntimeRegistry` | Registry keyed by runtime identity | `[NEW]` |
| `onx-branch-{server_id}-{runtime_short}` | Branch-instance container name | `[NEW]` |
| `runtime:{runtime_id}` | Lifecycle lease key | `[NEW]` |
| `runtime:{runtime_id}:console` | Console channel | `[NEW]` |
| `source=live|worktree` and `ref=<materialization_id>` | Files API branch mode | `[NEW]` |
| `branch_grants` | Branch-scoped grant table | `[NEW]` |
| `/servers/:serverId/b/:branch/<section>` | Branch-aware route | `[NEW]` |

### A.3 Not found in the repository

| Claim | Status |
|---|---|
| `RuntimeAdmissionScheduler` | `[UNKNOWN]` — not found; the implemented primitive is `admit()` (`admission.py:233`) |
| S4/S5 decision labels | `[UNKNOWN]` — no such decision label exists as an owner decision in the repository; an unrelated S4/S5 appears in `docs/design/SPEC-2026-10-02-DOCKER-STATUS-AND-DELETE-HONESTY-01.md:258-266`; owner-supplied label |
| Three-way merge / conflict resolution | `[UNKNOWN]` — not present; `merge_commits.py:139-143` requires a caller manifest |
| Restore/reset/cherry-pick commands | `[UNKNOWN]` — no command files exist |
| Branch-scoped permissions | `[UNKNOWN]` — no branch dimension in membership or permission strings |
| Multiple branch runtimes per server | `[UNKNOWN]` — `RuntimeSupervisor._instances` is keyed by `server_id` (`supervisor.py:28`) |

---

## Appendix B — Current Working-Tree Context

The following relevant files already carry uncommitted changes at the time of writing. Stage work must not overwrite them silently. This list is evidence of coordination risk, not authorization to edit.

**Untracked (new):**
- `backend/alembic/versions/b1e2100000023_add_server_lifecycle_leases.py`
- `backend/app/core/fs_utils.py`
- `backend/app/modules/server/application/lifecycle_lock.py`
- `backend/tests/api/test_files_protection.py`
- `backend/tests/application/test_lifecycle_lock.py`
- `backend/tests/modules/versioning/test_promote_commit_atomicity.py`
- `docs/design/SPEC-2026-11-08-SERVER-LIFECYCLE-HARDENING-01.md`

**Modified (relevant):**
- Backend: `backend/app/api/v1/routers/files.py`, `backend/app/api/v1/routers/servers.py`, `backend/app/core/config.py`, `backend/app/core/exceptions.py`, `backend/app/core/persistence/db_revision.py`, `backend/app/main.py`, `backend/app/registration.py`, `backend/app/modules/server/application/commands/{start,stop,restart,delete}_server.py`, `backend/app/modules/server/application/supervisor.py`, `backend/app/modules/server/domain/{aggregate,events,value_objects}.py`, `backend/app/modules/server/infrastructure/{fs,models}.py`, `backend/app/modules/server/infrastructure/providers/{docker,local,local_windows}.py`, `backend/app/modules/server/application/{runtime_ownership,reconciliation,runtime_reconciliation}.py`, `backend/app/modules/versioning/application/commands/{promote_commit,remove_materialization}.py`, `backend/app/modules/versioning/domain/entities.py`, `backend/app/modules/versioning/infrastructure/config_writer.py`.
- Frontend: `frontend/src/layouts/{AppShell,ServerShell}.tsx`, `frontend/src/server_manager/pages/ServerVersioningPage.tsx`, `frontend/src/server_manager/components/versioning/{BranchToolbar,CommitTimeline,StorageHealthBanner,TestRunList}.tsx`, `frontend/src/services/api.ts`.

---

## Appendix C — Reading Map for Implementation

| Topic | Primary evidence |
|---|---|
| Domain entities and invariants | `backend/app/modules/versioning/domain/entities.py`, `value_objects.py`, ADRs 0013–0016 |
| Commit DAG and merge behavior | `backend/app/modules/versioning/domain/dag.py`, `application/commands/merge_commits.py`, `create_commit.py` |
| Materialization and worktrees | `application/commands/create_materialization.py`, `write_materialized_file.py`, `infrastructure/tree_writer.py`, Stage C spec |
| Runtime identity and attach model | `domain/entities.py:378`, `infrastructure/models.py:145`, Stage F spec |
| Admission and concurrency | `application/scheduling/admission.py`, Stage D spec |
| Console streaming | `backend/app/modules/server/infrastructure/console_stream.py`, `backend/app/websocket/serializers.py`, Stage E spec |
| Test platform | `infrastructure/test_runner.py`, `application/commands/run_isolated_test.py`, Stage F spec |
| Files API | `backend/app/api/v1/routers/files.py`, `contracts/permissions.yaml:226-233` |
| Permissions and roles | `backend/app/api/deps.py:128-240`, `contracts/permissions.yaml:30-172` |
| Frontend workspace | `frontend/src/App.tsx:91-100`, `frontend/src/layouts/ServerShell.tsx:180-300`, `frontend/src/server_manager/pages/ServerVersioningPage.tsx` |
| Lifecycle hardening prerequisite | `docs/design/SPEC-2026-11-08-SERVER-LIFECYCLE-HARDENING-01.md`, `backend/app/modules/server/application/lifecycle_lock.py` (untracked) |
