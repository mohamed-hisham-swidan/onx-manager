# MCS Manager — Dependency Graph, Milestones & Risk Register

**Parts VI (Dependency Graph & Milestones) and VII (Risk Register)** of the Engineering Blueprint V4.
This is a reference file that consolidates what the phase files (`04`–`07`) state individually: how
the phases depend on each other, what a milestone means and when each closes, and every known risk /
open question in one place.

**Last updated:** 2026-08-06
**Status:** Reference — consulted as needed, not read start-to-end. The phase files remain
authoritative for per-phase acceptance criteria; this file synthesizes them and must not contradict
them.

---

## 1. Dependency graph (Part VI)

### 1.1 Phase dependencies

The roadmap is strictly sequential in its gates, while allowing parallel *work* on non-overlapping
phases (see `04` §0.5 track view). The dependency edges:

```
Phase 1 (structure)      → Phase 2 (product foundation)
Phase 3 (reliability)    → Phase 4 (security)   [hard gate]
Phase 4 (security)       → Phase 7 (network)    [hard gate]
Phases 1–6               → Phase 7              [blocking edge]
Phase 7                  → Phase 8 (DNS)
Phases 1–8               → Phase 9 (stabilization)
Phases 1–9               → Phase 10 (AI)        [blocked on everything]
Phase 3 (K9 DB-at-head)  → Phase 5 (versioning, soft, Alembic sub-stream only)
Phase 4 (backend CI)     → Phase 6 (extend CI, re-verification)
```

### 1.2 The two hard gates that matter most

1. **Phase 3 → Phase 4.** Route gating (Phase 4) requires the corrected singular permission
   namespace that Phase 3 fixes as part of K1. Framed as a hard gate because gating against a wrong
   namespace means redoing the gating work.
2. **Phases 1–6 → Phase 7.** Network exposure must not start while authorization gaps (Phase 4) and
   reliability gaps (Phase 3) are open — a contained internal risk becomes an externally exploitable
   one. This gate is what keeps Part IV's speculative scope from leaking into committed scope.

### 1.3 Track view (reading aid, from `04` §0.5)

| Track | Phases | Note |
|---|---|---|
| Product/UI | 1, 2 | Sequential — Phase 2 depends on Phase 1's nav baseline |
| Reliability | 3 | Gates Phase 4 |
| Security | 4 | Gates Phase 7 |
| Platform hygiene | 5, 6 | Partially parallel to 3/4 where scope is disjoint |
| Network | 7, 8 | Sequential, both blocked on 1–6 |
| Close-out | 9 | Blocked on 1–8 |
| AI | 10 | Blocked on everything |

---

## 2. Milestones (Part VI)

A milestone is not "work is happening on this"; it is a **binary, verified close of an exit gate**,
re-verified against live code per `04` §0.3. Milestones below correspond to the phase-level exit
criteria in the phase files (authoritative), restated here as a single close-out checklist.

| Milestone | Phase(s) | Verified-close criterion (abbreviated; see phase file) |
|---|---|---|
| M1 — Product structure clear | 1 | Marketplace independently navigable; install verified; D3, D4 resolved |
| M2 — UI is honest and stable | 2 | Uniform states; zero silently-no-op controls; zero "connected-silent" WS |
| M3 — Product is reliable | 3 | WS delivers events fail-closed; settings persist+enforce; suite 0 failures; DB at head (D12); error contract documented |
| M4 — Authorization enforced & CI-guarded | 4 | All mutating routes permissioned; permissions.yaml consistent; SECURITY.md honest; route-coverage CI |
| M5 — Versioning non-driftable | 5 | One-source propagation enforced; no orphan `7.1.0` |
| M6 — Tests/docs self-verifying | 6 | CI catches doc-vs-code drift; automated re-verification has run on its own schedule |
| M7 — Safe to expose to network | 7 | Local/publish choice explicit; independent game/management exposure; tunnel authz == local authz |
| M8 — Stable published hostname | 8 | Endpoint changes propagate to state + DNS automatically |
| M9 — Hardened baseline | 9 | End-to-end verification recorded before AI |
| M10 — Guardrailed AI layer | 10 | All AI actions permission-gated, confirmed, audited |

### 2.1 Milestone discipline

A milestone is marked met only when all its exit criteria are met **and re-verified live** at close.
A carried count from a prior volume does not close a milestone; it must be re-verified against code
(Part I §1, `04` §0.3). The current phase in progress is Phase 1 (see `04` §2).

---

## 3. Consolidated risk register (Part VII)

Risks are registered either at the phase where they are most material or cross-cutting. Each carries
its owning phase file section for detail.

### 3.1 Cross-cutting risks

| ID | Risk | Owner | Mitigation / note |
|---|---|---|---|
| R-NS-DOC | Every roadmap revision drifts within ~24h of a commit | Part I, Phase 6 | Automated re-verification cadence (Phase 6 workstream; can't fix now, must fix then) |
| R-NS-DUP | Duplicate sources of truth silently drifting (version, permissions, counts) | Part I §2 | Derive-at-source discipline; Phase 5/6 enforcement |
| R-NS-SCOPE-CREEP | Backlog work (e.g. K16 multi-provider) quietly becoming phase blockers | Phase 1 | Explicitly parked as backlog, not exit criteria |

### 3.2 Phase risks (summary; details in phase files)

| ID | Risk | Phase | Nature |
|---|---|---|---|
| R1 | D4 route-namespace churn breaks marketplace-adjacent builds | 1 | Must-resolve-before-Phase-2 |
| R2 | Permission-aware UI built against unsettled contract (D2) | 2 | Build defensively, read from contract |
| R3 | Phase 2 scope bleeding into Phase 3 fixes | 2 | Discipline; acceptance criteria kept separate |
| R4 | K1/K2 fix colliding with Phase 2 WS-honesty work | 3 | Build against current broken state; re-verify after K1/K2 |
| R5 | D5 test re-baselining papers over a real bug | 3 | Assume real bug until proven stale |
| R6 | D2 blocks Phase 4 start | 4 | Resolve D2 before any gating work |
| R7 | Rushed registration decision (D13) ships a race-prone half-fix | 4 | Documented fallback sanctioned; prefer it over rushing |
| R8 | CI route-coverage too strict or too loose | 4 | Literal public allowlist as the exemption list |
| R9 | Phase 5 skipped due to low urgency | 5 | Deliberate: enforce to prevent future break |
| R10 | Phase 6 fixes symptom, not cause (no enforcement) | 6 | Must produce automated checks, not another snapshot |
| R11 | Phase 7 exposes authz gap to public internet | 7 | Hard gate on Phase 4; tunnel ≠ auth |
| R12 | Speculative multi-node leaking into Phase 7 scope | 7 | Single-instance scope boundary + Part IV labeling |

### 3.3 Known issues (K) and open decisions (D) pointers

Not duplicated here — the K- and D- registers are the authoritative lists. K-items are distributed
throughout the phase files where they land (K1–K6, K8–K15 live across `04`–`05`); the D-register
(D1–D13) is **Part VIII** in `11-decision-records.md`. See the file map in `00` §3 for where each
lives.

---

*Continue to reference material. If reading top-to-bottom, the next files are: `09` and `10`
(non-committed Part IV design topics), then Part VIII `11` (decision records) and Part IX `12`
(working agreements).*