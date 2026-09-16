# Design Spec Folder — Enterprise Branch Runtime

**Status:** Draft — awaiting RECON + multi-agent review
**Roadmap placement:** ONX Manager Phase 7 (per Mohamed's 2026-09-16 decision — see governance note below)
**Source:** Derived from "MCS Manager — Enterprise Branch Runtime Platform" architecture report (uploaded 2026-09-16), an external AI-generated research proposal, not yet verified against the live codebase.

## Why this folder exists

The source report proposes rebuilding ONX Manager around five layers — Version Control (Git-style commit DAG), Workspace/Filesystem Materialization, Runtime, Observability, and UX — under one rule: **"Branch != Server != Container != Test."** These become distinct entities with explicit relationships instead of one another's stand-ins.

The report itself recommends a build order (Stage A → G) where later stages depend on the domain model Stage A establishes. This folder starts there, not at the full scope, because writing detailed specs for containerd/OCI/cgroup/scheduler work before the underlying domain model exists (or is even confirmed against live code) would be speculating on top of speculation.

## Governance note (flag, not a blocker)

Under the project's existing ROADMAP_v1.1 / GOVERNANCE.md, Phase 7 was previously scoped as **"visual/brand polish only"** — that narrowing was itself a fix applied when moving from ROADMAP v1.0 to v1.1, specifically to keep functional/architectural UX work out of Phase 7. Folding this proposal into Phase 7 changes that phase from visual polish to a runtime/versioning architecture change.

Per GOVERNANCE.md §4 this qualifies as a **D2 (Major)** decision — it changes architecture direction, persistence strategy, and roadmap order — and per Rule 5 ("no silent scope changes") it should get a short decision record for consistency with the project's own process, the same way the Phase 4↔5 reorder and the Containers pull-forward each got one. This is not a blocker; it's Mohamed's call and it's already been made. It's flagged here only so the roadmap doc doesn't quietly drift out of sync with what's actually being built — the exact failure mode this governance system exists to catch.

## What's in this folder

- **`01-stage-a-domain-reconstruction-design-spec.md`** — a full Design Spec (Orchestrator.md §5 format) for **Stage A only**: defining the Project/Repository/Commit/Branch/Revision/Materialization/Runtime/PersistentDataset/Run domain model, its state machines, invariants, and four required ADRs. This is the foundation everything else builds on.
- **`02-stages-b-through-g-outline.md`** — a captured **outline**, not a full spec, of the remaining stages (Real Version Control, Filesystem Model, Runtime Control, Console/Observability, Test Platform, Enterprise Capabilities). Each becomes its own Design Spec, through the same pipeline, once Stage A is approved and built.

## Review process

Per Orchestrator.md §4/§6, before `01-stage-a-...md` goes to Build:

1. **RECON — ✅ complete (2026-09-16).** Verified the spec's "Current Behavior" and "Affected Components" against live code; 3 of 6 checklist items required corrections (now applied in `01-...md` v2). One open design question remains (Invariant 2 vs. a shipped per-server lock) — blocks Design Review sign-off until resolved.
2. **Design Review** (a different agent than whoever did RECON, or Claude) checks the corrected spec against Orchestrator.md §6's criteria — root cause, scope, modular boundaries, duplication with existing work. Cannot sign off until the Invariant 2 question is resolved.
3. **Build** only starts after Design Review returns APPROVED or APPROVED WITH CHANGES.
4. **Separated Review** — implementation reviewed by an agent other than the builder, per the project's standing workflow.

## What this folder deliberately does not do

- It does not commit to Stage B-G's specific technology choices (containerd, OCI, cgroup v2, OpenTelemetry) — those get evaluated per-stage, with their own evidence and likely their own D2 records for new cross-cutting dependencies (GOVERNANCE.md §4), once Stage A actually ships and real usage patterns exist in this codebase.
- It does not itself pause bug-fixing work or write the Phase 7 decision record — that's Mohamed's decision to formalize (or not) separately.
