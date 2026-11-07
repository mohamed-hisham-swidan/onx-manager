# Design Spec: Bug 3 — Server Identity Loss & Provider-Badge Flip Remediation

**Document Status:** APPROVED BY MOHAMED (2026-09-13) — PROCEEDING TO BUILD  
**Governance Classification:** Decision Level D1 (Significant) / Release Critical track (Release Critical)  
**Governing Authority:** project governance standards§12; project engineering standards  
**Target Delivery:** Bug 3 Fix (Server Identity & Container Cleanup Pipeline)  
**Author:** ONX Engineering  
**Date:** 2026-09-13  

---

## 1. Goal

Eliminate server identity loss and the resulting provider-badge flip (`Docker Container` → `File / Host`) across server restarts, system reboots, and filesystem reconciliation passes.

### Concrete Objectives
1. **Creation/Import-Time Authoritative Identity Stamping:** Ensure every server created via `CreateServerHandler` or imported via `ImportServerHandler` writes an authoritative identity file (`.onx-manager/server.json`) directly during its transaction, persisting the server's real UUID and configured provider. (No legacy dual-write on creation/import; reconciliation retains its existing read-fallback and migrate-on-read for any legacy `.mcsmanager/` directories).
2. **Reconciliation Adopt-vs-Import Logic:** Enhance `FilesystemReconciliationService` so that when a Minecraft server directory lacks an on-disk identity file, it queries the database for an existing server row matching `deployment.root_path`. If found, it heals the on-disk identity file using the existing row's UUID and provider rather than minting a new random UUID and importing a local-provider duplicate.
3. **Orphaned Container Cleanup:** Ensure that when a Docker server row is deleted (or permanently purged during reconciliation), any Docker container associated with that server ID or bind-mounting that server directory is reliably destroyed via provider destroy wiring, preventing ghost containers from holding host ports and directory locks.

---

## 2. Current Behavior & Root Cause Analysis

### 2.1 The Confirmed Failure Mechanism (codebase audit Sandbox Repro)
Forensic investigation and sandbox reproduction revealed that the provider-badge flip is caused by a **multi-stage row-replacement cycle**, not an in-place column update:

```
[Server Creation: Docker]
  │
  ├─ 1. CreateServerHandler allocates ServerId X (provider="docker")
  ├─ 2. Saves Server X to DB: deployment.root_path = "data/servers/test-server-X"
  ├─ 3. Writes server.properties, eula.txt, downloads server.jar
  └─ 4. CRITICAL GAP: NEVER writes .onx-manager/server.json!
        (Directory on disk is completely identity-less)

[Server Restart / System Reboot]
  │
  ├─ 5. Backend restarts. main.py lifespan runs FilesystemReconciliationService.reconcile()
  ├─ 6. Reconciliation scans data/servers/test-server-X
  ├─ 7. Stage 2 (_read_single_identity): No identity file found → IdentityStatus.MISSING
  ├─ 8. Stage 3 (_detect_minecraft): Minecraft files detected → ScanCategory.MINECRAFT_VALID
  ├─ 9. Stage 4 (_build_plan) Line 425:
  │      - Blindly generates new UUID: uid = uuid.uuid4().hex (ServerId Y)
  │      - Plans ActionType.IMPORT for ServerId Y
  │      - ServerId X was never added to `accounted` set!
  │      - Lines 456-475 classify ServerId X as UNACCOUNTED → Plans ActionType.MARK_MISSING
  │
  └─ 10. Stage 5 (_execute_plan):
         - _handle_import writes .onx-manager/server.json with ServerId Y
         - _build_server_from_scan defaults provider to default_provider_for_platform() ("local")
         - Saves ServerId Y to DB (provider="local")!
         - _handle_mark_missing marks ServerId X as missing (missing_since = now)
         - On subsequent pass / restart: _handle_delete purges ServerId X from DB!
```

