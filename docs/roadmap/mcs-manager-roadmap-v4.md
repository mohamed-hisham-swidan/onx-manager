# MCS Manager — Engineering Roadmap V4

**Status:** Living planning document — engineering-owned
**Supersedes:** `mcs-manager-roadmap-v3.md` (2026-08-05), which remains the historical baseline this
document was built from
**Baseline sources:** `docs/STATUS.md` (batch history through Batch 10, 2026-08-03, plus later
uncommitted batch entries through 2026-08-06), `mcs-manager-roadmap-v3.md` (2026-08-05 live route
introspection), `docs/current-state.md` (2026-08-04)
**Last updated:** 2026-08-06

> **What this document is.** This is the execution roadmap: what's true right now, what's broken,
> what's next, in dependency order, with acceptance criteria per phase. It carries forward every
> open decision (D1–D13) and every K-issue from v3 without re-litigating them — v3 already did that
> work and re-verified its numbers live. Nothing here overrides a v3 number; where this document
> repeats a number, it is the same number, same citation.
>
> **What this document is not.** It is not a speculative architecture for infrastructure that
> doesn't exist yet (Kubernetes, multi-node, cloud hosting) and it is not a claim that AI feature
> work or container-orchestration decisions have been made. Those ideas exist — they're real, they
> came up in project discussion — but they are **not commitments**, not architecture, and not
> scheduled. They live in **Volume 9: Future Direction (Non-Committed)**, fenced off and labeled,
> specifically so a future reader (human or agent) doesn't mistake a brainstorm for a decision. This
> distinction is the main structural decision behind this document, driven directly by where the
> project actually stands: a production system with 0 servers deployed, 9 unauthenticated mutating
> routes, and 13 open decisions — not a system ready for Kubernetes-provider design.

---

## Table of Contents

