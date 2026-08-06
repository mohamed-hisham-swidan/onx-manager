<a name="volume-6"></a>
## Volume 6 — Phase 5: Versioning & State Consistency 🔶

### 6.1 Objective

One authoritative version, consistent state sources, enforced rather than accidental.

### 6.2 Current reality

- Backend `pyproject.toml` is the canonical version source; runtime, OpenAPI, and the displayed
  product version derive from it. **Already true in practice** (verified 2026-08-05: `4.0.0`
  uniform across `pyproject.toml`, `package.json`, `main.py`, `config.py`) — this phase formalizes
  it with an enforced rule (e.g. a CI check) rather than leaving it an observed accident. "Observed
  accident" is not a stable property — it held today because nobody has yet edited one file without
  the others; that's exactly the kind of invariant that silently breaks under normal development
  pressure unless something enforces it.
- Frontend displays the backend-provided version; `package.json` becomes build metadata only.
- SemVer conventions are stated explicitly; "v1.0 public release" is decoupled from the internal
  app version — this distinction matters because the project is already at `4.0.0` internally while
  having never had a public release, and conflating the two would make the version number
  meaningless as external communication.
- A per-release minimum-Alembic-revision rule governs DB compatibility; report/constrain
  production upgrade status against it. This directly depends on Phase 3's K9 work (production DB
  brought to head) — this phase's job is the *rule*, not the one-time fix.
- `.ai` state-file version fields align to the resolved version; docs stop asserting versions the
  code can't justify (the historical `7.1.0` figure should be scoped explicitly to planning-doc
  history, not implied as a current or past code version — this is exactly the kind of drift that
  originally motivated `current-state.md`'s creation as a single verified source).

### 6.3 Workstreams

1. CI check enforcing single-source version propagation (fails build if `pyproject.toml`,
   `package.json`, and runtime-reported version disagree).
2. Frontend version-display refactor to consume backend-reported version instead of its own
   `package.json`.
3. SemVer policy document — internal version vs. public release version, stated once, referenced
   everywhere else.
4. Per-release minimum-Alembic-revision rule + compatibility check against Phase 3's DB-at-head
   baseline.
5. `.ai` state-file audit and correction.

### 6.4 Dependencies

Soft dependency on Phase 3 (K9, DB at head) for the Alembic-compatibility workstream specifically;
the rest of this phase can proceed independently.

### 6.5 Acceptance criteria

Changing one source propagates everywhere without further edits; one document/command answers the
version question; no residual `7.1.0`-class orphan versions outside history and archived planning
docs.

### 6.6 Risks

- Low-risk phase overall, but easy to under-invest in because nothing is "broken" today — the whole
  point is preventing a future break, which is a harder sell than fixing a present one. Recommend
  not skipping this phase just because Phase 4's urgency makes it look comparatively unimportant.

---

<a name="volume-7"></a>
## Volume 7 — Phase 6: Testing / CI / Documentation Reliability 🔶

### 7.1 Objective

Make tests and docs trustworthy execution contracts — not just true at the moment someone checked,
but structurally hard to let go stale.

### 7.2 Current reality

- `STATUS.md` mixes historical narrative with numbers that have gone stale multiple times already
  (its own header now explicitly defers to `current-state.md` for current counts — a pattern this
  very document (V4) also follows, and which should itself be questioned in this phase: is a
  two-document split still the right model, or has it just added a layer of indirection that can
  itself drift?).
- v3's own existence is proof positive of the core problem: a "verified" snapshot went stale within
  24 hours when commit `b1b6dd8` landed. **V4 will do the same** — this is not a hypothetical risk,
  it's an observed, recurring pattern across v2→v3 and almost certainly v3→V4.

### 7.3 Workstreams

1. Re-baseline or remove historical-only counts in `STATUS.md`; keep `current-state.md` (or its
   successor) as the single current-state source — and resolve whether that split-document model
   is still earning its complexity, given the drift it's already exhibited twice.
2. Extend backend CI (built in Phase 4 §5.5) to fail on doc-vs-code drift where feasible — e.g., a
   check that grep's route counts, test counts, and ADR counts out of the actual repo and diffs
   them against whatever `current-state.md` claims, failing CI on mismatch rather than relying on
   someone noticing and writing another v-next document.
3. Documentation quality rules enforced (implemented/partial/planned/historical labels) — applied
   consistently across every doc in `docs/`, not just the roadmap and status files.
4. Remaining duplicate sources of truth removed or redirected.

### 7.4 Re-verification cadence (new in V4)

V3 flagged that a re-verification cadence needed to be *defined*, not just performed once more.
This phase is where that gets specified concretely: propose a fixed cadence (e.g., before every
tagged release, or on a rolling N-week schedule) for re-running the Phase 0-style live
introspection this document and v3 both depend on, and wire it into workstream 2's CI check so the
cadence is enforced by automation rather than by someone remembering to do it.

### 7.5 Dependencies

Phase 4 (backend CI must exist before it can be extended).

### 7.6 Acceptance criteria

