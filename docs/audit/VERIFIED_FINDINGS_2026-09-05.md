# Verified Findings - 2026-09-05 Audit

| ID | Original Confidence | Verdict | Corrected Description (if needed) | Verification Method |
|----|---------------------|---------|-------------------------------------|----------------------|
| F039 | FACT | CONFIRMED | (same as original) | Read sandbox.py:12-19; `str(target).startswith(str(self._plugin_dir))` without path separator check allows sibling directory traversal (e.g. `/opt/plugins/myplugin_other` passes check for `/opt/plugins/myplugin`) |
| F048 | FACT | CONFIRMED | (same as original) | Read runtime_ownership.py:291; `os.popen(f"tmux kill-session -t {session_name} 2>/dev/null")` uses unescaped shell interpolation and doesn't close pipe. While session_name is currently UUID-derived, the pattern is vulnerable to injection if input source changes. |
| F059 | FACT | CONFIRMED | (same as original) | Read files.py:158-174; `delete_file_or_dir` endpoint lacks `_assert_not_sensitive(target_path)` call present in read/write/upload endpoints, allowing deletion of .env, server.properties, etc. |
| F080 | FACT | CONFIRMED | (same as original) | Read handlers.py:167-177 and authentication.py:43-49; WS `refresh_token` handler accepts arbitrary token string and calls `WSAuthenticator.refresh_token()` which blindly updates token without any validation/verification against auth system. |
| F093 | FACT | CONFIRMED | (same as original) | Read Dockerfile:17; `COPY --chown=app:app . .` with no `.dockerignore` file present in repo root (verified via `ls -la .dockerignore` → not found), bundling .git, node_modules, .env, test caches into production image. |

---

**Tier 1 Security Summary: 5/5 CONFIRMED**

---

## Tier 2 — Data integrity / silent corruption

| ID | Original Confidence | Verdict | Corrected Description (if needed) | Verification Method |
|----|---------------------|---------|-------------------------------------|----------------------|
| F003 | FACT | CONFIRMED | (same as original) | Read base.py:53-56; `update()` calls `session.merge(entity)` but returns original `entity` instead of merged result. Caller receives detached entity. |
| F009 | FACT | CONFIRMED | (same as original) | Read unit_of_work.py:58-64; `commit()` publishes events in loop but if any publish fails, exception propagates, remaining events unpublished and `self._events.clear()` never reached. |
| F019 | FACT | CONFIRMED | (same as original) | Read chain.py:78; `verify_chain` initializes `prev_hash = ""` unconditionally. When `from_id > 1`, first event should use hash of `from_id - 1` event, not empty string. Always fails for `from_id > 1`. |
| F020 | FACT | CONFIRMED | (same as original) | Read repository.py:197-205; `replay_dead_letter` instantiates `EventBus()` with zero subscribers instead of using shared bus. Replayed events never reach actual subscribers. |
| F021 | FACT | CONFIRMED | (same as original) | Read dead_letter.py:72-74; `resolve()` calls `repo.resolve_dead_letter(event_id)` but returns `True` unconditionally, even if event_id doesn't exist. |
| F034 | FACT | CONFIRMED | (same as original) | Read repository.py:176-179; `save_classification` stores `classification.evidence_id` in `server_id` column (line 178), breaking server report lookups. |
| F050 | FACT | CONFIRMED | (same as original) | Read delete_server.py:45-76; `handle()` deletes DB record and filesystem dir (lines 51, 64) but never calls stop on active server, leaving orphaned JVM processes. |
| F068 | FACT | CONFIRMED | (same as original) | Read server_orchestrator.py:127-139; `_start_server` config only passes name, version, memory, port. Drops java_args, cpu_cores, cpu_affinity, env_vars, launch_config. |
| F077 | FACT | CONFIRMED | (same as original) | Read event_cleanup.py:19,27; retention params are in days (e.g. `rollup_1m_retention_days=30`) but passed to `timedelta(hours=ttl_hours)` (line 27). Purges 24x too aggressively (30 hours vs 30 days). |
| F090 | FACT | CONFIRMED | (same as original) | Read events.yaml:37-53; `backup.completed` defined twice (version 1 at lines 37-44, version 2 at 45-53). YAML duplicate key overwrites version 1. |
| F091 | FACT | CONFIRMED | (same as original) | Read plugin.yaml:41-59; `DISABLED` appears twice in states (lines 44, 48) and twice in transitions (lines 55, 59). Second transition at line 59 overwrites `ENABLING` from `DISABLED`. |
| F092 | FACT | CONFIRMED | (same as original) | Read config.schema.json:29-35; `java_args` typed as `string` (line 30) but code uses array/list. `provider_type` enum (line 35) omits `local_win`. |

