# Design Spec Folder — Enterprise Branch Runtime

**Status:** COMPLETED & VERIFIED (Stages A–G backend & frontend UI batch built, verified, and committed)
**Roadmap placement:** ONX Manager Phase 7 / Enterprise Branch Runtime Architecture (DECISION-2026-09-17-004)
**Source:** Derived from "MCS Manager — Enterprise Branch Runtime Platform" architecture report (uploaded 2026-09-16). All stages formalize and build upon the principle: **"Branch != Server != Container != Test."**

## Why this folder exists

The source report proposes rebuilding ONX Manager around five layers — Version Control (Git-style commit DAG), Workspace/Filesystem Materialization, Runtime, Observability, and UX — under one rule: **"Branch != Server != Container != Test."** These become distinct entities with explicit relationships instead of one another's stand-ins.

The implementation was executed in dependency order (Stage A → G + Frontend UI Batch):
- Stage A: Domain Reconstruction (Domain models, invariants, ADRs 0013–0016)
- Stage B: Real Version Control (Commit DAG, multi-parent merges, tags, diffs)
- Stage C: Filesystem Model & Materialization Engine (Worktrees, atomic fs, import review)
- Stage D: Runtime Control & Scheduling (Admission overlay, DB-level mutex, capacity accounting)
- Stage E: Console & Observability (WebSocket streaming follower, WS exec/input, unified docker stats)
- Stage F: Test Platform, Crash Correlation & Verification (TestDefinition aggregate, 1:1 Runtime attach, EvidenceBundle)
- Stage G: Protected Branches (Configurable protection policy, promotion gating, emergency bypass)
- Frontend: Enterprise Versioning UI Batch (Modals, DAG inspector, worktree browser, policy editor)

## What's in this folder

- **`00-README.md`** — Overview and index of the Enterprise Branch Runtime refactor.
- **`01-stage-a-domain-reconstruction-design-spec.md`** — Stage A: Domain Reconstruction (Built & Verified: `e72a219`).
- **`02-stages-b-through-g-outline.md`** — Stages B–G Outline and trigger dependencies.
- **`03-stage-b-real-version-control-design-spec.md`** — Stage B: Real Version Control (Built & Verified: `641ea58`, migration `b1e210000015`).
- **`04-stage-c-filesystem-materialization-design-spec.md`** — Stage C: Filesystem Model & Materialization Engine (Built & Verified: `8f10a4d`, migration `b1e210000016`).
- **`05-stage-d-runtime-scheduling-design-spec.md`** — Stage D: Runtime Control & Scheduling (Built & Verified: `e77a82c`, migration `b1e210000017`).
- **`06-stage-e-console-observability-design-spec.md`** — Stage E: Console & Observability (Built & Verified: `41da076` / `0b64ef2`).
- **`07-stage-f-test-platform-design-spec.md`** — Stage F: Test Platform, Crash Correlation & Verification (Built & Verified: `785c7cc`, migration `b1e210000018`).
- **`08-enterprise-versioning-frontend-design-spec.md`** — Frontend UI Batch for Stages B, C, F, and G (Built & Verified: `8b219ba`).

## Review & Governance Process

The design and build workflows adhere strictly to the project's canonical governance and execution policies:
- **codebase audit:** In-depth investigation of live code, dependencies, and invariants prior to design.
- **Design Spec:** Structured specification covering goals, current behavior, proposed changes, interfaces, and test criteria.
- **Design Review:** Independent review verifying root causes, failure modes, and boundaries before build authorization.
- **Build & Verification:** Strict test-driven execution requiring 100% CI quality gates PASS, zero regressions, and state synchronization before closure.

*(Note on historical citations: references in earlier design drafts to project engineering standards refer to the prompt execution instructions governing the agent workflow, codified canonically in project governance standards and project engineering policies.)*

