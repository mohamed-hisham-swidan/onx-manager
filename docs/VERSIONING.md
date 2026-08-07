# MCS Manager — Versioning Strategy

**Status:** PLANNED reference — this document defines the target versioning
strategy. Today's versioning is ad hoc; nothing here is implemented yet.

**Last updated:** 2026-08-04

---

## 1. Why this document exists

The repository carries several competing version numbers. Only documentation and
state files disagree with the code; the code itself is internally consistent. The
target is **one source of truth** for the application version, surfaced
consistently in the backend, frontend, docs, and state files.

---

## 2. Current version sources (verified 2026-08-04)

| # | Source | Value today | Notes |
|---|--------|-------------|-------|
| 1 | `backend/pyproject.toml` `[project] version` | `4.0.0` | Package metadata |
| 2 | `backend/app/core/config.py:14` `AppSettings.version` | `4.0.0` | Runtime default, read by `GET /settings` |
| 3 | `backend/app/main.py:216,268` OpenAPI `version=` | `4.0.0` | OpenAPI schema + info |
| 4 | `frontend/package.json` `version` | `4.0.0` | Frontend package |
| 5 | `frontend/package-lock.json` | `4.0.0` | Locks the package version |
| 6 | Stale planning docs (`STATUS.md`, `.ai/*.json`, old `docs/`) | `7.1.0` | **Stale** — superseded by `4.0.0` |
| 7 | `backend/data/servers/server/Implementation/...` (server-content copy) | `7.1.0` | Inside a managed server's working directory — **runtime/server data, not the app** |

**Findings**

- The **application code is uniformly `4.0.0`** across backend package, backend
  runtime, OpenAPI, and frontend package/lock. There is no code path that reads
  `7.1.0`.
- The `7.1.0` value survives only in (a) planning/history documents and (b) a
  stale `Implementation/` state tree stored under a managed server's data
  directory. Item (b) is server content, not the application — it is outside the
  versioning scope and must not be edited.
- Backend version is **duplicated three times** (pyproject, config.py, main.py)
  and requires manual syncing. The frontend version is independent of the
  backend version and has no linkage to it.

---

## 3. Problems with the current state

1. **No single source of truth.** Three backend files hold the version string and
   can drift from each other and from `package.json`.
2. **Frontend and backend versions are unlinked.** A backend release and a
   frontend release can disagree about what "the product version" is.
3. **No release semantics.** `4.0.0` is a string, not a SemVer contract. There is
   no documented meaning for major/minor/patch in this project.
4. **No migration/version compatibility rule.** With an Alembic migration chain
   (16 revisions) and a prod DB that trails head, there is no documented rule for
   "which DB revision a given app version expects."
5. **State files are hand-maintained.** `.ai/CURRENT_STATE.json` and
   `.ai/PROJECT_STATE.json` carry `version` fields that can silently diverge from
   code.

---

## 4. Target strategy

### 4.1 One source of truth

Backend `pyproject.toml` is the **canonical** source. Everything else derives from
it at build/runtime time:

- `AppSettings.version` is read from the installed package metadata
  (`importlib.metadata`) instead of a hardcoded default, with the current value as
  a fallback.
- OpenAPI `version=` uses the same value.
- The frontend reads the version from the backend
  (`GET /api/v1/settings` already returns `version`) and uses it as the single
  displayed product version; `package.json` version becomes internal build
  metadata only.
- CI injects the resolved version so a tagged build is immutable.

### 4.2 Release semantics

Adopt **SemVer 2.0.0** with conventions stated explicitly:

| Segment | Meaning |
|---------|---------|
| `major` | Architecture change, breaking auth/security model, or a new top-level Roadmap phase |
| `minor` | Backward-compatible feature (a new Roadmap workstream shipping) |
| `patch` | Bug fix, doc fix, non-breaking QoL with no new capability |
| `-pre`/`-rc` | Pre-release / release candidate suffixes |

The application is currently `4.0.0`. `v1.0` public-release naming (referenced in
older docs) is decoupled from internal app SemVer; the roadmap's "v1.0" means
"first public release," not "version 1.0.0".

### 4.3 Migration/version compatibility

Because state lives in SQLite/Postgres behind Alembic, define:

- Every release pins a minimum Alembic revision.
- On startup, if the DB is behind the required revision, log loudly and either
  auto-upgrade (documented decision) or refuse to start (decision log).
- Document per-release "head revision" in the release notes.

### 4.4 State-file discipline

- `.ai/CURRENT_STATE.json` / `.ai/PROJECT_STATE.json` `version` fields align to
  the resolved app version and note the verification date.
- Docs do not assert a version number they cannot justify from the code;
  cross-cutting version claims are centralized in `docs/README.md`.

---

## 5. Roadmap placement

Versioning is **Roadmap Phase 5 (Versioning & State Consistency)** in
`docs/roadmap/MCS-Manager-Engineering-Blueprint-V5.md`. It is deliberately scheduled after the
Plugins/Marketplace restructure, the UI stabilization, and the bug-fixing
phases, so the versioning change lands on a stable baseline.

**Do not implement this now** — this document is the plan, not the change.

---

## 6. Acceptance criteria (future)

- Changing `pyproject.toml` version propagates to runtime, OpenAPI, and the
  displayed product version without further edits.
- A single document/command answers "what version is this, and what does it mean."
- Production DB upgrade status is reported and constrained by a documented rule.
- Re-run of the state files after a release shows no residual `7.1.0`-class
  lifetime-orphan version values (other than historical records and server data).