---

**Tier 2 Summary: 12/12 CONFIRMED**

---

## Tier 3 — Core operational correctness (health/monitoring/lifecycle)

| ID | Original Confidence | Verdict | Corrected Description (if needed) | Verification Method |
|----|---------------------|---------|-------------------------------------|----------------------|
| F017 | FACT | CONFIRMED | (same as original) | Read feature_flags.py:55-79; `is_enabled` at line 79 returns `definition.enabled` (True) when `user_id=None`, `percentage>0`, `enabled=True`. The percentage rollout logic (lines 72-77) only executes when `user_id` is truthy, so unauthenticated requests bypass percentage check entirely. |
| F024 | FACT | CONFIRMED | (same as original) | Read collector.py:154-187; `_parse_tick_query` first regex (line 164-166) matches "Target tick rate" which is always 20.0 (the target), not actual TPS. It returns immediately at line 169, never reaching the second regex (line 173) that captures actual TPS ("with X ticks per second"). Lagging servers always report 20.0 TPS. |
| F025 | FACT | CONFIRMED | (same as original) | Read health.py:67-73; `check_database` passes raw string "SELECT 1" to `session.execute()` at line 70 without `text()`, raising SQLAlchemy 2.0 ArgumentError. The exception is caught and returns "down" status, so DB always reports as down. |
| F026 | FACT | CONFIRMED | (same as original) | Read health.py:76-88; `check_disk` hardcodes "/" in `shutil.disk_usage("/")` at line 80. On Windows, this fails (no root "/") or returns wrong drive. On multi-drive setups, only checks root partition, missing other drives. |
| F027 | FACT | CONFIRMED | (same as original) | Read health.py:91-99; `check_dlq_depth` takes unused `event_store` argument (line 91). If invoked with 0 args, raises TypeError. Query uses `limit=1` (line 96) but returns `len()` as total count, always returning 0 or 1 instead of actual depth. |
| F030 | FACT | CONFIRMED | (same as original) | Read health_calculator.py:36-39, 114-124; `NON_SKIPPABLE` only defines degradation paths (HEALTHY→{WARNING,CRITICAL}, WARNING→{CRITICAL,BROKEN}). `_apply_transition` (lines 114-124) applies these constraints to ALL transitions including recovery. When current=WARNING and target=HEALTHY (recovery), HEALTHY not in NON_SKIPPABLE[WARNING]={CRITICAL,BROKEN}, so it returns first allowed (CRITICAL). Healed server goes WARNING→CRITICAL instead of WARNING→HEALTHY. |
| F031 | FACT | CONFIRMED | (same as original) | Read integrity.py:111-135; `_check_modern_forge_layout` at line 116 only checks for `run_sh = srvd / "run.sh"` and `run_sh.is_file()`. No check for `run.bat` (Windows Forge). Windows servers with `run.bat` + `libraries/` fail the check at line 118 and get critical failure at lines 128-135. |
| F035 | FACT | CONFIRMED | (same as original) | Read server_crashed_handler.py:32; calls `self._collector.collect(server_id)` without `server_dir`. EvidenceCollector.collect() (evidence_collector.py:25) requires `server_dir` parameter; without it, `resolved_dir` is None, check at line 27 fails, returns EvidenceBundle with "Server directory not found" error. Evidence collection always fails. |
| F036 | FACT | CONFIRMED | (same as original) | Read generate_health_report.py:72; `worst = HealthStatusEnum.UNKNOWN`. status_score() at health_calculator.py:186-194 gives UNKNOWN=4, BROKEN=3, CRITICAL=2, WARNING=1. Comparison at lines 75-77 uses `>` (greater than). Since UNKNOWN=4 > BROKEN=3, no status ever replaces UNKNOWN as worst. Worst status always reports as UNKNOWN. |
| F038 | FACT | CONFIRMED | (same as original) | Read aggregate.py:18-31, 268-271; `PluginStatus.UNINSTALLED` exists in enum (line 23) but is absent from `_PLUGIN_TRANSITIONS` (lines 26-31). `mark_uninstalled()` (lines 268-271) emits event but never sets `self._status = PluginStatus.UNINSTALLED`. Transition to UNINSTALLED is impossible. |
| F041 | FACT | CONFIRMED | (same as original) | Read lifecycle.py:121-156; `on_heartbeat_missed` logs "restarting (attempt X/Y)" at line 141-146, but lines 147-155 transition to DISABLING, stop heartbeat, stop runner, then transition to DISABLED. No call to start or enable. Log message contradicts actual behavior — plugin is disabled, not restarted. |
| F042 | FACT | CONFIRMED | (same as original) | Read subprocess.py:112-116; `restart()` calls `await self.stop(plugin_id)`, sets `manifest = {}`, logs "Plugin %s restarted", but never calls `start()` or any method to spawn a new process. The method is a no-op after stop. |
| F045 | FACT | CONFIRMED | (same as original) | Read aggregate.py:7-10, 120-121; `ApiKeyRevokedEvent` imported at line 9 but `revoke()` (lines 120-121) only sets `self._is_revoked = True` and never emits `ApiKeyRevokedEvent`. |
| F047 | FACT | CONFIRMED | (same as original) | Read playit_agent.py:702-727; `_terminate_pid_direct` at lines 712-715 calls `os.kill(pid, signal.SIGTERM)` on Windows. `signal.SIGTERM` doesn't exist on Windows (AttributeError). The `except OSError` at line 714 doesn't catch `AttributeError`. |
| F049 | FACT | CONFIRMED | (same as original) | Read supervisor.py:458-477; `_cleanup_os_resources` at lines 463, 471 uses `os.popen(f"tmux has-session -t {session_name} 2>/dev/null")` and `os.popen(f"tmux kill-session -t {session_name} 2>/dev/null")` with unescaped shell interpolation and doesn't close pipe. |
| F051 | FACT | CONFIRMED | (same as original) | Read main.py:388-398; CORSMiddleware added first (line 388-394) making it innermost in Starlette stack. AuthMiddleware (line 396) and RateLimitMiddleware (line 398) return early with JSONResponse on 401/429, but CORSMiddleware is innermost and never sees those responses to add CORS headers. |
| F052 | FACT | CONFIRMED | (same as original) | Read middleware/auth.py (full file, 99 lines); `dispatch` has no OPTIONS bypass. Preflight OPTIONS requests without Authorization header fall through to lines 55-63 and return 401. |
| F053 | FACT | CONFIRMED | (same as original) | Read middleware/auth.py:26-28, 39-40; `_public_prefixes = {"/api/v1/schedules"}` with early `call_next` return. All schedule routes skip middleware auth-header check and Content-Type validation. (Route-level `require_permission` still applies downstream; verdict scoped to middleware gate as described.) |
| F054 | FACT | CONFIRMED | (same as original) | Read errors.py:57-66; `_error_response` emits `error/error_code/detail/timestamp`. contracts/api.yaml `error_format` specifies `code/message/details/request_id/retryable`. Key names diverge; `request_id`/`retryable` absent. |
| F055 | FACT | CONFIRMED | (same as original) | Read middleware/request_id.py (full file, 13 lines); `dispatch` generates ID (line 10), calls downstream (line 11), sets response header (line 12). No `request.state.request_id` assignment. Downstream handlers cannot access the ID. |
| F056 | FACT | CONFIRMED | (same as original) | Read schemas/common.py:18-22; `PaginatedResponse` has `items/total/page/page_size`. contracts/api.yaml specifies pagination `page/per_page/total/total_pages` plus envelope `data/pagination`. `page_size` vs `per_page` mismatch; `total_pages` missing. |
| F057 | FACT | CONFIRMED | (same as original) | Read routers/auth.py:146-157; `revoke_api_key` does `await command_bus.send(RevokeApiKeyCommand(...))` with no result capture and no `check_command_result`. Returns None → 204 regardless of command outcome. |
| F058 | FACT | CONFIRMED | (same as original) | Read routers/exposure.py:208-215, 320-332; `remove_server_exposure` and `delete_server_port` both `await command_bus.send(...)` with no result capture and no `check_command_result`. Both return None → 204 regardless of outcome. (DELETE/204 idempotency policy N/A: defect is swallowed command errors, not 204-vs-404 on missing resources.) |

