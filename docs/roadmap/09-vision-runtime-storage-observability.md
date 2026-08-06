# MCS Manager — Vision: Runtime Core, Storage, Observability

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
> verified from `docs/ARCHITECTURE.md`, `docs/runtime/*`, `docs/DATABASE.md`, and the source. The
> *direction* — what to harden or build next on top of them — is new analysis and is labeled as such
> (§0.1).

**Last updated:** 2026-08-06

---

## 0. Grounding and reading rules

### 0.1 What is fact vs. new

| Kind | Content | Authority |
|---|---|---|
| Fact (verified) | Runtime supervision, providers, reconciliation, orphan-cleanup ownership, event-store/DLQ, four-tier rollups, backup/aes-gcm | `docs/runtime/*`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md` |
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

*Read next, in reference order: `10` (networking + AI vision). The non-committed label here applies
to that file equally.*