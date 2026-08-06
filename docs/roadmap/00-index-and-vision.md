# MCS Manager — Engineering Blueprint V4

**Status:** Living engineering document — single source of truth for architecture, standards, and
execution
**Supersedes:** `mcs-manager-roadmap-v4.md` (2026-08-06, "Engineering Roadmap V4") and its
companion volumes, which remain the historical baseline this blueprint was built from
**Baseline sources:** the prior V4 roadmap (Volumes 0–8, verified through 2026-08-06),
`docs/STATUS.md`, `docs/current-state.md`, `mcs-manager-roadmap-v3.md`
**Last updated:** 2026-08-06

> **Source-material note, stated up front because the discipline below depends on it.** The prior
> V4 roadmap's table of contents referenced three volumes and a sources appendix — Volume 9
> (Future Direction), Volume 10 (Decision Log D1–D13), Volume 11 (Working Agreements), and
> *Sources* — that were not available when this blueprint was written. Every reference to those
> volumes elsewhere in the old document (D1–D13, the K-numbered issues, "carried from Volume 9")
> was cross-referenced from what *does* survive in Volumes 0–8's own text. Three decision numbers —
> **D7, D8, D10** — are never mentioned anywhere in the surviving text and could not be
> reconstructed at all; they're logged as open gaps in **Part VIII** (the gap disclosure at the top
> of `11-decision-records.md`), not invented. Nothing in
> this blueprint claims to "carry forward" Volume 9 or 11 content that wasn't actually seen — new
> material in Parts II–IV is written fresh, grounded in Volumes 0–8's verified facts, and labeled as
> new. This is the same discipline the old roadmap applied to its own predecessor (v2 → v3); it
> applies here too, including to this note itself.

---

## What changed structurally in this revision

The prior document was organized as a linear phase list (Volumes 1–11) with a fenced-off
speculative appendix. This revision keeps every phase, acceptance criterion, K-item, and open
decision **completely intact** — nothing here overrides a prior number, same as the discipline the
old document inherited from v3 — but reorganizes around what a blueprint needs to answer, in the
order a new reader actually needs it:

```
Part I    — Product Vision                (this file, §2 below)
Part II   — Architecture                  (02-architecture-and-domain-model.md)
Part III  — Engineering Standards         (03-engineering-standards.md)
Part IV   — Subsystem Designs (Vision)    (09-... and 10-... — explicitly NOT committed, see below)
Part V    — Execution Tracks              (04-... through 07-... — the actual phase plan)
Part VI   — Dependency Graph & Milestones (08-dependency-graph-milestones-risk-register.md)
Part VII  — Risk Register                 (08-..., same file, §3)
Part VIII — Decision Records              (11-decision-records.md)
Part IX   — Working Agreements            (12-working-agreements.md)
```

**The one rule that governs the whole reorganization:** moving content into a new Part changes
where it lives, never what it claims. A phase that was 🔶 *Planned* in the old document is still 🔶
*Planned* here. A brainstorm that was fenced off as non-committed is still non-committed here — Part
IV is, if anything, *more* explicit about this than the old Volume 9 pointer was, because it now
carries full designs that are easy to mistake for decisions if the label isn't repeated everywhere.
See §3 below for exactly what that label means and why it's load-bearing.

---

## File map

| File | Part(s) | Contents |
|---|---|---|
| `00-index-and-vision.md` | I | This file: index, product vision, non-goals |
| `01-engineering-principles.md` | I | Engineering philosophy underlying every later decision |
| `02-architecture-and-domain-model.md` | II | Domain/module boundaries, dependency rules, domain objects |
| `03-engineering-standards.md` | III | Coding standards, ADRs, testing philosophy, NFRs, performance targets |
| `04-phase0-1-2-current-reality-and-foundation.md` | V | Phase 0 (current reality), Phase 1 (Plugins/Marketplace), Phase 2 (Product Foundation) |
| `05-phase3-4-reliability-and-security.md` | V | Phase 3 (Reliability), Phase 4 (Security) |
| `06-phase5-6-versioning-and-testing.md` | V | Phase 5 (Versioning), Phase 6 (Testing/CI/Docs) |
| `07-phase7-10-network-and-ai-execution.md` | V | Phase 7–10 (Network, DNS, Stabilization, AI) as committed *execution* scope |
| `08-dependency-graph-milestones-risk-register.md` | VI, VII | Cross-phase dependency graph, milestone definitions, consolidated risk register |
| `09-vision-runtime-storage-observability.md` | IV | **Non-committed.** Runtime Core, storage architecture, observability |
| `10-vision-networking-and-ai-architecture.md` | IV | **Non-committed.** Expanded networking, AI subsystem design, migration strategy |
| `11-decision-records.md` | VIII | D1–D13 in full ADR format, gaps flagged |
| `12-working-agreements.md` | IX | Contribution workflow, commit strategy, AI-collaboration rules |