CI green across backend and frontend; any doc claim traces to code; no two docs contradict on
counts; a defined, automated re-verification cadence exists and has run at least once under its own
schedule (not just as part of writing this phase's rollout).

### 7.7 Risks

- **This phase fixing the symptom (stale docs) without fixing the cause (no enforcement).** Every
  prior roadmap revision in this project's history has been a manual catch-up. If Phase 6 produces
  another manually-verified snapshot instead of an enforced, automated check, the project is
  guaranteed to need a V5 for the same reason it needed v3 and V4.

---

<a name="volume-8"></a>
## Volume 8 — Phases 7–10: Network, DNS, Stabilization, AI 🔶⛔

*These four phases are carried forward from v3 with their content unchanged in substance — v3's
scoping here was already sound and grounded (single-instance remote access, explicit architectural
boundaries, AI guardrails). This document does not re-litigate them, only confirms they remain
correctly sequenced after everything above, and cross-references where V4's new volumes affect
their framing.*

### 8.1 Phase 7 — Network access / port forwarding 🔶⛔
**Blocked on Phases 1–6.**

**Design reference:** `docs/network-access-design.md`.

**Scope:** remote access to **your own single running instance** — not multi-tenant hosting, not
multi-node orchestration. **This scope boundary is why Volume 9's speculative multi-node/cloud
ideas cannot simply graduate into this phase without a separate decision process — Phase 7's entire
design, including its security posture, assumes single-instance scope. Multi-node is a different
threat model, not an extension of this one.**

**Two user-facing modes**
- **A. Tunnel (recommended default).** Abstracts NAT, router config, manual port forwarding,
  dynamic public-IP handling, endpoint changes, DNS sync.
- **B. Manual port forwarding.** Advanced users manage router/firewall/IP/ports themselves.

**Architectural boundaries that must hold**
1. `TunnelProvider` stays separate from `DnsProvider` — never conflate them.
2. Dynamic endpoints — accept endpoints discovered/assigned at runtime.
3. Game and management exposure are independent — separate toggles, separate tunnels, separate
   security postures; never gate them together.
4. Tunnel ≠ authentication — tunnel traffic runs through the exact same auth/authorization stack
   as local traffic. **This is where Phase 4's work becomes load-bearing rather than optional: if
   Phase 4 leaves any gap, Phase 7 exposes that gap to the public internet.**
5. DNS is optional and pluggable.
6. No provider preselection.
7. Provider extensibility uses official APIs only — never browser automation or scraping.

**Hardened defaults in publish mode**
- Rate limiting is already per-client and per-path (confirmed in Phase 0 §1.1, `current-state.md`
  §4.6 — corrects an earlier "process-global" claim).
- Shorter access-token lifetimes, mandatory HTTPS, optional-but-strongly-prompted 2FA (**D9,
  open**).
- RBAC/ABAC enforced everywhere; unauthenticated access is the explicit exception.
- Revisit `GET /metrics` exposure (K10) under this decision, per Phase 4 §5.7.

**Exit criteria:** explicit local/publish choice in the install flow; game and management exposure
independently controllable; tunnel traffic provably subject to the same authz as local traffic;
manual port-forwarding mode documented.

### 8.2 Phase 8 — Dynamic endpoint + DNS architecture 🔶⛔
**Blocked on Phase 7.**

**Objective:** make endpoint changes invisible to the user.

```
Tunnel starts → Get endpoint → Store endpoint state → Synchronize DNS
  → Monitor endpoint → Detect endpoint change → Update state → Update DNS
  → Verify → Expose stable hostname to user
```

- **Minecraft access:** `Minecraft → Tunnel → Public endpoint → DNS → Stable hostname`
- **Management access:** `MCS Manager → HTTP/HTTPS tunnel → Public endpoint → DNS → Stable hostname`

Don't assume the same tunnel provider serves both.

**Acceptance:** changing a tunnel endpoint updates stored state and DNS and re-verifies, surfacing
a stable hostname; game and management flows each support their own provider configuration.

### 8.3 Phase 9 — Final stabilization 🔶

Systematic close-out before AI: full security review against `docs/SECURITY.md`,
performance/diagnostic passes, production upgrade verification, remaining should-fix/optional
items. No new capability — harden and verify what exists.

**Acceptance:** documented end-to-end verification of the stable baseline Phase 10 builds on.

### 8.4 Phase 10 — AI features 🔶⛔ (final phase, intentionally deferred)
**Blocked on all prior phases.**

**Non-negotiable guardrails, built in from the start:**
1. Agent actions route through the exact same permission layer as normal API calls — no privileged
   bypass path.
2. Explicit user confirmation before any destructive action.
3. Full audit trail of every agent-issued command, attributable to the invoking user.
4. Pipeline: natural-language request → structured plan → execution, with CLI, API, GUI, and Agent
   all calling the same internal services.

**Status:** tracked, not scheduled with a start date. **See Volume 9 §9.5 for how the AI-Layer
brainstorm material relates to this phase — the relationship is one-directional: ideas from Volume
9 can inform this phase's eventual design once it starts, but this phase's guardrails above are
already decided and do not wait on Volume 9 resolving anything.**
