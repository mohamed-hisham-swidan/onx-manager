# SPEC-2026-11-09 — Windows CI Failure Triage & Fix Design (01)

Status: FIX IMPLEMENTED — Linux regression suites green; Windows CI rerun PENDING
Lane: A candidate (CI red — confirm classification with owner per GOVERNANCE §12)
Decision level: D1 (cross-platform behavior + test-contract changes)
Author role: RECON (read-only investigation; this document is the requested record)
Date: 2026-11-09

## 1. Source evidence

CI run: Windows backend job (`windows-ci`) reported at end of run:

- `28 failed, 3545 passed, 69 skipped, 220 warnings, 7 errors in 1339.20s`
- Runner: `C:\hostedtoolcache\windows\Python\3.12.10\x64`, Windows `10.0.26100`, Docker daemon in Windows-containers mode.

Local re-verification in this RECON (Linux, `backend/.venv/bin/python`, 2026-11-09):

- 8 cross-platform-agnostic tests that failed on Windows → `8 passed in 3.07s`
- 13 Docker path/provider tests → `13 passed in 2.16s`
- 5 launcher dynamic-port tests → `5 passed in 1.90s`
- 2 provider-conformance params (`local_linux`, `circuit_breaker`) → `2 passed, 4 deselected in 0.43s`

So all 28 failures are Windows-environment-only in this sample. Windows claims below are labelled FACT (from the CI log), INFERENCE (from code reading), or UNKNOWN. None of the Windows fixes were executed on Windows in this session.

## 2. Failure inventory and fix design

### Group A — Path identity: tests compare unresolved 8.3/short temp paths against resolved paths (5 failures)

Windows reports `TEMP` as `C:\Users\RUNNER~1\...`, while `Path.resolve()` (and `os.path.realpath`) canonicalises it to `C:\Users\runneradmin\...`. Production code legitimately resolves/normalises; the tests compare against the raw `tmp_path` string.

| ID | Failing test | Production location | Required fix |
|---|---|---|---|
| A1 | `tests/application/test_promote_commit_gating.py::test_promote_uses_atomic_text_writer_for_configs` | `app/core/fs_utils.py:19` (`assert_inside_root` resolves), `promote_commit.py:297` | Test only: build `expected` keys from resolved paths (`assert_inside_root(server_path / rel, server_path)`) or `Path(...).resolve()`. |
| A2 | `...::test_promote_config_write_failure_on_second_file_raises_filesystem_error` | same | Test only: compare `written` against `str(Path(...).resolve())`. |
| A3 | `tests/infrastructure/test_btrfs_zfs_snapshot_driver.py::test_btrfs_zfs_driver_clone_world_invokes_reflink` | `btrfs_zfs_driver.py:34-35` (`.resolve()`) | Test only: expect `str(world_dir.resolve())` / `str((dst/"world").resolve())`. |
| A4 | `tests/infrastructure/test_docker_provider.py::test_docker_start_with_launch_config_jar` | `docker.py:388` (`normalize_host_path` → `as_posix`) | Test only: expect `normalize_host_path(srv_dir)` (already imported in the DooD suite; add import here). |
| A5 | `tests/test_launcher_python_pin.py::test_check_python_accepts_312` | `launcher.py` `Validator.check_python` returns `str(Path(...))` | Test only: expect `str(Path("/fake/venv/bin/python"))` so separators match the host. |

Rationale: production behaviour is correct; rewriting production to stop resolving would weaken the containment invariant (`assert_inside_root`). Do not change production for A1–A5.

### Group B — `normalize_host_path` corrupts POSIX absolute paths on Windows (10 failures)

FACT from CI log: every DooD result gains a `D:/` prefix (`D:/srv/minecraft/servers/...`), and `test_normalize_host_path_posix` gets `D:/var/minecraft/servers/srv1`.

Root cause (FACT by code reading): `docker.py:82-99`:

```python
if sys.platform == "win32":
    return Path(path_str).resolve().as_posix()
...
return Path(path_str).resolve().as_posix()
```

On Windows, `Path("/srv/minecraft/servers").resolve()` is a drive-relative Windows path, so the current drive (`D:`) is prepended. This is wrong for a POSIX path that denotes a **Linux Docker host** path (DooD) or a container-internal path.

Affected tests (10):

