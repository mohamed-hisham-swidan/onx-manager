# Server Provisioning

## Flow

`POST /api/v1/servers` → `CreateServerHandler.handle()`:

1. Generate `ServerId` (UUID)
2. Resolve server directory path
3. Within a `UnitOfWork`:
   - Create `Server` aggregate (state machine: `CREATED`)
   - Save to DB via `SQLServerRepository`
4. **Download server JAR** (type-specific resolution, see below)
5. Write `eula.txt` (auto-accepted)
6. Write `server.properties`
7. If error at steps 4–6: **delete the server directory** + re-raise
8. Commit the `UnitOfWork` (only on full success)

## Supported Server Types

| Type     | JAR Source                                    | Auto-download |
|----------|-----------------------------------------------|---------------|
| vanilla  | `piston-data.mojang.com` (SHA1 from manifest) | Yes           |
| paper    | `fill.papermc.io/v3` (latest build · `fill-data.papermc.io` download object) | Yes           |
| purpur   | `api.purpurmc.org` (latest download)          | Yes           |
| fabric   | `meta.fabricmc.net` (latest loader)           | Yes           |
| spigot   | `download.getbukkit.org/spigot`               | Yes           |
| bukkit   | `download.getbukkit.org/craftbukkit`           | Yes           |
| forge ≥ 1.17 | Maven installer (`--installServer`)       | Auto-install  |
| forge < 1.17 | Maven `-universal.jar`                      | Yes           |

## Forge Auto-Install (≥ 1.17)

Forge ≥ 1.17 publishes an installer JAR instead of a runnable server jar. The
create flow handles this asynchronously so the HTTP request is not blocked:

1. `CreateServerHandler` detects `server_type == "forge"` and
   `forge_requires_installer(version)` (MC ≥ 1.17).
2. The aggregate transitions into a new **`PROVISIONING`** status and is
   committed **before** any install work runs, so the server is visible
   immediately and the request returns fast.
3. After commit, a tracked background task runs `ForgeProvisioner.provision(...)`
   (the task is kept strongly referenced in a module-level registry so it can
   never be garbage-collected mid-install):
   - **Disk guard** — requires ≥ 4096 MB free on the server directory's
     filesystem (`ForgeInsufficientDiskError`).
   - Resolves the highest build for the MC version from the Forge Maven
     metadata (numeric-tuple comparison, never lexical — `58.0.10` sorts above
     `58.0.2`). Only real Minecraft versions (major `1.x`) are candidates —
     Forge's own unified artifact revisions (e.g. `26.2-65.1.2`) never resolve
     so a server can't be tagged with a fake "Minecraft" version.
   - Downloads `forge-{mc}-{build}-installer.jar` (same timeout/retry/
     validation pattern as server jars), then runs
     `java -jar forge-installer.jar --installServer` in the server directory
     via the `InstallerRunner` port (`SubprocessInstallerRunner` for local
     filesystems; the port/impl boundary is the Phase 11 switch point). The
     runner starts the command in its own process group and kills the whole
     group on timeout so neither the shell nor the `java` child is orphaned.
   - Verifies `run.sh` was produced.
   - Writes `user_jvm_args.txt` from the requested memory allocation.
   - Deletes the now-unused `forge-installer.jar` (a leftover would make the
     integrity check report a stray top-level jar forever).
   - Persists `LaunchConfiguration(start_command="bash run.sh")` and returns
     the server to **`CREATED`**.
4. On any failure the directory is deleted and the server is marked
   **`BROKEN`** with a typed error (`ForgeInstallError` family).

### Status lifecycle

```
CREATED → PROVISIONING → {CREATED (success), STARTING (user override), BROKEN (failure)}
```

- The server is not startable as a "normal" server until provisioning succeeds;
  the frontend keeps the Start action disabled while `PROVISIONING`.
- **Reconciliation**: on backend restart any still-`PROVISIONING` server is an
  interrupted install → marked `BROKEN` and its directory is deleted
  (`reconciliation.py`, stale-PROVISIONING branch).

### Pre-1.17 Forge

