# ADR-0001: Modular Monolith with Hexagonal Boundaries

**Status**: Accepted
**Date**: 2026-07-22
**Author**: Architecture Review Board

## Context

We need to ship a commercial product quickly while preserving the ability to split into microservices later.

## Decision

Use a modular monolith where every module follows hexagonal (ports/adapters) architecture. Module boundaries are enforced by linting and code review. In-process Command/Query/Event buses simulate network boundaries.

## Consequences

- Fast development (single deployable, single process)
- Easy debugging (single log stream, single process)
- Extraction to microservices requires: extract module → add network layer → deploy separately
- Requires discipline — no direct cross-module imports
