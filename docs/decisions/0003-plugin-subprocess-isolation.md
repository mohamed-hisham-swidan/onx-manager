# ADR-0003: All Plugins Run as Subprocesses

**Status**: Accepted
**Date**: 2026-07-22
**Author**: Architecture Review Board

## Context

In-process plugins share the Python GIL and can block the event loop. A badly-behaved plugin can crash the entire manager.

## Decision

All plugins run as isolated subprocesses. Communication via JSON-RPC over a Unix socket. No in-process plugin execution is permitted.

## Consequences

- Plugin crashes do not affect the host process
- CPU-intensive plugins don't block the event loop
- Resource limits (CPU, memory, FD) are enforceable
- Higher latency for plugin↔host communication (~1ms via Unix socket)
- More complex development (plugins need their own process)
