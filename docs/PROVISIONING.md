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
| paper    | `api.papermc.io` (latest build)               | Yes           |
| purpur   | `api.purpurmc.org` (latest download)          | Yes           |
| fabric   | `meta.fabricmc.net` (latest loader)           | Yes           |
| spigot   | `download.getbukkit.org/spigot`               | Yes           |
| bukkit   | `download.getbukkit.org/craftbukkit`           | Yes           |
| forge    | Manual install required                        | No            |

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
| Unexpected exception        | Wrapped as `ProvisioningError`                 |

All provisioning errors **delete the server directory** and **do not commit** the DB row. The server_id is never persisted if provisioning fails.

## File Layout

```
data/servers/{server_id}/
├── server.jar
├── eula.txt
└── server.properties
```

Custom paths via `install_dir` in the request body.

## Key Source Files

- `app/modules/server/application/commands/create_server.py` — handler
- `app/modules/server/application/services/jar_service.py` — JAR download, validation, version fetching
- `app/modules/server/infrastructure/fs.py` — atomic writes, directory cleanup
- `app/core/exceptions.py` — `ProvisioningError`, `DownloadError`, `CorruptedDownloadError`, `VersionNotFoundError`
