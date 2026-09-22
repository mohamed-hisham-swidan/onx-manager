# Design Spec: Test DB Isolation + preflight.sh Kill-Predicate Fix

**Document Status:** IMPLEMENTED/VERIFIED — 2026-09-22 (3038 passed / 6 skipped, 3/3 clean `-n auto` runs, 6/6 CI gates PASS)
**Spec Identifier:** `SPEC-2026-09-22-TEST-DB-ISOLATION-01`
**Date:** 2026-09-22
**Source Recon:** Test DB isolation audit, 2026-09-22 (Finding / Files-Modules /
Current-Behavior / Problem / Constraints / Related-Tests / Unknowns / Recommendation;
5 findings: 4 real-DB violators, opt-in fixture archaeology, preflight kill predicate,
autouse feasibility, dev-DB pollution census — 66 phantom `test-srv-*` servers,
59 `feat-*` branches in `backend/data/onx.db`)
**Governing Authority:** `docs/governance/GOVERNANCE.md`; `.ai/pls-agent-ignore-that/Orchestrator.md` §5

> Design-completion gate note (per `.ai/RULES/documentation-and-state.md`):
> this is a **documented design, not yet implemented**. The file:line claims below
> were checked against actual code during the 2026-09-22 recon (violator sites,
> `db.py` path anchoring, `preflight.sh:84-353`, `application/conftest.py:32-53`).
> Saver-verified 2026-09-22: pytest marker registry lives at
> `backend/pyproject.toml:61-66` (`[tool.pytest.ini_options]`, currently only
> `docker` registered) — so the "unknown marker" edge case below is real and
> `no_isolated_db` must be added to that list during Build.

---

## Goal

Eliminate the -n auto crash by (a) guaranteeing every test uses an
isolated in-memory DB by default, and (b) making preflight.sh's
--restart path unable to kill a pytest worker. Dev-DB phantom-row
cleanup is explicitly OUT OF SCOPE for this spec (separate task,
pending owner confirmation of which rows are genuine).

## Current Behavior

- `AppSettings.database_url` defaults to `sqlite+aiosqlite:///data/onx.db`;
  `db.py:56-80` anchors relative paths to `backend/` regardless of cwd.
- `init_test_db` (safe in-memory fixture) is opt-in; 4 sites never opt in
  and bind the global engine to the real dev DB:
  - `backend/tests/integration/test_sqlite_locking_remediation.py:78`
  - `backend/tests/integration/test_sqlite_locking_remediation.py:126`
  - `backend/tests/integration/test_sqlite_locking_remediation.py:188`
    (no init(); inherits whatever engine a prior test left behind)
  - `backend/tests/test_settings_persistence.py:181` (autouse setup_db)
- `scripts/preflight.sh` `check_db_lock`/`belongs_to_project`/`kill_safe`
  (lines 84-353) SIGTERM→SIGKILLs any project-owned process holding a
  lock on `backend/data/onx.db`, with no pytest/xdist exclusion and no
  requirement that the holder look like a server process.

## Proposed Change

1. Add a root-level autouse fixture `_isolate_db_autouse` in
   `backend/tests/conftest.py`, mirroring
   `application/conftest.py:32-53`'s `init_test_db` (in-memory engine,
   `Base.metadata.create_all`, env sandbox, teardown resetting
   `database._engine` / `database._session_factory` to None).
2. Add an opt-out marker `no_isolated_db`; the autouse fixture checks
   `request.node.get_closest_marker("no_isolated_db")` and skips itself
   if present.
3. Mark the ~6 legitimate file-DB tests with `@pytest.mark.no_isolated_db`:
   `test_database.py`, `test_reconciler.py`,
   `auth/test_audit.py:86-87,169-170`,
   `event_store/test_chain_concurrency_recon.py:34-35`,
   `application/test_stage_d_admission.py:43,331-332`,
   `domain/test_stage_a_domain_invariants.py:145`.
