# ONX Manager — Real Engineering Roadmap
## v1.1 — Revised after external review

**Status:** DRAFT for Mohamed's review — each phase is scoped at the level needed to write individual Design Specs per stage; not itself a substitute for those specs.
**Supersedes:** `ROADMAP_v1.md` (2026-09-01 — external review found: no ground-truth baseline phase, a circular dependency between Phase 1 and Phase 2, branding conflated with functional UX, an unrecorded architecture-reorder decision, and looser language than the actual exit criteria implied). This version keeps every fact from v1.0 and fixes those five issues plus several smaller ones below.
**Governing document:** [`docs/governance/GOVERNANCE.md`](../governance/GOVERNANCE.md).
**Phase order:** dictated by Mohamed — ground truth first (new in v1.1), then bugs, backend, frontend, community-driven features, containers, install/wrap-up, and branding/UI polish **last**.

## Current Release Objective

> Prepare ONX Manager for a safe, verified, cross-platform open-source release — every claim in this roadmap backed by evidence gathered in this session or later, not carried forward from a prior document.

Any task, anywhere in this roadmap, should be explainable as serving this objective, or it doesn't belong in the current release scope (per `GOVERNANCE.md` §16, "why now?").

---

## Phase 0 — Ground Truth / Baseline Freeze *(new in v1.1)*

**Why this phase exists:** v1.0 mixed "figure out what's actually true" with "fix what's broken" inside Phase 1, which is why Phase 1 and Phase 2 ended up needing the same Windows-lifecycle answer — a genuine circular dependency an external review caught. This phase exists solely to establish facts. No fixing happens here.

**Scope — establish and freeze, with evidence, not assumption:**