### 2.2 Forensic Confirmation of the Couplings
1. **Creation Stamping Gap:** In `backend/app/modules/server/application/commands/create_server.py:174-201` and `import_server.py:84-150`, files are placed in `server_dir_path`, but neither handler invokes any identity file writer. In fact, `write_single_identity` exists exclusively as a private method in `filesystem_reconciliation.py:914`.
2. **Reconciliation Blind Import:** In `filesystem_reconciliation.py:423-433`, when `identity.status == IdentityStatus.MISSING` and `scan.is_minecraft == True`, the service immediately generates `uid = uuid.uuid4().hex` without checking if any existing row in `db_servers` has `root_path == entry.path`.
3. **Orphan Container Retention:** When `_handle_delete` (`filesystem_reconciliation.py:722-734`) deletes an unaccounted server from the DB, it executes `await self._repo.delete(server.id)` without invoking `provider.destroy(handle)`. As a result, Docker container `onx-<uuid-X>` remains running or exited in Docker daemon, retaining host port 25565 and volume mounts.

---

## 3. Proposed Change

### 3.1 Component 1: Authoritative Identity Stamping Helper
Extract identity writing into a reusable application service:  
`backend/app/modules/server/application/services/identity_writer.py`

#### Interface & Responsibilities
- `write_server_identity(dir_path: str | Path, uid: str, provider: str = "local", fs: FileSystem | None = None) -> None`:
  1. Writes the primary identity file atomically:
     - Target: `<dir_path>/.onx-manager/server.json`
     - Per Decision 1, no legacy `.mcsmanager/` dual-write is performed on creation or import.
  2. Implements POSIX-atomic write (`tempfile.NamedTemporaryFile` in `.onx-manager` dir + `os.replace` / `fs.rename`).
  3. JSON document schema:
     ```json
     {
       "version": 1,
       "uid": "<hex32>",
       "server_id": "<hex32>",
       "provider": "docker",
       "created_at": "2026-09-13T01:50:00.000000+00:00",
       "manager": "onx-manager",
       "schema_version": 1
     }
     ```
  4. Integration into `create_server.py`: Called within the `async with UnitOfWork` transaction block immediately after directory resolution and before jar download.
  5. Integration into `import_server.py`: Called within the `async with UnitOfWork` transaction block immediately after zip extraction or directory copy, explicitly overwriting any stale identity from the source archive.
  6. Reconciliation Legacy Compatibility: `filesystem_reconciliation.py` retains its existing read-fallback (`_identity_paths`) and migrate-on-read logic for any existing legacy `.mcsmanager/` directories, but all newly written or healed identity files write exclusively to `.onx-manager/server.json`.

### 3.2 Component 2: Reconciliation Adopt-vs-Import Logic
Update `backend/app/modules/server/application/services/filesystem_reconciliation.py`:

#### Stage 4 (`_build_plan`) Modification
Before classifying an entry with `IdentityStatus.MISSING`:
1. Build a root-path index of existing database servers:
   ```python
   db_by_path: dict[str, list[Server]] = {}
   for s in db_servers:
       if s.deployment and s.deployment.root_path:
           norm = str(Path(s.deployment.root_path).resolve())
           db_by_path.setdefault(norm, []).append(s)
   ```
2. When evaluating `entry` where `identity.status == IdentityStatus.MISSING` and `scan.is_minecraft`:
   - Compute `entry_norm = str(Path(entry.path).resolve())`.
   - Query `candidates = db_by_path.get(entry_norm, [])`.
   - **Branch A (Existing DB Match — Adopt & Heal):**
     - Select primary candidate using deterministic tie-breaking.
     - Add primary candidate to `accounted.add(str(candidate.id))`.
     - Plan `ActionType.HEAL_IDENTITY` with `pa.db_server = candidate`, `pa.fs_entry = entry`, `pa.scan = scan`.
   - **Branch B (No DB Match — True Unmanaged Server):**
     - Mint new random `uid = uuid.uuid4().hex`.
     - Plan `ActionType.IMPORT` with `pa.identity = IdentityResult(status=IdentityStatus.MISSING, uid=uid)`.

#### Stage 5 (`_execute_plan`) Addition
- Implement `_handle_heal_identity(self, pa: PlanAction, result: ReconciliationResult) -> None`:
  1. Extract `uid = str(pa.db_server.id)` and `provider = pa.db_server.runtime.provider or "local"`.
  2. Write identity to disk via `write_server_identity(pa.fs_entry.path, uid, provider, fs=self._fs)`.
  3. If `pa.db_server.missing_since is not None`:
     - Clear `missing_since = None`.
     - Save updated server to repository.
  4. Update server broken/repaired/deployment status if needed based on `scan`.
  5. Record in `result.identity_healed`.