Legacy Forge still ships a plain executable jar. `download_server_jar` is now
version-aware: `< 1.17` downloads `forge-{mc}-{build}-universal.jar`
(the plain `forge-{mc}-{build}.jar` artifact **does not exist** on Maven and
would 404). These servers keep the synchronous, no-status-change flow.

### Create-wizard edition chooser

The Create wizard's `VersionStep` shows a **Modern (1.17+)** vs **Legacy
(< 1.17)** segmented toggle whenever Software = Forge. It filters the version
grid to the selected edition and explains the flow (installer vs universal jar).
Edition is derived purely from the chosen `minecraft_version`
(`frontend/src/server_manager/utils/forgeEdition.ts`, mirroring
`forge_requires_installer`); the create API is unchanged. (2026-08-21)

## JAR Validation

Every downloaded JAR is validated before the server is committed:
- **Magic bytes**: must start with `PK\x03\x04` (ZIP header)
- **Minimum size**: ≥ 1 MB
- Files that fail validation raise `CorruptedDownloadError` → `ProvisioningError`

## Retry & Timeout

- **Timeout**: 120s per download
- **Retries**: 2 retries with exponential backoff (1s, 2s)
- Retries only on `DownloadError` / `DownloadTimeoutError`
- `CorruptedDownloadError` is not retried (waste of bandwidth)

## Error Handling

| Scenario                    | Behaviour                                     |
|-----------------------------|-----------------------------------------------|
| Version not found           | `VersionNotFoundError` → `ProvisioningError`  |
| Download fails (all retries)| `DownloadError` → `ProvisioningError`         |
| Downloaded JAR is corrupt   | `CorruptedDownloadError` → `ProvisioningError`|
| Unknown server type         | `ValueError`                                   |
| Forge (manual install)      | Returns dest path, no download                 |
| Forge installer timed out   | `ForgeInstallTimeoutError` → `BROKEN` + cleanup |
| Forge installer failed      | `ForgeInstallFailedError` → `BROKEN` + cleanup |
| Forge disk space too low    | `ForgeInsufficientDiskError` → `BROKEN` + cleanup |
| Unexpected exception        | Wrapped as `ProvisioningError`                 |

Synchronous provisioning errors (pre-commit) **delete the server directory**
and **do not commit** the DB row. Forge ≥ 1.17 install failures happen
post-commit in the background task and instead transition to **`BROKEN`** and
delete the directory there.

## File Layout

A vanilla/legacy-forge server:

```
data/servers/{slug}-{uuid[:8]}/
├── server.jar
├── eula.txt
└── server.properties
```

A modern Forge (≥ 1.17) server after auto-install:

```
data/servers/{slug}-{uuid[:8]}/
├── run.sh                 # installer-generated launcher
├── libraries/             # installer-generated dependency tree
├── user_jvm_args.txt      # memory flags written from the request
├── eula.txt
└── server.properties
```

The integrity checker accepts the `run.sh` + `libraries/` layout for these
servers (the runtime jar lives deep inside `libraries/`, so the top-level
jar check alone would wrongly block them).

Every server created through the Create flow lives under `data/servers/`.
For servers from an existing directory, use the **Import** endpoint (`POST /api/v1/servers/import`) instead — it copies the external directory into the managed layout.

## Key Source Files

- `app/modules/server/application/commands/create_server.py` — handler (+ background trigger)
- `app/modules/server/application/services/jar_service.py` — JAR download, validation, version fetching, Forge metadata/resolver
- `app/modules/server/application/services/forge_provisioner.py` — installer execution flow
- `app/modules/server/domain/installer.py` — `InstallerRunner` port
- `app/modules/server/infrastructure/installer.py` — local-shell `SubprocessInstallerRunner`
- `app/modules/server/domain/aggregate.py` — `ServerStatus.PROVISIONING` transitions
- `app/modules/server/domain/runtime_exceptions.py` — `ForgeInstallError` family
- `app/modules/server/application/reconciliation.py` — stale-`PROVISIONING` cleanup
- `app/modules/health/infrastructure/integrity.py` — `run.sh` + `libraries/` acceptance
- `app/modules/server/infrastructure/fs.py` — atomic writes, directory cleanup
- `app/core/exceptions.py` — `ProvisioningError`, `DownloadError`, `CorruptedDownloadError`, `VersionNotFoundError`
