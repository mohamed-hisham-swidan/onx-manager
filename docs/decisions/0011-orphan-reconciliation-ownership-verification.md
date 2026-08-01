# ADR-0011: Orphan Reconciliation Ownership Verification

**Status**: Accepted
**Date**: 2026-07-30
**Author**: Batch 6

## Context

`reconcile_orphans()` was designed to clean up stale OS resources (tmux sessions, Java processes) that previous runs of the project left behind. Its original approach was naive: discover all `mcs-*` tmux sessions and all Minecraft-looking Java PIDs system-wide, then kill anything not registered in the DB as running/starting.

This meant any real Minecraft server on the same machine — launched independently, not managed by this project — that happened to use a `mcs-*` tmux session name or matched the `-jar`+`server` cmdline heuristic was killed on every backend startup. The DB cross-reference (added in 3521d33) only protected servers this project was actively tracking; untracked servers had no DB row to match against.

## Decision

Reconcile-orphans must not kill a process unless it can verify the process was actually launched by this project. Three independent verification mechanisms are used, in order of specificity:

1. **Positive ownership marker** — Every project-spawned process gets `MCS_MANAGED=1` in its environment. This is the most reliable signal because it's under our control and not dependent on naming conventions.

2. **cwd-based ownership** — `/proc/{pid}/cwd` is checked against the project's `MCS_SERVERS_DATA_DIR`. A process whose working directory is inside the project's data directory is treated as owned. This catches processes launched before the marker was introduced.

3. **Process start-time verification** — `/proc/{pid}/stat` start_time is read for audit logging. This is now also compared against the DB-stored `deployment_start_time` (`ServerModel`), populated at start and migrated via revision `a3b2c3d4e5f6`.

### Scope parameter

The function accepts `scope: Literal["project_owned", "system_wide"]`:

- `"project_owned"` (default) — runs all three verification checks. Any uncertain check → skip (fail-safe).
- `"system_wide"` — legacy behavior: kills based on name/heuristic patterns alone. Only available via explicit API call.

### Consequences

- **Positive**: Backend startup no longer kills untracked real Minecraft servers on the same machine.
- **Positive**: Structured audit logging provides traceability for every kill/skip decision.
- **Positive**: Fail-safe default prevents transient I/O errors from causing false-positive kills.
- **Negative**: Genuinely orphaned project processes from before the marker was introduced will only be caught if their cwd still resolves to the project data directory or if `system_wide` scope is explicitly used.
- **Trade-off**: The cwd check depends on `/proc` being mounted and accessible. In Docker environments, this may require additional configuration (`--pid=host` or similar).
