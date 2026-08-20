# MCS Manager — Engineering Blueprint V5
**Status:** Living engineering document — single source of truth for architecture, standards, and execution
**Consolidated:** this file merges the 13-part Engineering Blueprint V4 (`00-index-and-vision.md` through `12-working-agreements.md`) into one document, in the reading order the parts already specify. No content was rewritten; only the per-file navigation footers were replaced with a single master table of contents and part dividers below.
---
## Table of Contents
- [Part I — Product Vision](#mcs-manager-engineering-blueprint-v4)
- [Part I (cont.) — Engineering Principles](#mcs-manager-engineering-principles)
- [Part II — Architecture & Domain Model](#mcs-manager-architecture-domain-model)
- [Part III — Engineering Standards](#mcs-manager-engineering-standards)
- [Part V — Execution Track: Phases 0–2](#mcs-manager-execution-track-phases-02-current-reality-structure-foundation)
- [Part V — Execution Track: Phases 3–4](#mcs-manager-execution-track-phases-34-reliability-security)
- [Part V — Execution Track: Phases 5–6](#mcs-manager-execution-track-phases-56-versioning-testingcidocs)
- [Part V — Execution Track: Phases 7–11 and 10](#mcs-manager-execution-track-phases-711-network-dns-stabilization-containerization-ai)
- [Parts VI–VII — Dependency Graph, Milestones & Risk Register](#mcs-manager-dependency-graph-milestones-risk-register)
- [Part IV — Vision: Runtime Core, Storage, Observability](#mcs-manager-vision-runtime-core-storage-observability)
- [Part IV — Vision: Networking & AI Architecture](#mcs-manager-vision-networking-ai-architecture)
- [Part VIII — Decision Records (D1–D13)](#mcs-manager-decision-records-d1d13)
- [Part IX — Working Agreements](#mcs-manager-working-agreements-contribution-workflow)

---

<a name="mcs-manager-engineering-blueprint-v4"></a>
## Part I — Product Vision
*source: `00-index-and-vision.md`*

**Status:** Living engineering document — single source of truth for architecture, standards, and
execution
**Supersedes:** `mcs-manager-roadmap-v4.md` (2026-08-06, "Engineering Roadmap V4") and its
companion volumes, which remain the historical baseline this blueprint was built from
**Baseline sources:** the prior V4 roadmap (Volumes 0–8, verified through 2026-08-06),
`docs/status/history.md`, `docs/current-state.md`, `docs/history/mcs-manager-roadmap-v3.md`
**Last updated:** 2026-08-07

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
| `07-phase7-10-network-and-ai-execution.md` | V | Phase 7–11 (Network, DNS, Stabilization, Containerization) and Phase 10 (AI) as committed *execution* scope |
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
already trusts (their own machine, running each server in its own container as of Phase 11, their
own network) — never a black box that hides what it's doing to that infrastructure.

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

<a name="mcs-manager-engineering-principles"></a>
# MCS Manager — Engineering Principles
*Part I (cont.) — Engineering Principles · source: `01-engineering-principles.md`*

**Part I** of the Engineering Blueprint V4. Defines the engineering philosophy that governs every
architecture decision, phase ordering, and code-level practice in this document. When two principles
conflict, the one listed earlier in this file wins.

**Last updated:** 2026-08-07
**Supersedes:** the philosophy statements scattered across `mcs-manager-roadmap-v3.md` §0 and the
V4 volume drafts (now collected here in one place).

---

## 1. Evidence before assertion

### 1.1 The core rule

No engineering claim — architecture, status, count, or correctness — is accepted on the authority of
a document. Documents are *claims about* the repository; the repository is the ground truth.
Anything in the codebase that contradicts a document wins. This is the same discipline that produced
the `v2 → v3 → V4` rewrites, each triggered by a stale number that had been "verified" once and then
copied forward.

Concretely:

| Statement type | Authority | Verification method |
|---|---|---|
| "Route X requires permission Y" | `contracts/permissions.yaml` + route source | Route-coverage diff against the live route table |
| "Module Z exists" | `find backend/app` | Filesystem listing |
| "Feature F is implemented" | Source + tests | Test run, not batch log |
| "Version is N" | `pyproject.toml`, `package.json`, runtime | `grep` across sources |
| "Test suite is green" | `pytest` / `vitest` run | Fresh run, not a copied number |

### 1.2 What "verified" means in this document

Every claim in this blueprint carries one of three provenance labels:

1. **Carried from V4/STATUS with a date** — taken from a prior verified document or batch narrative.
   *Not re-verified by this revision.* If an acceptance check depends on a carried number, the check
   must re-verify it live before claiming done.
2. **Verified** — checked against source, tests, or the filesystem during this revision.
3. **New** — this document's own analysis, marked as such.

The lesson that made this rule mandatory: **`b1b6dd8` (2026-08-04) made the v3 roadmap stale within
24 hours of its verification date.** A snapshot is never "the truth"; it is the truth *as of a
moment*. Re-verification cadence is itself a deliverable of Phase 6 (§06), not an assumed habit.

### 1.3 Statements that are never allowed

- "All routes are covered" without a route-coverage diff.
- "Fixed" without a test that would fail before the fix.
- "Implemented" for a stub (`NotImplementedError`, hardcoded `{"success": true}` responses).
- Version numbers asserted without a grep of the sources that own them.

---

## 2. Source of truth, exactly once

Every fact that the product depends on lives in exactly one place and is *derived* everywhere else,
never *duplicated*.

### 2.1 Facts and their owners

| Fact | Owner | Consumers that must derive, not copy |
|---|---|---|
| Application version | `backend/pyproject.toml` | `AppSettings.version`, OpenAPI, frontend display, `.ai/*.json` |
| Permission set | `contracts/permissions.yaml` | REST route gating, WebSocket channel auth, CI route-coverage check, frontend permission-aware UI |
| Plugin existence | Server `plugins/` directory | `plugins` DB table (a cache) |
| Server existence | Server data directory on disk | `servers` DB table (a cache) |
| Scheduled jobs | `cron_jobs` DB table | APScheduler runtime |
| Event schemas | `contracts/events.yaml` + `events/` catalog | All publishers and subscribers |
| Migration state | `alembic_version` table | Application startup, release procedure |

### 2.2 Why duplication fails here

Every duplication in this project's history has eventually drifted:

- The version string was copied into three backend files and one frontend package before Phase 5
  existed to enforce single-source.
- The permission model had **two** parallel lists (REST `CHANNEL_PATTERNS` plural strings vs. JWT
  singular claims), and the divergence caused the WebSocket layer to be dead-on-arrival (K1).
- `STATUS.md` carried counts that went stale repeatedly until `current-state.md` was created — and
  the two-document split is itself under review in Phase 6 (see `06` §2.2).

When you find yourself about to write the same value in a second place, stop. Either derive it at
build/runtime time, or schedule the derivation work rather than creating the duplicate.

### 2.3 Cache semantics

Where a DB table is a cache over a stronger source (filesystem for plugins/servers, package metadata
for version), the reconciliation direction is explicit and one-way:

```
source of truth ──reconcile──► cache
```

Reconciliation is idempotent, triggered at a defined point (list-time for plugins, startup + manual
refresh for servers), and never writes back the other direction. The cache may be stale by the width
of its reconciliation window; the product UI must not pretend otherwise.

---

## 3. Fail closed, fail loud

### 3.1 Default-deny authorization

Unauthenticated and unauthorized access is the explicit exception, not the baseline. Every route,
channel, and eventual tunnel must be denied unless a deliberate decision (recorded in
`contracts/permissions.yaml` or an ADR) allows it. The current allow-list is tiny and deliberate:

- `POST /auth/login`, `POST /auth/refresh` — needed to obtain a credential.
- `POST /users` — open registration, a **known risk** scheduled for Phase 4 investigation (see `05`
  §2.4).
- `GET /metrics` — public Prometheus scrape endpoint, deliberately deferred to Phase 7 (see `05`
  §2.7).

### 3.2 Fail-closed infrastructure

When the system cannot determine whether something is permitted or safe, it refuses:

- WebSocket channel authorization denies on any ambiguity (it currently denies on *everything* — a
  real bug, K1, but a *safe* bug).
- Orphan cleanup skips a process when ownership cannot be verified (§02, Runtime Reconciliation).
- A backup restore fails rather than partially applying.
- A plugin with an unverifiable checksum is not installed.

### 3.3 Honest failure surfaces

A control that does nothing must not report success. This is the rule behind the Phase 2 "settings
UX honesty" workstream: the settings page today shows a `PATCH /settings` that returns
`{"success": true, "message": "Settings updated (stub)"}` while persisting nothing (K3). A stub is a
broken promise dressed up as a success. The UI should either persist or show itself disabled.
The same principle governs this document: a phase marked done must meet its criteria, not just be
plausibly near done.

---

## 4. Foundation before capability

### 4.1 The ordering rule

Features are sequenced by risk, not by excitement. A product with broken WebSocket delivery, a
non-persisting settings page, and 9 unauthenticated mutating routes does not get new features; it
gets fixed. This is the literal ordering of every phase in Part V:

```
Phase 1  Structure (Plugins vs Marketplace)   — fixes a product-model ambiguity
Phase 2  Product foundation (UI honesty)      — fixes a trust gap in the UI
Phase 3  Reliability (WS, settings, tests)    — fixes functional breakage
Phase 4  Security (authorization everywhere)  — fixes the highest real-world risk
Phase 5  Versioning & state consistency       — makes versions non-driftable
Phase 6  Testing / CI / docs reliability      — makes the above non-regressable
Phase 7  Network access                       — only safe once 1–6 are closed
Phase 8  Dynamic endpoint + DNS               — builds on 7
Phase 9  Final stabilization                  — close-out before the runtime changes
Phase 11 Containerization migration           — final runtime change, once 1–9 are closed
Phase 10 AI                                   — deliberately last, after the runtime is final
```

### 4.2 Why network access is gated on everything

Phase 7 exposes the product to the public internet. Every authorization gap that exists before Phase
7 is a *contained* internal risk afterward — a gap that was a latent bug becomes an exploitable
vulnerability. The gate is therefore hard, not preferential: Phase 4 must be complete before Phase 7
starts. Phase 11 (containerization) is gated on Phases 1–9 for the same reasoning applied to runtime
rather than network exposure: reliability (Phase 3), security (Phase 4), and network hardening
(Phases 7–9) are all verified against the process-based runtime; changing the runtime before those
close would mean re-verifying each of them twice. AI (Phase 10) is last of all, after Phase 11, for
the same reason again: it adds a new privileged execution path, and the guardrails it requires
(permission-gated agent actions, audit trails) presuppose both a permission/audit layer that Phases 4
and 6 actually enforce, and a single, final runtime model (Phase 11) rather than a mix of
containerized and process-based servers depending on when each was created.

### 4.3 No phase ships "partially done"

A phase's exit criteria are binary at close: met or not met, re-verified against live code. Every
batch within a phase ends with a stabilization pass (per-phase in Part V) so that a phase never
accumulates unexamined debt while it approaches its exit criteria.

---

## 5. Small, correct surfaces over broad, approximate ones

### 5.1 The rule

A system should offer several small, precise capabilities rather than one large ambiguous one. The
canonical example is the Plugins vs. Marketplace separation:

- **Plugins** = "what plugins does this selected server have installed?" — server-scoped, lifecycle.
- **Marketplace** = "what plugins can I discover and install?" — global catalog, discovery.

Conflating them produced a page that couldn't browse the catalog without first picking a server, and
a product model where "install" was indistinguishable from "manage". Splitting them produced two
clear surfaces, each with an obvious mental model.

### 5.2 When not to apply

Smallness is not fragmentation. The system is deliberately a **modular monolith** (ADR-0001), not a
microservice constellation, because the project is a single-operator tool and the operational cost of
distributed systems is not justified. "Small, correct surfaces" applies to *product surfaces and
domain boundaries*, not to deployment topology.

---

## 6. Composable, not monolithic — bounded contexts

### 6.1 Nine DDD modules

The backend is organized into nine bounded contexts:

| Module | Responsibility |
|---|---|
| `server` | Server lifecycle, config, deployment, runtime supervision |
| `backup` | Backup/restore, verification |
| `plugin` | Plugin registry, lifecycle, subprocess execution, marketplace catalog |
| `auth` | Users, roles, JWT, API keys, RBAC/ABAC, audit |
| `health` | Health evaluation, crash diagnostics, integrity validation |
| `monitoring` | Metrics collection, alert rules |
| `event_store` | Append-only event log with cryptographic chain |
| `storage` | File storage backends (local/S3) |
| `shared` | Cross-context value objects |

### 6.2 The boundary rule

Modules communicate only through:

1. The Command/Query/Event buses (`core/`), or
2. Shared value objects (`modules/shared/`).

No module imports another module's internals. Domain never imports infrastructure. Application never
imports the API layer. These rules are enforced by linting and review (Phase 6 hardens the
enforcement), not by convention alone.

### 6.3 Why it matters

Each module can change, be tested, or (in principle) be extracted independently. The health module
was added post-Batch-10 as a complete domain/application/infrastructure stack without touching other
modules' internals — proof the boundary holds in practice.

---

## 7. Boring where it counts

### 7.1 The rule

Security, identity, and data-integrity mechanisms use well-understood, standard patterns — never
novel cleverness. Novelty is reserved for where it earns its keep (marketplace UX, AI-assisted
operations).

The concrete commitments:

- **Passwords:** Argon2id, the memory-hard KDF standard.
- **Tokens:** RS256 asymmetric JWTs (access) + opaque single-use DB-backed refresh tokens.
- **Integrity:** SHA-256 hash chains over the audit log and event store.
- **Encryption at rest (backups):** AES-256-GCM.
- **Concurrency:** `asyncio.Lock` for shared async state; no bespoke synchronization.

### 7.2 Why

A custom crypto scheme, a hand-rolled token format, or an exotic concurrency primitive is a security
review liability with no compensating benefit for a single-operator tool. When a standard pattern
has a known sharp edge (e.g., auto-generated ephemeral JWT keys), the standard pattern is kept and
the sharp edge is *documented* (K11) rather than replaced with something untested.

---

## 8. The operator stays in control

Automation augments a human decision; it never replaces the human's ability to see and override it.

- Scheduled backups are visible and cancellable.
- Auto-restart after crash escalation stops at a configurable limit (3 crashes / 300s) instead of
  looping forever.
- Publish-mode (Phase 7) requires an explicit choice — there is no silent default to exposure.
- AI actions (Phase 10) require explicit confirmation before destructive operations and route
  through the same permission layer as human API calls.

The product is a *thin, honest control plane* over infrastructure the operator already trusts — never
a black box that hides what it is doing to that infrastructure.

---

## 9. Preservation and canon

### 9.1 History is append-only

Past events (audit rows, event-store rows, decision records, documented decisions) are never deleted
or silently changed. This blueprint inherits the discipline from the audit/event-store design:

- An ADR once accepted is never deleted; it may be superseded by a later ADR.
- A roadmap phase marked done stays marked done, with its verification note.
- A decision deferred (D1–D13) stays tracked until resolved, even if months pass.

### 9.2 Historical documents

`mcs-manager-roadmap-v1.md`, `v2.md` (both superseded), `roadmap.md` (v0), and the V4 linear volume
drafts are preserved for history. They are not authoritative. When a reader needs the current plan,
this blueprint is the document. When they need the past, the historical files are there — labeled as
history, not silently deleted.

---

## 10. Practical consequences

The principles above resolve into a short checklist used during every review and every stabilization
pass:

1. Is this claim verified against source/tests, or just asserted?
2. Is this value derived from its single source of truth, or copied?
3. Does this surface deny by default, and fail loudly if it can't decide?
4. Am I building capability before the foundation under it is sound?
5. Is this a small, precise surface or an overloaded one?
6. Does this cross a module boundary directly instead of through a bus or shared value object?
7. Is this implementing a standard pattern, or inventing one?
8. Does this remove the operator's ability to see or override the behavior?
9. Does this rewrite history instead of appending to it?


---

<a name="mcs-manager-architecture-domain-model"></a>
# MCS Manager — Architecture & Domain Model
*Part II — Architecture & Domain Model · source: `02-architecture-and-domain-model.md`*

**Part II** of the Engineering Blueprint V4. The complete engineering architecture: system context,
module structure, the CQRS buses, runtime model, storage model, and per-subsystem design. A senior
engineer should be able to make correct changes after reading this document alone.

**Last updated:** 2026-08-06
**Supersedes:** `docs/architecture/ARCHITECTURE.md` and `docs/architecture/DATABASE.md` as the primary architecture reference.
Those files remain in `docs/` for cross-reference; this document is the canonical description.

---

## 1. System Context

### 1.1 Logical view

```
┌─────────────┐        ┌───────────────────────────────────────────────────────────┐
│  Browser     │◄─HTTP─┤                        FastAPI (single process)            │
│  (React SPA) │        │                                                           │
└─────────────┘        │  API layer ──► Application layer ──► Domain layer           │
        │              │       │                │                │                   │
        │        ┌─────┼───────┘                │                ▼                   │
        │        │  WS  │            Command/Query buses     Event Bus ──► Event Store│
┌─────────────┐  │  /ws │                │                        │         (hash chain)
│  CLI / curl  │◄─┤      │                ▼                        ▼                   │
└─────────────┘  │      │        Infrastructure adapters    (audit, DLQ, WS push)     │
        │        │      │                │                                            │
        │        │      │                ▼                                            │
┌─────────────┐  │      │   ┌──────────┐  ┌───────────┐  ┌───────────────────────┐   │
│ Plugin SDK   │◄─┼──────┼──►│ Providers│  │ Repos     │  │ Storage backends      │   │
│ subprocesses │  │      │   │ (tmux/   │  │ (SQLAlch) │  │ (local, S3)           │   │
└─────────────┘  │      │   │  docker/  │  │           │  └───────────────────────┘   │
                 │      │   │  ssh)     │  └─────┬─────┘                              │
                 │      │   └──────────┘        │                                     │
                 │      │                       ▼                                     │
                 │      │              ┌─────────────────┐      ┌────────────────┐    │
                 │      │              │  PostgreSQL 16 / │      │  Minecraft     │    │
                 │      │              │  SQLite 3        │      │  server data   │    │
                 │      │              └─────────────────┘      └────────────────┘    │
                 └──────┴────────────────────────────────────────────────────────────┘
```

### 1.2 Deployment topology

- **Single process, modular monolith** (ADR-0001). One uvicorn worker serves REST, WebSocket, and
  the scheduler. There is no separate worker process in the current production shape.
- **Frontend** is a static React build served by nginx, which proxies `/api`, `/ws`, `/health`,
  `/docs`, `/openapi.json` to the backend (see `docs/DEPLOYMENT.md`).
- **Database** is SQLite in the current deployment (`backend/mcs.db` dev, `backend/data/servers/mcs.db`
  production); PostgreSQL 16 is the supported upgrade path. Redis is *not* used by the running
  system despite appearing in early stack documentation (see §5.4).
- **Minecraft servers** run on the same host (local providers) or a reachable host (SSH provider),
  managed through tmux sessions by default.

### 1.3 Clients

| Client | Transport | Auth | Purpose |
|---|---|---|---|
| Browser SPA | HTTP + WebSocket | Bearer JWT + WS token query param | Primary admin UI |
| CLI / curl | HTTP | Bearer JWT or `mcs_` API key | Scripting, debugging |
| Plugin subprocess | JSON-RPC over stdin/stdout | host-issued (socket/process identity) | Plugin ↔ host communication |
| External scrapers | HTTP | none (`GET /metrics` public — K10) | Prometheus scraping |

---

## 2. Module Structure & Layering

### 2.1 Directory layout

```
backend/app/
├── main.py                 # FastAPI app factory, lifespan (all wiring), middleware, health/metrics
├── registration.py         # Command/Query/Event handler registration, infrastructure init
├── api/                    # Interface layer
│   ├── deps.py             # FastAPI dependency injection (buses, storage, auth deps)
│   ├── errors.py           # Global exception handlers → error envelope
│   └── v1/
│       ├── middleware/     # RequestID, Auth, Audit, RateLimit (in that order)
│       ├── routers/        # 11 routers: auth, backups, health, marketplace, monitoring, plugins,
│       │                   #   schedules, servers, settings, software, users
│       └── schemas/        # Pydantic request/response schemas
├── core/                   # Foundation layer
│   ├── persistence/        # DatabaseEngine, BaseRepository, UnitOfWork, DeclarativeBase
│   ├── command_bus.py      # CQRS command bus
│   ├── query_bus.py        # CQRS query bus
│   ├── event_bus.py        # Async event bus with retry + dead-letter
│   ├── saga.py             # Saga orchestrator
│   ├── circuit_breaker.py  # Circuit breaker pattern
│   ├── idempotency.py      # Idempotency keys
│   ├── feature_flags.py    # Feature flag system
│   ├── config.py           # AppSettings + ConfigFactory
│   ├── exceptions.py       # MCSError hierarchy
│   ├── security.py         # Argon2id, API key hashing
│   ├── http_client.py      # Shared aiohttp client
│   └── logging.py          # Structured logging
├── modules/                # 9 DDD bounded contexts (see §3)
├── services/               # Cross-module saga orchestrations (server lifecycle, backup)
├── tasks/                  # TaskQueue, Scheduler, task definitions
└── websocket/              # Connection manager, auth, authorization, dispatcher, handlers
```

### 2.2 Dependency direction (hexagonal / ports-adapters)

```
api/ ──► application/ ──► domain/
  │                         │
  └────────────────► infrastructure/
                        │
core/ ───────────────────┘
```

- **Domain** never imports infrastructure, application, or API.
- **Application** never imports API.
- **Infrastructure** never imports API.
- Cross-module communication is only via buses (`core/`) or shared value objects (`modules/shared/`).
- The `core/` layer is shared infrastructure consumed by all layers.

This was verified clean in the Batch 4 architecture audit (2026-07-27) and is enforced by ruff
import rules and review. Phase 6 (§06) hardens enforcement with CI.

### 2.3 Validation: two-layer defense (ADR-0009)

1. **Pydantic schema layer** (HTTP boundary): `@field_validator` on request schemas rejects invalid
   input at HTTP 422 with a structured `detail` list.
2. **Handler safety-net** (domain boundary): try/except around domain value-object constructors
   catches `ValueError` and re-raises `InvalidValueError` (MCSError) for a consistent
   `VALIDATION_ERROR` code.

Applied today to `minecraft_version`, `email`, port ranges, memory minimums, and JVM args. Any new
domain value object that validates input must have a matching Pydantic validator — this is a standing
rule (ADR-0009), not a one-time fix.

---

## 3. The Nine Bounded Contexts

Each module is a complete hexagonal slice: `domain/` (aggregates, value objects, events, repository
interfaces), `application/` (command/query handlers), `infrastructure/` (SQLAlchemy models,
repository implementations, adapters). The per-module detail below covers the parts a changing
engineer needs.

### 3.1 `server` — Server Lifecycle & Deployment

**Purpose.** Owns the server aggregate — the central entity of the product — and its runtime lifecycle:
create, configure, import, start, stop, restart, delete, console, diagnostics, and filesystem
reconciliation.

**Domain objects.** `Server` aggregate root; value objects `ServerId`, `MinecraftVersion`,
`ServerType`, memory bounds, port, `ServerStatus` state machine
(`created → installing → stopped → running`, plus crash states). Domain events: `server.created`,
`server.starting`, `server.running`, `server.stopping`, `server.stopped`, `server.crashed`,
`server.config_changed`.

**State machine.** All transitions go through aggregate methods (`mark_running()`, `mark_stopped()`,
`mark_crashed()`, `mark_missing()`), never through private field writes. `Server.crash(exit_code,
last_log_lines)` records crash data and emits `server.crashed`.

**Key application services.**

- `FilesystemReconciliationService` — 6-stage pipeline reconciling DB ↔ disk (see §6.2).
- `RuntimeSupervisor` — per-server asyncio watchdog (see §6.3).
- `RuntimeOwnershipManager` / `reconcile_orphans` — ownership-verified OS resource cleanup (see §6.4).
- `migrate_old_import_arch` — one-time migration of legacy import-layout servers.

**Lifecycle.** Servers are created either explicitly (`CreateServerCommand`) or auto-imported by
filesystem reconciliation. Deletion is DB-row-delete plus directory removal after commit (verified in
Batch 2.5 fix 4). Runtime reconciliation at startup repairs DB/OS mismatches.

**Dependencies.** `core/` buses + persistence; `shared/` value objects; `storage/` for nothing
directly (backups are a separate module); providers in `server/infrastructure/providers/`.

**Extension points.** New deployment providers (see §6.1). New scan categories in reconciliation.

**Failure modes / recovery.** Server start failures are diagnosed by `RuntimeSupervisor` and surfaced
as `server.crashed` with diagnostics. Crash recovery is handled by the `health` module (§3.5). The
startup guard (`StartServerHandler`) pre-flights Java, disk, memory, and provider availability before
launch.

**Security.** Start/stop/command/refresh/import/delete are permission-gated (`server:write`,
`server:start`, `server:stop`, `server:delete`) — enforced since Batch 9. Commands are validated
against a whitelist to avoid injecting arbitrary console commands with elevated context.

**Testing.** 40 command tests, 15 query tests, 5 console tests, 30 aggregate tests, 25 runtime
reconciliation tests, 38 runtime ownership tests, 22 provider tests.

### 3.2 `backup` — Backup & Restore

**Purpose.** Create, restore, verify, and delete backups of Minecraft server data. Multiple granular
backup types (full, world, plugins, config) with matching restore.

**Domain objects.** `BackupJob` and `BackupPolicy` aggregates. `backup.job` columns: `backup_type`,
`status` (`pending/running/completed/failed`), `size_bytes`, `checksum` (SHA-256), `storage_path`.
Events: `backup.started`, `backup.completed` (v1 + v2 schemas), `backup.failed`.

**Pipeline (CreateBackupHandler → BackupSaga).**
1. **Save-world** (`_save_world`): if the server is running, send `save-all` and poll provider
   console output (≤30s) for `saved the (game|world)` before proceeding; timeout marks the job
   `FAILED`. **K14: this regex is unverified against a real Purpur server** — see Phase 3.
2. **Archive**: tar.gz of the world/config/plugin directories.
3. **Encrypt**: AES-256-GCM (`cryptography.hazmat`), producing `{backup_id}.tar.gz.enc`.
4. **Upload** to the configured `StorageBackend` with size + checksum.
5. **Verify**: re-read the artifact and compare checksums.
6. **Persist** `BackupJob` with `storage_path` tracked end-to-end.

**Restore pipeline.** Decrypt → extract to a **same-filesystem staging directory** (ADR-0012 —
staging must share a filesystem with the target or `os.replace` fails with EXDEV) → atomically swap
folders/files onto the live server directory, deferred-until-restart for the running JVM.

**Delete order.** Delete the storage artifact **before** deleting the DB row; on failure keep the
row and return `success=False`. This prevents orphaned encrypted files (Batch 8 fix 1). Also note the
`artifact_path()` fix: returns `f"{backup_id}.tar.gz.enc"` without a duplicated `backups/` prefix.

**Saga.** `BackupSaga` orchestrates the multi-step pipeline with compensation (a failed step cleans
up partial artifacts). Saga state lives in `saga_instances`/`saga_steps` tables.

**Dependencies.** `storage/` for backends; `server/` for console and directory paths; `core/` buses.

**Failure modes.** Save-world timeout → job FAILED. Checksum mismatch at verify → failed, artifact
removed. Staging on wrong filesystem → EXDEV (fixed by ADR-0012). **Known limitation:** saga step
failures store only `"Failed at step '<step_name>'"` in `job.error_message`; the underlying cause is
visible only in server logs — see Phase 3 (§05) and the `backup_saga_error_detail` backlog item.

**Security.** Backup artifacts are encrypted at rest. Restore/delete/create are permission-gated
(`backup:restore`, `backup:delete`, `backup:create`); verify is `backup:read`.

**Testing.** 9 command tests, 6 saga tests, 21 storage tests. Regression coverage exists for
delete-order and artifact-path issues.

### 3.3 `plugin` — Plugin Registry, Lifecycle, Marketplace

**Purpose.** Two distinct responsibilities (a product decision — see Phase 1):

1. **Server-scoped plugin management** — installed `.jar` files on a selected server, their state,
   enable/disable/uninstall.
2. **Global marketplace** — discover and install plugins from a catalog provider (Modrinth today).

**Filesystem is the source of truth.** `ReconcilePluginsHandler` runs on every
`GET /servers/{id}/plugins`: `.jar` files on disk with no DB row → new `source="detected"` rows; DB
rows whose file is gone → pruned (unless pending deletion). The `plugins` table is a metadata cache.

**Plugin row columns.** `filename` (reconciliation key), `source` (`detected` | `modrinth`),
`external_project_id`/`external_version_id`/`external_url`/`checksum` (Modrinth provenance),
`pending_deletion` (deferred deletion — file removed on next server start/restart so the JVM never
loses a loaded `.jar`).

**Deferred deletion.** `UninstallPluginHandler` sets `pending_deletion=True`; the file is removed at
the next server start/restart. This prevents removing a `.jar` out from under a running JVM.

**Catalog provider abstraction (K16A).** `PluginCatalogProvider` ABC:
`search`, `get_project`, `get_project_versions`, `get_version`, `download(url, expected_sha1,
expected_sha512)`. `ModrinthProvider` is the only registered provider. Selection is
**configuration-driven** via `MCS_PLUGIN_PROVIDERS` (default `modrinth`), validated fail-fast at
startup by `validate_plugin_providers`. **K16A accepts exactly one active provider**; list syntax is
preserved for future multi-provider work, but multi-provider config currently fails at startup.

**Version selection.** `select_best_version()` ranks: exact game version + exact loader → exact game
version on nearest compatible parent loader (`purpur → paper → spigot → bukkit`, with a
`loader_fallback` notice) → closest available game version (with a `version_mismatch` warning, never
hard-blocking). Always returns the full version list newest-first for manual override.

**Install flow.** `InstallModrinthPluginHandler`: resolve server deployment root (rejects
`vanilla`/`fabric`/`forge` as manual-only) → resolve version (explicit or best-version) → download
with SHA-1/SHA-512 verification → atomic write into `<server_dir>/plugins/` (existing filename →
`FILE_CONFLICT`) → create `modrinth` row → commit.

**Plugin subprocess execution (ADR-0003).** Plugins the product itself runs (distinct from
Minecraft plugins) run as isolated subprocesses communicating via JSON-RPC over stdin/stdout. This is
the plugin *system* (Batch 07), separate from the marketplace concept. Filesystem sandbox restricts
writes to the plugin directory; network sandbox allows only hosts from the manifest.
`ContainerPluginRunner` is a stub (`NotImplementedError`) — future Docker-in-Docker isolation.
**Note:** this subsystem is currently dormant — no first-party plugins ship — but it is complete and
tested (60 tests across 6 files).

**Permissions.** Delete + all three marketplace routes require `plugin:manage`; **enable/disable are
auth-only (K4, no `require_permission`)** — a Phase 4 gap. `GET /plugins` list triggers
reconciliation. The global marketplace search (`GET /api/v1/marketplace/search`, new router
`marketplace.py`) requires `plugin:manage`.

**Testing.** 25 command tests, 12 manifest tests, 12 runner tests, 12 sandbox tests, 14 provider
tests, plus dependency-resolver and lifecycle tests.

### 3.4 `auth` — Users, Roles, JWT, Authorization

**Purpose.** Identity (login/logout/refresh), credentials (API keys), authorization (RBAC+ABAC),
and audit.

**Domain objects.** `User` aggregate (email, Argon2id password hash, `is_active`, `last_login_at`),
`Role` aggregate (permissions text field), `RefreshTokenModel`, `ApiKeyModel`.

**Authentication (ADR-0005).**
- **JWT RS256**, 2048-bit RSA, 15-min access tokens. Keypair auto-generated in-process by default;
  production must load persistent PEM via `set_private_key()` / `MCS_JWT_PRIVATE_KEY` /
  `MCS_JWT_PRIVATE_KEY_PATH`. **K11: ephemeral auto-generated keys are lost on restart** unless set.
- **Refresh tokens**: opaque 48-byte random, stored as SHA-256 hash, single-use rotation, 7-day TTL,
  individually revocable (logout revokes by hash lookup).
- **API keys**: `mcs_` prefix, SHA-256 hash via `hash_api_key()` (**unsalted** — documented), shown
  once at creation.
- **Argon2id** password hashing.

**Authorization (RBAC + ABAC hybrid).**
- 17 `resource:action` permission strings; three roles: `viewer`, `operator`, `admin`.
- `PermissionEvaluator` (RBAC) + `evaluate_abac()` (ownership/scope rules).
- **Known gap:** the evaluator builds token claims at login/refresh but is **not** invoked to gate
  requests on most routes. Only 32 routes are gated by `require_permission` (verified 2026-08-11;
  `contracts/permissions.yaml` documents 67 distinct API route keys, 42 enforced). 9 mutating routes + 23 sensitive GET
  routes remain auth-only. This is the central Phase 4 work (§05).

**Audit log.** `audit_log` table, append-only, SHA-256 hash chain over JSON-serialized content
(`_fmt_ts()` normalizes timestamps). `verify_chain()` exists but **nothing schedules it** — automatic
periodic verification is Phase 3/6 scope. No audit query endpoint exists yet.

**Permission storage debt (K12).** Roles/API keys store permissions as comma-separated `Text`
(non-normalized); `SQLUserRepository.save()` performs an async lazy-load on `model.roles`
(`MissingGreenlet` risk) at `repository.py:55` — currently unreachable (no code path assigns roles),
but sits in the exact code Phase 4 expands.

**WebSocket auth.** `verify_ws_token()` validates the JWT before `accept()`. Channel authorization
exists but always denies (K1, §6.6).

**Testing.** 37 auth command tests, 15 login-flow tests, 8 audit tests, plus jwt/password/api-key/
permissions tests.

### 3.5 `health` — Health Evaluation, Crash Diagnostics, Integrity

**Purpose.** Evaluate a server's health from signals (runtime, integrity, crashes), diagnose crashes,
and orchestrate recovery. This is the newest module (post-Batch-10), built from
`architecture/health-engine-design.md`.

**Pipeline.**

1. **Evidence collection**: `EvidenceCollector` gathers log tail, crash-report parsing, system
   snapshot.
2. **Crash analysis**: `PatternCrashAnalyzer` maps 18 failure patterns to `FailureCode`s.
3. **Health calculation**: `SignalHealthCalculator` — sliding window, signal weighting, transition
   constraints, trend detection.
4. **Recovery**: `RecoveryOrchestrator` — auto-restart with escalation after 3 crashes / 300s.
5. **Event flow**: `ServerCrashedEvent` → collect → classify → recover. `HealthSignalHandler`
   subscribes to `RuntimeHealthSignal`/`IntegrityCheckFailed`/`CrashClassified` and re-computes
   health. `GenerateHealthReport` query produces uptime %, crash frequency, worst status.

**Health tables.** `health_status`, `health_timeline`, `health_evidence`, `health_diagnostics`
(migration `876be46160d4`).

**Dependencies.** `server/` (crash events, diagnostics types), `monitoring/` (runtime signals),
`core/` buses.

**Extension points.** New `FailureCode`s, new crash patterns, new health signals, new recovery
strategies.

**Failure modes.** Evidence collection can fail (unreadable logs) — the pipeline degrades to the
best available evidence. Recovery orchestrator must not loop (escalation cap).

**Testing.** 15 aggregate, 20 event, 30 value-object, 6 command, 6 query, 12 repository, 22
calculator, 11 evidence, 18 crash-analyzer, 13 recovery-orchestrator tests.

### 3.6 `monitoring` — Metrics & Alerts

**Purpose.** Collect time-series performance data (TPS, players, RAM, CPU) per server; define and
evaluate threshold alert rules.

**Data sources (in priority order, each with honest fallback).**

| Source | Provides | Fallback when unavailable |
|---|---|---|
| `psutil.Process(pid)` | RAM (RSS→MB), CPU% | `0.0` values |
| RCON (`/tps`, `/list`) | TPS, player count | `tps=20.0, players=0` |
| Hardcoded defaults | — | Baseline |

**Important honesty note:** `metric_points` rows can contain functionally default values even when
the pipeline runs correctly — the data source (PID reachable, RCON enabled + password set) may simply
not be reachable. A zero isn't necessarily a broken collector.

**Persistent RCON.** `PersistentRCONClient` reuses a single long-lived TCP session per server instead
of reconnecting every tick (each connect forces the Minecraft server to spawn/destroy a thread).
`send_command()` serializes under an `asyncio.Lock`, retries with backoff, reconnects between
retries; the re-acquire deadlock bug (double-lock on close) was fixed — use `_close_unlocked()` when
the lock is already held. The pool lives only as long as the worker process (matches single-worker
deployment).

**Metrics registry.** Prometheus gauges (TPS, players, RAM, CPU) updated by `MetricsCollector`;
exposed at `GET /metrics` (public — K10, deferred decision).

**Task wiring.** `MetricsCollector` is instantiated in `main.py` lifespan and passed to
`init_collector()`. The scheduler registers the `metrics_collect_every_60s` cron job. **If this
wiring is removed, metric_points silently stop growing** — there is no second-chance init path
(ADR-0006 post-hoc finding).

**Alert rules.** `alert_rules` table: per-server, per-metric threshold rules (`>`, `<`, `>=`, `<=`),
severity, cooldown. **Known limitation:** the alerts/schedules REST routes are stubs (K13).

**Retention (ADR-0006 decision 4).** Four-tier pipeline is *designed* (raw→1m→1h→1d with retention
1h/30d/1y/forever) but **rollups are not implemented** — raw `metric_points` only.

**Testing.** 20 monitoring tests, 15 collector tests, 20 task tests.

### 3.7 `event_store` — Append-Only Event Log

**Purpose.** Persist every domain event as an immutable, tamper-evident log; provide query,
pagination, and dead-letter handling.

**Design.** `event_store` table: `event_id`, `event_type`, `correlation_id`, `data_json`,
`schema_version`, `previous_hash`, `hash`. Hash = `SHA-256(previous_hash + event_id + event_type +
data_json + created_at_iso)`. No UPDATE/DELETE at the application layer. Retention 1 year (partitioned
by month). Integrity verified by replaying the chain (`verify_chain()`).

**Write path.** Events are collected during a transaction by `UnitOfWork` and flushed to the event
store before the domain transaction commits; they are then published to the `EventBus`. Event-store
persistence is therefore *atomic with the transaction* — this is the load-bearing distinction from
the (currently uninstantiated) WS dispatcher (K2).

**Dead letter queue.** `dead_letter_events` — events that exhausted the EventBus's 3 retries. Admin
replays via DLQ commands (re-publish to the bus); never auto-retried.

**Security.** The chain detects tampering but does not prevent it. `GET /metrics`-style public
exposure of the event store is not implemented and must not be added without auth.

**Testing.** 15 event-store tests, 8 dead-letter tests.

### 3.8 `storage` — File Storage Backends

**Purpose.** Abstract object/file storage for backups (and future artifacts) behind one interface.

**Design.** `StorageBackend` ABC with `stream_read`/`stream_write` defaults; `LocalStorage` and
`S3Storage` adapters. Encryption helpers (`BackupEncryption`, AES-256-GCM) live here or in backup
infra (see `docs/architecture/DATABASE.md`); selected via `MCS_STORAGE_BACKEND` (`local` default, `s3` optional).

**Failure modes.** S3 unavailability → backup upload fails with a clear error; the saga
compensates. **Important:** this module is unrelated to the old `app/storage/` directory (renamed to
`app/core/persistence/` by ADR-0007) — the naming collision is resolved and documented.

**Testing.** 21 storage tests.

### 3.9 `shared` — Cross-Context Value Objects

**Purpose.** Types that more than one module needs, defined once: `EntityId` base (`ServerId`,
`PluginId`, etc.), `Permission`, `AggregateRoot` base with event collection, `MinecraftVersion`
semantics where shared, domain event base.

**Dependency rule.** `shared` may be imported by any module; it imports nothing from modules.

---

## 4. The CQRS Buses (ADR-0002)

### 4.1 CommandBus

- **Synchronous**, returns `CommandResult(success, data, error, error_code)`.
- **Transactional** — handlers create `UnitOfWork` internally and use SQL repositories via the UoW
  session.
- **Idempotency** — commands carry idempotency keys; duplicates return cached results
  (`idempotency_keys` table, 24h TTL).
- Dispatch: `await command_bus.dispatch(CommandType, payload)` → registered handler.
- Errors are caught at the bus boundary and mapped to `MCSError`; unexpected exceptions become
  `UNEXPECTED_ERROR`.

### 4.2 QueryBus

- **Synchronous**, returns `QueryResult(data, total)` for paginated queries.
- **No idempotency, no transactions** — reads only.
- Caching is described in ADR-0002 as a middleware option; in practice read caching is handled at
  the frontend layer (TanStack Query), not in the query bus.

### 4.3 EventBus

- **Asynchronous**, fire-and-forget, with **retry (3 attempts, exponential backoff 2^n) + per-handler
  timeout (10s) + dead-letter queue**.
- Subscriptions are **exact event-type match** — the bus has no wildcard support. Subscribers must
  register per event type (this is why the WS `EventDispatcher` must be started with an explicit
  event-type list — K2).
- Priority ordering via `Priority` IntEnum (CRITICAL/HIGH/NORMAL/LOW).
- `UnitOfWork.commit()` publishes collected events **after** the DB commit, in order.

**Cross-module communication rule:** modules publish domain events; they never call each other's
services. This is what keeps the modular monolith's boundaries real.

---

## 5. Persistence & Storage Model

### 5.1 DatabaseEngine and sessions

`DatabaseEngine` (`core/persistence/db.py:16`) wraps `create_async_engine` (SQLAlchemy 2.0 async)
and provides an `async_sessionmaker`. Sessions are injected via FastAPI `Depends(get_db)`. Pooling:
20 pool size / 10 max overflow / `pool_pre_ping=True` for PostgreSQL; SQLite mode skips pooling
(`pool_size` params disabled for SQLite compatibility).

URL from `MCS_DATABASE_URL`; supports `postgresql+asyncpg://` and `sqlite+aiosqlite:///`. Alembic
reads the same URL (via env or `alembic.ini` fallback).

### 5.2 UnitOfWork

```
async with UnitOfWork(event_bus) as uow:
    repo = uow.get_repo("servers", ServerModel)
    await repo.add(server)
    uow.add_event(DomainEvent(...))
    # __aexit__: commit → publish events on success; rollback + run cleanups on exception
```

- Sessions are created inside `__aenter__` (not reused across requests — no request-scoped session
  leak).
- `defer_cleanup(fn)` registers async cleanups run on rollback (used for temp file cleanup).
- Events are published **only after a successful commit**, in insertion order.

### 5.3 Key tables (schema highlights)

See `docs/architecture/DATABASE.md` for the full column listing; the architecture-relevant subset:

| Table | Purpose | Notable columns |
|---|---|---|
| `servers` | Central aggregate | `root_path`, `launch_config_json`, `missing_since`, `deployment_start_time`, `external_id` |
| `backup_jobs` | Backup metadata | `storage_path`, `checksum`, `backup_type`, `status` |
| `backup_policies` | Retention/schedule | retention days, max backups |
| `plugins` | Plugin registry cache | `filename`, `source`, `pending_deletion`, Modrinth provenance |
| `users` / `roles` / `user_roles` | Identity + RBAC | password_hash (Argon2id), permissions (Text) |
| `api_keys` / `refresh_tokens` | Credentials | `key_hash`/`token_hash` (SHA-256) |
| `event_store` | Append-only event log | hash chain columns |
| `dead_letter_events` | Failed events | replay metadata |
| `metric_points` / `alert_rules` | Monitoring | TPS, players, RAM, CPU |
| `idempotency_keys` / `feature_flags` / `circuit_breaker_states` | Infrastructure | — |
| `saga_instances` / `saga_steps` | Saga orchestration | — |
| `task_queue` / `cron_jobs` | Scheduling | cron expressions, task name |
| `health_status` / `health_timeline` / `health_evidence` / `health_diagnostics` | Health engine | — |
| `pending_restores` | Restore queue | deferred restores |

### 5.4 What Redis is *supposed* to do vs. what runs

| Claimed (docs) | Reality |
|---|---|
| Redis cache | Not used. No Redis cache exists. |
| Arq/Redis task queue | `ArqQueue` defined in `tasks/arq_queue.py`, **never instantiated or wired**. `aredis` isn't a declared dependency, so importing it would fail. Runtime always uses `InProcessQueue`. |
| Redis pub/sub for events | Not used. Events flow through the in-process `EventBus`. |

Phase 6 explicitly asks whether `ArqQueue` and the Redis story should be **implemented, removed, or
formally declared a non-goal** rather than remaining half-documented (§06).

### 5.5 Migration strategy

Alembic with async engine (`alembic/env.py:34`). 16 revisions at time of verification
(2026-08-04), head `c4d5e6f7a8b9`. The production DB (`backend/data/servers/mcs.db`) is **3
revisions behind head** (K9) — see Phase 3. A documented fresh-clone bug (9 ORM-only tables never
migrated) was fixed with idempotent migrations; replay against pre-migration backup is
column-for-column identical (see `docs/architecture/DATABASE.md` §Migration Guide).

---

## 6. Runtime Model & OS Interaction

### 6.1 Server providers (Strategy pattern)

`ServerProvider` ABC (`modules/server/infrastructure/providers/base.py`) abstracts OS-level server
lifecycle. Implementations:

| Provider | `provider_type` | Mechanism |
|---|---|---|
| `LocalLinuxProvider` | `local` | tmux sessions, process-tree JVM PID resolution |
| `LocalWindowsProvider` | `local_windows` | PowerShell background jobs |
| `DockerProvider` | `docker` | `itzg/minecraft-server` image, `docker create/start/stop` |
| `SSHProvider` | `ssh` | remote tmux via asyncssh, connection pooling |
| `CloudProvider` (abstract) + `CloudProviderStub` | `cloud` | VM provisioning (AWS/GCP/Azure/DO/Hetzner); `start/stop` raise `NotImplementedError` |

`ProviderFactory` is a registry singleton (`providers/__init__.py`); `CircuitBreakerProviderWrapper`
wraps any provider with the circuit breaker (5 failures, 30s cooldown by default).

**JVM PID resolution.** tmux's pane PID is the wrapper shell, not the Java process.
`LocalLinuxProvider._resolve_server_pid()` walks the process tree (up to 4 levels via
`ps -o pid=,ppid=,comm= --ppid`) and returns the first `java` descendant; falls back to pane PID if
none found. This is what makes metrics/RAM/CPU reflect the real server rather than a near-empty
shell.

### 6.2 Filesystem reconciliation (disk = truth)

`FilesystemReconciliationService` (`server/application/services/filesystem_reconciliation.py`),
6-stage pipeline:

1. **FilesystemScanner** — list directories only.
2. **IdentityReader** — read/validate `.mcsmanager/server.json` (every dir gets a UID, even
   non-Minecraft).
3. **MinecraftDetector** — `scan_server_directory()` with `ScanCategory` (MINECRAFT_VALID /
   MINECRAFT_BROKEN / NOT_MINECRAFT / SCAN_FAILED).
4. **ReconciliationPlanner** — pure logic, builds a `Plan`, no I/O.
5. **TransactionExecutor** — write identity **first** (write-ahead), then DB writes.
6. **IdentityWriter** — called during execution, not post-commit.

**Properties:** identity belongs to the directory, not the server (renaming folders is safe);
identity files written *before* each DB write (write-ahead — a failure rolls back cleanly and the
next run is idempotent); self-healing for corrupted identity files; two-pass deletion via
`mark_missing()`/`missing_since` (prevents data loss on transient moves); `dry_run` support;
servers deployed outside `data/servers/` skipped.

**Runs:** at application startup (after runtime reconciliation) and via
`POST /api/v1/servers/refresh?dry_run=true`.

### 6.3 RuntimeSupervisor (per-server watchdog)

`RuntimeSupervisor` (created via `start_for()` after a server launch):

- `_verify_startup()` — polls `provider.wait_ready()` (log line `Done (`) until deadline (120s
  default); process dies → collect diagnostics → `_handle_crash()` with `failure_code=STARTUP_TIMEOUT`.
- `_health_check()` every 5s — `provider.verify_process()`; dead process with non-STOPPED status →
  `RUNTIME_PROCESS_LOST` → `_handle_crash()`.
- `_handle_crash()` — suppression check (stop requested?), log diagnostics, tmux cleanup, persist
  `server.crash(...)`, fire `_on_crash` callback, stop the loop.
- Class-level `_instances` registry prevents duplicate supervisors; `stop_for()`/`get_for()`
  support command lookup.

### 6.4 Runtime ownership & orphan cleanup

`reconcile_orphans(scope="project_owned")` kills stale OS resources **only** if ownership is proven:

1. **`MCS_MANAGED=1` env marker** on the process (spawned by `LocalLinuxProvider`).
2. **cwd inside `MCS_SERVERS_DATA_DIR`** (`/proc/{pid}/cwd`).
3. **DB cross-reference** + `deployment_start_time` comparison (PID-reuse protection).

Any check that cannot complete with certainty → **skip** (fail-safe). `scope="system_wide"` is the
legacy kill-by-heuristic mode, available only via explicit API call. Every decision logs a
`KILL_DECISION` structured line. This is what guarantees startup never kills an untracked real
Minecraft server (ADR-0011).

### 6.5 Task queue & scheduler

- `TaskQueue` ABC with `InProcessQueue` (SQLite-backed `task_queue` table, `asyncio.ensure_future`)
  and `ArqQueue` (defined, unused).
- `Scheduler` loads `cron_jobs` from DB into APScheduler; `add_job()` persists + schedules.
- Wired **only** in `main.py` lifespan: queue → registered handlers → `init_task_queue` →
  `reclaim_pending()` (reclaims tasks orphaned by restart) → `mark_stale_running_failed()` →
  `MetricsCollector` → `scheduler.start()` → idempotent cron registration
  (`metrics_collect_every_0.5s`).
- **Vulnerability:** this wiring is the only place these systems are created. Removing it silently
  kills metrics and scheduling (ADR-0006 post-hoc finding). Phase 6 must make this resilient.

### 6.6 WebSocket layer

Files: `websocket/` — `manager.py` (registry), `authentication.py`, `authorization.py`, `endpoint.py`,
`dispatcher.py`, `handlers.py`, `serializers.py`, `buffer.py`, `rate_limiter.py`.

**Working today:**
- Handshake validates the JWT **before** `accept()` (`endpoint.py:51-62`); invalid → WS close 1008.
- `ConnectionManager` registry guarded by `asyncio.Lock` (ADR-0004).
- Message serialization/deserialization, offline message buffer, WS rate limiter (50 msg/s).
- Frontend client with auto-reconnect/backoff, ping keepalive, message queue flush, channel
  resubscribe — fully implemented.

**Broken today (Phase 3 must-fix):**
- **K1** — `CHANNEL_PATTERNS` requires *plural* permission strings (`servers:read`, `backups:read`),
  but JWT/api-key claims carry *singular* REST permissions (`server:read`). `set() is subset` fails
  for every real claim set, and `admin:full` is in no required set. Every `subscribe` is denied —
  fail-closed but dead.
- **K2** — `EventDispatcher` and `MetricsBatcher` are never instantiated in production. There is no
  event-bus subscription, so no domain event ever reaches a client, even with a valid subscription.
- Secondary gaps (see `docs/PERMISSIONS_FUTURE_IDEAS.md` §4): `refresh_token` accepts any non-empty
  string without validation; idle timeout defined but never invoked; dispatcher never re-checks
  authorization per pushed message; expiry set to `now + 3600` regardless of the 900s access-token
  TTL.

**Channel auth model (intended).** Channel patterns map to permissions:
`server:*`/`server:{id}` → `servers:read`, `server:{id}:console` → `servers:console`, etc. The
frontend channel manager validates prefixes (`server`/`backup`/`plugin`/`monitoring`/`metrics`/
`health`/`auth`/`user`), max 50 channels.

**Frontend bridge.** `WebSocketManager` maps WS `onCacheUpdate` keys to TanStack Query keys
(`"servers:list"` → `["servers","list"]`, etc.). Invalidation events derive from domain event types.

### 6.7 Rate limiting

`RateLimitMiddleware` — in-memory sliding window keyed by **`client_ip:path`**, 60 req/min, returns
429 with `Retry-After: 60`. No `X-RateLimit-*` headers, not per-route configurable. WS rate limiter:
50 msg/s per connection. **Already per-client** (corrects an earlier "process-global" claim).

---

## 7. API Layer

### 7.1 Middleware stack (order matters)

```
RequestIDMiddleware → AuthMiddleware → AuditMiddleware → RateLimitMiddleware
```

- **RequestID** — attaches `X-Request-ID`; propagated to logs and error responses.
- **Auth** — parses Bearer JWT / API key; writes `request.state.user`, `request.state.permissions`;
  allows a small public allow-list (login, refresh, users POST, health, metrics, docs).
- **Audit** — records mutating requests to the audit log (hash-chained).
- **RateLimit** — per `client_ip:path`.

### 7.2 Routers (11 as of 2026-08-06)

`auth`, `backups`, `health`, `marketplace`, `monitoring`, `plugins`, `schedules`, `servers`,
`settings`, `software`, `users` — plus the WebSocket router. Phase 0 in `04-...` carries the live
counts; note that `marketplace.py` (global `GET /api/v1/marketplace/search`, K5) is newer than the
earlier 10-router counts.

### 7.3 Error contract

`{ code, message, details, request_id, retryable, documentation_url }` (defined in
`contracts/api.yaml` and enforced by `api/errors.py`). Status mapping: `VALIDATION_ERROR` → 422,
`NOT_FOUND` → 404, `PERMISSION_DENIED` → 403, `UNAUTHORIZED` → 401, domain errors → 4xx per code,
unexpected → 500. DELETE endpoints return 204 (no body). Route-count introspection requires forcing
`app.openapi()` for lazy `_IncludedRouter` materialization (FastAPI 0.139 quirk) — relevant to the
Phase 4/6 route-coverage CI check.

### 7.4 OpenAPI

`backend/openapi.json` generated from the app. `docs/API.md` is the maintained reference.

---

## 8. Frontend Architecture

### 8.1 Stack

React 19, TypeScript 5 (strict), Vite 5, TailwindCSS 4 (raw components, **no shadcn/ui** — an
intentional dependency-avoidance decision), TanStack Query 5 (server data), Zustand 5 (UI state),
React Router v7, custom chart components (no chart library).

### 8.2 State layers

| Layer | Responsibility |
|---|---|
| TanStack Query | Server data; centralized query keys in `services/queryClient.ts`; default `staleTime: 10s`, `retry: 1`, `refetchOnWindowFocus: false` |
| Zustand | Client-only state: `authStore` (tokens in localStorage `mcs_auth`), `uiStore` (theme `mcs_theme`), `wsStore` (WS connection state) |
| Local component state | Selected server in marketplace page, forms |

### 8.3 API client

`services/api.ts` — typed fetch wrapper: Bearer injection, automatic refresh on 401
(deduplicated via a `refreshing` promise guard), `ApiError` with status/code/message/detail.

### 8.4 WebSocket client

Fully implemented client: `wss://<host>/ws?token=<jwt>`, reconnect backoff (1s→30s, max 10),
30s ping, message queue flush on reconnect, channel resubscribe. **Behaviorally non-functional
against the current backend** (K1/K2) — a Phase 2/3 concern (§04/§05). The `metrics` snapshot
ordering contract: `GET /monitoring/metrics` returns newest-first; consumers must pick the max
`timestamp`, never `[length - 1]` (fixed with regression coverage in
`ServerMetricsCharts.test.tsx`).

### 8.5 Pages/routes

`/login`, `/register`, and guarded: `/` (Dashboard), `/servers`, `/servers/create`,
`/servers/import`, `/servers/:serverId`, `/backups`, `/plugins`, `/plugins/marketplace`,
`/marketplace` (K5, top-level), `/settings`, `/settings/api-keys`. Sidebar:
Dashboard / Servers / Backups / Plugins / **Marketplace** / Settings. AuthGuard wraps authenticated
routes.

---

## 9. Security Architecture (summary; see `docs/architecture/SECURITY.md`)

| Concern | Mechanism | Status |
|---|---|---|
| Password | Argon2id | Implemented |
| Access token | RS256 JWT, 15 min | Implemented (ephemeral keys — K11) |
| Refresh token | Opaque, SHA-256 hash, rotation, revocable | Implemented |
| API key | `mcs_` + SHA-256 (unsalted) | Implemented |
| Authorization | RBAC+ABAC `require_permission` | **Partially enforced** (32 routes; 9 mutating + 23 GET gaps — Phase 4) |
| WS auth | JWT before accept + channel gate | Handshake works; channel gate always denies (K1) |
| Audit | SHA-256 hash chain | Implemented; no scheduled verify; no query endpoint |
| Backups at rest | AES-256-GCM | Implemented |
| TLS | TLS 1.3 at reverse proxy | Deployment-level |
| Rate limiting | `client_ip:path` in-memory, 60/min | Implemented |
| `/metrics` | Public | Deliberately public (K10, deferred) |

---

## 10. Cross-Cutting Concerns

### 10.1 Circuit breaker

`CircuitBreaker` wraps provider calls (and other external boundaries). States
closed/open/half-open persisted in `circuit_breaker_states`. `call_factory` supports lazy coroutine
creation. Default 5 failures, 30s cooldown via `CircuitBreakerProviderWrapper`.

### 10.2 Idempotency

`idempotency.py` + `idempotency_keys` table (24h TTL). Applied at the command bus. Duplicates return
the cached result rather than re-executing. This protects against client retries on flaky networks
(especially relevant once Phase 7 exposes the API to the internet).

### 10.3 Feature flags

`feature_flags.py` + tables (`feature_flags`, `feature_flag_overrides`) — boolean + percentage
rollout, per-user overrides. Used for rolling out risky behavior without redeploys.

### 10.4 Structured logging

`core/logging.py` (structlog-style, with the Python 3.14 keyword-args caveat recorded in Batch 1).
`X-Request-ID` correlation; `KILL_DECISION`, `Event moved to dead letter queue`, and cron-wiring
lines are the important operational signals.

---

## 11. Failure Modes & Recovery — the patterns inventory

| Failure | Detection | Recovery | Owner |
|---|---|---|---|
| Server crash | RuntimeSupervisor health check | Crash diagnostics + health recovery orchestration (3/300s cap) | `health` |
| Server start timeout | `_verify_startup` deadline | Diagnostics + `_handle_crash` | `server`/`health` |
| Provider unavailable | Circuit breaker open | Calls fail fast; UI surfaces provider status | `server`/`monitoring` |
| Backup save-world timeout | `_save_world` 30s poll | Job `FAILED` | `backup` |
| Restore cross-device move | `os.replace` EXDEV | **Prevented** by same-FS staging (ADR-0012) | `backup` |
| Event handler failure | EventBus retry (3×backoff) | Dead-letter queue + manual replay | `event_store` |
| Plugin install checksum mismatch | SHA-1/SHA-512 verify | Install refused | `plugin` |
| Stale server dir (transient) | First-pass `mark_missing()` | Second-pass delete; grace period | `server` |
| Orphan OS resources | Ownership-verified reconcile | Kill only on proven ownership | `server` |
| SQLite lock contention | `database is locked` | Preflight script kills stale processes | ops |
| Queue orphaned by restart | `reclaim_pending()` at boot | Re-queue PENDING, fail stale RUNNING | `tasks` |
| Metrics collector silently dead | Cron rows stop growing | Wiring is in one place (main.py) — Phase 6 hardens | `tasks` |
| WS delivery dead | (K1/K2) | Phase 3 wiring | `websocket` |


---

<a name="mcs-manager-engineering-standards"></a>
# MCS Manager — Engineering Standards
*Part III — Engineering Standards · source: `03-engineering-standards.md`*

**Part III** of the Engineering Blueprint V4. Defines the *how* of writing code in this repository:
coding standards, the architecture-decision-record (ADR) process, the testing philosophy and quality
gate, and the non-functional requirements (NFRs) and performance targets the product must hold to.

These standards are not suggestions. They are enforced by tooling where possible (ruff, pyright,
ESLint, `tsc`, CI) and by review and the ADR process where enforcement must be a judgment call.

**Last updated:** 2026-08-06
**Supersedes:** the scattered code-conventions sections in `docs/DEVELOPMENT.md` (§Code Conventions,
§Script Conventions, §Testing Strategy) and `docs/testing.md` (§Quality Gates); it also formalizes the
ADR process that `docs/decisions/README.md` introduced informally and pulls the quality gate into one
place. Where this file and a source document disagree, this file is the definitive engineering
standard and the source document should be updated to match.

---

## 1. Scope and how this file is used

This is the reference for *how we write code*, not *what we build* (that is Parts II, IV, V) and not
*why we build it in this order* (Part I). A contributor should read this file before writing their
first line, and a reviewer should hold submissions against it.

The file is organized so that concrete, checkable rules come first (§2–§5), process and philosophy
come in the middle (§6–§8), and non-functional requirements are collected at the end (§9). Part IX
(`12-working-agreements.md`) covers the collaborative workflow *around* the code — how commits are
made, how AI is used — and is the companion to this file.

---

## 2. Backend coding standards

### 2.1 Language baseline

- **Python 3.12+.** This is declared in `backend/pyproject.toml` and assumed everywhere.
- **Type hints everywhere.** No untyped public functions, handlers, or domain contracts. The project
  runs `pyright` in the quality gate (§8), so new code must type-clean out of the gate.

### 2.2 Style and formatting (enforced by tooling)

- **Formatting:** `ruff format .` (see `scripts/format`). All code must be `ruff format`-clean.
- **Lint:** `ruff check .` (see `scripts/lint`). Zero lint errors allowed.
- **Function length:** a function should stay under ~40 lines. When it exceeds that, it is a signal
  the logic is doing more than one thing and should be split. (Not a hard rule — a long, linear,
  well-named computation may stay — but reviewers should ask why.)
- **Docstrings:** only where the "why" is not obvious from the code or name. Do not write docstrings
  that restate the code. This keeps noise low on a file-by-file basis.

### 2.3 Package/import hygiene

- **Module boundaries are enforced, not conventional.** A module must not import another module's
  internals; communication happens across the CQRS buses or shared value objects (§Part II). This is
  the DDD boundary rule and a review blocker.
- **Domain never imports infrastructure or the API layer.** `application` may import from `domain`
  (as interfaces) and `infrastructure` (as adapters the app wires); `api` wires everything. The
  dependency direction is one-way: `api → application → domain ← infrastructure`.
- **Exception hierarchy:** domain-specific exceptions live in the owning module and extend a shared
  base from `core`; the API layer maps them to HTTP status codes, never to raw 500s unless truly
  unexpected.

### 2.4 Async discipline

- The backend is **asyncio-native**. Blocking calls must not run on the event loop; filesystem,
  network, and subprocess work go through infrastructure adapters that are async or offloaded.
- **Shared async state is protected with an `asyncio.Lock`** (ADR-0004), never a bespoke
  synchronization primitive.
- A coroutine that awaits must be awaited; no dangling tasks without ownership and cancellation
  handling. Long-lived background loops are cancelled in the owning lifecycle's shutdown path.

### 2.5 Config and environment

- All runtime configuration flows through `AppSettings` (`backend/app/core/config.py`), sourced from
  environment variables with the `MCS_` prefix and `.env` support. Never read `os.environ` ad hoc in
  module code.
- **Sandbox-isolation variables are load-bearing** (`MCS_DATABASE_URL`, `MCS_SERVERS_DATA_DIR`),
  ADR-0008. Test and development processes that touch the database or server files MUST set both, in
  the same command as the process, so they never reach production state.

---

## 3. Frontend coding standards

### 3.1 Language baseline

- **TypeScript, strict mode**, with `tsc --noEmit` as the typecheck gate. No unchecked `any` in new
  code. (See `frontend/tsconfig.json` and `npm run typecheck`.)

### 3.2 Style and lint

- **ESLint** over `src/` (`npm run lint`) with the `react-hooks` and `react-refresh` plugins (§`rules-of-hooks`, `react-refresh/only-export-components`).
- Formatting follows the project's prettier/eslint configuration; generated code must be lint-clean.

### 3.3 State and data-fetch conventions

- **Remote state goes through TanStack Query** (React Query): queries are cached and keyed by
  endpoint; mutations invalidate the relevant queries. There is no hand-rolled HTTP state store.
- **Local/UI state uses Zustand stores** where the state is shared across the tree (auth, UI, WS);
  component-local state stays in `useState`/`useReducer`.
- **The WebSocket layer is the live-update bridge.** Incoming messages route to the cache-callback
  mechanism (ADR-0004) so TanStack Query caches stay fresh without polling. A page that can render
  live data must subscribe through the WS client, not poll.

### 3.4 Test conventions

- Tests use Vitest + jsdom + `@testing-library/react` + `userEvent` (prefer `userEvent` over
  `fireEvent`). Mocks are `vi.fn()`. Stores are reset between tests.

---

## 4. The quality gate (must pass before merge)

Every change must pass the full gate locally **and** in CI before it is merged or marked done. The
gate is linear and additive; a failure at any step halts the merge.

### 4.1 Backend gate

```
ruff check .          # lint
pyright               # type check
pytest                # full suite
```

Runnable in one step as `./scripts/check`, which runs lint + typecheck + test in order.

### 4.2 Frontend gate

```
npm run lint          # ESLint
npm run typecheck     # tsc --noEmit
npm test              # Vitest
```

### 4.3 Coverage rule

New code must maintain ≥ 90% coverage on the exercised paths. This applies to both the backend
(`pytest --cov=app`) and the frontend (`vitest run --coverage`). The project currently runs
**1070 backend tests / 236 frontend** (verified 2026-08-04); the two backend env failures are
tracked in `docs/current-state.md` §4, not silently waived (Part I "fail loud").

### 4.4 Verification, not declaration

A change is done only when its gate passes against **live** code. It is not acceptable to mark a
unit done because the previous batch's log said tests passed. This mirrors Part I's *evidence before
assertion* rule and is restated here because it is the single most common way "done" gets falsified
in this project's history.

---

## 5. Tests and the testing philosophy

### 5.1 The test pyramid

Backend tests are organized to mirror the module/DDD layer (from `docs/testing.md`):

- **Domain tests** — aggregates and value objects in pure isolation (`backend/tests/domain/`).
- **Application tests** — command/query handler behavior, sagas, idempotency
  (`backend/tests/application/`, `test_command_bus.py`, `test_saga.py`, `test_idempotency.py`).
- **Infrastructure tests** — providers and repositories mocked at interface boundaries; unit tests
  never call real Docker or filesystem APIs (`backend/tests/infrastructure/`).
- **API tests** — endpoint behavior via `httpx.AsyncClient` on FastAPI's `TestClient`
  (`backend/tests/api/`, `tests/test_integration.py`).
- **Cross-cutting** — buses, config, exceptions, logging, security, database, websocket, feature
  flags, circuit breaker.

Frontend tests mirror component structure (`frontend/src/**/*.test.*`): stores, services, websocket,
components, pages.

### 5.2 Fixtures and isolation

- Shared fixtures (event loop, buses, mock handler) live in `backend/tests/conftest.py`.
- Infrastructure providers are mocked at their interfaces; integration tests use SQLite in memory.
- **Tests MUST never touch production state** (ADR-0008): sandbox database and directory.
- A handler that can raise is tested for both success and failure; a stub that returns conditional
  behavior is tested for every branch, not just the happy path.

### 5.3 Where tests are written

A test accompanies a feature unless a test is genuinely impossible (a pure-presentation toggle with
no observable behavior, in which case the omission is called out in review, not assumed).

### 5.4 Integration / E2E (planned, not yet committed)

`backend/tests/e2e/` is planned to exercise the full stack (backend + PostgreSQL + Redis via Docker
Compose, headless frontend via Playwright, WebSocket reconnect, auth refresh, real plugin
subprocess). This is **future scope**, not a current requirement — it is tracked in Part V Phase 6.

---

## 6. The architecture-decision-record (ADR) process

### 6.1 What deserves an ADR

A decision deserves an ADR when it is **significant and hard to reverse** — it changes a public
contract, a security property, a data-integrity property, an isolation boundary, or a cross-cutting
behavior. Routine implementation choices (naming, internal helper factoring) do **not**.

Examples that *did* deserve ADRs (see `docs/decisions/`): modular monolith (0001), CQRS buses
(0002), all-plugins-as-subprocesses (0003), WS concurrency/permissions (0004), JWT RS256 (0005), task
queue dual impl (0006), persistence rename (0007), sandbox isolation (0008), pydantic field
validators (0009), commit-per-step (0010), orphan ownership verification (0011), same-filesystem
staging (0012).

### 6.2 The process

1. **Propose.** Document the ADR using the established template: `Context`, `Decision` (with date,
   author), `Consequences`. It must capture the options considered and the trade-offs, not just the
   conclusion.
2. **Number sequentially and append to the table in `docs/decisions/README.md`.**
3. **Never delete or rewrite history.** An ADR once accepted is never removed; it is superseded by a
   newer ADR that explicitly marks the prior one as superseded (Part I §9).
4. **Statuses:** `Accepted` (the norm), `Superseded` (a later ADR replaced it), `Rejected` (considered
   and deliberately not taken — worth recording). Finished/abandoned proposals are recorded with the
   reason.

### 6.3 When an ADR is out of date

When code drifts from an ADR, the ADR is authoritative unless and until a new ADR supersedes it. A
silent drift without an ADR is a defect to fix or document, not a de-facto decision to accept.

---

## 7. Releasablility and the versioning contract

Versioning strategy is described in `docs/VERSIONING.md` and scheduled as **Phase 5** within Part V.
The standards it imposes once landed, which the phase must satisfy:

1. **One source of truth:** `backend/pyproject.toml` is canonical; runtime (`AppSettings.version`),
   OpenAPI, and the frontend-displayed version derive from it rather than duplicating it.
2. **SemVer 2.0.0 semantics** with explicit meaning per segment (see `VERSIONING.md` §4.2); `v1.0`
   public-release naming is decoupled from internal app version.
3. **Migration/version compatibility rule:** every release pins the minimum Alembic revision; startup
   enforces or loudly reports the DB revision state vs. the app version.
4. **State-file discipline:** `.ai/CURRENT_STATE.json` and `.ai/PROJECT_STATE.json` align their
   `version` fields to the resolved value and note a verification date; docs never assert a version
   they can't justify from the code.

These become **requirements** for any code that touches versioning, release, or state files — the
standard to which Phase 5 closes out.

---

## 8. Repository & script discipline

### 8.1 Dev-loop scripts

All developer-facing commands are **canonical, named scripts in `scripts/`** (symlinked at project
root) `bootstrap`, `lint`, `format`, `typecheck`, `test`, `check`, `build`, `release`, plus
`scripts/preflight.sh`. Ad-hoc commands must not replace them.

### 8.2 Script conventions

Every script:
- Runs from the project root (`cd "$(dirname "$0")/.."`).
- Is executable (`chmod +x`).
- Follows `set -euo pipefail`.

### 8.3 CI

- **GitHub Actions** at `.github/workflows/frontend-ci.yml`. Today **only the frontend has a CI
  workflow** — the backend has none. That asymmetry is **a known gap (K6)** and closing it is part of
  Part V Phase 6. Until it is closed, the backend gate is enforced locally (`./scripts/check`) and by
  review.

---

## 9. Non-functional requirements (NFRs)

This section records the cross-cutting non-functional requirements and the performance targets the
product is expected to meet. Where a target is not yet measured, it is labeled. These apply to any
commit during execution (Part V), not only at specific phases.

### 9.1 Performance targets

| Target | Value | Status |
|---|---|---|
| API cold-start latency (interactive route) | p95 < 300 ms | Target (not yet baselined) |
| Backend boot time (modular monolith, warm) | < 5 s | Target |
| Concurrent live WS subscribers | 500 without connection-dropping | Target (currently singleton HPA) |
| Monitored-server metrics collection | On cadence without blocking server I/O | Target (λ poller design) |
| Acknowledge-then-process health/lifecycle events | No event lost on bounded-crash | Definition (event-store + DLQ) |

> These are *targets*, not commitments — a public baseline has not yet been published or measured. They
> exist so a performance regression in a later batch is detected against a *number*, not vibes.

### 9.2 Reliability and recoverability

- **Backups and restores are the lineage** (Part II, storage). The cost of any design change that
  makes backup/restore riskier is a review-blocking concern.
- **Automatic crashes escalate to a configurable stop** (default 3 crashes / 300 s) rather than a
  loop (Part I §8).
- **Reconciliation is idempotent, one-directional** (disk → DB cache), and its direction never
  reverses (Part I §2.3).
- **A operation that can't be rolled back atomically must fail before it mutates anything** (ADR
  0012 same-filesystem staging).

### 9.3 Observability

- Serve **Prometheus** metrics; the current `/metrics` endpoint is **public** — that is a known
  deferred risk (K10) to be closed in Phase 7, not a permanent design.
- Event-store and audit rows are append-only with a cryptographic chain (Part II, event_store).

### 9.4 Testability

- Every path a developer can permanently break is covered by the gate (§4). A feature must be
  testable to be shipped; untested surfaces are bugs waiting to be named.

### 9.5 Performance of the product over time

The metrics/retention pipeline and alerting are designed with **bounded retention and aggregation**
(four-tier rollup, ADR-0006) so the database does not grow without bound from monitoring.

---

## 10. Summary: the standard as a checklist

A change is "done" to this standard when all of the following hold:

1. Backend: `ruff check`, `pyright`, `pytest` green and coverage ≥ 90% on new code.
2. Frontend: `npm run lint`, `npm run typecheck`, `npm test` green.
3. Tests accompany non-trivial behavior, including the failure path.
4. Type-safe, no `any`, formatted per ruff/prettier.
5. No new rule or guideline was invented ad hoc — if a new convention emerged, it's recorded (ADR and
   update to this file), not just followed once.
6. No cross-module import violation; dependencies flow one direction.
7. Nothing blocks the event loop; shared async state uses `asyncio.Lock`.
8. Config is via `AppSettings`/`MCS_*`; test/dev processes sandbox their state.
9. The change is documented per the ADR/commit discipline, and history is never rewritten.


---

<a name="mcs-manager-execution-track-phases-02-current-reality-structure-foundation"></a>
# MCS Manager — Execution Track: Phases 0–2 (Current Reality, Structure, Foundation)
*Part V — Execution Track: Phases 0–2 · source: `04-phase0-1-2-current-reality-and-foundation.md`*

**Part V** of the Engineering Blueprint V4 — the actual phase plan. This file covers **Phase 0
(current reality)**, **Phase 1 (Plugins/Marketplace separation)**, and **Phase 2 (Product Foundation &
UI stabilization)**. It is the first execution-track file a contributor reads, and it is where the
"current reality" each later phase is checked against lives.

**Last updated:** 2026-08-07
**Supersedes:** `mcs-manager-roadmap-v4.md` Volumes 1–3 (now historical baseline). Status indicators
below use the roadmap legend: ✅ done, 🔄 in progress, 🔶 planned, ⛔ blocked, ⚠️ risk/open question.

---

## 0. How the execution track works

### 0.1 Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Done — verified, with citation |
| 🔄 | In progress — active now |
| 🔶 | Planned — not started |
| ⛔ | Blocked — gated on an earlier phase |
| ⚠️ | Risk, open question, or unresolved doc/code mismatch |

### 0.2 Bug classification

| Class | Meaning |
|-------|---------|
| Must fix | Blocks a phase exit criterion or a security/availability claim |
| Should fix | Real defect; can be deferred within a phase, but must stay scheduled |
| Optional | Quality-of-life; can be dropped with a documented reason |
| Known limitation | Accepted behavior, documented, not scheduled |
| Doc-only | Documentation correction, no code change |
| Future work | Tracked in a later phase's backlog, not current scope |

### 0.3 Evidence discipline (the governing rule for this track)

Every count or claim in the execution-track files is one of three things, and is labeled as such:

1. **Carried** from a prior verified source (marked "carried from v3" or with batch/date) — *not
   re-verified by this revision.* If an acceptance check depends on a carried number, the check must
   re-verify it live before claiming done.
2. **Verified** — checked against source, tests, or the filesystem during this revision.
3. **New** — this document's own analysis, marked as such.

The reason this rule is load-bearing: commit `b1b6dd8` (2026-08-04) made the v3 roadmap stale within
24 hours of its verification date. A snapshot is never "the truth"; it is the truth *as of a moment*.
Part I, `01-engineering-principles.md` §1, states this fully; here it is stated as the operating rule
of every phase below. Re-verification cadence is itself a Phase 6 deliverable (`06`), not assumed.

### 0.4 Governing product direction (carried from V4, unchanged)

- **Foundation before capability.** Structure and reliability come before advanced features.
- **Plugins ≠ Marketplace.** Plugins = installed plugins on a selected server. Marketplace = global
  catalog/discovery. Distinct surfaces.
- **Network access is gated on stability.** Tunnel/port-forwarding work doesn't start until product,
  authorization, versioning, and CI are reliable.
- **AI is the final phase**, intentionally deferred.
- **Speculative infrastructure is not roadmap.** Ideas without a committed decision are tracked in
  Part IV (`09`, `10`) and never merged into the phase plan until they clear the decision record.

### 0.5 Track view (informational only — phases remain the unit of execution)

Phases are the unit of execution; tracks are a reading aid so independent work can proceed in
parallel without colliding, and to clarify that neither can *close out* before its declared
dependency does.

| Track | Phases | Note |
|---|---|---|
| Product/UI | 1, 2 | Sequential — Phase 2 depends on Phase 1's nav baseline |
| Reliability | 3 | Gates Phase 4 |
| Security | 4 | Gates Phase 7 |
| Platform hygiene | 5, 6 | Can run partially parallel to 3/4 where scope doesn't overlap |
| Network | 7, 8 | Sequential, both blocked on 1–6 |
| Close-out | 9 | Blocked on 1–8 |
| Runtime migration | 11 | Blocked on 1–9; gates Phase 10 |
| AI | 10 | Blocked on everything, including Phase 11 |

This table changes no acceptance criterion or dependency stated in the phase files — those are
authoritative.

---

## 1. Phase 0 — Current Reality ✅

*Carried from v3 §2, live-verified 2026-08-05, unless flagged in §1.1's "since v3" table. This phase
intentionally does not re-run every check — restating v3's numbers without re-verification would be
exactly the mistake the rewrite exists to correct. Its role is to be the ground truth every later
phase is checked against.*

### 1.1 Codebase shape

| Item | Count | Verified how |
|---|---|---|
| Backend Python source files | 261 | `find backend/app -name '*.py'` (2026-08-04) |
| Backend test files | 90 | `find backend/tests -name 'test_*.py'` |
| Frontend test files | 41 | `find frontend/src -name '*.test.*'` |
| REST routers | 11 ✅ | `backend/app/api/v1/routers/` (verified 2026-08-06): auth, backups, health, **marketplace**, monitoring, plugins, schedules, servers, settings, software, users (marketplace added by K5) |
| DDD modules | 9 | `backend/app/modules/` |
| Alembic revisions | 16 | `backend/alembic/versions/*.py` |
| ADRs | 12 | `docs/decisions/*.md` (excl. README) |
| Contract files | 6 | `contracts/` |
| Backend tests collected | 1,070 | `pytest --collect-only -q` |
| Backend tests passed/failed | 1,068 / 2 ⚠️ **not re-run 2026-08-05, not re-run here** | carried from `current-state.md` (2026-08-04) via v3 |
| Frontend tests | 236 across 41 files | `vitest list` |
| App version (code) | `4.0.0` everywhere | grepped; `7.1.0` appears only as an unrelated semver-range substring and in historical planning docs |
| CI workflows | 1 (frontend only) | `.github/workflows/frontend-ci.yml` — no backend CI (K6) |

**Since v3 (from `docs/status/history.md` uncommitted batch entries, 2026-08-05 → 2026-08-06):**

| Item | Change | Source |
|---|---|---|
| Backend tests collected | 1,070 → **1,084** | Batch K16A (2026-08-05): plugin catalog provider tests |
| Marketplace frontend | First-class — own `/marketplace` route, sidebar entry, global search endpoint | K5 (2026-08-06), STATUS.md |
| Plugin catalog providers | Configuration-driven via `MCS_PLUGIN_PROVIDERS`, fail-fast validated at startup | K16A (2026-08-05), STATUS.md |

The two batches above post-date v3's 2026-08-05 snapshot. This blueprint treats K5 and K16A as done
(§Volume 2 ⇐ §2 of this file) on the strength of the STATUS.md batch entries — a *lower* verification
bar than v3's live route introspection. **Flagged, not hidden**, and Phase 2's first workstream
confirmed followup (§2.6).

### 1.2 Outstanding file-state item (carried from v3 §2, unresolved)

Two tracked, committed files carry uncommitted working-tree changes: `.../routers/plugins.py` (8
commits, latest `b1b6dd8`) and `.../tests/api/test_api_endpoints.py` (9 commits, latest `b1b6dd8`).
Pending diff: a `_to_version_response()` helper (+/−) and one new test
`test_marketplace_versions_returns_files` (+54). **D3, open** ($ref Part VIII `11`).

### 1.3 What Phase 0 establishes

Phase 0 has no deliverables of its own; it is the baseline every later phase's "current reality" is
checked against. If a later acceptance criterion depends on a Phase 0 number that hasn't been
re-verified since 2026-08-05, that check must re-verify it before claiming done. This is stated
explicitly because it is exactly the failure mode that produced v2 → v3 → V4.

---

## 2. Phase 1 — Plugins / Marketplace Separation ✅ CLOSED — 2026-08-07

### 2.1 Objective

Split **"what plugins does this server have"** (server-scoped, lifecycle-oriented) from **"what
plugins can I discover and install"** (global catalog, discovery-oriented) into genuinely distinct
product surfaces — not one page with a sub-tab. This is the canonical application of Part I §5
(*small, correct surfaces*).

### 2.2 Current reality

| Area | Answers | Scope |
|------|---------|-------|
| **Plugins** | "What plugins does this server have?" | Server-scoped: installed list, state, lifecycle, enable/disable, removal, configuration |
| **Marketplace** | "What plugins can I discover and install?" | Global catalog/store; server selection happens at install time |

- Backend historically: one router, `/api/v1/servers/{server_id}/plugins/*`, handling both plugin
  management and marketplace (search/versions/install). Provider selection configuration-driven via
  `MCS_PLUGIN_PROVIDERS` (default `modrinth`), validated fail-fast at startup (K16A).
- Live route table (v3, verified 2026-08-05): `GET /plugins`, `GET /plugins/{id}`,
  `DELETE /plugins/{plugin_id}`, `POST /plugins/{id}/enable`, `POST /plugins/{id}/disable`,
  `GET /plugins/marketplace/search`, `GET /plugins/marketplace/projects/{id}/versions`,
  `POST /plugins/marketplace/install`. No standalone install route outside marketplace — the old
  `POST /plugins` manual-install route was removed in `b1b6dd8`.
- **Per K5 (2026-08-06):** Marketplace now has its own top-level route (`/marketplace`), sidebar
  entry, and a global search endpoint (`GET /marketplace/search`) distinct from the server-scoped
  one. The install flow was reworked with a server picker (server selection happens at install
  time), pre-selecting by deep link → last-used server → first compatible → any server.

### 2.3 Workstreams

1. **Frontend nav restructure (K5).** ✅ Done per STATUS.md 2026-08-06 — own sidebar entry, own
   route, own search, install flow with server picker. **Not yet independently re-verified by live
   route/component introspection.** A short verification pass is recommended at the start of Phase 2
   rather than trusting the batch note alone (§2.6).
2. **Route/namespace clarity.** Decide whether marketplace API routes stay under
   `/servers/{id}/plugins/marketplace/*` or move to a marketplace-owned namespace. **Open — D4.**
3. **Provider abstraction (K16).** ✅ K16A done (2026-08-05): configuration-driven, validated
   fail-fast at startup on unknown/empty/multiple providers. K16A accepts exactly one active
   provider; the comma-separated syntax remains for the remaining K16 scope (inspect configured list
   via API; add a second provider). Remaining K16 work is **not Phase 1 exit scope** — it's backlog
   for whenever a second provider is needed.
4. **Foundation for future catalog features.** Checksums, version metadata, and dependency info
   already exist in the version-selection model — reuse rather than rebuild.

### 2.4 Dependencies

None — backend marketplace already shipped before this phase started.

### 2.5 Acceptance criteria

| Criterion | Status |
|---|---|
| Marketplace independently navigable (own nav entry + route) | ✅ Met per K5 (2026-08-06) |
| Installing from Marketplace places a verified `.jar` in the selected server's `plugins/`; reconciled list reflects it | ✅ Met — verified via install_modrinth_plugin.py + test_install_modrinth_plugin.py, 2026-08-07 |
| Plugin management reads server-scoped; Marketplace reads global | ✅ Met per K5 — separate search endpoints |
| Provider list configuration-driven, Modrinth default | ✅ Met per K16A (2026-08-05) |
| D4 (route namespace) resolved | ✅ Resolved — marketplace.py registered under /api/v1/marketplace prefix |

### 2.6 What's actually left before this phase can close

Phase 1 is close to done but not formally closed. Three concrete items:

1. **Independent verification of K5/K16A.** Both logged done in STATUS.md's batch narrative, which
   per its own header is not the source of truth for current counts. A short pass — hit the routes,
   confirm the sidebar entry renders, confirm install actually writes the `.jar` to the right server
   directory — closes "logged done" → "verified done" the way v3 closed it for Phase 0.
2. **D4.** The route-namespace decision blocks a clean Phase 1 → Phase 2 handoff for new
   marketplace-adjacent frontend work.
3. **D3.** The two files with pending diffs (§1.2) should be committed as their own commit before
   Phase 1 is called closed — an open diff against a "done" phase is a doc-vs-code mismatch
   waiting to happen.

### 2.7 Testing

Backend + frontend suites green (1,084 backend, 236+ frontend); manual UX walk of both nav surfaces;
frontend tests for both server-scoped and global marketplace search paths.

### 2.8 Risks

- **Route namespace churn (D4).** If marketplace routes move after other code depends on the
  current path, that's a breaking change needing a shim. Resolving D4 now, before Phase 2 builds more
  surface against the current path, is cheaper than resolving it later.
- **Silent scope creep into K16 remainder.** Multi-provider support is real work with its own
  testing surface. It must not quietly become a Phase 1 blocker — it's explicit backlog, not exit
  criteria.

---

## 3. Phase 2 — Product Foundation & UI Stabilization ✅ CLOSED — 2026-08-07

### 3.1 Objective

Make the frontend a first-class, stable surface — consistent loading/error/empty states and
navigation — on top of Phase 1's nav baseline. Honesty and consistency in the UI layer, **not new
features**.

### 3.2 Current reality (frontend)

- React 19 + Vite + TypeScript 5, TanStack Query, Zustand, TailwindCSS 4.
- Routes (`frontend/src/App.tsx`): `/login`, `/register`, then guarded: `/`, `/servers`,
  `/servers/create`, `/servers/import`, `/servers/:serverId`, `/backups`, `/plugins`,
  `/plugins/marketplace`, `/marketplace`, `/settings`, `/settings/api-keys`, `*`.
- Sidebar: Dashboard, Servers, Backups, Plugins, Marketplace, Settings.
- Zustand stores: `authStore` (localStorage `mcs_auth`), `uiStore`, `wsStore`.

### 3.3 Desired state

- Navigation clearly separates plugin-management from marketplace, and server-scoped from global.
- Loading/error/empty states uniform across all pages.
- API state and cache behavior deterministic (TanStack Query configured once, applied consistently).
- WebSocket behavior documented and either works or is explicitly disabled per surface.
- Settings UX reflects what actually persists. Persistence lands in Phase 3; Phase 2 disables /
  annotates non-persistent controls rather than faking success.
- Permissions UX shows only actions the user may take. Enforcement lands in Phase 4; Phase 2 lays
  the presentation groundwork against `contracts/permissions.yaml` (which has an open version
  question, D2). Phase 2 builds against whichever version is committed at the time and flags if D2
  resolves mid-phase.
- No new design system — apply consistently what already exists.

### 3.4 Workstreams

1. **Navigation & IA**, on Phase 1's restructure, including the post-K5 refresh in §3.2. ✅ Done.
2. **Shared loading/error/empty primitives**, applied repo-wide — one set of components, not
   per-page reinvention. ✅ Done.
3. **API client + TanStack Query configuration audit** — one query-client config; consistent
   staleTime; cacheTime; retry policy across queries rather than ad hoc per-hook settings. ✅ Done.
4. **Settings page accuracy** relative to actual persistence — every control either persists or is
   visibly disabled/labeled non-functional. No control silently no-ops. ✅ Done.
5. **WebSocket surface honesty** — live vs. explicitly disabled, surfaced in the UI. ✅ Done (commits `5eedd7c`, `2996aa2`, `88ec695`, `3690d52`, `04d92cd`).
6. **Dashboard & Server Detail Redesign (Part A & Part B)** — Blade Hosting-style server detail layout, contextual in-server navigation, File Manager UI (`/servers/:serverId/files`), Files REST API, and server-type-aware Mods/Plugins UI. ✅ Done (commits `bdbb877`, `b6a47fc`, `54428ad`, `adbf556`, `72e8c1c`, `ae6848d`, `e96f902`, `7226e6c`, `79d18d7`).
7. **Frontend test coverage** for the above. ✅ Done (362 tests / 50 files).
8. **Permissions UX presentation groundwork (DEFERRED)** — out of Phase 2 scope pending D2 resolution (`contracts/permissions.yaml`).

### 3.5 Dependencies

Phase 1 (nav restructure).

### 3.6 Acceptance criteria

- Every route has defined loading/error/empty behavior. ✅
- Navigation distinguishes server-scoped from global surfaces. ✅
- Frontend tests cover the restructured navigation and state primitives. ✅
- Settings page has zero controls that silently no-op. ✅
- WebSocket surface has zero "shows connected, does nothing" states. ✅

---

<a name="mcs-manager-execution-track-phases-34-reliability-security"></a>
# MCS Manager — Execution Track: Phases 3–4 (Reliability, Security)
*Part V — Execution Track: Phases 3–4 · source: `05-phase3-4-reliability-and-security.md`*

**Part V** of the Engineering Blueprint V4. This file covers **Phase 3 (Reliability)** and **Phase 4
(Authorization / Security Cleanup)** — together the highest-leverage work in the roadmap. Phase 3
makes the existing product actually reliable; Phase 4 closes the security gaps an audit found and
then enforces the model in CI so it cannot regress.

**Last updated:** 2026-08-09
**Supersedes:** `mcs-manager-roadmap-v4.md` Volumes 4–5 (now historical baseline). Status indicators
use the roadmap legend: ✅ done, 🔄 in progress, 🔶 planned, ⛔ blocked, ⚠️ risk/open question.
Evidence discipline and definitions of terms are in `04` §0 and Part I.

---

## 1. Phase 3 — Backend/Frontend Reliability ✅ CLOSED — 2026-08-09


### 1.1 Objective

Make the existing product actually reliable. This is the highest-leverage phase in the roadmap: it
**gates Phase 4**, and Phase 4 is where the project's real open risk lives (unauthorized mutating
routes, open registration). Every day Phase 3 is incomplete is a day Phase 4 cannot start.

### 1.2 Dependencies

None structural — runs in parallel with Phase 2 where the two overlap (see `04` §3.9 scope-bleed
risk). Phase 3 must **not** be started-for-done before the K-items below pass; "reliable" is a
binary, verified claim (Part I §1, §4).

### 1.3 WebSocket delivery — must fix

- **K1:** channel authorization always denies — plural `CHANNEL_PATTERNS` (e.g. `servers:read`) vs.
  singular JWT claims (e.g. `server:read`) — fail-closed, so no channel ever subscribes. Reconcile to
  a single singular `resource:action` namespace with an `admin:full` passthrough.
- **K2:** `EventDispatcher`/`MetricsBatcher` are never instantiated, so no server-push event ever
  reaches a client. Wire both into the app lifespan via event-bus subscription; stay fail-closed
  during the transition.
- **Secondary WS gaps** (`docs/PERMISSIONS_FUTURE_IDEAS.md` §4): validate `refresh_token` payloads,
  enforce idle timeout, re-check authorization per pushed message.
- **Acceptance:** a client with `server:read` subscribes and receives `state`/`event` frames;
  publishing a domain event reaches subscribers (integration test); fail-closed still holds without
  permission.
- **Why this matters beyond WS:** K1's root cause — plural vs. singular permission-string namespace —
  is the *same class of bug* Phase 4's route-gating will hit. Fixing the namespace once here, and
  having Phase 4 build on the corrected singular namespace, avoids fixing the same inconsistency
  twice in two subsystems.

### 1.4 Settings persistence — must fix

- **K3:** `PATCH /api/v1/settings` is a stub (`{"success": true, "message": "Settings updated (stub)"}`)
  — nothing persists. Decide the persisted field set (start with what `GET /settings` already
  returns — **D6**), persist it, apply it at runtime, gate with `settings:write`.
- **Acceptance:** updating a setting persists, is returned by `GET /settings`, and is enforced at
  runtime.
- **Sequencing note:** gating with `settings:write` here does a small piece of Phase 4's job on one
  route. That's intentional — same pattern Phase 4 applies everywhere, done first as a concrete
  precedent.

### 1.5 Test suite green — must fix

- **K8 / D5:** 2 failing tests (per `current-state.md`, 2026-08-04, ⚠️ not re-run since):
  `test_start_server` (closed-DB rollback in API teardown) and
  `test_metrics_task_requires_collector` (stale expectation vs. graceful warning handler). Fix or
  formally re-baseline — **D5 is explicitly open** on which of the two paths applies to which test;
  investigate `test_start_server`'s teardown first, since `test_metrics_task_requires_collector`
  looks like a stale assertion against since-changed behavior rather than a real regression.
- **Acceptance:** a fresh `python -m pytest tests/` run passes with **0 failures**.

### 1.6 Runtime / system consistency — should fix

- **K9:** production DB is **3 revisions behind head** (per `current-state.md`, 2026-08-04, ⚠️ not
  re-verified); 0 servers in production lowers immediate operational risk but doesn't remove the need
  to close it before Phase 4 or Phase 7 assume a consistent schema. Bring to head with a documented
  upgrade procedure. **D12 (auto-upgrade on boot vs. refuse-to-start) should be resolved as part of
  this item**, not left dangling after the migration runs.
- **K15:** clean up the repo-root `data/` directory (confirm unused first — **D11**).
- **K14:** backup save-all completion regex is unverified against a real Purpur server — add a
  live/mocking regression check. Listed here precisely so it doesn't quietly become permanent
  known-limitation by attrition.

### 1.7 Honest error handling

Audit HTTP status/error-payload consistency across all 11 routers (verified 2026-08-06: the 10
carried from v3 plus the marketplace router added by K5); document the contract. This is
foundational for Phase 4's route-coverage CI check — a route-coverage test is only as good as the
error contract it asserts against.

### 1.8 Testing strategy for this phase

- Every K-item needs its own **regression test**, not just a manual fix-and-verify — K1/K2
  especially (a WS auth regression is invisible until it silently breaks a client in production).
- The route-coverage habit Phase 4 will formalize in CI (§2.5) should be dry-run at the end of this
  phase against whatever gating §1.4 already did, as a sanity check that the pattern generalizes.

### 1.9 Acceptance criteria (phase-level)

WS live and delivering events with fail-closed authorization intact; settings persist and are
enforced; test suite 100% green (0 failures, not just 0 *new* failures); production DB at head with a
documented, decided (D12) upgrade procedure; HTTP error contract documented.

### 1.10 Risks

- **K1/K2 fix touching the code Phase 2's WS-honesty workstream depends on.** If Phase 2 and 3 run
  in parallel, Phase 2's WS surface-honesty work must either wait for K1/K2 or be built against the
  *current* broken behavior and re-verified once K1/K2 land. Recommend the latter.
- **Test re-baselining (D5) papering over a real bug.** If `test_metrics_task_requires_collector`
  is catching a real regression rather than a stale assertion, re-baselining hides a genuine defect.
  Default to "assume real bug until proven stale," not the reverse.

---

## 2. Phase 4 — Authorization / Security Cleanup ✅

### 2.1 Objective

Close the security gaps the audit found, then enforce the model in CI so it cannot regress. **This
is the single most important phase in the document.** Every other phase either leads into it or waits
behind it. Part IV's speculative future work cannot start until this phase *and* Phase 7's network
exposure close, because opening the product to the network with an unresolved authorization gap turns
a contained internal risk into an externally exploitable one.

### 2.2 Dependencies

Phase 3 (a stable, tested base). **Hard gate, not soft preference** — gating routes correctly
requires the corrected singular permission namespace from Phase 3 §1.3 (K1).

### 2.3 Enforce remaining routes — must fix

**Live-verified state (2026-08-05, from v3, superseding v2 §6.1 and `current-state.md` K7):**

- **28 routes are gated** by `require_permission` — 26 mutating (servers 12,
  backups 4, plugins-delete + marketplace-install 3, users 2, auth/API-keys 2, files 4) + 2 read-only
  marketplace GET routes.
- **Files API IDOR Gap (NEW open security item):** `GET /servers/{id}/files`, `GET /servers/{id}/files/content`, and `GET /servers/{id}/files/download` endpoints check authentication (`get_current_user`) but do NOT enforce per-server permissions. This presents an IDOR vulnerability that must be resolved prior to Phase 7 network exposure.
- **12 mutating routes are unprotected, not 13** — corrected from earlier, since `b1b6dd8` removed
  the legacy manual-install route:
  `POST /auth/login`, `POST /auth/logout`, `POST /auth/refresh`,
  `POST /health/evaluate/{server_id}`, `POST /monitoring/alerts`,
  `DELETE /monitoring/alerts/{alert_rule_id}`, `POST /schedules`,
  `DELETE /schedules/{schedule_id}`, `POST /plugins/{plugin_id}/enable` (K4),
  `POST /plugins/{plugin_id}/disable` (K4), `PATCH /settings`, `POST /users`.
  Of these, `login`/`logout`/`refresh` are intentionally public; **the other 9 are real gaps** — the
  single number that matters most in the whole document.
- **23 sensitive GET routes** are auth-only with no permission check (strict middleware count — an
  earlier "21" used a different classification; reconciling the two is **D1, still open**).
- **3 intentionally public routes:** login, refresh, registration (`POST /users` — see §2.4).

**Work:** gate the real gaps (9 mutating routes beyond the 3 intentional public ones, plus the 23
sensitive GETs) with permission strings, and enforce in CI.

**Sequencing within this workstream:**
1. Resolve **D2** (`contracts/permissions.yaml` version) first — §2.8 explains why.
2. Resolve **D1** (GET-route classification) before the 23-route GET work — the count itself is
   disputed.
3. Gate the **9 confirmed mutating gaps** — undisputed, can start immediately after D2.
4. Gate the **reconciled GET set** once D1 resolves.

### 2.4 Registration bootstrap (`POST /api/v1/users`) — investigate first

Registration is open with no auth — arguably the single highest real-world risk item in the roadmap:
an unauthenticated user-creation endpoint on a system about to gain network exposure in Phase 7 is a
direct path to account takeover.

**Decision procedure (carried, unchanged — D13):** investigate whether a first-user-bootstrap
exception is safe and simple (open only while zero users exist, then require `user:write`). If the
investigation surfaces hidden onboarding dependencies or ambiguous "first user" semantics, do **not**
improvise — document the finding in `docs/PERMISSIONS_FUTURE_IDEAS.md` and leave the route unchanged.
**Not yet investigated.**

**Why it can't just be deferred:** leaving `POST /users` open isn't a neutral "known limitation" —
it's an active, growing risk the longer the system exists before Phase 7 exposes it. Recommend
investigating this item *first* within §2.3's sequencing, ahead of the bulk GET work, because it is
higher severity than its alphabetical position suggests.

### 2.5 Backend CI + route-coverage test — must fix (K6)

No backend CI exists — only `.github/workflows/frontend-ci.yml`. Add a workflow running `pytest`,
`ruff`, `pyright`, and a route-coverage test that walks the live FastAPI route table and asserts
every mutating route carries a permission dependency.

**Acceptance:** a new mutating route without a permission dependency fails CI;
`contracts/permissions.yaml` matches the live route table with zero gaps.

This converts everything else in the volume from a one-time cleanup into a **standing guarantee**.
Without it, a new route can silently reopen exactly the gap this phase closes — not coincidentally
how the gaps identified here came to exist: nothing was stopping them.

### 2.6 WebSocket authorization hardening

Fold WS channel checks into the same (now singular, per Phase 3 §3.3) permission path. Phase 3 did
the namespace reconciliation; this workstream is primarily about confirming the WS auth path reads
from the same contract source (`contracts/permissions.yaml`) as the REST route-coverage check rather
than maintaining a second, parallel, driftable permission list.

### 2.7 `GET /metrics` — explicitly deferred

Public and unauthenticated (K10). Not locked down here — risk of breaking an existing external
scraping setup is unknown. Revisit alongside Phase 7, when network-exposure decisions are being made
anyway.

### 2.8 `contracts/permissions.yaml` stabilization — must resolve before §2.3 starts

Committed HEAD is v1.3. The working tree has an **uncommitted** v1.4 edit (adds 3 marketplace rows,
still lists the now-deleted legacy install route under `status: missing`). §2.3's gating can't
proceed correctly until (a) the v1.4 edit is committed or discarded, and (b) the phantom
deleted-route entry is removed. **This is D2 — a hard prerequisite, not a parallel task.** Gating
routes against a contract that may change out from under the work is how the work gets done twice.

### 2.9 Security docs must match reality

`docs/architecture/SECURITY.md` currently documents the partial-enforcement gap; §2.3 resolves that caveat.
Re-verify the whole doc afterward: `httpOnly` vs. localStorage refresh token, API-key SHA-256
hashing, per-client rate limiting (confirmed per-`client_ip:path` in `current-state.md` §4.6), WS
fail-closed behavior.

### 2.10 Testing strategy

- Every confirmed mutating gap gets a **permission-denied** test (401/403 without the right scope)
  and a **permission-granted** test, following the pattern established in earlier batches for the
  servers and backups modules.
- The registration decision (§2.4), whichever way it resolves, needs a test proving the resolved
  behavior — including a test that a second user cannot be created without `user:write` if the
  bootstrap-exception path is chosen.
- The route-coverage CI test (§2.5) is itself a test artifact and should be written **last**, once
  manual gating is complete, so it asserts against a genuinely complete state.

### 2.11 Acceptance criteria (phase-level)

Every mutating endpoint checked and CI-enforced; `contracts/permissions.yaml` complete and internally
consistent (single committed version, no phantom routes); `SECURITY.md` carries no
partial-enforcement caveat beyond the explicitly allow-listed public routes (login, refresh, and
whatever §2.4 decides for registration).

### 2.12 Risks

- **D2 blocking the phase's start.** Called out three times deliberately (§2.3, §2.8, here) because
  it's the most likely way the phase stalls — gating against an unsettled contract file means half
  the gating work gets redone.
- **A rushed registration decision.** §2.4's investigation should not be rushed because it's
  highest-severity; an incorrectly-designed bootstrap exception (ambiguous "first user" semantics in
  a multi-process startup) could be *worse* than the current open state, because it would look fixed
  while still exploitable in a race. The documented fallback (leave unchanged, log finding) is
  sanctioned — take it rather than ship a rushed half-fix.
- **CI route-coverage too strict or too loose.** Too strict trains developers to add exemption
  comments carelessly; too loose defeats the purpose. The 3-route public allowlist (§2.3) should be
  the literal exemption list the check reads from — not a judgment call made by whoever writes a new
  route that day.


---

<a name="mcs-manager-execution-track-phases-56-versioning-testingcidocs"></a>
# MCS Manager — Execution Track: Phases 5–6 (Versioning, Testing/CI/Docs)
*Part V — Execution Track: Phases 5–6 · source: `06-phase5-6-versioning-and-testing.md`*

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

<a name="mcs-manager-execution-track-phases-711-network-dns-stabilization-containerization-ai"></a>
# MCS Manager — Execution Track: Phases 7–11 (Network, DNS, Stabilization, Containerization, AI)
*Part V — Execution Track: Phases 7–11 and 10 · source: `07-phase7-10-network-and-ai-execution.md`*

**Part V** of the Engineering Blueprint V4. This file covers **Phase 7 (Network access / port
forwarding)**, **Phase 8 (Dynamic endpoint + DNS)**, **Phase 9 (Final stabilization)**, **Phase 11
(Containerization Migration)**, and **Phase 10 (AI features)** as the **committed execution scope**
of the roadmap. These five phases are all gated behind the foundation in Phases 1–6; none of them can
be started (beyond `🔶` *planned* status) until their declared gates close.

**A boundary that must be read before anything below:** this file covers Publish *scope commitments*
— what the roadmap is actually going to build and the hardened defaults it will enforce. Part IV
(`09`, `10`) contains the *non-committed* expanded design ideas for networking and AI. Ideas from
Part IV may inform these phases once they start, but nothing here depends on Part IV resolving
anything, and Phase 7's security posture explicitly assumes **single-instance scope** — see §1.2's
scope boundary, which is the gate that keeps Part IV's speculative multi-node ideas from leaking into
committed scope.

**Last updated:** 2026-08-07
**Supersedes:** `mcs-manager-roadmap-v4.md` Volume 8 (now historical baseline). Status indicators use
the roadmap legend: ✅ done, 🔄 in progress, 🔶 planned, ⛔ blocked, ⚠️ risk/open question. Evidence
discipline is in `04` §0 and Part I.

**Reading order note:** Phase 11 (Containerization) is numbered after Phase 9 in the roadmap's
history — it was added once Phases 1–9 were already planned — but it **executes and is read before
Phase 10 (AI)** below. Phase 10 is intentionally the last phase in both number and execution order;
Phase 11 sits immediately before it so that AI-driven operations (Phase 10) are built against the
**final** runtime model, not a process-based one that gets replaced later.

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

**Design reference:** `docs/architecture/network-access-design.md`.

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

Systematic close-out before AI: a full security review against `docs/architecture/SECURITY.md`, performance and
diagnostic passes, production upgrade verification, and resolution of remaining should-fix / optional
items. **No new capability** — harden and verify what exists.

### 3.2 Acceptance criteria

Documented end-to-end verification of the stable baseline Phase 10 builds on.

---

## 4. Phase 11 — Containerization Migration 🔶⛔

**Blocked on Phases 1–9.** Runs after final stabilization and before AI features, so Phase 10 is
built against the runtime model this phase leaves in place, not one that changes under it later.

### 4.1 Objective

Every Minecraft server the product manages runs inside a Docker container. Docker becomes the
**only** supported way to run a server — not the recommended default alongside the existing
process-based providers, but their replacement. Existing servers created under a process-based
provider are migrated to a container, not left running the old way indefinitely.

This is the **single long-term execution model for server hosting on every host platform** — Linux,
Windows/macOS via Docker Desktop, and any OS that can run Docker — not a Windows-specific add-on.
The MCS Manager panel itself may run on any host OS; all server lifecycle management
(create/start/stop/console/exec) goes through containers exclusively, never direct host execution
(tmux on Linux `providers/local.py`, PowerShell on Windows `providers/local_windows.py`). The
direct-host providers (`LocalLinuxProvider`, `LocalWindowsProvider`) are the **legacy path this
phase phases out** in favor of containers.

**Windows hosting is delivered BY this phase** — by making the container path work end-to-end —
**not by finishing `LocalWindowsProvider`**, which is dormant/dead code (no code path selects it,
its `start()` signature is incompatible with the provider interface, and it was never completed). It
is marked for **eventual removal** once this phase completes; no active development is scheduled for
it. Current environments are pre-production with disposable test servers, so no automated migration
path is required — migrating is a manual copy of `data/servers/<id>/` into a container volume if ever
needed.

### 4.2 Current reality (fact, `02` §6.1)

- `ServerProvider` is already a Strategy-pattern abstraction (`server/infrastructure/providers/`)
  with five implementations behind one interface: `LocalLinuxProvider` (`local`, tmux + process-tree
  PID resolution), `LocalWindowsProvider` (`local_windows`, PowerShell background jobs),
  `DockerProvider` (`docker`, `itzg/minecraft-server` image, `docker create/start/stop`),
  `SSHProvider` (`ssh`, remote tmux), and `CloudProvider`/`CloudProviderStub` (`cloud`, unimplemented
  stub).
- `DockerProvider` is **not new work** — it already exists, is registered in `ProviderFactory`, and
  is wrapped by the same `CircuitBreakerProviderWrapper` (5 failures, 30s cooldown) every other
  provider gets. This phase is about making it the *only* path, not building it from scratch.
- `local` (tmux-based) is the provider new servers get today unless a different one is explicitly
  chosen at creation time. This is the default this phase removes.
- Filesystem reconciliation (`FilesystemReconciliationService`, `02` §6.2) currently treats
  `data/servers/<id>/` as disk-truth for a process-based layout. A containerized server's
  world/plugin data still needs a canonical on-disk location (bind mount or named volume) that this
  same reconciliation pipeline can scan — this phase must state which, not assume it works
  unchanged.
- `RuntimeSupervisor` (`02` §6.3) health-checks via `provider.verify_process()` and does JVM PID
  resolution by walking the OS process tree. `DockerProvider` already implements `verify_process()`
  against the container's own state rather than a host PID — this phase must verify that path is as
  reliable as the tmux/PID path it replaces, not assume parity.
- `LocalWindowsProvider` is dormant, not functional: no code path ever sets
  `server.runtime.provider = "local_windows"` (default is hardcoded `"local"`,
  `app/modules/server/domain/value_objects.py` `RuntimeInfo`), its `start()` omits the
  `deployment`/`launch_config` parameters the interface declares
  (`app/modules/server/infrastructure/providers/local_windows.py:24` vs `providers/base.py:53-60`),
  and it is never finished. No OS-detection code selects it.
- `DockerProvider` (`app/modules/server/infrastructure/providers/docker.py`) is **structurally
  complete** — every `ServerProvider` method is implemented (`docker.py:24-26, 93-138, 140-147`).
  Its client is the bare `docker` CLI via subprocess (`docker.py:156-165`) with **no hardcoded
  socket path**, so it reaches Docker Desktop's Windows named pipe (Linux socket, or TCP) through
  the CLI's default transport unchanged — the Windows-transport requirement is already satisfied on
  paper.
- What is missing is **integration, not the provider primitive**: `"docker"` is not selectable
  anywhere (`ServerCreateRequest`/`ServerUpdateRequest` expose no provider field,
  `app/api/v1/schemas/server.py:10-44`; the default is `"local"`), `DockerProvider.start()` takes
  only `(server_id, config)` without `deployment`/`launch_config` (`docker.py:28`), there is no
  bind of `deployment.root_path` into the container (`docker.py:45-47` maps only an optional
  `world_dir`), and `wait_ready()` falls through to the ABC default that returns `True` immediately
  (`providers/base.py:82-88`).

### 4.3 Why this phase sits here (dependency reasoning)

- **After Phase 3 (Reliability) and Phase 4 (Security):** the crash-detection, health-check, and
  authorization work in Phases 3–4 is written and tested against the current provider behavior.
  Making Docker mandatory changes what "the runtime" means for that work; doing it before Phases 3–4
  close would mean re-verifying reliability and security twice, against two different runtime
  models, instead of once.
- **After Phase 7 (Network) and Phase 8 (DNS):** network exposure assumes a specific process/port
  model (`02` §6.1's provider table). Containerizing after Phase 7 closes means the exposure
  hardening in §1.5 is verified once, against the final runtime, not re-verified after this phase
  changes how a server's process (now container) is reached.
- **After Phase 9 (Final stabilization):** Phase 9 is a close-out pass on the *existing* system, not
  a phase that should be run against a runtime mid-migration. Running Phase 11 after it means Phase
  9's verification results describe a system this phase then deliberately changes once, cleanly —
  not a system in flux during its own stabilization pass.
- **Before Phase 10 (AI):** Phase 10's guardrails (`§5.1` below) route agent actions through the same
  permission layer and audit trail as normal API calls, regardless of runtime. But an AI agent
  reasoning about "the server" should reason about one runtime model, not a mix of containerized and
  process-based servers depending on when each was created. Closing this phase before Phase 10 starts
  means Phase 10 never has to special-case runtime type.

### 4.4 Workstreams

1. **Container image and defaults.** Formalize the `itzg/minecraft-server`-based image (or a
   maintained fork/pin of it) as the standard image for every server type currently supported by
   `select_best_version()` (`02` §3.3) — vanilla, Paper/Purpur/Spigot/Bukkit, Fabric, Forge.
   **Per-server-type awareness ships via the image's own `TYPE` environment variable rather than
   custom per-type Dockerfiles** — the image's documented `TYPE` set covers `VANILLA`, `PAPER`,
   `PURPUR`, `SPIGOT`, `BUKKIT`, `FORGE`, `FABRIC` (plus NEOFORGE/QUILT/etc.), so a single image
   with `-e TYPE=<mapped>` + `-e VERSION=<mc>` covers every `ServerType`. `DockerProvider.start()`
   must map `server_type` → `TYPE` (it currently passes only `VERSION`/`MEMORY`/`JVM_XX_OPTS`,
   `app/modules/server/infrastructure/providers/docker.py:39-43`). Caveat from the image's own docs:
   the Bukkit/Spigot download provider no longer supports automated downloads, so
   `TYPE=BUKKIT`/`TYPE=SPIGOT` may be unreliable and the docs recommend Paper — note this in operator
   messaging. Confirm version-selection logic needs no change (it selects a Minecraft/loader
   version, not a runtime).
2. **Provider selectability & default — make `docker` the only creation-time provider choice.**
   Today `provider` is not settable by any surface: `ServerCreateRequest`/`ServerUpdateRequest` have
   no provider field (`app/api/v1/schemas/server.py:10-44`) and `server.runtime.provider` defaults
   to hardcoded `"local"` (`app/modules/server/domain/value_objects.py` `RuntimeInfo`). This
   workstream adds `docker` as the default creation-time provider, removes the `local`/`local_windows`
   fallback, and ensures `CreateServerCommand` no longer selects `local`/`local_windows`/`ssh` as a
   runtime target. `SSHProvider` and `CloudProvider` are explicitly out of scope for removal by this
   phase (they solve a different problem — remote/cloud *hosts*, not local runtime type) and are
   re-evaluated separately, not silently deprecated by this workstream.
3. **One-time migration of existing servers.** A migration service, following the existing
   `migrate_old_import_arch` pattern (`02` §3.1) already used for legacy import-layout servers:
   detect servers running under `local`/`local_windows`, stop them cleanly, wrap their existing
   `data/servers/<id>/` directory as a container bind mount (no data copy, no re-download), create
   the equivalent `DockerProvider`-managed container, verify it starts and reaches the same running
   state, then flip the stored provider type. Must be resumable and safe to re-run (same idempotency
   discipline as filesystem reconciliation, `02` §6.2). **Operational note:** current environments
   are pre-production with disposable test servers, so the immediate need is satisfied by a
   low-effort manual copy of `data/servers/<id>/` into the container's volume; the automated
   migration service above is deferred until a non-disposable install exists.
4. **Volume/bind-mount mapping to `deployment.root_path` + filesystem reconciliation.** A
   containerized server's data must live under `deployment.root_path` (`data/servers/<id>/`) via a
   bind mount so it remains visible to `FileSystem` (`app/modules/server/infrastructure/fs.py`) and
   therefore to the file browser, backups, and mod/plugin/file operations. This mapping is currently
   missing entirely: `DockerProvider.start()` maps only an optional `world_dir` to `/data/world`
   (`docker.py:45-47`) and otherwise leaves data in an ephemeral/unnamed container filesystem.
   `start()` must render `deployment.root_path` into the image's `/data` mount. Then extend
   `FilesystemReconciliationService` so disk-truth scanning works unchanged for a bind-mounted
   container's world directory — the six-stage pipeline (`02` §6.2) should not need to know whether
   a directory belongs to a container or a bare process. (FileSystem ↔ volume parity is a
   **critical** item — without it, backups/file-browser/mod-install silently break for Docker-hosted
   servers.)
5. **RuntimeSupervisor parity + readiness polling.** Verify `DockerProvider.verify_process()` and
   crash detection give the same fidelity `RuntimeSupervisor` currently gets from tmux/PID-tree
   resolution — same `STARTUP_TIMEOUT` / `RUNTIME_PROCESS_LOST` failure codes, same diagnostics
   quality. Also implement real readiness: `DockerProvider` does not override `wait_ready()` and
   inherits the ABC default that returns `True` immediately (`app/modules/server/infrastructure/providers/base.py:82-88`),
   so the supervisor would skip the `"Done ("` readiness signal `LocalLinuxProvider` polls
   (`providers/local.py:486-538`); the Docker path needs equivalent polling (container healthcheck
   or log scanning). If parity doesn't hold, that's a blocking finding for this phase, not a
   follow-up.
6. **Resource limits.** Container-level CPU/memory limits (`docker create --memory`, `--cpus`) as
   the enforcement point for the memory bounds already in the `Server` aggregate's value objects —
   `MemoryAllocation` (`app/modules/server/domain/value_objects.py`) — so `min_mb`/`max_mb` render
   into container limits. Today only JVM `-Xms/-Xmx` env flags are passed (`docker.py:39-43`); no
   container-level `--memory`/`--cpus` is set. This replaces whatever host-level enforcement (or
   lack of it) the process-based providers relied on.
7. **Documentation and operator messaging.** `docs/DEVELOPMENT.md` / install docs updated to state
   Docker as a hard prerequisite, not an option; the cross-platform execution model (panel on any
   host OS, servers always in containers) documented; migration behavior documented for anyone
   upgrading from a pre-Phase-11 install.
8. **`start()` signature parity with the provider interface.** `DockerProvider.start()` must accept
   `deployment: ServerDeployment | None` and `launch_config: LaunchConfiguration | None` exactly as
   the interface declares (`app/modules/server/infrastructure/providers/base.py:53-60`) and the live
   start flow passes (`app/modules/server/application/commands/start_server.py` →
   `provider.start(...)`); it currently takes only `(server_id, config)`
   (`app/modules/server/infrastructure/providers/docker.py:28`), which the existing call path would
   reject with `TypeError` and which blocks reading `deployment.root_path`/`startup_jar` (needed by
   workstream 4).
9. **Port mapping + host-port verification.** Map the game port (`-p {port}:25565`, already present
   at `docker.py:49`) and the RCON port (the itzg image's `RCON_PORT` env) into the container. Add
   the equivalent of `LocalLinuxProvider._verify_port_free()` (`providers/local.py:51-61`) as a
   pre-create check so an occupied host port fails cleanly instead of racing. Internal panel console
   commands continue via `docker exec … rcon-cli` (`docker.py:126-134`); a *published* RCON port only
   matters for external tools. playit/cloudflared/UPnP tunnel the host's published game port — no
   app-side dynamic game-port allocator exists today, so no conflict with container port mapping.
10. **Windows host support is delivered here, not by another provider.** This phase is what unblocks
    real Windows hosting: the container client is already transport-agnostic (bare `docker` CLI with
    no hardcoded socket, `docker.py:156-165` — reaches Docker Desktop's Windows named pipe unchanged),
    so once workstreams 1–9 land, a Windows Docker Desktop host runs the same container runtime as
    Linux. **No separate Windows-native provider work should be scheduled**; `LocalWindowsProvider`
    is marked for **eventual removal** (with `LocalLinuxProvider`) after this phase and stays out of
    active development. Windows acceptance must be exercised on a Windows host with Docker Desktop,
    not only on Linux.

### 4.5 Dependencies

Phases 1–9 (see §4.3). Requires Docker as a host prerequisite (Docker Engine on Linux; Docker
Desktop on Windows/macOS) — this phase makes that prerequisite mandatory rather than optional,
which is itself part of what needs explicit documentation and, if the project supports a
non-Docker-capable host today, a decision record (Part VIII) on how that's handled.

### 4.6 Acceptance criteria

- No code path can create a server under `local` or `local_windows`.
- Every server that existed under a process-based provider before this phase started is running
  under `DockerProvider` after it closes, verified against the running container (not the migration
  log) — same evidence discipline as every other phase (`04` §0.3).
- Filesystem reconciliation, `RuntimeSupervisor` health checks, and crash diagnostics work
  identically (same failure codes, same diagnostic quality) for containerized servers as they did for
  process-based ones.
- Resource limits are enforced at the container level and match the `Server` aggregate's configured
  bounds.
- Migration is idempotent and resumable — interrupting it mid-run and re-running produces the same
  end state, not a duplicated or half-migrated one.
- A Windows (or macOS) host running Docker Desktop — and any other Docker-capable OS — can create,
  start, stop, console, and exec a server through `DockerProvider` with the same fidelity as Linux,
  with no `LocalWindowsProvider` involvement.

### 4.7 Risks

- **Runtime-parity risk (highest):** if `DockerProvider`'s health/crash signals are less reliable
  than the tmux/PID-tree path, Phase 3's reliability guarantees regress silently unless §4.4
  workstream 5 is actually verified against real crash scenarios, not just happy-path start/stop.
- **Migration data-loss risk:** the migration must never re-download or re-copy world data — bind
  mounting the existing directory is the only acceptable mechanism; anything that duplicates or moves
  world data risks corruption or loss on interruption. Follows the same "atomic same-filesystem
  staging" discipline already established for backup restores (ADR-0012, referenced in `09` §2.1).
- **Host-prerequisite risk:** making Docker mandatory removes support for any host that cannot run
  Docker (e.g. certain restricted/shared hosting). If the target audience (Part I §1.5) includes such
  hosts today, this is a scope decision that belongs in Part VIII (D-numbered), not a silent
  consequence of this phase.
- **Scope-creep risk:** this phase is about the *local* runtime (`local`/`local_windows` →
  `docker`), not about `SSHProvider` or `CloudProvider`. Folding "also finish `CloudProviderStub`"
  into this phase's workstreams would block a well-scoped migration behind unrelated, currently
  unimplemented work (`CloudProvider.start/stop` still raise `NotImplementedError` per `02` §6.1).

---

## 5. Phase 10 — AI features 🔶⛔ (final phase, intentionally deferred)

**Blocked on all prior phases, including Phase 11.**

### 5.1 Non-negotiable guardrails (built in from the start, already decided)

1. Agent actions route through the **exact same permission layer** as normal API calls — no
   privileged bypass path.
2. **Explicit user confirmation** before any destructive action.
3. **Full audit trail** of every agent-issued command, attributable to the invoking user.
4. **Pipeline:** natural-language request → structured plan → execution, with CLI, API, GUI, and
   Agent all calling the same internal services.

### 5.2 Status

Tracked, **not scheduled with a start date**. Part IV §10.5 (in `10-vision-networking-and-ai-architecture.md`)
holds the expanded AI-Layer design brainstorm. The relationship is one-directional: ideas from Part
IV can inform Phase 10's eventual design once it starts, but this phase's guardrails above are
already decided and do not wait on Part IV resolving anything.


---

<a name="mcs-manager-dependency-graph-milestones-risk-register"></a>
# MCS Manager — Dependency Graph, Milestones & Risk Register
*Parts VI–VII — Dependency Graph, Milestones & Risk Register · source: `08-dependency-graph-milestones-risk-register.md`*

**Parts VI (Dependency Graph & Milestones) and VII (Risk Register)** of the Engineering Blueprint V4.
This is a reference file that consolidates what the phase files (`04`–`07`) state individually: how
the phases depend on each other, what a milestone means and when each closes, and every known risk /
open question in one place.

**Last updated:** 2026-08-07
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
Phases 1–9               → Phase 11 (containerization)   [hard gate]
Phases 1–9, 11            → Phase 10 (AI)        [blocked on everything, incl. 11]
Phase 3 (K9 DB-at-head)  → Phase 5 (versioning, soft, Alembic sub-stream only)
Phase 4 (backend CI)     → Phase 6 (extend CI, re-verification)
```

### 1.2 The three hard gates that matter most

1. **Phase 3 → Phase 4.** Route gating (Phase 4) requires the corrected singular permission
   namespace that Phase 3 fixes as part of K1. Framed as a hard gate because gating against a wrong
   namespace means redoing the gating work.
2. **Phases 1–6 → Phase 7.** Network exposure must not start while authorization gaps (Phase 4) and
   reliability gaps (Phase 3) are open — a contained internal risk becomes an externally exploitable
   one. This gate is what keeps Part IV's speculative scope from leaking into committed scope.
3. **Phases 1–9 → Phase 11 → Phase 10.** Containerization (Phase 11) must close after Phases 3, 4,
   and 7–9 so the reliability, security, and network-exposure guarantees those phases establish are
   verified once against the final runtime, not re-verified after the runtime changes underneath
   them. Phase 10 (AI) then inherits a single, final runtime model instead of having to reason about
   a mid-migration mix of containerized and process-based servers (`07` §4.3).

### 1.3 Track view (reading aid, from `04` §0.5)

| Track | Phases | Note |
|---|---|---|
| Product/UI | 1, 2 | Sequential — Phase 2 depends on Phase 1's nav baseline |
| Reliability | 3 | Gates Phase 4 |
| Security | 4 | Gates Phase 7 |
| Platform hygiene | 5, 6 | Partially parallel to 3/4 where scope is disjoint |
| Network | 7, 8 | Sequential, both blocked on 1–6 |
| Close-out | 9 | Blocked on 1–8 |
| Runtime migration | 11 | Blocked on 1–9; gates Phase 10 |
| AI | 10 | Blocked on everything, including Phase 11 |

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
| M11 — Every server containerized | 11 | No `local`/`local_windows` creation path remains; all pre-existing servers migrated and verified running under `DockerProvider`; reconciliation/health/crash parity confirmed; cross-platform hosting verified on a Windows (Docker Desktop) host |
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
| R13 | `DockerProvider` health/crash signals less reliable than tmux/PID-tree path, silently regressing Phase 3's reliability guarantees | 11 | Must verify parity against real crash scenarios, not just happy-path start/stop (`07` §4.7) |
| R14 | Migration re-copies or moves world data instead of bind-mounting it, risking corruption/loss on interruption | 11 | Bind-mount only; same atomic-staging discipline as backup restores (ADR-0012) |
| R15 | Mandatory Docker silently drops support for hosts that can't run it | 11 | Scope decision belongs in Part VIII (D-numbered), not a silent side effect |
| R16 | `CloudProviderStub` completion scope-creeps into Phase 11 | 11 | Explicitly out of scope; Phase 11 covers `local`/`local_windows` → `docker` only |

### 3.3 Known issues (K) and open decisions (D) pointers

Not duplicated here — the K- and D- registers are the authoritative lists. K-items are distributed
throughout the phase files where they land (K1–K6, K8–K15 live across `04`–`05`); the D-register
(D1–D13) is **Part VIII** in `11-decision-records.md`. See the file map in `00` §3 for where each
lives.


---

<a name="mcs-manager-vision-runtime-core-storage-observability"></a>
# MCS Manager — Vision: Runtime Core, Storage, Observability
*Part IV — Vision: Runtime Core, Storage, Observability · source: `09-vision-runtime-storage-observability.md`*

**Part IV** of the Engineering Blueprint V4 — the non-committed dump of **expanded** subsystem
designs around runtime core, storage architecture, and observability.

> **READ THIS LABEL FIRST.** This entire file is **NOT COMMITTED**. It is design vision that
> *informs* later work; it is **not** a decision, not an architecture, and not scheduled. Nothing here
> overrides a phase's committed acceptance criteria (Part V, `04`–`07`), and nothing here may be
> treated as "the plan" by a contributor or agent. Where a committed phase and this file disagree on
> *scope* (not on facts), the phase file wins. This is the same discipline that the prior roadmap
> applied to its own "Volume 9: Future Direction" — made more explicit here because full designs are
> easy to mistake for decisions if the label is not repeated.
>
> **Grounded, not invented:** the *facts* referenced here (module boundaries, the runtime
> reconciliation pipeline, providers, event-store/DLQ, storage backends, monitoring rollups) are
> verified from `docs/architecture/ARCHITECTURE.md`, `docs/runtime/*`, `docs/architecture/DATABASE.md`, and the source. The
> *direction* — what to harden or build next on top of them — is new analysis and is labeled as such
> (§0.1).

**Last updated:** 2026-08-06

---

## 0. Grounding and reading rules

### 0.1 What is fact vs. new

| Kind | Content | Authority |
|---|---|---|
| Fact (verified) | Runtime supervision, providers, reconciliation, orphan-cleanup ownership, event-store/DLQ, four-tier rollups, backup/aes-gcm | `docs/runtime/*`, `docs/architecture/ARCHITECTURE.md`, `docs/architecture/DATABASE.md` |
| New (labeled) | Every "direction" / "the system could…" / "a future design…(designed as…)" statement | This file's own analysis |

The `="…"` label and the words "designed as", "could", "candidate", "direction" mark non-committed
ideas. A paragraph without such a marker restates a verified fact.

### 0.2 How these designs relate to committed scope

Part IV exists so a future reader (human or agent) can see the full shape something *could* take
without mistaking it for the committed shape. When a committed phase (e.g. Phase 10 AI) reaches the
point of needing one of these designs, the reader consults this file as input — never as the
decision.

---

## 1. Runtime core (vision)

### 1.1 What exists today (fact)

- A **runtime core** supervising server processes: lifecycle (start/stop/restart), crash
  escalation with a configurable limit (3 crashes / 300 s) and a `RuntimeSupervisor`, plus a
  **reconciliation pipeline** that repairs DB ↔ OS state mismatches for tracked servers and rejects
  orphaned/stale OS resources, verifying a process *belongs* to the managed set before acting
  (`docs/runtime/reconciliation.md`, ADR-0011). Ownership is verified via the `MCS_MANAGED=1` env
  marker or cwd inside `MCS_SERVERS_DATA_DIR`; `project_owned` is the safe default scope.
- **Providers** abstract process/OS interactions so the runtime is portable across hosts, and are
  replaceable / configurable.
- A **task queue** supports in-process execution today (the `InProcessQueue`); an Arq-backed
  implementation is defined but unused — no Redis is deployed.

### 1.2 Design directions (all `[new]`)

- **Provider matrix for host/OS abstraction.** Stand up a matrix mapping host type (bare-metal,
  container, and — only if the scope boundary in `07` §1.2 is ever deliberately crossed — cloud) to
  the supervision, files, and networking providers, so the runtime doesn't hardcode one host's
  assumptions. *Designed as:* each provider stays small and correct (§ `01` §5); host-specific
  behavior does not leak into domain logic.
- **Runtime state as a reconcilable ledger.** Model desired-vs-actual per server (desired state in
  repo, actual on the host), and make reconciliation idempotent and self-healing rather than an
  error-and-return. The reconciliation window is a property the UI must honestly show.
- **Graceful handoff between event-bus publishing and runtime actions.** When the event-store / DLQ
  and the runtime change the same server, a clearly-owned boundary prevents double-drive.

---

## 2. Storage architecture (vision)

### 2.1 What exists today (fact)

- Database is SQLite (embedded) / optional Postgres behind Alembic (16 revisions).
- **Backups/restores are the lineage** — AES-256-GCM encryption at rest, verified restores, produced
  on schedule (cron-backed) with optional storage transfer. The product treats backup continuity as
  a hard property.
- `storage` module provides backend abstraction (local disk / S3-style) for backup and file
  transfer; server content lives on the filesystem (see `02` storage /fs design).
- **Atomic same-filesystem staging** (ADR-0012) for swaps that touch live data — never OS default
  `/tmp`.
- Server/plugin existence lives in DB tables that are **caches** of the filesystem source of truth,
  reconciled one-direction (Part I §2.3).

### 2.2 Design directions (all `[new]`)

- **Backup policy vs. backup engine separation.** A policy layer (what to back up, when, retention)
  separate from the engine (how to snapshot / restore) so scheduled backups and manual restores and
  emergency recovery share one implementation. Retention could be enforced on the policy layer.
- **Snapshot consistency scripting.** For Minecraft, a correct backup requires flushing the world
  state to disk. The save-all + completion-regex guarantee (K14) is the live-mission checkpoint, and
  the storage design should make the flush a named step in the restore story, not an incidental.
- **Cold + hot storage tiering for archives** with the four-tier rollup model (ADR-0006) extended
  to backup/manifests. A "dirty" (retained forever) vs "rotated" (bounded) split for backup retention
  so the DB and backing store don't grow without bound.

---

## 4. Observability (vision)

### 4.1 What exists today (fact)

- **Prometheus metrics** on a public `/metrics` endpoint (K10 — deliberately deferred to Phase 7).
- **health module**: health evaluation, crash diagnostics, integrity validation (complete
  domain/application/infra stack, added post-Batch-10).
- **event_store**: append-only log with a cryptographic chain and dead-letter handling.
- **audit chain**: SHA-256 hash chain over audit rows; four-tier metrics rollup tables for
  monitoring (ADR-0006).
- Alert rules live in the `monitoring` module; `alerts`/`schedules` routes are currently stubs
  (K13 in the current state).

### 4.2 Design directions (all `[new]`)

- **Tunneling the `/metrics` decision in Phase 7** rather than keeping scrape public — the decision
  is deferred deliberately (Phase 4 §2.7 / `07` §1.5); observability should support that decision
  when it lands.
- **Using the event-store chain as an observability spine** — health/metadata events and state
  summaries emitted as typed events to a unified stream that consumers (the WS live-push layer,
  monitoring, crash diagnostics) each read from, rather than each polling the DB.
- **Operator-facing single pane.** Surface reconcile-window age, DB-schema drift (vs `alembic head`),
  provider health, and retry/DLQ backlog in one `health`/`status` view so the operator answers "does
  this inventory match reality right now?" without archaeology (Part I, `00` §1.4 goal #1).

---

## 5. Cross-cutting notes

- These three themes share one spine: **state, and honest visibility into it** (Part I, `00` §1.4
  goal #1: legible state). Runtime/storage/observability all surface "what is actually true right
  now" — the same question Part V's phases force the roadmap to answer about itself.
- The boundary to the committed roadmap: none of the directions above is scheduled. Runtime core
  stabilization is partly in Phase 3 (K1/K2, DB-at-head); storage hardening is implicit in Phase 3
  (K14) and Phase 9; observability meets the committed /metrics decision at Phase 7. Everything else is vision.


---

<a name="mcs-manager-vision-networking-ai-architecture"></a>
# MCS Manager — Vision: Networking & AI Architecture
*Part IV — Vision: Networking & AI Architecture · source: `10-vision-networking-and-ai-architecture.md`*

**Part IV** of the Engineering Blueprint V4 — the non-committed dump of **expanded** design material
around networking (tunnels / DNS / exposure) and the AI subsystem, plus migration strategy.

> **READ THE LABEL FIRST, SAME AS `09`.** This file is **NOT COMMITTED**. It is design vision that
> *informs* later work; it is **not** a decision, not architecture, and not scheduled. The committed
> execution scope for Phases 7–11 lives in `07` and its hard guardrails are **already decided**
> (§5.1 there); this file expands on the *shape* those phases could take, strictly as input.
> Where this file and `07` disagree on scope, `07` wins.

**Last updated:** 2026-08-07
**Grounded, not invented:** the networking principles here are carried from the committed design
reference `docs/architecture/network-access-design.md` (which Phase 7 builds on). The AI subsystem is grounded in
`07`'s non-negotiable guardrails and the product vision in `00` §1.2. The *expansion* beyond what is
committed is new and labeled.

---

## 0. Grounding

| Kind | Content | Authority |
|---|---|---|
| Fact (committed) | Phase 7 scope, two user modes, 7 architectural boundaries, hardened defaults; Phase 8 endpoint/DNS flow | `07` §1–2; `docs/architecture/network-access-design.md` |
| Fact (committed) | Phase 10 guardrails (same permission layer, confirmation, audit, unified pipeline) | `07` §5.1 |
| New (labeled) | Provider-evaluation criteria, multi-deployment topology, AI-layer refinements, migration strategy | This file |

---

## 1. Networking design expansion

### 1.1 The four axes (fact, from `docs/architecture/network-access-design.md`)

Tunnel, DNS, exposure, authentication are **four independent axes**, deliberately separated. A common
failure is treating them as one "remote access" feature; the committed design separates them.

### 1.2 Provider selection criteria (new, `[new]`)

Phase 7 requires simultaneous `TunnelProvider` and `DnsProvider` interfaces (see `docs/architecture/network-access-design.md` §3.1
— `start()/stop()` and `ensure_record()`/`delete_record()`). The terms the system must judge:

- **Stability & official-API support** only — never browser automation or scraping (committed
  boundary 7, `07` §1.4).
- **Dynamic endpoint reporting** — can the provider hand back an endpoint the system itself didn't
  configure (the `endpoint_url` field)? (committed boundary 2).
- **No preselection** — evaluation + rationale recorded before wiring; switching must not change app
  code (committed boundary 6).

### 1.3 Exposure matrix (fact, from `docs/architecture/network-access-design.md`)

| Axis | What's exposed | Auth model |
|------|----------------|------------|
| **Game exposure** | Minecraft server port (`25565`), so friends can join | No transport-level auth — game handles identity internally; opening exposes the game to the public |
| **Management exposure** | The web UI/API, so *you* can administer remotely | Always the full auth stack (login, permissions, audit, rate limits) |

Must be **two independent toggles**, separate tunnels, separate endpoints, separate security
defaults — never gated together, never presented as one decision (committed boundary 3).

### 1.4 Tunnel ≠ Authentication (fact, `docs/architecture/network-access-design.md` §2.1)

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

### 2.1 Committed guardrails (fact, `07` §5.1 — do not weaken)

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

Phase 10 remains **future and unscheduled** (`07` §5.2). None of the above changes that; it is the
*shape* the eventual design may take, gated on `07`'s guardrails.

---

## 3. Migration strategy (new, `[new]`)

**Not to be confused with Phase 11 (Containerization Migration, `07` §4)** — that phase is
committed, scheduled, and about *how each server's runtime is hosted* (process vs. container) on a
single instance. This section is the opposite in every load-bearing way: non-committed, unscheduled,
and about whether the *product itself* (the modular monolith) should ever be split across multiple
nodes.

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

<a name="mcs-manager-decision-records-d1d13"></a>
# MCS Manager — Decision Records (D1–D13)
*Part VIII — Decision Records (D1–D13) · source: `11-decision-records.md`*

**Part VIII** of the Engineering Blueprint V4. This is the **decision log**: every open decision that
is *not yet* an ADR (the committed decisions live in `docs/decisions/`, ADRs 0001–0012). Each entry
records what the decision is, where it lives, why it's open, and what resolving it depends on — in
ADR-format shape (Context / Options / Path / Consequences), but marked **Open** until decided.

**Last updated:** 2026-08-06

> **Gap disclosure (carried from the V4 source-material note in `00` §0):** the prior V4 roadmap
> referenced a "Volume 10 — Decision Log (D1–D13)" that was not present in the surviving text.
> D1–D6, D9, and D11–D13 are reconstructed **from their references** throughout the surviving
> volumes — each entry below cites the exact text that proves the decision's content. **D7, D8, and
> D10 are never mentioned anywhere in the surviving volumes** and could not be reconstructed at all.
> They are logged below as **open gaps**, not invented. If a future session finds the original
> Volume 10, these three entries should be filled from it and this paragraph removed.

---

## How to use this log

- **A decision is open until** a resolution is recorded here and, where appropriate, a code change +
  test land (Part III §6 ADR process, Part I §9 preservation).
- **Deferred decisions are tracked, not forgotten** — a decision deferred (as several are) stays
  here until resolved.
- **Resolving a decision here** does not delete it; it is marked **Resolved** with the outcome, per
  append-only canon.

---

## 1. D1 — Sensitive GET-route classification 🔶 Open

**Context (from `05` §2.3, carried from v3, live-verified 2026-08-05):** the count of sensitive
`GET` routes that are auth-only but carry no permission check is disputed — "23" by a strict
middleware count vs. an earlier "21" using a different classification.

**Why open:** Phase 4's GET-route gating work can't start correctly until the classification is
settled; gating the wrong set wastes effort either way. Resolution of D1 must precede workstream
"gate the reconciled GET set" (`05` §2.3 step 4).

**Options:** (a) adopt the strict middleware count as canonical; (b) re-derive a single
classification rule; (c) record the discrepancy as a doc fix and gate against the reconciled rule.

**Owner:** Phase 4 (§2.3).

---

## 2. D2 — `contracts/permissions.yaml` version 🔶 Open — hard prerequisite for Phase 4

**Context (from `05` §2.8, carried):** committed HEAD is v1.3; the working tree has an
**uncommitted** v1.4 edit (adds 3 marketplace rows, still lists the now-deleted legacy install route
under `status: missing`).

**Why it's load-bearing:** §2.3's route-gating work can't proceed until (a) the v1.4 edit is
committed or discarded, and (b) the phantom deleted-route entry is removed. Gating against a contract
that may change out from under the work means doing the gating twice.

**Options:** (a) commit v1.4 as-is and remove the phantom entry; (b) discard the uncommitted edit and
regenerate; (c) version-bump discipline going forward (link to Phase 5 versioning rule).

**Owner:** Phase 4, first item in its sequencing (`05` §2.3 step 1, §2.8).

---

## 3. D3 — Pending working-tree diffs against a "done" phase 🔶 Open

**Context (from `04` §1.2, carried from v3 §2, unresolved):** two tracked, committed files carry
uncommitted changes: `backend/app/api/v1/routers/plugins.py` (8 commits, latest `b1b6dd8`) and
`backend/tests/api/test_api_endpoints.py` (9 commits, latest `b1b6dd8`). Pending diff: a
`_to_version_response()` helper and one new test `test_marketplace_versions_returns_files` (+54).

**Why it matters:** an open working-tree diff against a "done" phase (Phase 1) is a
documentation-vs-code mismatch waiting to happen — the exact class of error this blueprint's rewrite
exists to avoid.

**Options:** (a) commit the diff as its own commit per ADR-0010 discipline before Phase 1 closes
(recommended, per `04` §2.6); (b) discard; (c) fold into a Phase 1.5 verification pass.

**Owner:** Phase 1 close-out (`04` §2.6).

---

## 4. D4 — Marketplace route namespace 🔶 Open

**Context (from `04` §2.3, carried):** whether marketplace API routes stay under
`/servers/{id}/plugins/marketplace/*` or move to a marketplace-owned namespace.

**Why it matters now:** a route-namespace decision is required for a clean Phase 1 → Phase 2 handoff;
building new marketplace-adjacent frontend work against a namespace that might move means rework.
K5 (2026-08-06) already introduced a global search endpoint (`GET /marketplace/search`) distinct from
the server-scoped one, sharpening the question.

**Options:** (a) keep routes server-scoped, add global ones where semantics are global; (b) move to a
marketplace-owned namespace and shim compatibility; (c) document a single naming rule.

**Risk:** namespace churn is a breaking change needing a compatibility shim if resolved late (`04`
§2.8).

**Owner:** Phase 1 close-out (`04` §2.6).

---

## 5. D5 — Test re-baselining vs. real bug 🔶 Open

**Context (from `05` §1.5, carried):** 2 failing backend tests (per `current-state.md`, 2026-08-04,
not re-run since): `test_start_server` (closed-DB rollback in API teardown) and
`test_metrics_task_requires_collector` (stale expectation vs. graceful warning handler).

**Why open:** the decision is *which* of the two paths applies to *which* test — fix the underlying
defect vs. formally re-baseline a stale assertion. Guidance in `05` §1.5/§1.10: investigate
`test_start_server`'s teardown first; default to "assume real bug until proven stale" for
`test_metrics_task_requires_collector`.

**Options:** (a) fix both; (b) fix one + re-baseline the other; (c) re-baseline both (risky — could
hide a real defect).

**Owner:** Phase 3, K8 (`05` §1.5). **Resolution required for the "0 failures" acceptance criterion.**

---

## 6. D6 — Settings persisted field set 🔶 Open

**Context (from `05` §1.4, carried):** `PATCH /api/v1/settings` is a stub (`{"success": true,
"message": "Settings updated (stub)"}`) — nothing persists. The decision is the persisted field set:
start with what `GET /settings` already returns.

**Options:** (a) persist exactly the `GET /settings` field set; (b) a curated subset; (c) schema-driven
(generalize). Coupled with Phase 3's `settings:write` gate and Phase 2's "zero silently-no-op
controls" rule (`04` §3.6).

**Owner:** Phase 3, K3 (`05` §1.4).

---

## 7. D7 — [GAP] 🔶 Open — unverifiable from surviving sources

**Status:** This decision number is never mentioned in any surviving V4 volume. It could not be
reconstructed and is **not invented** here. See the gap disclosure at the top of this file.

---

## 8. D8 — [GAP] 🔶 Open — unverifiable from surviving sources

**Status:** Same as D7.

---

## 9. D9 — 2FA in publish mode 🔶 Open

**Context (from `07` §1.5, carried):** Phase 7 hardened defaults include "optional-but-strongly-prompted
2FA (**D9, open**)" alongside shorter access-token lifetimes and mandatory HTTPS.

**Why open:** TOTP (or another standard) needs a decision before Phase 7's publish-mode UX is built;
it affects the auth module (ADR-0005) and the login flow.

**Options:** (a) TOTP via a standard library; (b) WebAuthn/passkeys; (c) defer 2FA entirely and keep
it out of Phase 7 exit criteria (would need re-flagging in `07`).

**Owner:** Phase 7 (`07` §1.5).

---

## 10. D10 — [GAP] 🔶 Open — unverifiable from surviving sources

**Status:** Same as D7/D8.

---

## 11. D11 — Repo-root `data/` cleanup 🔶 Open

**Context (from `05` §1.6, carried):** Phase 3 should-fix K15: clean up the repo-root `data/`
directory — **confirm unused first**.

**Options:** (a) confirm unused and remove; (b) keep but document as legacy; (c) migrate its contents
into the configured `MCS_SERVERS_DATA_DIR` layout.

**Risk:** deleting live data the operator cares about. The "confirm unused first" step is the
decision's guard.

**Owner:** Phase 3, K15 (`05` §1.6).

---

## 12. D12 — DB upgrade policy: auto-upgrade vs. refuse-to-start 🔶 Open

**Context (from `05` §1.6, carried):** production DB is 3 Alembic revisions behind head (K9). The
decision is the standing policy: on startup, if the DB is behind the required revision, **auto-upgrade
on boot** or **refuse to start**. `05` §1.6 states D12 "should be resolved as part of this item, not
left dangling after the migration runs." Phase 5's per-release minimum-revision rule depends on it
(`06` §1.3 #3).

**Options:** (a) auto-upgrade with a logged decision; (b) refuse-to-start until operator acts; (c)
hybrid (auto-upgrade for patch-level, refuse for major).

**Owner:** Phase 3, K9 → Phase 5 (`05` §1.6, `06` §1.3).

---

## 13. D13 — Registration bootstrap (`POST /api/v1/users`) 🔶 Open — highest real-world risk item

**Context (from `05` §2.4, carried):** registration is open with no auth. The decision procedure
(carried, unchanged): investigate whether a **first-user-bootstrap exception** is safe and simple
(open only while zero users exist, then require `user:write`). If the investigation surfaces hidden
onboarding dependencies or ambiguous "first user" semantics, do **not** improvise — document the
finding in `docs/PERMISSIONS_FUTURE_IDEAS.md` and leave the route unchanged. **Not yet
investigated.**

**Why it can't just be deferred:** an unauthenticated user-creation endpoint on a system about to
gain network exposure in Phase 7 is a direct path to full account takeover if left unresolved; it is
an active, growing risk, not a neutral "known limitation." Recommended to be investigated *first*
within Phase 4's sequencing.

**Options:** (a) first-user-bootstrap exception (open only while zero users exist); (b) leave
unchanged + document; (c) registration invite/secret token.

**Guardrail:** the documented fallback (leave unchanged, log finding) is explicitly sanctioned — take
it rather than ship a rushed half-fix (`05` §2.12).

**Owner:** Phase 4, §2.4 — must be resolved before Phase 7.

---

## 14. Resolution log

This section is append-only. As decisions resolve, add a dated entry marking the decision **Resolved**
with the outcome, the code change that implemented it (if any), and the test that proves it.

| Decision | Status | Resolution | Date |
|---|---|---|---|
| — | — | (none yet — all D1–D13 currently open) | — |


---

<a name="mcs-manager-working-agreements-contribution-workflow"></a>
# MCS Manager — Working Agreements (Contribution Workflow)
*Part IX — Working Agreements · source: `12-working-agreements.md`*

**Part IX** of the Engineering Blueprint V4. The collaborative rules that govern *how* code and
documentation get built in this repository — contribution workflow, commit strategy, and
AI-collaboration rules. This file is the human- and agent-readable codification of the same rules
that `.ai/AI_RULES.md`, `AGENTS.md`, and ADR-0010 already state in operational form; the blueprint
places them in one place, labeled as the *agreement* they are.

**Last updated:** 2026-08-07
**Supersedes:** the "Volume 11: Working Agreements" section of the prior V4 roadmap (referenced but
not present in surviving text — this file is written fresh from the rules that *are* present and
active in the repository today).

---

## 1. Contribution workflow

### 1.1 The plan governs

Work is sequenced by **roadmap phase**, not by request convenience (`.ai/AI_RULES.md` — Governing
Plan). A request that does not help close the current phase's exit criteria belongs in a later
phase's backlog, not in current work. Phase gating is enforced: nothing in Phase 2+ starts until
Phase 1's exit criteria are met, and so on (`04`–`07`).

### 1.2 Bootstrap before work

Before any work begins, the entry-point files are read in order (`AGENTS.md`): `.ai/AI_RULES.md`,
`.ai/TOKEN_POLICY.md`, `.ai/CURRENT_STATE.json`, `.ai/PROJECT_STATE.json`. Then task-specific files
only. Reading discipline is context-budget-driven (`.ai/TOKEN_POLICY.md`): read only what the task
requires, use targeted reads, and never load entire files on speculation.

### 1.3 Ask when uncertain

If the task, the files to modify, commit policy, testing requirements, or scope boundaries are
unclear — **stop and ask the user.** Do not guess. This is an explicit agreement, not a preference
(`.ai/AI_RULES.md` — Decision Uncertainty; `AGENTS.md` Step 3).

### 1.4 Evidence before assertion

Nothing is stated as fact without evidence: source code, repository state, git history, docs, test
results, or user-provided information. If evidence is insufficient, say "insufficient evidence" —
never guess (`.ai/AI_RULES.md` — Evidence Rule; Part I §1).

---

## 2. Commit strategy

### 2.1 Default: do not commit

By default **DO NOT COMMIT** (`.ai/AI_RULES.md` — Commit Policy). A commit happens only if the user
explicitly requests it, or the task/repository workflow requires it. Otherwise: prepare the commit
message, show what would be committed, and **wait for confirmation**. Editing files is not permission
to commit.

### 2.2 Commit-per-step discipline

Every commit represents exactly **one logical change** (ADR-0010). Each commit must be immediately
verifiable (tests pass, app boots); no bundling of unrelated changes; the message explains *what, why,
and how verified*. Never `git add .` unless explicitly requested — stage only relevant files.

### 2.3 What that means during phases

- A structural/organizational/bug-fix change is one commit per step (ADR-0010).
- Unrelated files are never included even if trivially fixable (`.ai/AI_RULES.md` — Scope Control).
- An open working-tree diff against a "done" phase is a defect in the close-out, not a norm (see D3,
  `11` §3).

---

## 3. Quality and self-review

### 3.1 Self-review before continuing

Every modification is reviewed before moving on: logic, edge cases, consistency, readability, dead
code, duplicate code, imports, naming. Fix your own mistakes before proceeding
(`.ai/AI_RULES.md` — Self Review).

### 3.2 Test selection

Tests are chosen as the **minimum required verification** for the change class
(`.ai/AI_RULES.md` — Test Selection): docs-only → none; config → affected validation; code → relevant
tests; behavior → regression; architecture → affected suites. Do **not** run unrelated tests.

### 3.3 Regression protection

Every fixed bug receives a regression test. If no code changed, regression tests are not required
(`.ai/AI_RULES.md` — Regression Tests). This is the operational form of the quality gate's
"verification, not declaration" rule (Part III §4.4).

### 3.4 Documentation

Documentation is updated **only if** public behavior, API, architecture, user workflow,
configuration, a known limitation, or project status changed. Otherwise, report "no documentation
update required." Never rewrite unrelated documentation (`.ai/AI_RULES.md` — Documentation).

---

## 4. AI-collaboration rules

### 4.1 AI is a contributor, not a narrator

AI agents work under the same scope, evidence, self-review, and commit rules as any contributor.
The blueprint is not "about" AI; it is the shared contract AI operates under.

### 4.2 Rule inheritance and self-modification

- If `.ai/AI_RULES.md` is modified during a task, the new rules become active **only after the
  current task finishes**; they are never retroactively applied (Rule Inheritance).
- Editing `.ai/AI_RULES.md` (or this file) is normal repo work: not auto-committed, not auto-activated
  mid-task, and subject to the same commit policy as any other change (Self-Modifying Rules).

### 4.3 The "ask, don't assume" discipline is strongest for AI

Because AI is prone to confidently guessing, the Ask-When-Uncertain agreement (§1.3) is absolute for
agents: ambiguous tasks → present options, ask; uncertain commits → ask; uncertain file scope → ask
(`.ai/AI_RULES.md` — Ambiguity Policy, Decision Uncertainty).

### 4.4 AI and this blueprint

- An AI agent must read the blueprint's relevant Part before working in its domain (per §1.2
  bootstrap), and must not treat Part IV (non-committed vision, `09`/`10`) as committed scope.
- The re-verification discipline (Part I §1, Phase 6 `06` §2.4) means an AI agent may not claim a
  number is current without re-checking it live.
- Future AI *product* features (Phase 10) are governed by `07` §5.1's guardrails; nothing in this
  file changes those.

---

## 5. Preservation

- History is append-only (Part I §9): audit rows, event-store rows, ADRs, decision records, and
  roadmap status markers are never deleted or silently changed.
- Roadmap status markers are authoritative for phase state; a marker is not changed without updating
  `docs/status/history.md`/`current-state.md` accordingly (`.ai/AI_RULES.md` — Governing Plan).
- Historical docs (v1–v3, V4 linear volumes) are preserved and labeled as history, never silently
  deleted.