1. `tests/infrastructure/test_docker_dood.py::TestDooDHostPathResolution` — `test_dood_translates_app_data_servers_path`
2. `...::test_dood_translates_relative_data_servers_path`
3. `...::test_dood_translates_exact_base_servers_dir`
4. `...::test_dood_fallback_for_custom_leaf_path`
5. `...::test_mcs_legacy_host_data_dir_env_supported`
6. `...::test_dood_trailing_slash_normalization`
7. `...::test_dood_dot_dot_normalization`
8. `...::TestDooDDockerProviderVolumeMount::test_docker_provider_start_uses_dood_host_mount`
9. `...::test_container_installer_runner_uses_dood_host_mount`
10. `tests/infrastructure/test_docker_network_windows.py::TestDockerWindowsPolicyAndPathNormalization::test_normalize_host_path_posix`

Recommended production fix in `normalize_host_path`: preserve POSIX-absolute inputs before any `Path` handling.

```python
def normalize_host_path(path: str | Path) -> str:
    raw = str(path).strip()
    if not raw:
        return ""
    if raw.startswith("/"):
        # POSIX absolute path (Linux host / container path): never resolve via
        # the current Windows drive and never backslash-convert.
        return posixpath.normpath(raw)
    if sys.platform == "win32":
        return Path(raw).resolve().as_posix()
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        return raw.replace("\\", "/")
    return Path(raw).resolve().as_posix()
```

This keeps the existing Windows-drive tests green (`C:\...`, `C:/...`, mixed slashes) and makes all DooD joins correct because `resolve_host_mount_path` already strips trailing slashes and joins with `/`.

Caveat: a Windows user who passes `/var/...` as a real Windows host path will now get a POSIX path. That is acceptable: the function's contract is host-path normalisation for Docker, and a leading `/` is never a valid Windows absolute host path; the existing design intent (docstring item 4) is to treat POSIX paths as POSIX.

### Group C — Docker containment check runs after image pull (1 failure)

FACT from CI: `test_docker_start_containment_enforcement` reaches `docker pull eclipse-temurin:21-jre-jammy` and dies with `no matching manifest for windows(...)` instead of raising `PathContainmentError`.

Root cause (FACT): `docker.py:406` calls `await self._ensure_image(image)` before `docker.py:470` calls `assert_inside_root(server_dir, AppSettings().servers_data_dir)`. The second half of the test does not mock the pull, so on Windows the pull fails first. On Linux the pull happens to succeed/daemon available (or test env is permissive), hiding the ordering defect.

Recommended production fix: move containment validation to immediately after `server_dir` is computed/normalised (before `server.properties` read and before `_ensure_image`), and keep a single validation site (delete the later duplicate). Security validation must precede side effects.

Test-side hardening (also recommended, defence in depth): mock `_ensure_image` in the “outside path” block too, so the test proves containment even if pull is available.

### Group D — Newline translation: write paths inject CRLF on Windows (4 failures)

#### D1 (production) — materialized configs are written with CRLF

FACT from CI: `GetMaterializationFileQuery` returns `difficulty=easy\r\nmotd=Initial\r\n`, and `test_stage_c_materialization_commands.py:261` expects LF.

Root cause (FACT): `app/modules/versioning/infrastructure/tree_writer.py:42` uses `dest_file.write_text(content, encoding="utf-8")`. On Windows, text mode translates every `\n` to `\r\n`. The verification pass at `tree_writer.py:73` uses `read_text()` (universal newlines), which normalises back to `\n`, so the corruption is masked during the verify step; `GetMaterializationFileHandler` later reads raw bytes (`get_materialization_file.py:98`) and exposes the CRLF.

Recommended production fix: write bytes, or open with `newline="\n"`:

```python
dest_file.write_bytes(content.encode("utf-8"))
```

Apply the same rule to every config-content write identified below (adjacent findings).

#### D2 (test) — launcher log tests write CRLF through `write_text`

Three failures:

- `tests/test_launcher_dynamic_port.py::test_f2_reader_resets_to_zero_ignores_preceding_stale_marker` (line 917: `"clean current attempt log\n" in '...\r\n'`)
- `...::test_read_backend_log_from_normal_append_not_reset` (line 1056)
- `...::test_read_backend_log_from_intact_marker_not_reset` (line 1083)

Root cause (FACT): `_read_backend_log_from` (`launcher.py:3394`) deliberately reads bytes and returns them decoded without newline normalisation, which is correct (it must detect bind errors byte-exactly). The tests seed/append using `Path.write_text(...)` / `open("a", encoding="utf-8")` with default newline mode, so on Windows the test fixture itself contains `\r\n` before the assertion compares LF.

