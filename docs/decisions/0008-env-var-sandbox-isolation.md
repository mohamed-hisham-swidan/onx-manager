# ADR-0008: Environment-Variable-Driven Sandbox Isolation

**Status**: Accepted
**Date**: 2026-07-27
**Author**: Batch 2.5

## Context

Testing and development operations (server creation, deletion, file manipulation) wrote directly to the production `data/servers/` directory and the production database. During Batch 2 testing, a filesystem cleanup command accidentally deleted production server directories because there was no environment-based isolation — test and production shared the same paths.

Additionally, `setsid` was used to daemonize test backends but does not propagate environment variables, causing test processes to silently fall back to production paths.

## Decision

Adopt an environment-variable-driven sandbox pattern:

1. **`MCS_SERVERS_DATA_DIR`**: Overrides the server files directory (default: `data/servers`). All server file operations read this value from `AppSettings`.
2. **`MCS_DATABASE_URL`**: Overrides the database connection string. Already existed but was not consistently used in test scripts.

Every test script must set BOTH variables to sandbox paths. The backend must be started with both variables in the same `setsid` invocation (since `setsid` drops inherited variables).

## Consequences

- Production data is isolated from test/development operations
- Test scripts are self-documenting (the sandbox paths are explicit in the command)
- Developers must remember to set both variables (CI/CD will enforce this)
