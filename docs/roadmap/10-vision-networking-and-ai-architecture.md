# MCS Manager — Vision: Networking & AI Architecture

**Part IV** of the Engineering Blueprint V4 — the non-committed dump of **expanded** design material
around networking (tunnels / DNS / exposure) and the AI subsystem, plus migration strategy.

> **READ THE LABEL FIRST, SAME AS `09`.** This file is **NOT COMMITTED**. It is design vision that
> *informs* later work; it is **not** a decision, not architecture, and not scheduled. The committed
> execution scope for Phases 7–10 lives in `07` and its hard guardrails are **already decided**
> (§4.1 there); this file expands on the *shape* those phases could take, strictly as input.
> Where this file and `07` disagree on scope, `07` wins.

**Last updated:** 2026-08-06
**Grounded, not invented:** the networking principles here are carried from the committed design
reference `docs/network-access-design.md` (which Phase 7 builds on). The AI subsystem is grounded in
`07`'s non-negotiable guardrails and the product vision in `00` §1.2. The *expansion* beyond what is
committed is new and labeled.

---

## 0. Grounding

| Kind | Content | Authority |
|---|---|---|
| Fact (committed) | Phase 7 scope, two user modes, 7 architectural boundaries, hardened defaults; Phase 8 endpoint/DNS flow | `07` §1–2; `docs/network-access-design.md` |
| Fact (committed) | Phase 10 guardrails (same permission layer, confirmation, audit, unified pipeline) | `07` §4.1 |
| New (labeled) | Provider-evaluation criteria, multi-deployment topology, AI-layer refinements, migration strategy | This file |

---

## 1. Networking design expansion

### 1.1 The four axes (fact, from `network-access-design.md`)

Tunnel, DNS, exposure, authentication are **four independent axes**, deliberately separated. A common
failure is treating them as one "remote access" feature; the committed design separates them.

### 1.2 Provider selection criteria (new, `[new]`)

Phase 7 requires simultaneous `TunnelProvider` and `DnsProvider` interfaces (see `network-access-design.md` §3.1
— `start()/stop()` and `ensure_record()`/`delete_record()`). The terms the system must judge:

- **Stability & official-API support** only — never browser automation or scraping (committed
  boundary 7, `07` §1.4).
- **Dynamic endpoint reporting** — can the provider hand back an endpoint the system itself didn't
  configure (the `endpoint_url` field)? (committed boundary 2).
- **No preselection** — evaluation + rationale recorded before wiring; switching must not change app
  code (committed boundary 6).

### 1.3 Exposure matrix (fact, from `network-access-design.md`)

| Axis | What's exposed | Auth model |
|------|----------------|------------|
| **Game exposure** | Minecraft server port (`25565`), so friends can join | No transport-level auth — game handles identity internally; opening exposes the game to the public |
| **Management exposure** | The web UI/API, so *you* can administer remotely | Always the full auth stack (login, permissions, audit, rate limits) |

Must be **two independent toggles**, separate tunnels, separate endpoints, separate security
defaults — never gated together, never presented as one decision (committed boundary 3).

### 1.4 Tunnel ≠ Authentication (fact, `network-access-design.md` §2.1)

Terminate the tunnel **in front of** the existing FastAPI middleware stack
(`AuthMiddleware → AuditMiddleware → RateLimitMiddleware`), never around it. A tunnel adds **no
"trusted" status** to a request. Recommended hardening: a shared secret or mTLS between tunnel client
and app so a compromised provider cannot inject locally-sourced-looking traffic.

### 1.5 Multi-domain topology (new, `[new]`)

- **Ephemeral vs named tunnels:** ephemeral assign a random URL that *is* the endpoint (no DNS
  exists); named/custom-domain tunnels need a `DnsProvider`. DNS becomes a separate configurable
  profile, not a thing every deployment has.
- **Game and management diamond shape** (from `07` §2.2): `Minecraft → Tunnel → Public endpoint →
  DNS → Stable hostname` and `Manager → HTTPS tunnel → Public endpoint → DNS → Stable hostname`.
  Do not assume one provider serves both — `[new]` this suggests a config surface where each flow
  picks its own tunnel/DNS provider.

---

## 2. AI subsystem design expansion

### 2.1 Committed guardrails (fact, `07` §4.1 — do not weaken)

1. Agent actions route through the **exact same permission layer** — no privileged bypass.
2. **Explicit user confirmation** before any destructive action.
3. **Full audit trail** attributable to the invoking user.
4. **Pipeline:** NL request → structured plan → execution, with CLI/API/GUI/Agent all calling the
   same services.

### 2.2 Expanded design (new, `[new]`)

- **A single "capability registry" as the action surface.** The agent can only invoke operations
  that are already first-class API commands (same services as the UI). This makes guardrail #1
  structural: if it isn't an API-permitted action, the agent simply has no capability to request.
- **Plan-then-confirm as the interaction contract.** Rather than free-form, the flow is: user gives
  natural language → the system renders a *structured plan* (named operations + parameters + a
  plain-language explanation) → user confirms → execution → audit log. Destructive steps are flagged
  in the plan, satisfying #2 and #4 without ad-hoc checks.
- **Attribution modeled as an `acting_as` identity.** Every agent-issued command is recorded with the
  invoking user's identity in the audit chain, so it is impossible to have an unauthored command.
- **A recovery/test-harness for guardrails.** Because guardrails are non-negotiable, test them with
  the same rigor as review authz — an agent-issued destructive action against a sandbox must be
  confirm-blocked.

### 2.3 Realism about scope

Phase 10 remains **future and unscheduled** (`07` §4.2). None of the above changes that; it is the
*shape* the eventual design may take, gated on `07`'s guardrails.

---

## 3. Migration strategy (new, `[new]`)

The system is a modular monolith (ADR-0001) with clean module boundaries. Options if a future need to
extract or host-drift arises — all are long-term, non-committed:

- **Monolith remains default.** Small-correct-surfaces (Part I §5) doesn't mean distributed. Any
  migration must justify operational cost (single-operator tool).
- **Gradual extraction candidate:** the runtime core and storage are the two most self-contained
  candidates *if* multi-node is ever deliberately pursued — but that crosses the `07` §1.2 scope
  boundary and requires a new decision, not an assumption.
- **No migration is scheduled.** This section is explicitly labeled as idea-space so nobody reads it
  as a roadmap.

---

## 4. Boundary reminder (from `07` §1.2)

Multi-node, Kubernetes, and cloud hosting remain **non-committed ideas** with their own threat model.
Crossing the single-instance scope boundary requires a separate decision process via Part VIII
(`11`). This file does not cross it; it only maps what such a crossing would involve.

---

*Read next: Part VIII [`11-decision-records.md`](./11-decision-records.md) — the D1–D13 open
decision log in ADR format, the place where these vision topics get a committed decision if any.*