Recommended test fix: write bytes (`write_bytes(text.encode("utf-8"))`) or pass `newline="\n"`. Do not normalise newlines inside the production reader.

Adjacent findings (not failing in this run, same class — record, do not fix in this batch unless owner expands scope):

- `app/modules/versioning/infrastructure/tree_writer.py:73` verification masks the corruption (D1).
- `app/modules/versioning/infrastructure/manifest_builder.py:78,92` uses `read_text()` (universal newlines), so CRLF source configs are silently converted to LF in commits. This is byte-fidelity loss in the other direction.
- `app/modules/versioning/infrastructure/test_runner.py:456`, `app/modules/versioning/application/commands/promote_commit.py:278` use `write_text`/staged text writes on Windows.
- `app/modules/server/infrastructure/fs.py:80-84` (`LocalFileSystem.write_text/read_text`) also translate newlines.

### Group E — `LocalLinuxProvider` uses `signal.SIGKILL` unconditionally (2 failures)

FACT from CI: `AttributeError: module 'signal' has no attribute 'SIGKILL'` at `app/modules/server/infrastructure/providers/local.py:137`, for params `[local_linux]` and `[circuit_breaker]`.

Root cause (FACT): `_kill_processes` (`local.py:128-139`) uses `signal.SIGTERM` then `signal.SIGKILL`. `SIGKILL` does not exist on Windows. The conformance suite instantiates `LocalLinuxProvider` on every OS, and its autouse fixture makes `_find_java_processes` return a synthetic PID, so the kill path is exercised on Windows.

Recommended production fix (defensive, minimal): pick the strongest signal the platform exposes:

```python
force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
...
os.kill(pid, force_signal)
```

Test-side hardening: in `tests/infrastructure/test_provider_conformance.py`, either skip `local_linux` / `circuit_breaker` on `win32`, or keep them but assert the fallback path. Prefer keeping the production guard and a Windows skip for `local_linux` only if the owner wants strict provider/platform semantics (LocalLinuxProvider is Linux-only by definition). Do NOT switch to `platform_force_kill` in this test context: the conformance fixture's synthetic PID could trigger a real `TerminateProcess` on Windows.

Also note `local.py:439,489` already handle signals elsewhere; audit them under the same rule when patching.

### Group F — Platform-specific test assumptions (4 failures)

| ID | Failing test | Root cause | Required fix |
|---|---|---|---|
| F1 | `tests/application/test_runtime_reconciliation.py::TestReconcileServerRuntime::test_tmux_pid_dead` | Test patches `runtime_reconciliation.os.kill` (POSIX liveness path) but production uses `platform_pid_alive(tmux_pid)` (`runtime_reconciliation.py:279`), which on Windows uses `_windows_pid_alive` and ignores `os.kill`. Result: no `TMUX_PID_DEAD` mismatch on Windows. | Test only: patch `...runtime_reconciliation.platform_pid_alive` to return `False` (and drop the `os.kill` patch). Deterministic on all OSes. |
| F2 | `tests/application/test_server_commands.py::TestStartServerHandler::test_start_server_timeout_marks_stopped_and_returns_details` | Expected `details["provider"] == "local"`, but the test server has no runtime provider, so `default_provider_for_platform()` yields `local_windows` (`start_server.py:451` reports `provider_type`). | Test only: expect `default_provider_for_platform()` (or set the server runtime provider explicitly). |
| F3 | `...TestRestartServerHandler::test_restart_server_timeout_marks_stopped_and_returns_details` | Same as F2; `restart_server.py:421,447`. | Same test fix. |
| F4 | `tests/test_settings_persistence.py::TestSettingsAPIEndpoints::test_persist_atomic_and_preserves_mode` | POSIX mode assertion (`st_mode & 0o777 == 0o600`) on Windows, where `chmod` only toggles read-only and `stat` reports `0o666` (`33206`). `_persist` correctly best-effort preserves mode. | Test only: `@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")` or assert mode only on POSIX. Do not change `_persist`. |

Additional observation for F2/F3 (production, low severity): `details["provider"]` reports the resolved `provider_type`, not the actual provider instance name (`provider_name = getattr(provider, "name", provider_type)` at `start_server.py:104`). If the owner wants the detail to describe the provider that actually ran (the test injects a provider whose `provider_type` is `docker`), report `provider_name` instead. This is a behaviour change; keep out of the test-only fix unless explicitly approved.

