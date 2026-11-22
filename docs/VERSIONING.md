# ONX Manager — Versioning Strategy

**Status:** ✅ **ADOPTED & IMPLEMENTED (policy + mechanism)** — policy adopted
2026-08-12 (Phase 5, Workstream 5.1); the single-source **mechanism** is
implemented (verified 2026-08-13, Workstreams 5.2–5.6). Runtime, OpenAPI,
settings, health, and frontend version display derive from `pyproject.toml`
through `backend/app/core/version.py:get_app_version()`.

**Last updated:** 2026-08-13

---

## 1. Why this document exists

The repository carries several competing version numbers. Only documentation and
state files disagree with the code; the code itself is internally consistent. The
target is **one source of truth** for the application version, surfaced
consistently in the backend, frontend, docs, and state files.

---

## 2. Current version sources (verified 2026-08-19)

| # | Source | Value today | Notes |
|---|--------|-------------|-------|
| 1 | `backend/pyproject.toml` `[project] version` | `0.1.0` | **The canonical single source** — read via `get_app_version()` |
| 2 | `backend/app/core/version.py:get_app_version()` | `0.1.0` | Resolver: `pyproject.toml` (tomllib) → `importlib.metadata` fallback → `_FALLBACK_VERSION` `0.1.0` last resort |
| 3 | `backend/app/core/config.py` `AppSettings.version`, `main.py` OpenAPI + `/health`, `settings.py`, `schemas/common.py`, `setup.py`, `get_system_status.py`, `update_access_mode.py` | `0.1.0` | All consume `get_app_version()` — no hardcoded version literals remain in these files |
| 4 | `frontend/package.json` `version` | `0.1.0` | Frontend package (build metadata; not the runtime display source) |
| 5 | `frontend/package-lock.json` | `0.1.0` | Locks the package version |
| 6 | Frontend runtime display (`SettingsPage`) | `0.1.0` | Read from `GET /api/v1/settings` → `version` (resolved via `get_app_version()`) |
| 7 | Archived history docs (`docs/history/`, Blueprint v4 set) | `7.1.0` / `4.0.0` (historical) | **Stale** — kept for history only, superseded by `0.1.0` |
| 8 | `backend/data/servers/server/Implementation/...` (server-content copy) | `7.1.0` | Inside a managed server's working directory — **runtime/server data, not the app** |

**Findings**

- The **application code is uniformly `0.1.0`** across backend package, backend
  runtime, OpenAPI, settings responses, and frontend package/lock. There is no
  code path that reads `7.1.0`.
- The version is read from **one canonical source** (`pyproject.toml`) through
  `get_app_version()`. No backend file hardcodes the version literal anymore;
  the previous nine-hardcoded-literals-across-eight-files state is **resolved**
  (Phase 5.2).
- The `7.1.0` value survives only in (a) archived planning/history documents and
  (b) a stale `Implementation/` state tree stored under a managed server's data
  directory. Item (b) is server content, not the application — it is outside the
  versioning scope and must not be edited.

---

## 3. Problems with the current state

**Resolved 2026-08-13 (Phase 5).** The historical problems were:

1. **No single source of truth.** Eight backend files held the version string
   (nine literals) and could drift from each other and from `package.json` —
   **resolved**: `pyproject.toml` is canonical, consumed via
   `get_app_version()`.
2. **Frontend and backend versions were unlinked.** A backend release and a
   frontend release could disagree about what "the product version" is —
   **resolved**: the frontend runtime display reads the version from
   `GET /api/v1/settings` (resolved by the backend); `package.json` is build
   metadata only.
3. **No release semantics.** `4.0.0` was a string, not a SemVer contract —
   **resolved**: SemVer 2.0.0 semantics adopted (§4.2).
4. **No migration/version compatibility rule.** With an Alembic migration chain
    (51 revisions, head `b1e2100000031`) and a prod DB that trails head, there was
    no documented rule for "which DB revision a given app version expects" —
    **resolved**: per-release minimum DB revision, fail-closed, never auto-migrated
    (§4.3).

---

## 4. Target strategy

### 4.1 One source of truth (implemented)

Backend `pyproject.toml` is the **canonical** source. Everything derives from it
at build/runtime time:

- `backend/app/core/version.py:get_app_version()` reads `pyproject.toml`
  (tomllib) first, falls back to installed package metadata
  (`importlib.metadata`), then to a hardcoded `_FALLBACK_VERSION` last resort.
- `AppSettings.version`, OpenAPI `version=`, `/health` version, `GET/PATCH
  /settings`, `GET /setup/status`, `GetSystemStatusQuery`,
  `UpdateAccessModeCommand` all read `get_app_version()`.
- The frontend reads the version from the backend
  (`GET /api/v1/settings` → `version`) and displays it in `SettingsPage`;
  `package.json` version is internal build metadata only.
