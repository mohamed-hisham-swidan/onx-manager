# MCS Manager — Execution Track: Phases 7–10 (Network, DNS, Stabilization, AI)

**Part V** of the Engineering Blueprint V4. This file covers **Phase 7 (Network access / port
forwarding)**, **Phase 8 (Dynamic endpoint + DNS)**, **Phase 9 (Final stabilization)**, and **Phase 10
(AI features)** as the **committed execution scope** of the roadmap. These four phases are all gated
behind the foundation in Phases 1–6; none of them can be started (beyond `🔶` *planned* status) until
their declared gates close.

**A boundary that must be read before anything below:** this file covers Publish *scope commitments*
— what the roadmap is actually going to build and the hardened defaults it will enforce. Part IV
(`09`, `10`) contains the *non-committed* expanded design ideas for networking and AI. Ideas from
Part IV may inform these phases once they start, but nothing here depends on Part IV resolving
anything, and Phase 7's security posture explicitly assumes **single-instance scope** — see §1.2's
scope boundary, which is the gate that keeps Part IV's speculative multi-node ideas from leaking into
committed scope.

**Last updated:** 2026-08-06
**Supersedes:** `mcs-manager-roadmap-v4.md` Volume 8 (now historical baseline). Status indicators use
the roadmap legend: ✅ done, 🔄 in progress, 🔶 planned, ⛔ blocked, ⚠️ risk/open question. Evidence
discipline is in `04` §0 and Part I.

---

## 1. Phase 7 — Network access / port forwarding 🔶⛔

**Blocked on Phases 1–6.**

### 1.1 Objective

Provide remote access to **your own single running instance** — not multi-tenant hosting, not
multi-node orchestration.

### 1.2 The scope boundary (why it is load-bearing)

Phase 7's entire design and security posture assume **single-instance scope**. This boundary is why
the speculative multi-node / cloud tools in Part IV cannot simply graduate into this phase without a
separate decision process: multi-node is a different threat model, not an extension of this one. Any
work that crosses this boundary must first clear the decision record (Part VIII).

**Design reference:** `docs/network-access-design.md`.

### 1.3 Two user-facing modes

- **A. Tunnel (recommended default).** Abstracts NAT, router config, manual port forwarding, dynamic
  public-IP handling, endpoint changes, DNS sync. The operator exposes the server without becoming
  their own network engineer.
- **B. Manual port forwarding.** Advanced users manage router/firewall/IP/ports themselves.

### 1.4 Architectural boundaries that must hold

1. `TunnelProvider` stays separate from `DnsProvider` — never conflate them.
2. **Dynamic endpoints** — accept endpoints discovered/assigned at runtime, not hardcoded.
3. **Game and management exposure are independent** — separate toggles, separate tunnels, separate
   security postures; never gate them together.
4. **Tunnel ≠ authentication.** Tunnel traffic runs through the exact same auth/authorization stack
   as local traffic. **This is where Phase 4's work becomes load-bearing rather than optional:
   if Phase 4 leaves any gap, Phase 7 exposes that gap to the public internet.**
5. DNS is optional and pluggable.
6. No provider preselection.
7. Provider extensibility uses **official APIs only** — never browser automation or scraping.

### 1.5 Hardened defaults in publish mode

- Rate limiting already per-client and per-path (confirmed in `04` §1.1, `current-state.md` §4.6 —
  corrects an earlier "process-global" claim).
- Shorter access-token lifetimes, mandatory HTTPS, optional-but-strongly-prompted 2FA (**D9, open**).
- RBAC/ABAC enforced everywhere; unauthenticated access is the explicit exception.
- Revisit `GET /metrics` exposure (K10) under this decision, per Phase 4 §2.7.

### 1.6 Exit criteria

Explicit local/publish choice in the install flow; game and management exposure independently
controllable; tunnel traffic provably subject to the same authz as local traffic; manual
port-forwarding mode documented.

### 1.7 Dependency on Phases 1–6

This is a **hard gate**, not a preference. Phase 4 (authorization) and Phase 7 (network exposure) are
jointly the precondition for any Part IV speculative work, because opening the product to the network
on top of an unresolved authorization gap turns a contained internal risk into an externally
exploitable one.

---

## 2. Phase 8 — Dynamic endpoint + DNS architecture 🔶⛔

**Blocked on Phase 7.**

### 2.1 Objective

Make endpoint changes invisible to the user.

### 2.2 The flow

```
Tunnel starts → Get endpoint → Store endpoint state → Synchronize DNS
  → Monitor endpoint → Detect endpoint change → Update state → Update DNS
  → Verify → Expose stable hostname to user
```

- **Minecraft access:** `Minecraft → Tunnel → Public endpoint → DNS → Stable hostname`
- **Management access:** `MCS Manager → HTTP/HTTPS tunnel → Public endpoint → DNS → Stable hostname`

Do **not** assume the same tunnel provider serves both flows.

### 2.3 Acceptance criteria

A tunnel-endpoint change updates stored state and DNS and re-verifies, surfacing a stable hostname;
game and management flows each support their own provider configuration.

### 2.4 Dependency on committed guards

This phase builds directly on Phase 7's tunnel/DNS separation (boundaries 1, 5, 7 in §1.4). It is
architected as the follow-on that makes Phase 7's dynamic endpoints stable to the user.

---

## 3. Phase 9 — Final stabilization 🔶

**Blocked on Phases 1–8.**

### 3.1 Objective

Systematic close-out before AI: a full security review against `docs/SECURITY.md`, performance and
diagnostic passes, production upgrade verification, and resolution of remaining should-fix / optional
items. **No new capability** — harden and verify what exists.

### 3.2 Acceptance criteria

Documented end-to-end verification of the stable baseline Phase 10 builds on.

---

## 4. Phase 10 — AI features 🔶⛔ (final phase, intentionally deferred)

**Blocked on all prior phases.**

### 4.1 Non-negotiable guardrails (built in from the start, already decided)

1. Agent actions route through the **exact same permission layer** as normal API calls — no
   privileged bypass path.
2. **Explicit user confirmation** before any destructive action.
3. **Full audit trail** of every agent-issued command, attributable to the invoking user.
4. **Pipeline:** natural-language request → structured plan → execution, with CLI, API, GUI, and
   Agent all calling the same internal services.

### 4.2 Status

Tracked, **not scheduled with a start date**. Part IV §10.5 (in `10-vision-networking-and-ai-architecture.md`)
holds the expanded AI-Layer design brainstorm. The relationship is one-directional: ideas from Part
IV can inform Phase 10's eventual design once it starts, but this phase's guardrails above are
already decided and do not wait on Part IV resolving anything.

---

*Continue to [`08-dependency-graph-milestones-risk-register.md`](./08-dependency-graph-milestones-risk-register.md)
for the cross-phase dependency graph, milestone definitions, and consolidated risk register — or,
depending on your goal, to the reference files (Part IV `09`/`10`, Parts VI–IX). Execution continues
with whichever phase file is currently active.*