### Group G — Launcher Windows behaviour (2 failures)

#### G1 — `test_retry_aborts_when_previous_owned_listener_cannot_be_stopped` (`StopIteration`)

FACT from CI: the mocked `PortManager.resolve_startup_port` (2 decisions) is called a third time, raising `StopIteration`, after “Starting on port … (attempt 1/3)” and “(attempt 2/3)”.

Root cause (INFERENCE): the test assumes `_reconcile_failed_attempt` aborts after attempt 1 because the project-owned listener survives. On Windows `PortManager.can_bind(port1)` (`launcher.py:951-962`, no `SO_REUSEADDR` on Windows, binds `0.0.0.0` while the fixture listener is `127.0.0.1` + `SO_REUSEADDR`) returned `True`, so `_reconcile_failed_attempt` returned `True` and a retry proceeded; attempt 2 also retried, requiring a third decision. The exact Windows socket semantics are UNKNOWN without a Windows repro.

Recommended fix (prefer test determinism; production hardening optional):

- Test: monkeypatch `PortManager.can_bind` (False for `port1`, True afterwards), `PortManager.get_pid_by_port` (listener pid), and `_handle_own_unhealthy` (returns False) so the abort branch is exercised on every OS. Alternatively supply three decisions and assert `opened_ports == [port1, cand2, …]` with abort at the expected point.
- Production (separate, optional): make `PortManager.can_bind` bind the same address family/interface it is asked about and use `SO_EXCLUSIVEADDRUSE` on Windows to avoid false “free” results. This is a launcher-wide behaviour change; do not bundle silently.

#### G2 — `test_status_uses_healthy_active_port_file` (`running=False` while `port_open=True`)

FACT from CI: `ServiceInfo(name='Backend', pid=None, running=False, port_open=True, port=57283, uptime=None)`.

Root cause: UNKNOWN. The test patches `launcher.check_backend_health`, and `_collect_service` computes `port_open` and `serving` from the same `effective_port`; `port_open` is True but `serving` is False, so either the second health call did not observe the patched function, or the ephemeral listener was not connectable at that instant on the Windows runner. No deterministic explanation from code reading.

Recommended fix: make the test deterministic instead of relying on socket timing/Windows semantics: monkeypatch `PortManager.is_open` (True for the active port) and/or `launcher._backend_is_serving` (True), then assert port/pid/running. Keep a real-socket integration test separately if desired. Do not change `StatusDisplay` before the Windows symptom is reproduced with a stack/trace.

### Group H — SQLite test teardown holds an open handle on Windows (7 errors)

FACT from CI: `PermissionError: [WinError 32]` at `tests/api/test_api_endpoints.py:120` (`db_file.unlink()`) for:

1. `tests/api/test_api_endpoints.py::TestEdgeCases::test_send_command`
2. `tests/api/test_files_api.py::test_files_missing_server`
3. `tests/api/test_files_protection.py::test_env_variants_blocked[.Env. .]`
4. `tests/api/test_server_import_upload.py::test_upload_rejects_non_zip`
5. `...::test_upload_rejects_corrupted_zip`
6. `...::test_upload_insufficient_disk_space`
7. `tests/api/test_servers.py::test_create_server_rejects_invalid_java_args`

Root cause (FACT/INFERENCE): the shared `client` fixture (`tests/api/test_api_endpoints.py:57-123`, re-used via `pytest_plugins`) calls `await engine.dispose()` then immediately `db_file.unlink()`. On Windows an `aiosqlite`/SQLite handle can still be open (leaked session/background task, or WAL/SHM finalization) at unlink time; POSIX allows unlinking open files, Windows does not. The CI log also shows an `aiosqlite` worker thread raising `RuntimeError: Event loop is closed` for a background connection, which supports the “connection alive at teardown” hypothesis. The precise leaking session is UNKNOWN.

Recommended test-infrastructure fix (new helper or in this fixture):

1. `await engine.dispose()`.
2. Let pending callbacks finish (`await asyncio.sleep(0)`), optionally `gc.collect()`.
3. Delete WAL/SHM first, then the DB, retrying briefly and suppressing `PermissionError` as a last resort; `tmp_path` cleanup by pytest is the final fallback. Never fail a test because a temp DB could not be unlinked on Windows.

