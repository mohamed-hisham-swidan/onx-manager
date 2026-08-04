# ADR-0012: Same-Filesystem Staging for Atomic File Swaps

**Status**: Accepted
**Date**: 2026-08-04
**Author**: Production bugfix batch

## Context

Restore (`perform_safe_restore` in `backend/app/modules/backup/application/restore_service.py`) decrypts a backup archive and extracts it to a staging directory before atomically swapping the resulting folders/files onto the live server directory. The staging directory originally came from `tempfile.mkdtemp()` with no `dir` argument, which uses the OS default temporary directory (`/tmp` on POSIX).

On deployments where `/tmp` and the live server data directory live on different filesystems or mounts (verified on the production machine: `/tmp` is `tmpfs`, `backend/data/` is `btrfs`), the final `os.replace()` rename fails with:

```
OSError: [Errno 18] Invalid cross-device link: '/tmp/mcs-restore-*/extract/world' -> 'data/servers/server/world'
```

This is an OS-level constraint, not a Python or codebase bug: a rename (link) cannot cross a filesystem boundary. POSIX raises `EXDEV`; Windows has an analogous cross-volume restriction. It cannot be papered over in code — the staging location must be chosen correctly up front.

## Decision

Any code that extracts/stages files intended to be atomically swapped (`os.replace` / `os.rename`) onto a live target MUST stage them on the same filesystem as that target. Never assume the OS default temporary directory (`/tmp`, or platform equivalents) shares a filesystem with the destination.

Canonical pattern — stage as a sibling of the destination (same parent ⇒ same filesystem):

```python
staging_parent = os.path.dirname(os.path.abspath(target_dir))
os.makedirs(staging_parent, exist_ok=True)
temp_dir = tempfile.mkdtemp(prefix="mcs-restore-", dir=staging_parent)
```

File-level equivalent — the same-directory temp-write pattern used by `_atomic_replace_file` (same module): the temp file is written inside `os.path.dirname(dst)`, so the final `os.replace()` is same-directory by construction.

This decision is platform-independent: it relies only on portable stdlib behavior (`os.path.dirname`, `os.path.abspath`, `tempfile.mkdtemp(dir=...)`, `os.replace`) and behaves identically on Linux, macOS, and Windows.

## Consequences

- Directory and file swaps never cross a mount boundary, so atomic restore works regardless of the OS temp directory's filesystem.
- Staging/cleanup semantics are unchanged: the temp directory is created and removed (`shutil.rmtree`) exactly as before, on success or failure.
- On systems where `/tmp` shares a filesystem with the destination, behavior is identical — only the staging location differs.
- Future features that stage data for atomic moves must follow this pattern; defaulting to the OS temp dir will reintroduce EXDEV failures.
