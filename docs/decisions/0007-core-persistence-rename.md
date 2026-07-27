# ADR-0007: Rename app/storage/ to app/core/persistence/

**Status**: Accepted
**Date**: 2026-07-27
**Author**: Batch 3

## Context

The project had two directories both named "storage":

- `app/storage/` — DB persistence layer: `DeclarativeBase`, `DatabaseEngine`, `UnitOfWork`
- `app/modules/storage/` — File storage backends: `StorageBackend` ABC, `LocalStorage`, `S3Storage`

These are fundamentally different concerns, but the shared "storage" name caused confusion. The documentation (`docs/STATUS.md`) incorrectly listed file-storage files (`local.py`, `s3.py`, `encryption.py`) as belonging to `app/storage/`, and developers looking for DB persistence code would look in the wrong directory.

## Decision

Rename `app/storage/` → `app/core/persistence/` to make the DB-persistence purpose self-evident. This follows the established pattern where `app/core/` already contains shared infrastructure (`command_bus.py`, `event_bus.py`, `config.py`, `exceptions.py`, etc.).

`app/modules/storage/` is left unchanged — it is a proper DDD module with its own domain/infrastructure boundary.

## Consequences

- Clear separation: `core/persistence/` = database, `modules/storage/` = file storage
- 87 import paths updated across the codebase
- Documentation (`STATUS.md`, `module-map.md`, `file-ownership.md`, `DATABASE.md`) updated to reflect new paths
- Backward-incompatible for any external code importing from `app.storage` (none known)