Do not weaken production DB lifecycle logic for this.

## 3. Patch plan (suggested order, smallest first)

1. **Production, Group B**: `docker.py` `normalize_host_path` POSIX guard. Fixes 10 tests at once.
2. **Production, Group C**: move `assert_inside_root` before `_ensure_image`; add test mock in the outside-path block.
3. **Production, Group D1**: `tree_writer.py` byte write.
4. **Production, Group E**: `local.py` SIGKILL fallback (+ Windows handling decision for `local_linux` conformance).
5. **Tests, Group A**: resolved/normalised path expectations (5 tests).
6. **Tests, Group D2**: write bytes/newline in 3 launcher log tests.
7. **Tests, Group F**: patch `platform_pid_alive`; platform-aware provider expectation; skip/guard POSIX mode assertion.
8. **Tests, Group G**: deterministic mocks for the retry-abort and status tests; investigate `can_bind` on Windows before any launcher change.
9. **Tests, Group H**: Windows-safe teardown in the shared API client fixture.

## 4. Verification plan (required before calling this fixed)

Per `.ai/RULES/testing-and-verification.md`, this is a Windows-only failure set; Linux passes are not evidence of a fix.

1. Run the exact 28 failed node IDs + 7 error node IDs on Windows (locally or `windows-ci` dispatch).
2. Run the full `windows-ci` backend job, not just the subset, because Group B/D affect other path/newline assertions.
3. On Linux, run the touched files sequentially to prove no regression: `test_promote_commit_gating.py`, `test_btrfs_zfs_snapshot_driver.py`, `test_docker_dood.py`, `test_docker_network_windows.py`, `test_docker_provider.py`, `test_provider_conformance.py`, `test_runtime_reconciliation.py`, `test_server_commands.py`, `test_stage_c_materialization_commands.py`, `test_launcher_dynamic_port.py`, `test_launcher_python_pin.py`, `test_settings_persistence.py`, `tests/api/`.
4. Re-run the six quality gates; confirm no stray SQLite files (`scripts/check-stray-db`).
5. Record the Windows run ID in `.ai/STATE.json` only after it is green; until then the item stays OPEN / `IMPLEMENTED_PENDING_FIRST_CI_RUN`.

## 5. Non-goals

- No GUI/frontend work.
- No production rewrite to accommodate test-only assumptions (Groups A, D2, F, G2, H).
- No general newline/encoding refactor beyond the D1 write fix unless the owner expands scope; the adjacent read_text findings are recorded above, not scheduled here.
- No change to `PortManager.can_bind` without a Windows reproducer and an explicit decision, because it affects startup safety.

## 6. Owner decisions (resolved) and implementation result

1. **Group B**: owner chose to preserve POSIX-absolute paths on every platform. Implemented in `normalize_host_path` (return `posixpath.normpath` for `/`-prefixed input before the `win32` branch). DooD-on-Windows remains supported.
2. **Group E**: owner chose the `getattr(signal, "SIGKILL", signal.SIGTERM)` fallback so `LocalLinuxProvider` stays runnable on `win32`.
3. **F2/F3**: left `details["provider"]` as the resolved `provider_type`; tests now compare against `default_provider_for_platform()`.
4. **G1/G2**: hardened deterministically with mocks (`_capture_process_create_time`, `can_bind`, `get_pid_by_port`, `belongs_to_project`, `kill_on_port`, `is_open`). No production launcher change.
5. **Group H**: suppress/retry `PermissionError` in the shared API fixture teardown.
6. **Group C**: `assert_inside_root` now runs immediately after `normalize_host_path`, before `_ensure_image`; outside-path tests mock `_ensure_image` for isolation.

Implementation status per group: A, B, C, D1, D2, E, F, G, H applied. Linux regression run of the affected suites: `170 passed` (promote/btrfs/docker/dood/runtime/stage-c), `6 passed` (provider conformance start kwargs), `5 passed` (launcher log/retry/status), `3 passed` (start/restart timeout + settings mode), `163 passed` (`tests/api/`). Ruff baseline gate: OK, all at or below baseline.

Still required: Windows CI rerun of the 28 failed + 7 error node IDs and the full `windows-ci` backend job (see §4). Until green, the item stays `IMPLEMENTED_PENDING_FIRST_CI_RUN`; no Windows run ID yet.
