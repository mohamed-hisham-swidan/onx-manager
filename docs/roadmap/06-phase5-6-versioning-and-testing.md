# MCS Manager — Execution Track: Phases 5–6 (Versioning, Testing/CI/Docs)

**Part V** of the Engineering Blueprint V4. This file covers **Phase 5 (Versioning & State
Consistency)** and **Phase 6 (Testing / CI / Documentation Reliability)** — the "platform hygiene"
that turns the foundation built in Phases 1–4 into something that cannot silently regress. These two
phases often read as lower-urgency than Phase 4; that framing is exactly why they exist and why they
must not be skipped (see §1.6 and §2.7 risks).

**Last updated:** 2026-08-06
**Supersedes:** `mcs-manager-roadmap-v4.md` Volumes 6–7, and the versioning target previously
described only in `docs/VERSIONING.md` (this file's Phase 5 makes that a committed standard).
Status indicators use the roadmap legend: ✅ done, 🔄 in progress, 🔶 planned, ⛔ blocked, ⚠️
risk/open question. Evidence discipline is in `04` §0 and Part I.

---

## 1. Phase 5 — Versioning & State Consistency 🔶

### 1.1 Objective

One authoritative version, consistent state sources, enforced rather than accidental. The word
*enforced* is the point: "one version" is already largely true in practice, but only as an observed
accident — a stable property until the day someone edits one file without the others.

### 1.2 Current reality (verified 2026-08-05)

- **The codebase is uniformly `4.0.0`** across `pyproject.toml`, `package.json`, `main.py`,
  `config.py`, and `package-lock.json`. The legacy `7.1.0` survives only in historical planning docs
  and a stale `Implementation/` tree inside a managed server's data directory — the latter is server
  content, out of versioning scope, and must not be edited.
- Backend version is **duplicated three times** (`pyproject.toml`, `config.py`, `main.py`) and
  requires manual syncing. Frontend version is independent and unlinked from the backend version.
- The plan is therefore to formalize the currently-true single-source arrangement into an *enforced*
  rule, not to change what the version *is*.

### 1.3 Target strategy (the standing standard, from `docs/VERSIONING.md` §4)

1. **One source of truth.** `backend/pyproject.toml` is canonical. Everything derives:
   - `AppSettings.version` reads the installed package metadata (`importlib.metadata`) with the
     current value as fallback, instead of a hardcoded default.
   - OpenAPI `version=` uses the same value.
   - The frontend consumes the backend-reported version (`GET /api/v1/settings` already returns
     `version`) as the single displayed product version; `package.json` version becomes build
     metadata only.
   - CI injects the resolved version so a tagged build is immutable.
2. **SemVer 2.0.0 semantics**, stated explicitly:

   | Segment | Meaning |
   |---------|---------|
   | `major` | Architecture change, breaking auth/security model, or a new top-level Roadmap phase |
   | `minor` | Backward-compatible feature (a new Roadmap workstream shipping) |
   | `patch` | Bug fix, doc fix, non-breaking QoL with no new capability |
   | `-pre` / `-rc` | Pre-release / release-candidate suffixes |

   `v1.0` public-release naming is decoupled from internal app SemVer — the roadmap's "v1.0" means
   "first public release," not "version 1.0.0."
3. **Migration/version compatibility.** Every release pins a minimum Alembic revision. On startup, if
   the DB is behind the required revision, auto-upgrade or refuse-to-start (a documented decision —
   links to D12, resolved in Phase 3 §1.6 K9). Per-release "head revision" documented in release notes.
4. **State-file discipline.** `.ai/CURRENT_STATE.json` / `.ai/PROJECT_STATE.json` `version` fields
   align to the resolved app version and note a verification date. Docs never assert a version they
   cannot justify from code; cross-cutting version claims centralize in `docs/README.md`.

### 1.4 Workstreams

1. CI check enforcing single-source version propagation (fails build if `pyproject.toml`,
   `package.json`, and the runtime-reported version disagree).
2. Frontend version-display refactor to consume backend-reported version instead of its own
   `package.json`.
3. SemVer policy document — internal version vs. public release version, stated once, referenced
   everywhere else.
4. Per-release minimum-Alembic-revision rule + compatibility check against Phase 3's DB-at-head
   baseline (K9).
5. `.ai` state-file audit and correction.

### 1.5 Dependencies

Soft dependency on Phase 3 (K9, DB at head) for the Alembic-compatibility workstream specifically;
the rest of this phase can proceed independently.

### 1.6 Acceptance criteria

Changing one source propagates everywhere without further edits; one document/command answers the
version question; no residual `7.1.0`-class orphan versions outside history and archived planning
docs.

### 1.7 Risks

- **Under-investment because nothing is "broken" today.** The whole point is preventing a future
  break, which is a harder sell than fixing a present one. This phase must not be skipped just
  because Phase 4's urgency makes it look comparatively unimportant.
- **Conceptual trap: `4.0.0` vs "v1.0".** Keeping internal iteration number and public-release
  identifier separate is deliberate and load-bearing (Part I, §1.7). Any implementation that conflates
  them makes both numbers meaningless as external communication.

---

## 2. Phase 6 — Testing / CI / Documentation Reliability 🔶

### 2.1 Objective

Make tests and docs trustworthy execution contracts — not just true the moment someone checked, but
structurally hard to let go stale.

### 2.2 Current reality

- `STATUS.md` mixes historical narrative with numbers that have gone stale multiple times; its own
  header now defers to `current-state.md` for current counts — a pattern this blueprint also follows,
  and which this phase should itself question: is a two-document split still the right model, or has
  it just added an indirection layer that can itself drift?
- V3's existence is proof of the core problem: a "verified" snapshot went stale within 24 hours when
  commit `b1b6dd8` landed. V4 will do the same — this is an observed, recurring pattern
  (v2 → v3 → V4), not a hypothetical risk.

### 2.3 Workstreams

1. **Re-baseline or remove historical-only counts in `STATUS.md`;** keep `current-state.md` (or its
   successor) as the single current-state source, and resolve whether that split-document model is
   still earning its complexity given the drift it has already exhibited twice.
2. **Extend backend CI** (built in Phase 4 §2.5) to fail on doc-vs-code drift where feasible — check
   that greps route/test/ADR counts out of the actual repo and diffs them against whatever
   `current-state.md` claims, failing CI on mismatch rather than relying on someone noticing and
   writing a v-next document.
3. **Documentation quality rules enforced** (implemented/partial/planned/historical labels) applied
   consistently across every doc in `docs/`, not just the roadmap and status files.
4. **Remaining duplicate sources of truth removed or redirected.**

### 2.4 Re-verification cadence (new in V4)

Specify concretely a fixed cadence (e.g., before every tagged release, or on a rolling N-week
schedule) for re-running the Phase 0-style live introspection this document and v3 both depend on,
and wire it into workstream 2's CI check so the cadence is enforced by automation rather than by
someone remembering.

### 2.5 Dependencies

Phase 4 (backend CI must exist before it can be extended) and, for count-checking, the version rules
of Phase 5.

### 2.6 Acceptance criteria

CI green across backend and frontend; any doc claim traces to code; no two docs contradict on
counts; a defined, automated re-verification cadence exists and has run at least once under its own
schedule (not just as part of writing this phase's rollout).

### 2.7 Risks

- **Fixing the symptom (stale docs) without fixing the cause (no enforcement).** Every prior roadmap
  revision has been a manual catch-up. If Phase 6 produces another manually-verified snapshot instead
  of an enforced, automated check, the project is guaranteed to need a V5 for the same reason it
  needed v3 and V4.
- **The two-document model drifting further.** If the `STATUS.md`/`current-state.md` split stays, it
  must be made non-redundant; if it can't be, collapsing it is correct (and is itself a
  doc-vs-code-structure decision the stream should make explicitly, not by default).

---

*Continue to [`07-phase7-10-network-and-ai-execution.md`](./07-phase7-10-network-and-ai-execution.md) for
Phases 7–10 (Network access, Dynamic endpoint + DNS, Final stabilization, AI) as committed execution
scope — all gated behind the foundation Phases 1–6.*