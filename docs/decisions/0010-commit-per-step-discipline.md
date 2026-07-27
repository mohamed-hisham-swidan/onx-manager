# ADR-0010: Commit-per-Step Discipline for Structural Changes

**Status**: Accepted
**Date**: 2026-07-27
**Author**: Batch 2.5 (learned) / Batch 3 (formalized)

## Context

Earlier batches bundled unrelated changes into single commits, making it difficult to review, roll back, or understand what was done for each specific fix. During Batch 2.5, four distinct bug fixes were committed separately, and this pattern was formalized in Batch 3 (5 commits across 5 steps).

## Decision

All structural, organizational, and bug-fix work MUST follow a commit-per-step discipline:

- One logical change per commit
- Each commit must be immediately verifiable (tests pass, app boots)
- No bundling of unrelated changes, even small ones
- The commit message must explain what was changed, why, and how it was verified

This replaces the previous "batch-level commit at the end" pattern.

## Consequences

- Cleaner git history for auditing and rollback
- Slightly more commits, but each is smaller and focused
- Easier code review (reviewers can verify one change at a time)
- CI/CD can validate each commit independently
- This discipline is now encoded in `.ai/AI_RULES.md` and `AGENTS.md`