- CI verifies propagation: `scripts/check-version-propagation` +
  `.github/workflows/backend-version-ci.yml`.

### 4.2 Release semantics

Adopt **SemVer 2.0.0** with conventions stated explicitly:

| Segment | Meaning |
|---------|---------|
| `major` | Architecture change, breaking auth/security model, or a new top-level Roadmap phase |
| `minor` | Backward-compatible feature (a new Roadmap workstream shipping) |
| `patch` | Bug fix, doc fix, non-breaking QoL with no new capability |
| `-pre`/`-rc` | Pre-release / release candidate suffixes |

The application is currently `0.1.0`. `v1.0` public-release naming (referenced in
older docs) is decoupled from internal app SemVer; the roadmap's "v1.0" means
"first public release," not "version 1.0.0".

#### Internal app version vs public API version (independent)

The internal application SemVer and the public API contract version are **two
independent concepts**. They must never be conflated:

- **`0.1.0`** is the internal release/application version — the version of the
  ONX Manager application itself, carried by the package, runtime, OpenAPI info,
  settings responses, and (since Phase 5.2) derived from `pyproject.toml`
  via `get_app_version()`.
- **`/api/v1`** is the public API contract version — the version of the REST API
  surface (all routers mount under the `/api/v1` prefix; the WebSocket endpoint
  is `/ws`).
- **Changing `0.1.0` does NOT automatically imply changing `/api/v1`.**
- **Changing `/api/v1` requires an explicit API-compatibility decision**, recorded
  in the decision log (ADR) — a breaking API contract change, separate from an
  application release.

These two numbers must therefore be able to move independently. A patch or minor
app release (`0.1.1`, `0.2.0`) leaves the API at `/api/v1`. Only a deliberate,
documented breaking API change increments the API prefix/version.

### 4.3 DB compatibility floor (per release)

Each release pins a **minimum compatible database schema revision**. This is the
schema floor the application refuses to start below — **fail closed, never
auto-upgraded**.

| Release | Minimum DB revision |
|---------|---------------------|
| `0.1.0` | `b1e2100000031` (current Alembic head and floor) |

- **Authoritative declaration:** `backend/app/core/persistence/db_revision.py`
  (`RELEASE_MINIMUM_DB_REVISION`). No other runtime source duplicates it.
- **Invariant:** `DB revision >= release minimum`, decided from the migration
  **graph** (ancestry walk over `down_revision`), never by string comparison of
  revision ids.
- **Behavior:** at startup the application reads `alembic_version` from the live
  database and refuses to start if the revision is missing, unknown, behind the
  minimum, or on an incompatible branch. Exact minimum and compatible descendants
  are allowed. See `docs/architecture/DATABASE.md` §Migration Strategy and
  `docs/DEPLOYMENT.md`.
- **Policy:** the application **never** runs migrations automatically. The
  operator runs `alembic upgrade head` as part of deployment; a too-old database
  aborts startup with an actionable error naming the current revision, the
  required minimum, and the required command.

> **DB floor vs app SemVer:** the pinned minimum is chosen by the release (it is
> not derived from the SemVer number). A later release (`4.1.0`) may raise the
> floor to a future head.

#### Plugin compatibility floor (separate)

`PluginManifest.min_app_version` (`backend/app/modules/plugin/infrastructure/manifest.py`)
is a **separate plugin compatibility floor**, not part of the application version
policy. It asserts "this plugin requires app ≥ `X.Y.Z`" and is governed by the
plugin system's own contract. It is intentionally excluded from the single-source
version propagation check (Workstream 5.4).

### 4.3 Migration/version compatibility

Because state lives in SQLite/Postgres behind Alembic, define:

- Every release pins a minimum Alembic revision.
- On startup, if the DB is behind the required revision, log loudly and either
  auto-upgrade (documented decision) or refuse to start (decision log).
- Document per-release "head revision" in the release notes.

### 4.4 State-file discipline

- Docs do not assert a version number they cannot justify from the code;
  cross-cutting version claims are centralized in `docs/README.md`.

---

## 5. Implementation Status

The versioning policy above (SemVer semantics, single source of truth via `backend/app/core/version.py:get_app_version()`, CI propagation check, and fail-closed Alembic minimum revision floor in `backend/app/core/persistence/db_revision.py`) is active and enforced in CI.

---

## 6. Acceptance criteria (enforcement, Workstreams 5.2–5.6)

**Met (verified 2026-08-13).**

- Changing `pyproject.toml` version propagates to runtime, OpenAPI, settings
  responses, and the displayed product version without further edits.
- A single document/command answers "what version is this, and what does it
  mean": `backend/app/core/version.py:get_app_version()` + `scripts/check-version-propagation`.
- Production DB upgrade status is reported and constrained by a documented rule
  (`scripts/check-db-revision`, fail-closed floor).
- Re-run of the state files after a release shows no residual `7.1.0`-class
  lifetime-orphan version values (other than historical records and server data).