### 3.3 Component 3: Orphaned Container Cleanup
Prevent zombie Docker containers from persisting when server rows are deleted or purged:

#### 1. Enhanced `DockerProvider.destroy(handle: ServerHandle)`
In `backend/app/modules/server/infrastructure/providers/docker.py`:
- In addition to removing the container by primary name (`handle.external_id` or `onx-{handle.server_id}`), query and clean up:
  1. Legacy named container: `mcs-{handle.server_id}`.
  2. Containers with server ID labels:
     `docker ps -a -q --filter label=com.onx-manager.server_id={handle.server_id}` and legacy prefix.
  3. Containers bind-mounting the server directory:
     If `root_path = handle.metadata.get("root_path")` is present:
     `docker ps -a -q --filter volume={host_mount}`.
  4. Force-remove all matching containers with `docker rm -f`.

#### 2. Reconcile Deletion Provider Teardown
In `filesystem_reconciliation.py`:
- Inject `ProviderFactory` into `FilesystemReconciliationService` (`provider_factory: ProviderFactory | None = None`).
- In `_handle_delete(self, pa: PlanAction, result: ReconciliationResult)`:
  - Extract `provider_type = server.runtime.provider if server.runtime and server.runtime.provider else default_provider_for_platform()`.
  - Construct `ServerHandle(provider=provider_type, server_id=sid, external_id=external_id, metadata={"server_name": server.name, "root_path": server.deployment.root_path if server.deployment else None})`.
  - Safely invoke `await provider.destroy(handle)` with `DESTROY_TIMEOUT_SECONDS = 10.0` inside `try...except Exception` before `repo.delete(server.id)`.

#### 3. DeleteServerHandler Metadata Enrichment
In `backend/app/modules/server/application/commands/delete_server.py`:
- Ensure `handle.metadata` includes `"root_path": server_dir` so `DockerProvider.destroy` receives directory context for volume-filter cleanup.

---

## 4. Affected Components

| Module / File | Change Type | Description |
|---|:---:|---|
| `backend/app/modules/server/application/services/identity_writer.py` | **New** | Centralized atomic identity writer stamping `.onx-manager/server.json` with provider metadata. |
| `backend/app/modules/server/application/commands/create_server.py` | **Modify** | Invoke `write_server_identity` at server creation time within UoW. |
| `backend/app/modules/server/application/commands/import_server.py` | **Modify** | Invoke `write_server_identity` at server import time within UoW, overwriting archive identity. |
| `backend/app/modules/server/application/commands/delete_server.py` | **Modify** | Pass `root_path` in `ServerHandle.metadata` for volume-based container cleanup. |
| `backend/app/modules/server/application/services/filesystem_reconciliation.py` | **Modify** | Add `ActionType.HEAL_IDENTITY`, adopt-vs-import matching logic by `root_path`, single-write to `.onx-manager`, and provider destroy teardown in `_handle_delete`. |
| `backend/app/modules/server/infrastructure/providers/docker.py` | **Modify** | Broaden `destroy()` to clean up containers by server ID labels and volume mount filter. |

---

## 5. Interfaces & Contracts

