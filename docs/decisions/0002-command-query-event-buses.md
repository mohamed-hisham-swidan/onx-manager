# ADR-0002: Separate Command, Query, and Event Buses

**Status**: Accepted
**Date**: 2026-07-22
**Author**: Architecture Review Board

## Context

Initial design used the Event Bus for everything. Commands (intent), events (facts), and queries (reads) were mixed.

## Decision

Split into three buses:
- **CommandBus**: synchronous, returns result, with transaction middleware
- **QueryBus**: synchronous, returns data, with cache middleware
- **EventBus**: asynchronous, fire-and-forget, with retry + dead letter queue

## Consequences

- Clear separation of concerns (CQRS at the bus level)
- Idempotency applied only to commands (not queries or events)
- Transactions only on commands (queries don't modify state)
- More code, but clearer boundaries