4. Fix the 4 violating sites in `test_sqlite_locking_remediation.py`
   (:78, :126, :188) and `test_settings_persistence.py:181` to rely on
   the new autouse fixture (drop their bare `database.init()` calls,
   or pass the isolated settings explicitly where a local override is
   still needed).
5. Delete the ~13 local shadowing `init_test_db` definitions that
   duplicate the fixture, now that it's available at root scope
   (opportunistic cleanup, only where mechanically safe — do not touch
   files outside this list).
6. In `scripts/preflight.sh`, scope `check_db_lock`'s kill predicate to
   an actual server-process signature: require the cmdline to match
   `uvicorn`/`app.main:app` AND not match `pytest`/`xdist`/`py.test`.
   Do not remove `belongs_to_project`; add the server-signature check
   as an additional AND condition before `kill_safe` is called.
7. Point `test_preflight.py`'s `--restart` test (`test_preflight_force_
   clean_flag`) at a tmp DB path via env override instead of exercising
   the real `ONX_DB` resolution, so the test itself can never touch the
   real file.
8. Remove the interim "KNOWN ISSUE" caveat added to
   `.ai/RULES/testing-policy.md` on 2026-09-22, since the root cause
   will no longer exist.

## Affected Components

- `backend/tests/conftest.py` (new fixture + marker registration)
- `backend/tests/integration/test_sqlite_locking_remediation.py`
- `backend/tests/test_settings_persistence.py`
- `backend/tests/test_database.py`, `test_reconciler.py`,
  `auth/test_audit.py`, `event_store/test_chain_concurrency_recon.py`,
  `application/test_stage_d_admission.py`,
  `domain/test_stage_a_domain_invariants.py` (marker only)
- `scripts/preflight.sh`
- `backend/tests/test_preflight.py`
- `.ai/RULES/testing-policy.md` (remove caveat)
- Up to ~13 files with duplicate local `init_test_db` (list to be
  confirmed during Build via grep, per Finding 2 census)

## Interfaces & Contracts

None changed — no DB schema, API, or permission-contract changes.
Internal-only test-infrastructure and one dev shell script.

## Failure Cases & Edge Cases

- A test outside the audited list that also bypasses isolation and
  isn't caught by the census → Build must re-grep for
  `database.init(` and `session_factory(` calls project-wide before
  closing, not just trust the recon's sampled list.
- `no_isolated_db` marker not registered in `pytest.ini`/`pyproject.toml`
  → pytest will warn "unknown marker"; must add it to the markers list.
- Autouse fixture ordering: must run before any fixture that touches
  `database.*` — verify no other autouse fixture in a parent/sibling
  conftest.py races with it.
- preflight.sh signature check must still work on the actual dev
  Windows/Linux command-line formats used by `uvicorn` in this repo —
  verify the real cmdline string (don't assume) before hardcoding the
  match pattern.

## Tests & Verification

- New regression test: spawn two fake "servers" that hold a lock on the
  isolated (not real) DB and run `preflight.sh --restart` against them
  in a test harness — confirm it does NOT kill a process whose cmdline
  matches `pytest`/`xdist`.
- Re-run the 4 previously-violating tests in isolation and confirm (via
  `git diff`/row count) that `backend/data/onx.db` is untouched
  (byte-identical or unchanged row counts) after each.
- Full suite `python -m pytest -q -n auto` must complete without any
  worker being killed, run to run, 3 consecutive times (to catch
  xdist-scheduling nondeterminism).
- All 5 CI gates + full backend/frontend suites per Orchestrator.md §9.

## Out of Scope

- Cleaning the 66 phantom `test-srv-*` / 59 `feat-*` rows already in
  `backend/data/onx.db` (Finding 5) — separate task, pending Mohamed's
  confirmation of which non-prefixed rows are genuine.
- Any change to `.ai/STATE.json` Lane classification — governance call,
  not part of this spec's implementation.
