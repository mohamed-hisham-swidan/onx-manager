# Outline — Stages B through G (Enterprise Branch Runtime)

**Status:** Captured for future planning. **Not** design specs — each of these gets its own full Design Spec, through the normal RECON → Design Spec → Design Review pipeline, once Stage A is built and the entities below actually exist in code. Writing detailed specs for these now would mean designing against entities that don't exist yet.

Each stage below lists: what it covers, what from the source report it borrows, and the trigger condition for when it's ready to become a real spec.

---

## Stage B — Real Version Control

**Covers:** Making the `Repository`/`Commit`/`Branch` domain model (Stage A) actually persist and behave like Git — branch-from-any-commit, arbitrary diff, tags, merge (later).
**Report basis:** §4.1 (Git's separation of history and working trees), Appendix B sources 1-3.
**Trigger for spec:** Stage A's domain entities and ADR #1 (git-binding decision) are built and reviewed. ADR #1 specifically decides whether this stage shells out to `git` or implements DAG persistence directly — that decision must exist before this spec can be written.

## Stage C — Filesystem Model

**Covers:** Implementing `Materialization` for real — branch/revision file browser, path classification (tracked/persistent/generated/ignored/ephemeral), runtime-change import review flow.
**Report basis:** §3.3 (branch vs. filesystem distinction), Stage C steps 13-17.
**Trigger for spec:** Stage B's revision resolution works, since materialization needs a real revision to materialize.

## Stage D — Runtime Control

**Covers:** Domain `Runtime` identity + a global scheduler/resource-pool/admission policy. **RECON-narrowed (2026-09-16):** container lifecycle, multi-runtime support, and per-container resource policy are already shipped via Phase 5's `DockerProvider` — this stage is NOT "build container runtime control," it's "add the scheduling/admission layer the shipped provider doesn't have."
**Report basis:** §3.5 (never hide concurrency behind arbitrary global locks), Stage D steps 18-23 — largely superseded by what Phase 5 already shipped.
**Trigger for spec:** Stage A's Invariant 2 open question (lock lifted vs. kept vs. deferred, see `01-...md`) must be resolved first — it directly determines whether this stage needs a scheduler at all in the near term, or whether the existing per-server lock is "good enough" until real multi-runtime demand appears.

## Stage E — Console and Observability

**Covers:** WebSocket console streaming, interactive exec, reconnect/cursors, per-runtime metrics, correlated logs/events, historical retention.
**Report basis:** §Observability & Control, Appendix B sources 12-14 (OpenTelemetry).
**Trigger for spec:** **RESOLVED & RESCOPED (Stage E Build):** Per ADR-0015 and Stage D spec §(e), domain `Runtime` entity instantiation is deferred to Stage F; Stage E triggers and attaches directly to shipped `ServerHandle`, `server_id`, and `onx-test-{test_id}` container identities.

## Stage F — Test Platform

**Covers:** Making `TestDefinition`/`TestRun` first-class, bound to exact revisions, parallel runs, structured assertions/evidence, cleanup/retention.
**Report basis:** Stage F steps 30-34.
**Trigger for spec:** This directly overlaps the Phase 4 "test environment" feature — RECON in Stage A already needs to map this overlap. This stage's spec should fold in (not duplicate) whatever's already shipped there.

## Stage G — Enterprise Capabilities

**Covers:** RBAC/ABAC, audit logging, protected branches, multi-host scheduler, resource pools, persistent-volume snapshots, backup/restore.
**Report basis:** Stage G steps 35-41.
**Trigger for spec:** Explicitly the last stage in the report's own recommended order, and the one furthest from anything currently in ONX Manager (single-host, no multi-tenant RBAC model yet). Each item in this stage likely needs its own GOVERNANCE.md D2 record before a spec is even written — this is the stage most likely to be partially rejected or deferred to Lane E (Future/Backlog) once real usage of Stages A-F exists to justify it.
