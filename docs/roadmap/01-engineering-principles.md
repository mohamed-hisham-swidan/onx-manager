# MCS Manager — Engineering Principles

**Part I** of the Engineering Blueprint V4. Defines the engineering philosophy that governs every
architecture decision, phase ordering, and code-level practice in this document. When two principles
conflict, the one listed earlier in this file wins.

**Last updated:** 2026-08-06
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
Phase 9  Final stabilization                  — close-out before AI
Phase 10 AI                                   — deliberately last
```

### 4.2 Why network access is gated on everything

Phase 7 exposes the product to the public internet. Every authorization gap that exists before Phase
7 is a *contained* internal risk afterward — a gap that was a latent bug becomes an exploitable
vulnerability. The gate is therefore hard, not preferential: Phase 4 must be complete before Phase 7
starts. AI (Phase 10) is last for the same reason: it adds a new privileged execution path, and the
guardrails it requires (permission-gated agent actions, audit trails) presuppose a permission and
audit layer that Phases 4 and 6 actually enforce.

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

*Continue to [`02-architecture-and-domain-model.md`](./02-architecture-and-domain-model.md) for the
full architecture: module structure, the CQRS buses, runtime model, storage model, and subsystem
designs.*