---

**Tier 3 Summary: 23/23 CONFIRMED**

---

## Tier 4 — Remaining FACT findings

| ID | Original Confidence | Verdict | Corrected Description (if needed) | Verification Method |
|----|---------------------|---------|-------------------------------------|----------------------|
| F001 | FACT | CONFIRMED | (same as original) | Read config.py:53; `model_config = {"env_prefix": "MCS_", "extra": "ignore"}`. Pydantic settings only reads `MCS_*` env vars; `ONX_*` vars are ignored. |
| F004 | FACT | CONFIRMED BUT MISDESCRIBED | Code constant matches reality; STATE.json has the typo. `RELEASE_MINIMUM_DB_REVISION = "b1e2100000010"` (db_revision.py:30) matches the real migration file `b1e2100000010_add_server_cpu_allocation.py` (`revision = "b1e2100000010"`). STATE.json `alembic_head` is `"b1e210000010"` (one zero short, matches no real file). Zero counts in original description are off by one (code: 6 zeros, STATE: 5 zeros, not 7 vs 6). | Compared db_revision.py:30 vs STATE.json `alembic_head` vs `ls backend/alembic/versions/` + `grep ^revision`; counted zeros programmatically. |
| F005 | FACT | CONFIRMED | (same as original) | Read event_bus.py:60-72, 96-109; `subscribe()` sorts by priority (line 71), but `publish()` builds all dispatch coroutines and runs them via `asyncio.gather(*tasks)` (lines 108-109). All subscribers execute concurrently; priority order does not serialize or prioritize execution. |
| F014 | FACT | CONFIRMED | (same as original) | Read saga.py:134-165; timeout path (lines 137-145) sets FAILED and returns without `_compensate`. Step-failure path (lines 155-165) calls `await self._compensate(instance, i)`. Completed steps before a timeout are never compensated. |
| F018 | FACT | CONFIRMED | (same as original) | Read shared/value_objects.py:144-160; `__lt__` (lines 144-151) never compares `build` metadata; no custom `__eq__`, so frozen-dataclass eq includes `build`. For versions differing only by build: `a<b` False, `a==b` False → `__gt__` (`not (self<=other)`) True both ways. Strict weak ordering violated. |
| F023 | FACT | CONFIRMED | (same as original) | Read storage/s3.py:80-96; `delete` (lines 82-87) and `exists` (lines 91-96) wrap the whole S3 call in `except Exception: return False`. Credential, IAM, network, and config errors are indistinguishable from not-found/delete-failed. |
| F028 | FACT | CONFIRMED | (same as original) | Read restore_service.py:166-186; `_atomic_replace_dir` calls `os.replace()` on directory paths (lines 177, 179). On Windows `os.replace` on directories raises (MoveFileEx REPLACE_EXISTING does not replace directories). POSIX-only logic. |
| F029 | FACT | CONFIRMED | (same as original) | Executed isolated script: two `RestoreBackupCommand` instances share the identical `IdempotencyKey` object (`is` → True, same value). Counted 35 occurrences of `idempotency_key = IdempotencyKey()` across command classes (grep). Class-level mutable default evaluated once at class definition. |
| F040 | FACT | CONFIRMED | (same as original) | Read dependency_resolver.py:62-127; `visited` added at line 107, discarded only on failure path (line 117); success path (line 121) pops `chain` but never discards `visited`. Executed isolated script: diamond A→B→D, A→C→D fails with false "Circular dependency detected" on D. |
| F063 | FACT | CONFIRMED | (same as original) | Read routers/marketplace.py:45-52 (no try/except around `provider.get_project`); providers/modrinth.py:123-124, 253-288 (`_get_json` retries MODRINTH_MAX_RETRIES=2 → 3 attempts, `_do_get_json` raises `DownloadError(url, 404)` on non-200); grep confirms no `DownloadError` handler in api/errors.py. 404 bubbles as unhandled 500. |
| F064 | FACT | CONFIRMED | (same as original) | Read routers/monitoring.py:74-86; `list_alerts` returns hardcoded `[]` (line 78); `delete_alert_rule` body is `pass` (line 86) → 204. Both endpoints are unimplemented stubs. (DELETE/204 policy N/A: defect is that delete is a complete no-op even for existing rules, per dead-code category.) |
| F070 | FACT | CONFIRMED | (same as original) | Read backup_orchestrator.py:204-223; `_wait_for_save_confirmed` polls `provider.console(tail=200)` and returns on first `_SAVE_CONFIRMED_RE` match. No baseline of console length before issuing save-all, so a stale historical "Saved the game/world" line satisfies the check immediately without waiting for the current save. |
| F072 | FACT | CONFIRMED | (same as original) | Read tasks/arq_queue.py (full file, 76 lines); `import aredis` at line 18 (unmaintained aioredis fork); `get_status` hardcoded `return TaskStatus.PENDING` (lines 66-67); `get_result` hardcoded `return None` (lines 69-70). Stub implementations. |
| F073 | FACT | CONFIRMED | (same as original) | Read tasks/queue.py:37-62, 111-118, 138-149; `cancel()` (lines 111-118) flips DB row to CANCELLED only. Live `asyncio.Task` in `_background_tasks` (lines 42, 44-62) is never cancelled. `_execute` unconditionally sets RUNNING (lines 143-149), overwriting CANCELLED when the task runs. |
| F076 | FACT | CONFIRMED | (same as original) | Read definitions/cleanup_task.py:43-57; `delete("event_store")` (line 46) and `delete("task_queue")` (line 54) pass string literals. Executed `delete('event_store')` in isolation → `ArgumentError: subject table for an INSERT, UPDATE or DELETE expected, got 'event_store'`. |
| F078 | FACT | CONFIRMED | (same as original) | Read definitions/discovery_scan.py:14-15 (`params["event_bus"]`) and definitions/health_check_task.py:11-12 (`params["registry"]`); both require live in-memory objects. queue.py:90-99 (`enqueue` stores `params_json=json.dumps(params)`) and queue.py:192 (`reclaim_pending` does `json.loads`) prove params travel via JSON/DB. Live objects cannot survive that round-trip (`json.dumps` of them raises TypeError at enqueue). |
| F079 | FACT | CONFIRMED | (same as original) | Read definitions/metrics_collector.py:22-28 (`init_collector(collector, prometheus=None)`) + main.py:247 (alias `init_collector as init_metrics_collector`) and main.py:279 (`init_metrics_collector(metrics_collector)` — no prometheus arg). `_run_collection` lines 58-65 only touches Prometheus when `_prometheus is not None`. Prometheus TPS/RAM/CPU gauges never update. |
| F084 | FACT | CONFIRMED | (same as original) | Read start.bat (full file, 28 lines); lines 16-19 delegate to `%~dp0onx.exe` immediately when present, skipping the start.ps1 Python bootstrap (line 27). Any local Python source changes are bypassed while the stale binary exists. |
| F087 | FACT | CONFIRMED BUT MISDESCRIBED | Bare `ruff check .` fails and breaks `scripts/check` + `scripts/release` (both `set -euo pipefail`; check calls `./scripts/lint`). But live count is 504 errors, not 340 (drift since the original scan). | Read scripts/lint (5 lines), scripts/check (calls `./scripts/lint` under `set -euo pipefail`), scripts/release:16 (calls `./scripts/check`); ran `ruff check .` in backend → "Found 504 errors". |
| F088 | FACT | CONFIRMED | (same as original) | Read scripts/release (full file, 29 lines); `git tag -a` + `git push origin` at lines 19-20 run before `./scripts/build` at line 23. Under `set -euo pipefail`, a build failure still leaves the tag pushed to origin. |
| F094 | FACT | CONFIRMED | (same as original) | Read frontend/nginx.conf (full file, 59 lines); no `client_max_body_size` directive anywhere. Nginx default is 1MB, so server ZIP imports and file uploads over 1MB get HTTP 413. |
| F095 | FACT | CONFIRMED | (same as original) | Read stores/authStore.ts:73-78; `logout()` clears auth, resets API singleton, clears queryClient — but never touches `useActivityStore` or `useProvisionProgressStore` (both exist in stores/). Event/progress history survives logout and leaks across sessions. |
| F096 | FACT | CONFIRMED | (same as original) | Read hooks/useProvisionProgress.ts:22 (subscribes `provision:${serverId}`); backend authorization.py:88 (`valid_prefixes` = 7 entries, no "provision") with INVALID_CHANNEL rejection at handlers.py:134. Backend `validate_channel` rejects the frontend's provision channel. |
| F097 | FACT | CONFIRMED | (same as original) | Read websocket/channels.ts:132-137 (frontend `validateChannel` requires `parts.length === 2`); backend authorization.py:86-93 accepts 3-segment `server:<id>:console` (and CHANNEL_PATTERNS includes `server:{server_id}:console`). Frontend's own validator rejects a backend-supported channel. |
| F098 | FACT | CONFIRMED | (same as original) | Read ServerFilesPage.tsx:46-69; `syncedFileParam` set at line 49 but `handleCloseEditor` (lines 60-69) resets `editingFile`, `userEdited`, and URL params — never `syncedFileParam`. Guard at line 48 (`fileParam !== syncedFileParam`) stays false, so re-selecting the same file URL param never reopens the editor. |

---

**Tier 4 Summary: 25/25 verified (23 CONFIRMED, 2 CONFIRMED BUT MISDESCRIBED: F004, F087)**

---

## Grand totals — all 65 FACT rows

- Reached: 65/65
- CONFIRMED: 63
- CONFIRMED BUT MISDESCRIBED: 2 (F004, F087)
- REFUTED: 0
- UNABLE TO VERIFY: 0
