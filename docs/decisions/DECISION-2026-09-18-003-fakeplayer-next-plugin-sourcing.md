# DECISION-2026-09-18-003 — FakePlayer-Next Plugin Sourcing & Pre-Launch Staging (Fix 2)

**Date:** 2026-09-18  
**Status:** Accepted (2026-09-19)  
**Decision Level:** D1 (new external dependency origin + behavior change in test runs)  
**Lane:** Lane A (Release Critical, owner-confirmed)  
**Roadmap Drift:** Controlled  
**Supersedes/Relates:** Fix 1 / 1.5 (already implemented, D0); `SPEC-2026-09-15-ISOLATED-TEST-REAL-VERIFICATION-01 §3.1.2`  
**Evidence Base:** Recon #1, #2, #3; Spike Part 1 (`SPIKE-FAKEPLAYER-2026-09-18.md`) and Part 2 (`SPIKE-PART2-2026-09-19.md`) with independent reviews (`SPIKE-REVIEW-2026-09-18.md`, `SPIKE-PART2-REVIEW-2026-09-19.md`; raw logs archived under `docs/reports/_archive/` and `docs/reports/spike-logs-p2/`).  

---

## Context

Bot verification on Paper/Purpur test runs fails deterministically. Verified root causes (all FACT):

1. **RCON is disabled in test containers:** No RCON password is ever set.
2. **Post-boot installation:** The plugin is installed after the boot gate, so Paper never loads it.
3. **Placeholder artifact:** The "plugin" is a 30-byte placeholder; the download URL constant points at a nonexistent repo and tag.
4. **Command grammar drift:** The spawn command set is wrong for the real plugin: `fp action ...` does not exist in v0.4.4.
5. **No fail-fast strategy checking:** The strategy resolver picked `full_bot` / `fakeplayer_next` without checking that the artifact exists.
6. **Invalid bot naming:** Bot names of the form `onx-bot-<run>-<n>` are rejected by the plugin (`Invalid name` on hyphen).

Fix 1 / 1.5 (honest accounting, artifact fail-fast to `SMOKE_TEST`, config decoupling) is done and independently reviewed PASS. Until Fix 2 lands, Paper/Purpur bot verification downgrades to `SMOKE_TEST` by design.

---

## Evidence

| Concern | Evidence | Source |
|---|---|---|
| **CommandAPI resolution** | itzg automatically downloads `CommandAPI-12.0.0-Paper.jar` for Paper 26.2 when `MODRINTH_PROJECTS=commandapi`. Missing CommandAPI causes `UnknownDependencyException`. | `A-success.log:5`, `q2-modrinth.log:2,16`, `B-missing-dep.log:44-45` |
| **FakePlayer-Next artifact** | GitHub API exposes `digest: sha256:8de459b6...`, matching downloaded jar bit-for-bit. Manually staged jars survive reboots unmodified. | `r1-hashes.txt`, `r1-release.json:68-69`, `r2-plugins-before-after.txt:26-28` |
| **RCON environment handling** | Without RCON env vars, itzg overwrites staged passwords with random hex. When env vars are set, env wins. `rcon-cli` reads env with no flags and zero argv exposure. | `r4-staged-no-env.txt:2-9`, `r4-env-override.txt`, `r3-rcon-exec.txt:2-9` |
| **Command grammar** | Working grammar: `fp spawn <name>`, `fp move forward <name>`, `fp jump once/continuous <name>`, `fp stop <name>`. `fp action` does not exist. | `q4-rcon.txt:17-54`, `r7-fp-commands.txt:3-63` |
| **Bot names** | Hyphens are strictly rejected (`Invalid name`). Underscores and alphanumeric characters are accepted (`bot_seq_1`). | `r7-fp-commands.txt:40-47` |
| **`PLUGINS=<url>` env** | Valid URL downloads via `mcopy`, but bad URL (404) crashes container boot immediately with exit code 1. | `r5-plugins-url.log:4`, `r5-bad-url.log:1-2` |

---

## Options & Alternatives Considered

| Option | Verdict | Why |
|---|---|---|
| **A. Vendor jars in the repo** | Rejected (for now) | Binary blobs in git, manual update per MC line. Reconsider only if the upstream feed proves unreliable. |
| **B. `PLUGINS=<url>` for FakePlayer jar** | Rejected as primary | No backend-side digest check or cache; 404 URL crashes container initialization immediately (`r5-bad-url.log`). |
| **C. Own `PluginResolver` with loader × version × build table** | Rejected | Contradicts the no-hardcoded-versions constraint and duplicates what itzg already does for CommandAPI. |
| **D. Drop plugin path; Mineflayer for everything** | Rejected | Mineflayer is unreliable above 1.20.4 and requires an unbuilt npm bootstrap. Explicitly rejected for unsupported servers by owner decision. |
| **E. Backend-staged FakePlayer + itzg-resolved CommandAPI + runtime log verification** | **Accepted** | Smallest code surface; fails safe to `SMOKE_TEST`; zero secrets in argv or files. |

---

## Decision

Make FakePlayer-Next bot verification actually work for Paper/Purpur test runs, with no hardcoded Minecraft-version table, and with every failure degrading to `SMOKE_TEST` with a stated reason:

1. **CommandAPI Dependency:** Let the itzg container resolve it via `-e MODRINTH_PROJECTS=commandapi`. We never stage or pin CommandAPI ourselves.
2. **FakePlayer-Next Artifact:** Backend downloads it from GitHub release feed, verifies SHA-256 against release asset `digest` field, caches it by digest, and stages it into `plugins/` BEFORE `docker run`.
3. **Version Selection:** No version table in code. Server type gates eligibility (`paper`/`purpur` only). Version compatibility is proven at runtime by post-boot plugin-enabled log inspection; failure downgrades cleanly to `SMOKE_TEST` with reason.
4. **RCON Configuration:** Configure via container env only (`ENABLE_RCON=true`, `RCON_PORT`, `RCON_PASSWORD`); never write `rcon.password` to `server.properties`. Random throwaway password generated per run.
5. **Container Provisioning:** Pin `TYPE`, `VERSION` (and `PAPER_BUILD` if pinned) as env vars in test container. Pin the itzg image by digest (`itzg/minecraft-server:java25@sha256:dc7913a69c878594ff7b568862b2cd5541fac6e409d1dc86f0313b1ef7a4d9d4`).
6. **Command Grammar:** `fp spawn <name>`, then `fp move forward <name>`, `fp jump continuous <name>`, `fp stop <name>`. Strictly remove `fp action`.
7. **Bot Naming:** No hyphens. Use generated names composed of lowercase letters, digits, and underscores (`onx_bot_{run_id}_{i}`). Length <= 16.
8. **Staging Isolation:** Always ensure a clean `plugins/` directory before staging to prevent duplicate jar conflicts (e.g. duplicate CommandAPI causing ambiguous plugin errors).

---

## Why

This approach satisfies all governance constraints:
1. Zero hardcoded Minecraft version matrices.
2. Clean separation between container-level dependency resolution (CommandAPI via itzg) and verified test artifact staging (FakePlayer-Next via backend).
3. Fail-safe degradation: any network failure, checksum mismatch, or load failure cleanly falls back to `SMOKE_TEST` without failing the test platform.
4. Secrets hygiene: throwaway RCON passwords never touch disk or process argument vectors.

---

## Impact

- **Product/User:** Honest and functional bot verification on Paper and Purpur servers; test runs accurately exercise server ticks and entity spawning.
- **Stability:** High; missing dependencies or corrupt jars degrade safely to `SMOKE_TEST`.
- **Performance:** Negligible overhead; caching ensures GitHub release asset is downloaded at most once per unique digest. Boot time ~23–36s is well inside the 120s boot gate.
- **Architecture:** Preserves hexagonal boundaries and DDD aggregates; no DB migrations or contract changes required.
- **Operations:** Operator experience transitions from placeholder smoke fallbacks to verified `full_bot` runs when network access is available.

### Negative / Risks (Accepted):
- **Single-maintainer upstream plugin (4 stars):** Mitigated by digest pinning at download time, local content-addressable cache, and `SMOKE_TEST` fallback. No pinned tag: "latest release" is resolved dynamically, so an upstream bad release degrades to `SMOKE_TEST` rather than corrupting runs.
- **External network origins:** `api.github.com` (release metadata), GitHub release asset CDN, Modrinth CDN (via itzg).
- **GitHub API rate limiting:** Unauthenticated rate limit is 60 requests/hour; local cache is mandatory.
- **Image digest drift:** Image digest is pinned and updated deliberately as a reviewed change.

---

## Unknowns (Recorded, Not Blocking)

| Unknown | Handling |
|---|---|
| `PLUGINS=` 404 behavior | Not used; backend downloads and verifies artifact directly. |
| Password absence from process argv | Verified via `r3-rcon-exec.txt`; unit test asserts password never appears in `failure_reason`, logs, or command strings. |
| Bot-name rule details | Generator conservatively uses `[a-z0-9_]{3,16}`. |
| Support beyond Paper 26.2 b123 / FP 0.4.4 / CommandAPI 12.0.0 | Runtime log check decides; failure degrades to `SMOKE_TEST` with reason. No unbacked claims of broader support. |
| Future Modrinth resolution for new MC versions | Runtime log check: missing dependency degrades to `SMOKE_TEST` with reason. |

---

## Effort & Reversibility

- **Effort:** Controlled (Lane A, D1). Implementation touches ~4 backend infrastructure files and test fixtures.
- **Reversibility:** Easy. Reverting the Fix 2 commits cleanly returns Paper/Purpur bot verification to the Fix 1/1.5 state (`SMOKE_TEST` fallback). No database schema, migration, or route contract to unwind.

---

## Roadmap Impact

None. Fix 2 remains strictly within Lane A (Bug Remediation / Release Critical) and preserves the Phase 4 / Feature 1 scope definition without roadmap drift.

---

## Verification

1. Unit and regression tests verifying:
   - Dynamic asset digest verification against GitHub release JSON.
   - Cache hit/miss and content-addressable storage.
   - Spawn command formatting emitting `fp move forward`, `fp jump continuous`, `fp stop`, with underscore bot names.
   - Clean downgrade to `SMOKE_TEST` on simulated network error, 404, or corrupt digest.
2. Integration run against real itzg container verifying honest `passed=True` on Paper 26.2.
3. 6/6 CI quality gates pass.

---

## Governance & CI

- **No DB migration, no route/contract/schema/frontend change.**
- Gates at risk: `check-ruff-baseline` (100 cols limit) and `pytest`. Keep fixtures in `tmp` to avoid `check-stray-db` violations.
- D1 record committed to `docs/decisions/DECISION-2026-09-18-003-fakeplayer-next-plugin-sourcing.md`.
- `STATE.json` and `docs/current-state.md` updated with fresh measured metrics upon implementation.

---

## Outcome

*Pending implementation in Fix 2 (Commits ④⑤⑥).*