### 5.1 Identity Document Contract
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ServerIdentityDocument",
  "type": "object",
  "required": ["version", "uid", "created_at", "manager", "schema_version"],
  "properties": {
    "version": { "type": "integer", "enum": [1] },
    "uid": { "type": "string", "minLength": 32, "maxLength": 32 },
    "server_id": { "type": "string", "minLength": 32, "maxLength": 32 },
    "provider": { "type": "string", "enum": ["docker", "local", "local_windows"] },
    "created_at": { "type": "string", "format": "date-time" },
    "manager": { "type": "string", "enum": ["onx-manager", "mcsmanager"] },
    "schema_version": { "type": "integer", "enum": [1] }
  }
}
```

### 5.2 Plan Action & Result Contract Extensions
In `filesystem_reconciliation.py`:
- Add `ActionType.HEAL_IDENTITY = "heal_identity"` to `ActionType` enum.
- Add `identity_healed: list[dict[str, Any]] = field(default_factory=list)` to `ReconciliationResult`.
- Property `total_healed: int` on `ReconciliationResult` returning `len(self.identity_healed)`.

---

## 6. Failure Cases & Edge Cases

### 6.1 Two DB Rows Pointing to the Same `root_path`
- **Scenario:** Previous erroneous import or unmanaged duplicate records created two DB rows pointing to the same server directory.
- **Resolution Algorithm:**
  1. Score all candidate DB rows:
     - `+100` if `missing_since is None` (row is currently active).
     - `+50` if status is active (`RUNNING`, `STARTING`, or `CREATED`).
     - `+25` if provider matches detected runtime or is explicitly non-default (`docker`).
     - Tie-breaker: most recent `updated_at` / `created_at`.
  2. The candidate with the highest score is chosen for `ActionType.HEAL_IDENTITY` and added to `accounted`.
  3. All other candidate rows are left out of `accounted`. They will naturally receive `ActionType.MARK_MISSING` (or `ActionType.DELETE`), and their provider handles will be cleaned up.
  4. Log structured warning:
     `"Duplicate DB servers match root_path %s: adopted %s, marking %s as stale"`.

### 6.2 Pre-Fix Damaged Servers
- **Scenario:** Servers created before Bug 3 fix that have no `.onx-manager/server.json` and may have been marked `MISSING` by a previous restart.
- **Resolution Algorithm:**
  1. When reconciliation runs, `db_by_path` identifies the existing DB row.
  2. Reconciliation heals the missing identity on disk with the DB row's UUID and configured provider (`docker`).
  3. If `server.missing_since is not None`, `_handle_heal_identity` clears `missing_since` and restores server health.
  4. The server row is never deleted, and the provider badge remains intact (`Docker Container`).

### 6.3 Concurrent Creation + Boot Reconciliation Race
- **Scenario:** Server creation API request (`POST /api/v1/servers`) arrives while lifespan reconciliation is scanning `data/servers/`.
- **Resolution Algorithm:**
  1. **Write-Ahead Identity Stamping:** `CreateServerHandler` writes `.onx-manager/server.json` before initiating jar downloads or long-running operations.
  2. **Provisioning Status Immunity:** Line 485 of `filesystem_reconciliation.py` already checks `if server.status == ServerStatus.PROVISIONING: plan.actions.append(UNCHANGED); return`. A server undergoing setup is never touched.
  3. **Scan Failure Immunity:** If reconciliation inspects a directory before the jar or identity file finishes writing, `scan_server_directory` marks it `ScanCategory.SCAN_FAILED`, which maps strictly to `ActionType.IGNORE`.
  4. **Atomic Rename:** Identity stamping uses atomic temporary file replacement, ensuring no reader ever observes a partially written JSON file.

### 6.4 Docker Daemon Unreachable During Destruction
- **Scenario:** Server row is deleted while Docker daemon is stopped or socket is unresponsive.
- **Resolution Algorithm:**
  - `DockerProvider.destroy` catches `OSError`, `FileNotFoundError`, and `asyncio.TimeoutError`, logging warnings without raising.
  - Deletion of the database record proceeds cleanly to avoid permanently locking the user interface.

---

## 7. Tests & Verification Plan

### 7.1 Unit & Service Tests
1. `tests/unit/test_identity_writer.py`:
   - Verify atomic creation of `.onx-manager/server.json`.
   - Verify contents match schema including `uid`, `server_id`, `provider`, `manager`.
   - Verify directory creation if `.onx-manager` does not exist.
   - Verify overwrite safety on existing files.
2. `tests/application/test_create_import_identity_stamping.py`:
   - Verify `CreateServerHandler` stamps identity with `provider="docker"` for Docker servers.
   - Verify `CreateServerHandler` stamps identity with `provider="local"` for local servers.
   - Verify `ImportServerHandler` stamps identity and overwrites any foreign identity from imported zip.
3. `tests/application/test_reconciliation_adopt_heal.py`:
   - **Missing Identity + DB Row Exists:** Assert reconciliation executes `ActionType.HEAL_IDENTITY`, writes `.onx-manager/server.json`, leaves DB row ID and provider intact, and does NOT import a duplicate.
   - **Missing Identity + No DB Row:** Assert reconciliation executes `ActionType.IMPORT`, generates new UUID, and creates new managed server.
   - **Duplicate DB Rows for Same Path:** Assert reconciliation adopts active row and marks duplicate as missing.
   - **Repaired Identity with DB Row:** Assert invalid identity file is healed using existing DB row UUID.
4. `tests/infrastructure/providers/test_docker_container_cleanup.py`:
   - Verify `DockerProvider.destroy` removes container by name, label filter, and volume mount filter.
   - Verify `FilesystemReconciliationService._handle_delete` invokes provider destroy before repository delete.

### 7.2 End-to-End Sandbox Repro Test
`tests/integration/test_bug_3_sandbox_repro.py`:
1. Spin up test environment with SQLite and mock Docker provider.
2. Create Docker server `test-srv` (`provider="docker"`).
3. Verify identity file is stamped on disk immediately upon creation.
4. Trigger `FilesystemReconciliationService.reconcile()`.
5. Verify:
   - Server row count in DB is exactly 1.
   - Server ID is unchanged.
   - Server provider is still `docker`.
   - Result reports 0 imported, 0 missing, 0 deleted.
6. Delete identity file on disk to simulate pre-fix state.
7. Trigger `FilesystemReconciliationService.reconcile()`.
8. Verify:
   - Server row count is still exactly 1.
   - Identity file is restored on disk with original UUID and `provider="docker"`.
   - Server provider in DB is still `docker` (badge flip prevented).

---

## 8. Out of Scope

1. **Retroactive Database Migrations Without User Consent:** No automated schema migration will guess or mutate server provider values for servers created on other machines without filesystem evidence.
2. **Phase 4 Features / COW Git Versioning:** Decoupled per `DECISION-2026-09-12-001`.
3. **Modifications to Non-Docker Provider Teardowns:** Local Linux (tmux/process) and Windows (JobObject) teardowns are unaffected.

---

## 9. Design Review Self-Application (project engineering standardsChecklist)

| Criteria | Assessment | Detail |
|---|:---:|---|
| **1. Scope & Boundaries** | **PASS** | Strictly resolves Bug 3 root causes: creation stamping, reconciliation adopt/heal, and container cleanup. No feature creep. |
| **2. Architecture & DDD** | **PASS** | Follows Hexagonal / CQRS boundaries. Identity writer is an application service; UoW encapsulates transactional writes; aggregate invariants preserved. |
| **3. Safe Fallbacks** | **PASS** | Keeps existing reconciliation read-fallback and migrate-on-read for `.mcsmanager` while standardizing new writes to `.onx-manager`. |
| **4. Deterministic Resolution** | **PASS** | Eliminates non-deterministic row replacement by indexing DB rows on `root_path` and applying priority scoring. |
| **5. Contracts & Quality Gates** | **PASS** | Zero schema breakage. Compatible with all 5 CI quality gates. |
| **6. Edge Cases Handled** | **PASS** | Covers duplicate DB rows, pre-fix damaged servers, boot races, and daemon timeouts. |
| **7. Unknowns Resolved** | **PASS** | Confirmed row-replacement mechanism verified via sandbox repro. |

---

## 10. Locked Decisions Approved by Mohamed (2026-09-13)

1. **Single-Write Identity Stamping:** Write identity exclusively to `.onx-manager/server.json` during server creation and import. Do not dual-write `.mcsmanager/`. Keep reconciliation's existing read-fallback and migrate-on-read logic unchanged.
2. **Deterministic Adopt-vs-Heal Tie-Breaking:** When reconciliation detects an un-identified directory matching an existing DB `root_path`, heal the identity file with that row's UUID and provider. If duplicate DB rows match, score them (`active > created > stopped/broken`, newest `updated_at`), adopt the highest-scoring row, and mark duplicates as missing.
3. **Volume-Filter Container Cleanup in Provider Destroy:** Enhance `DockerProvider.destroy()` to clean up containers by server ID labels and volume mount filter (`root_path`), and wire provider destroy into `FilesystemReconciliationService._handle_delete()`.

> **DESIGN SPEC APPROVED — PROCEEDING TO BUILD.**