Read order for a new contributor: this file → `01` → `02` → `03`, then whichever phase file is
currently active (check `04`'s Phase 0 section for "current reality" first). Parts IV, VI–IX are
reference material, consulted as needed rather than read start-to-end.

---

<a name="part-i-vision"></a>
## Part I — Product Vision

### 1.1 What MCS Manager is

MCS Manager is a self-hosted control plane for running and operating Minecraft servers: creating
and configuring server instances, managing their plugins, taking and restoring backups, monitoring
health and performance, and — once the reliability and security foundation is in place — exposing a
server to the internet safely and administering it through natural-language-assisted tooling. It is
built for a single operator running a single instance (or a small number of instances) they control
directly, not a multi-tenant hosting platform.

### 1.2 Long-term vision

A person should be able to stand up a Minecraft server, keep it healthy, back it up without
thinking about it, install plugins without editing config files by hand, and — when they're ready —
share it with friends over the internet without becoming their own network engineer or security
team. Every later capability (AI-assisted operations, richer marketplace integration, deeper
observability) exists to make that operator's job smaller, not to make the product bigger for its
own sake.

The long-run shape of the product is a thin, honest control plane over infrastructure the operator
already trusts (their own machine, their own containers if they choose them, their own network) —
never a black box that hides what it's doing to that infrastructure.

### 1.3 Product philosophy

- **Foundation before capability.** A product with unauthenticated mutating routes and a broken
  WebSocket layer does not get new features; it gets fixed. This isn't a slogan — it's the literal
  ordering of every phase in Part V.
- **Say what's true, not what's aspirational.** A settings page that doesn't persist should look
  disabled, not "successful." A roadmap that hasn't verified a number should say so. This
  document's own evidence discipline (§0.3 of the phase-0 file) is this principle applied to
  itself.
- **The operator stays in control.** Automation — scheduled backups, AI-assisted actions, dynamic
  DNS — augments a human decision, it doesn't replace the human's ability to see and override it.
- **Small, correct surfaces over broad, approximate ones.** Plugins vs. Marketplace is one small
  example: two clear, distinct, well-scoped surfaces beat one page trying to do both jobs
  ambiguously.

### 1.4 Design goals

1. **Legible state.** At any time, the operator (and the codebase itself, via `current-state.md`
   or its successor) can answer "what is actually true right now" without archaeology.
2. **Fail safe, fail loud.** Default-deny authorization, fail-closed WebSocket channels, explicit
   error states instead of silent no-ops.
3. **Composable, not monolithic.** Runtime, storage, networking, and AI are separable concerns with
   explicit boundaries (Part II), so any one of them can change without rewriting the others.
4. **Boring where it counts.** Authentication, authorization, and data integrity use well-understood
   patterns, not novel cleverness. Novelty is reserved for where it earns its keep (AI-assisted
   operations, marketplace UX).

### 1.5 Target audience

- **Primary:** a single technically-comfortable operator (hobbyist, small community admin) running
  Minecraft for themselves and friends, who wants less manual server administration, not more.
- **Secondary:** a slightly more advanced operator who wants to expose their server to the internet
  safely and is willing to make explicit tradeoffs (tunnel vs. manual port-forwarding, DNS provider
  choice) rather than have the product make those choices invisibly.
- **Explicitly not (today):** a hosting company running many tenants' servers on shared
  infrastructure, or an enterprise IT department. Nothing in the current architecture assumes
  multi-tenancy, and no phase in Part V commits to building it.

### 1.6 Explicit non-goals

These are deliberate exclusions, not omissions — restating them here so a future reader doesn't
mistake absence for oversight:

- **Multi-tenant hosting.** Out of scope for the committed roadmap. If it's ever pursued, it's a
  different threat model and a different product, not an extension of Phase 7 (see Part IV,
  `10` §4 boundary reminder).
- **Multi-node orchestration / Kubernetes.** Same reasoning. Tracked only as a labeled, non-committed
  idea (Part IV, `10` §3).
- **General-purpose game server hosting.** The domain model (`02` §3) is Minecraft-specific by
  design; broadening it is a real architectural decision this document doesn't make.
- **A public SaaS offering.** MCS Manager is software the operator runs, not a service the project
  runs on the operator's behalf.
- **AI features before the foundation is secure.** Phase 10 is deliberately last and blocked on
  everything before it (Part V, `07-phase7-10-network-and-ai-execution.md`).

### 1.7 Release philosophy

- **Internal version vs. public release are different numbers.** The codebase is at `4.0.0`
  internally and has never had a public release — conflating "how many internal iterations" with
  "what a user should trust as stable" makes both numbers meaningless. Part V's versioning phase
  (Phase 5) formalizes this split.
- **No phase ships partially "done."** A phase's acceptance criteria (defined per-phase in Part V)
  are binary at exit: met or not met, re-verified against live code, not assumed from a batch log.
  This is why every batch also closes with a stabilization pass (§ per-phase "Batch Stabilization
  Pass" sections in Part V) rather than being marked complete the moment a feature lands.
- **Backward compatibility is a promise made at the first public release, not before.** Pre-release,
  the project can and does make breaking internal changes (e.g., the Phase 1 plugin-route
  restructure) when they improve the eventual public contract. Post-release, the versioning /
  compatibility rules in `03` §7 take over.

---

*Continue to [`01-engineering-principles.md`](./01-engineering-principles.md) for the engineering
philosophy that governs how every phase and subsystem in this blueprint is designed.*