- [Volume 0 — How to Read This Document](#volume-0)
- [Volume 1 — Current Reality (Phase 0)](#volume-1)
- [Volume 2 — Phase 1: Plugins / Marketplace Separation](#volume-2)
- [Volume 3 — Phase 2: Product Foundation & UI Stabilization](#volume-3)
- [Volume 4 — Phase 3: Backend/Frontend Reliability](#volume-4)
- [Volume 5 — Phase 4: Authorization / Security Cleanup](#volume-5)
- [Volume 6 — Phase 5: Versioning & State Consistency](#volume-6)
- [Volume 7 — Phase 6: Testing / CI / Documentation Reliability](#volume-7)
- [Volume 8 — Phases 7–10: Network, DNS, Stabilization, AI](#volume-8)
- [Volume 9 — Future Direction (Non-Committed Ideas)](#volume-9)
- [Volume 10 — Decision Log (D1–D13 + new)](#volume-10)
- [Volume 11 — Working Agreements (Agent/Dev Rules)](#volume-11)
- [Sources](#sources)

---

<a name="volume-0"></a>
## Volume 0 — How to Read This Document

### 0.1 Status legend (carried from v3, unchanged)

| Symbol | Meaning |
|--------|---------|
| ✅ | Done — verified, with citation |
| 🔄 | In progress — active now |
| 🔶 | Planned — not started |
| ⛔ | Blocked — gated on an earlier phase |
| ⚠️ | Risk, open question, or unresolved doc/code mismatch |

### 0.2 Bug classification (carried from v3, unchanged)

| Class | Meaning |
|-------|---------|
| Must fix | Blocks a phase exit criterion or a security/availability claim |
| Should fix | Real defect; can be deferred within a phase, but must stay scheduled |
| Optional | Quality-of-life; can be dropped with a documented reason |
| Known limitation | Accepted behavior, documented, not scheduled |
| Doc-only | Documentation correction, no code change |
| Future work | Tracked in a later phase's backlog, not current scope |

### 0.3 Evidence discipline

Every count or claim in Volumes 1–8 is either:
1. **Carried** from `mcs-manager-roadmap-v3.md` §2 or §6.1 (live-verified 2026-08-05) — marked
   "carried from v3," not re-verified here, and not to be treated as re-checked just because it
   appears in a newer document.
2. **Carried** from `docs/STATUS.md` batch history — marked with batch number and date.
3. **New** to this document — marked with what needs to happen to verify it (nothing in this
   revision claims a fresh live check that wasn't actually run).

This mirrors the discipline v3 itself introduced after v2 went stale within 24 hours (v3 §0). The
lesson holds here too: this document will drift the moment code moves. Re-verification cadence is
itself a Phase 6 deliverable (§7.4 below), not assumed to happen automatically.

### 0.4 Governing product direction (carried from v3, unchanged)

- **Foundation before capability.** Coherent product structure and reliability come before
  advanced features.
- **Plugins ≠ Marketplace.** Plugins = installed plugins on a selected server. Marketplace =
  global catalog/discovery. Distinct surfaces.
- **Network access is gated on stability.** Tunnel/port-forwarding work doesn't start until
  product, authorization, versioning, and CI are reliable.
- **AI is the final phase**, intentionally deferred.
- **New in V4: Speculative infrastructure is not roadmap.** Ideas without a committed decision
  (container orchestration beyond Docker, multi-node, cloud) are tracked separately in Volume 9 and
  never merged into the phase plan until they clear the decision log in Volume 10.

### 0.5 Track view (informational only — phases remain the unit of execution)

V3 sequences work strictly by phase number and dependency. That's preserved here — **phases are
still the unit of execution, not tracks.** But it's useful to see which phases share a concern,
because two phases in the same track can sometimes be worked by different people without
collision, even though neither can *close out* before its declared dependency does.

| Track | Phases | Note |
|---|---|---|
| Product/UI | 1, 2 | Sequential — Phase 2 depends on Phase 1's nav baseline |
| Reliability | 3 | Gates Phase 4 |
| Security | 4 | Gates Phase 7 |
| Platform hygiene | 5, 6 | Can run partially parallel to 3/4 where scope doesn't overlap |
| Network | 7, 8 | Sequential, both blocked on 1–6 |
| Close-out | 9 | Blocked on 1–8 |
| AI | 10 | Blocked on everything |

This table is a reading aid. It does not change any acceptance criterion or dependency stated in
Volumes 2–8 — those are authoritative.

---

<a name="volume-1"></a>
## Volume 1 — Current Reality (Phase 0) ✅

*Carried from v3 §2, live-verified 2026-08-05, unless flagged. This volume intentionally does not
re-run any check — restating v3's numbers in a new document without re-verification would be
exactly the mistake v3 was written to correct.*

### 1.1 Codebase shape

| Item | Count | Verified how |
|---|---|---|
| Backend Python source files | 261 | `find backend/app -name '*.py'` (2026-08-04) |
| Backend test files | 90 | `find backend/tests -name 'test_*.py'` |
| Frontend test files | 41 | `find frontend/src -name '*.test.*'` |
| REST routers | 10 | `ls backend/app/api/v1/routers/*.py`: auth, backups, health, monitoring, plugins, schedules, servers, settings, software, users |
| DDD modules | 9 | `ls backend/app/modules/` |
| Alembic revisions | 16 | `ls backend/alembic/versions/*.py` |
| ADRs | 12 | `ls docs/decisions/*.md` (excl. README) |
| Contract files | 6 | `ls contracts/` |
| Backend tests collected | 1,070 | `pytest --collect-only -q` |
| Backend tests passed/failed | 1,068 / 2 ⚠️ **not re-run 2026-08-05, not re-run in this document either** | carried from `current-state.md` (2026-08-04) via v3 |
| Frontend tests | 236 across 41 files | `vitest list` |
| App version (code) | `4.0.0` everywhere | grepped `pyproject.toml`, `package.json`, `main.py`, `config.py`, `package-lock.json`; `7.1.0` appears only as an unrelated semver-range substring and in historical planning docs |
| CI workflows | 1 (frontend only) | `.github/workflows/frontend-ci.yml` — no backend CI |

**Since v3 (from `docs/STATUS.md` uncommitted batch entries, 2026-08-05 → 2026-08-06):**

| Item | Change | Source |
|---|---|---|
| Backend tests collected | 1,070 → **1,084** (+14) | Batch K16A (2026-08-05): plugin catalog provider tests |
| Marketplace frontend | Now first-class — own `/marketplace` route, sidebar entry, global search endpoint | K5 (2026-08-06), STATUS.md |
| Plugin catalog providers | Configuration-driven via `MCS_PLUGIN_PROVIDERS`, fail-fast validated at startup | K16A (2026-08-05), STATUS.md |

These two batches post-date v3's 2026-08-05 snapshot. They are **not yet reflected in v3's Phase 1
workstream table** — this document treats K5 and K16A workstream items as done (§Volume 2) on the
strength of the STATUS.md batch entries, which is a lower verification bar than v3's live route
introspection. Flagged, not hidden.

### 1.2 Outstanding file-state item (carried from v3 §2, unresolved)

Two files carry uncommitted working-tree changes (both tracked and committed, not "deliberately
uncommitted" as v2 mistakenly said): `backend/app/api/v1/routers/plugins.py` (8 commits, latest
`b1b6dd8`) and `backend/tests/api/test_api_endpoints.py` (9 commits, latest `b1b6dd8`). Pending
diff: a `_to_version_response()` helper (+19/−3) and one new test,
`test_marketplace_versions_returns_files` (+54). **Still open — see D3, Volume 10.**

### 1.3 What Phase 0 establishes

Phase 0 is not a phase with deliverables — it's the ground truth every later phase's "current
reality" section is checked against. If a later phase's acceptance criterion depends on a Phase 0
number, and that number hasn't been re-verified since 2026-08-05, the acceptance check must
re-verify it before claiming done. This is stated explicitly because it's the exact failure mode
that produced the v2 → v3 rewrite.