1. **Full test run, both platforms.** Actual current backend + frontend pass/fail counts on Linux CI and on the new `windows-ci.yml` (which already produced real failures on its first run 2026-09-01 — those failures get catalogued here, not fixed here). Record real numbers in `.ai/STATE.json`, replacing every `UNVERIFIED` field where evidence is now obtainable.
2. **Windows lifecycle ground truth.** One RECON pass answering plainly: is `local_windows.py` dead code or live code today; if live, does it use Job Objects or something else; which of the original W-01–W-06 blockers (if any) still apply to whatever exists now; does a server survive a graceful backend shutdown on Windows, tested for real.
3. **`preflight.py` hang ground truth.** Resolve the direct contradiction between "not yet fixed" (last detailed investigation) and "fixed, commit 623c3d2" (a draft roadmap's claim, which looks like it conflated this hang with the separately-and-actually-fixed detection-loop hang). One evidence-based answer, no assumption either way.
4. **Repo/DB state.** Current Alembic head + migration count, current git state, whether the `_archive/` folder pre-existing at repo root needs review before it's considered separate from `.ai/archive/`.
5. **Old-roadmap claims spot-check.** Workstreams A/B/C ("Complete, ready for commit" per the old `ROADMAP.md`) — confirm or refute each with evidence, don't carry the claim forward either way.

**Gate:** Phase 0 has an owner and a hard expectation — this is investigation, not a place to live indefinitely. Target: resolved within the time it takes to run the test suites and do the two RECON passes (§2, §3 above) — not an open-ended research phase.

**Exit criteria:** `.ai/STATE.json` contains real, freshly-verified numbers with no `UNVERIFIED` field left where evidence was obtainable. The Windows-lifecycle and `preflight.py` questions each have one evidence-backed answer, recorded. This baseline is then **frozen** — Phase 1 classifies against it, Phase 2/3 fix against it; nothing here gets silently re-investigated later without a new decision record.

---

## Phase 1 — Bug Triage & Classification *(re-scoped in v1.1 — diagnosis and routing, not deep fixes)*

**Goal:** every item below reaches a **verified disposition** — fixed (if small and self-contained enough to close right here), or routed to Phase 2/3 with a Lane + Decision Level, or explicitly deferred with a decision record. *(v1.0 said "ALL known bugs, no exceptions" — too strong given the actual exit criteria always allowed deferral/reclassification; this wording matches what the system actually does.)*

Using Phase 0's frozen baseline as input, classify:

| Item | Lane | Likely routing |
|---|---|---|
| Windows lifecycle (whatever Phase 0 found it to actually be) | A (auto-critical) | → Phase 2, deep backend work |
| `preflight.py` hang (whatever Phase 0 found it to actually be) | A (auto-critical) | → Phase 2 if still open; closed here if Phase 0 found it genuinely fixed |
| Fresh-clone BOM/encoding hang | A | ✅ Already fixed & verified — closed, no routing needed |
| Python-detection loop hang | A | ✅ Already fixed & verified — closed, no routing needed |
| Bug track 2 (TPS anomaly, scheduler skips, SQLAlchemy pool warnings) | A (auto-critical) | → Phase 2, needs its own RECON first |
| Syntax highlighting broken | B | → Phase 3 |
| "Extended files" issue | Unclassified | **Blocked — needs Mohamed's clarification of what this refers to before it can even get a Lane** |
| Comment feature incomplete | B | → Phase 3 |
| Files API possible IDOR | Unclassified, pending evidence | → Phase 2, needs RECON to confirm real before it gets a Lane |
| ROADMAP.md Workstream A/B/C claims | N/A — this is a documentation/state-integrity check, not a bug | Resolved in Phase 0 §5, not a Phase 1 bug item |
| Rename pipeline final status | N/A — state-verification task | Quick check, closed wherever it naturally fits once confirmed (likely Phase 0/1 boundary, not deep work) |
| FastAPI `merged_lifespan` recursion | Unclassified, needs reproduction | → Phase 2 once a traceback exists; can't be classified without one |
| Windows CI first-run failures | A (surfaces real Phase 2 work) | → Phase 2, these ARE the Windows-lifecycle work in practice |

**Exit criteria:** every row above has moved from "?" to a routed destination with a Lane. Nothing is fixed *in* Phase 1 beyond what's trivially self-contained; the deep work happens in Phase 2/3 where it can be scoped properly instead of turning this phase into what the external review correctly called a "bug graveyard."

---

## Phase 2 — Backend Stabilization

Receives everything routed here from Phase 1. Known contents going in (final scope depends on Phase 1's routing table, detailed in its own Design Spec):

- Windows lifecycle real implementation/fix, built against Phase 0's ground truth (not re-investigated here).
- `preflight.py` fix, if Phase 0 found it still open.
- Bug track 2 items, each RECON'd individually.
- Files API IDOR, if confirmed real.
- Workstream B (diagnostics-leak) re-verification.
- Full backend suite green on **both** Linux and Windows CI — the 2026-09-01 Windows CI failures get resolved here, not deferred.
- Re-verify the 5 CI quality-gate scripts genuinely pass, not just historically claimed to.

## Phase 3 — Frontend Stabilization *(now also carries functional UX/reliability fixes — see Phase 7 note)*

- Syntax highlighting fix.
- Comment feature completion.
- "Extended files" issue, once Mohamed clarifies what it refers to.
- Workstream A re-verification.
- **Any functional UX or reliability fix discovered along the way lands here (Lane B), not in Phase 7.** Phase 7 is visual/brand polish only — see the split below.
- Full frontend suite green on both Linux and Windows CI.

## Phase 4 — Feature Build from Community Feedback Pool

Same five features, same evidence base (r/admincraft, 2026-08-10), same priority order as v1.0:

1. Transparent update system (rollback/proceed/disable + failed-mod list).
2. Test environment (temporary test container/server).
3. Custom mod support.
4. Change history log.
5. Better log/crash readability.

**Dependency on Phase 5 — RESOLVED (2026-09-01).** Mohamed's decision: the test-environment isolation backend is a **permanent user-facing choice**, not a temporary stand-in — the product ships with both a **files-based mode** and a **container-based mode**, selectable by the user. Containers become the **default** once Phase 5 lands; files-based stays available long-term (e.g. for setups without Docker). This means feature #2 starts now, built files-based first, with the container backend added as an additional (and eventually default) option once Phase 5's core primitive exists — not a swap, an addition. No blocking dependency remains between Phase 4 and Phase 5.

## Phase 5 — Containers System

**Decision Record required and included below** (v1.0 pulled this forward from the old roadmap's Phase 11 without formally recording why — the external review correctly flagged this as a `GOVERNANCE.md`-governed reorder that needs its own record).

Scope: replace host-level tmux/process execution with isolated per-server Docker containers across Linux/macOS/Windows. Also covers "state-of-the-art validation of GPS/local mode/global mode" and port-forward library testing — **"GPS" is a blocked item, not committed scope, pending Mohamed's definition of what it refers to.**

## Phase 6 — Final Installs / Wrap-up

**Scope clarified in v1.1:** this is the *final public-facing* documentation and packaging pass — installer polish, first-run experience, distribution packaging, a last README/CONTRIBUTING review. It is **not** where documentation happens for the first time; per `GOVERNANCE.md` §10, docs stay synchronized with decisions and state continuously, throughout every phase above.

## Phase 7 — Visual / Brand Polish *(renamed and narrowed in v1.1)*

Deliberately last, and now scoped tightly to what's actually branding: logo, visual identity, shapes, animation, imagery. **Functional UX fixes are explicitly excluded from this phase** — those are Lane B work that lands in Phase 3 (or wherever the fix naturally belongs) as soon as they're found, not held until here. This was v1.0's clearest gap: "Branding/UI-UX" conflated two different kinds of work with two different urgencies.

---

## Decision Record — Containers moved from old-roadmap Phase 11 to new Phase 5

```
# DECISION-2026-09-01-001 — Move containerization work forward in release order

Status: Accepted
Lane: Release Improvement (enables Phase 4 feature #2) / Engineering
Decision level: D2 (Major — roadmap drift, architectural)
Roadmap drift: Controlled

## Context
The prior roadmap (old ROADMAP.md / GOVERNANCE.md's original phase sketch)
placed Docker containerization as Phase 11, well after launch-adjacent work.
Mohamed's explicit phase order for the real roadmap places a working
containers system at position 5 of 7, ahead of final install/wrap-up and
branding, and it is also a likely prerequisite for Phase 4's "test
environment" community-requested feature.

## Evidence
- Mohamed's explicit dictated phase order (2026-09-01 session).
- r/admincraft feedback: two independent commenters (Mr_Potatoez,
  notyoursocialworker) specifically requested a temporary/isolated test
  environment before touching production — real container isolation is the
  most credible way to deliver that safely.

## Options considered
1. Keep containers at old Phase 11 position (rejected — blocks the
   highest-leverage community-requested feature from being done safely).
2. Move containers to Phase 5, as scoped here (accepted).

## Decision
Containers work moves to Phase 5 of the new roadmap, per Mohamed's
directive and the Phase 4 dependency evidence above.

## Impact
- Product/user: unlocks a safer path to Phase 4's test-environment feature.
- Architecture: introduces Docker as a new runtime provider alongside
  LocalLinuxProvider/LocalWindowsProvider — real, scoped architectural
  change, hence D2 not D1.
- Operations: adds a new deployment dependency (Docker) not previously
  required.

## Effort
Not yet estimated — pending Phase 5's own Design Spec.

## Reversibility
Moderate — the container provider is additive (existing local providers
keep working), but the Phase 4 feature #2 dependency decision (see Phase 4
above) is coupled to this and would need revisiting if this were reversed.

## Roadmap impact
Major — this document (ROADMAP v1.1) reflects the new position directly.

## Verification
Phase 5's Design Spec + its own exit criteria (not yet written).

## Outcome
Pending — filled in once Phase 5 actually starts.
```

---

## Open questions carried into v1.1 (need Mohamed's input)

1. What does "extended files not working properly" refer to? (Phase 1 table) — Mohamed will check and report back.
2. What does "GPS" refer to in "state-of-the-art validation of GPS/local mode/global mode"? (Phase 5)
3. Is the agent-role-division idea (backend owner / frontend owner / network owner) something to formalize into `GOVERNANCE.md`, or keep informal?
4. `preflight.py`'s real current status — this is now Phase 0's job to resolve with evidence, but if Mohamed already knows the answer, it saves a RECON pass.

---

*Like v1.0, this document is the ordering/scoping layer above individual Design Specs, not a replacement for them.*
