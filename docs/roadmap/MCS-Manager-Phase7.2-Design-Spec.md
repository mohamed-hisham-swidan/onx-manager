# BATCH 7.2a — DESIGN REVISION SPECIFICATION
# Cloudflare Panel Exposure (DESIGN ONLY — NO IMPLEMENTATION)

**Status:** DESIGN READY FOR IMPLEMENTATION (post-RECON revision)
**Date:** 2026-08-14
**Authoritative Phase-7 roadmap:** `docs/roadmap/MCS-Manager-Phase7-Network-Access-Roadmap-v3.1.md` (§6b amended by the 7.2a RECON: §6b.1–§6b.4).
**Base / prerequisite:** Batch 7.1 — **COMMITTED** (`56cd384`). Migration `b1e2100000001` live. `PanelExposure` aggregate, `SQLPanelExposureRepository`, `SetPanelExposureCommand/Handler`, and `GET/PUT /api/v1/exposure/panel` routes exist.
**This document does NOT implement anything.** No code, no migrations, no SQLAlchemy model changes, no routes, no API schema changes, no frontend, no contracts changes are authorized in this batch.

---

## 1. Scope

Batch 7.2a design revision covers **only** the design decisions required to unblock implementation of Cloudflare Panel Exposure, per the 7.2a RECON:

1. **Decision 1 — Cloudflare URL model:** Custom-domain-only.
2. **Decision 2 — Cloudflare credential storage:** extend `PanelExposure`, not a generic credentials subsystem.
3. **Decision 3 — Panel bind address:** single authoritative configuration source.
4. **Decision 4 — Panel permission:** explicit Owner-only authorization.

Batch 7.2a implementation (future, deferred) will add: Named-Tunnel orchestration, token intake, CNAME creation for the tunnel only, `cloudflared` subprocess supervision, `RECLAIM_REQUIRED` handling. None of that is designed in detail here beyond what is needed to fix the four RECON blockers.

---

## 2. Locked Decisions (from v3.2 + RECON — DO NOT CHANGE)

| # | Decision | Source |
|---|---|---|
| 2.1 | Cloudflare is the **primary** Panel exposure method (`cloudflare_tunnel`). | Roadmap v3.2 |
| 2.2 | `panel_exposure` is the network switch; **MODEL B** — `access_mode` (registration/auth) and `panel_exposure` (network) are strictly separated. Changing one never changes the other. | Roadmap v3.2, 7.1 spec §3.4 |
| 2.3 | Credential encryption = **AES-GCM `BackupEncryption`** (`app/modules/storage/encryption.py`), key via `load_or_create_backup_key`. Fernet excluded. | v3.2 (2026-08-13) |
| 2.4 | **Custom-domain-only** — no Quick Tunnel / `trycloudflare.com` fallback. | **RECON 7.2a / Decision 1** |
| 2.5 | Credential storage on the `panel_exposure` row — **no generic credentials table**. | **RECON 7.2a / Decision 2** |
| 2.6 | Panel bind derived from one authoritative config field, localhost-only ingress. | **RECON 7.2a / Decision 3** |
| 2.7 | Panel GET/PUT routes enforce **`require_owner()`** at the dependency; permission-string only is NOT sufficient. | **RECON 7.2a / Decision 4** |
| 2.8 | `--token-file` (not `--token`) for the `cloudflared` subprocess (VULN-118896 hardening). | **RECON 7.2a / §1 (cloudflared)** |
| 2.9 | Orchestrate-only: MCS never bundles the `cloudflared` binary. | Roadmap §8.5 |

---

## 3. Decision 3 — Panel Bind Address (authoritative source)

**Verification performed (read-only):**
- `backend/Dockerfile` runs `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- `docs/getting-started.md` runs `uvicorn app.main:app --reload --port 8000`.
- `backend/app/core/config.py` `AppSettings` has **no host/port/bind field** for the Panel.
- `backend/app/core/settings_store.py` `LiveSettings` / `_DEFAULTS` has **no port field**.

**Conclusion:** there is **no existing authoritative Panel-bind configuration**. The port is currently a uvicorn command-line literal. Decision 3 therefore introduces a single configuration field.

**Design:**

| Item | Value |
|---|---|
| Config owner | `backend/app/core/config.py` — `AppSettings` (env prefix `MCS_`) |
| New fields | `panel_bind_host: str = "127.0.0.1"` · `panel_bind_port: int = 8000` |
| Env overrides | `MCS_PANEL_BIND_HOST` / `MCS_PANEL_BIND_PORT` |
| Default | `127.0.0.1:8000` |
| Authoritative reader | one module-level accessor (single source of truth); Cloudflare code derives the ingress from it |
| Ingress target | `http://{panel_bind_host}:{panel_bind_port}` — **must be a loopback/local address**; `0.0.0.0` is rejected as a tunnel ingress target |
| Validation | `panel_bind_host` must resolve to loopback (127.0.0.0/8 or ::1) for Cloudflare ingress purposes |

**Documented default:** `127.0.0.1:8000`.

No `:8000` literals are introduced into Cloudflare code; all ingress computation reads the config accessor.

---

## 4. Decision 2 — Updated `panel_exposure` Schema

Extends the existing single-row singleton. No new table.

| Column | Type | Nullable | Default | 7.1? | Notes |
|---|---|---|---|---|---|
| `id` | String(36) PK | no | `"default"` | yes | Singleton (mirrors `SystemStateModel`) |
| `method` | String(32) | no | `"none"` | yes | `none \| cloudflare_tunnel \| playit_http \| port_forward` |
| `desired_state` | String(16) | no | `"DISABLED"` | yes | `ENABLED \| DISABLED` |
| `status` | String(32) | no | `"DISABLED"` | yes | 9-state vocabulary |
| `public_address` | String(512) | yes | NULL | yes | User-facing hostname (the user's own domain) |
| `error_code` | String(64) | yes | NULL | yes | e.g. `RECLAIM_REQUIRED` evidence |
| `error_message` | Text | yes | NULL | yes | — |
| `cloudflare_tunnel_id` | String(64) | yes | NULL | **new (7.2a)** | Non-secret tunnel UUID metadata |
| `cloudflare_token_ciphertext` | LargeBinary | yes | NULL | **new (7.2a)** | AES-GCM(nonce\|ciphertext) of the tunnel token |
| `created_at` / `updated_at` | per mixin | no | now | yes | — |

**Credential rules (Decision 2):**
- Plaintext token is **never persisted**, **never returned by any API**, **never logged**.
- `cloudflare_tunnel_id` is non-secret metadata — safe in status responses.
- Rotation: encrypt the new token → replace `cloudflare_token_ciphertext` (overwrite).
- DELETE exposure / Cloudflare removal → set `cloudflare_token_ciphertext = NULL`, clear `cloudflare_tunnel_id` and `public_address`.
- Revoked/invalid token → `RECLAIM_REQUIRED`; **no auto-reissuance**; owner explicitly provides a new token.
- **No generic credentials table.**

---

## 5. Decision 4 — Panel Authorization Path

**Verification performed (read-only):**
- `backend/app/api/deps.py`: `require_permission` returns success if `admin:full` is present **or** the literal permission matches (`lines 96-99`).
- `backend/app/api/v1/routers/exposure.py`: both panel routes (`GET`, `PUT /exposure/panel`) use `require_permission("exposure.panel.manage")`.
- `bootstrap_instance.py`: Owner bootstrap grants roles `[admin:full, global:*]`.
- `require_owner` (`deps.py`) accepts only the `owner` role or a `global.*` claim — `admin:full` alone is NOT enough.

**Conclusion:** today, an admin with `admin:full` (short-circuit) can toggle Panel exposure — broader than the Owner-only contract.

**Selected option — (A) make the dependency explicitly owner-only:**

```
GET  /api/v1/exposure/panel   → Depends(require_owner())
PUT  /api/v1/exposure/panel   → Depends(require_owner())
```

- `require_owner()` (existing helper) = the `owner` role or a `global.*` permission claim. `admin:full` alone is **insufficient**.
- The `exposure.panel.manage` string remains documented (contract clarity, audit trail) but is **not** the route-gating mechanism.
- No other grant path broadens access. This is unambiguous Owner-only, matching the approved contract.

---

## 6. Decision 1 — Cloudflare URL Model (Custom-Domain-Only)

**Locked model:**

| Aspect | Decision |
|---|---|
| Address options | Exactly one: the **user-provided Cloudflare-managed hostname** |
| Quick Tunnels / `trycloudflare.com` | **Not implemented** (no fallback) |
| Direct `*.cfargotunnel.com` | **Never surfaced** as a stable user-facing URL (it is not browsable anyway — CNAME target only) |
| User input required | Hostname/domain + Cloudflare API token (Tunnel Edit + DNS Edit scopes) |
| DNS writes | **Strictly limited** to the `CNAME` (proxied, `name=<user hostname>`, `content=<tunnel_id>.cfargotunnel.com`) for the MCS-created tunnel |
| General DNS/domain management | **Phase 8** — out of scope for 7.2a |

**Explicit documentation (per RECON):**
- No stable no-DNS named-tunnel URL exists for this product flow.
- 7.2a therefore requires the domain/hostname input.
- DNS writes are strictly limited to the MCS-created tunnel CNAME.

---

## 7. Cloudflare Lifecycle

- **create** — `POST /accounts/{account_id}/cfd_tunnel` `{"name", "config_src":"cloudflare"}` → `{id, token}`; persist `cloudflare_tunnel_id` + AES-GCM `cloudflare_token_ciphertext`.
- **configure ingress** — `PUT .../cfd_tunnel/{tunnel_id}/configurations` with `ingress:[{hostname:"<user hostname>", service:"http://{panel_bind_host}:{panel_bind_port}"}, {service:"http_status:404"}]` (catch-all mandatory).
- **DNS CNAME** — `POST /zones/{zone_id}/dns_records` `{type:CNAME, proxied:true, name:"<user hostname>", content:"<tunnel_id>.cfargotunnel.com"}`. Only DNS write allowed.
- **run** — `cloudflared tunnel run --token-file <root-restricted path>` as a child subprocess (orchestrate-only). `--token-file` hard-required (2.8).
- **health** — probe cloudflared metrics (`127.0.0.1:20241–20245`) or watch "Registered tunnel connection" log lines; feed §6a.1 thresholds (30s interval / 90s stale → `DEGRADED`; hard failure → `ERROR`).
- **RECLAIM_REQUIRED** — revoked/invalid token → subprocess failure evidence → `RECLAIM_REQUIRED`, stop, persist; **never** silent retry/auto-reissue.
- **credential replacement** — owner provides a new token → rotate ciphertext → resume run.
- **disable/remove** — `desired_state=DISABLED` or Cloudflare removal → kill subprocess, clear stored secret (`cloudflare_token_ciphertext=NULL`, `cloudflare_tunnel_id=NULL`, `public_address=NULL`).

---

## 8. Phase Boundary (7.2a vs Phase 8)

| Concern | 7.2a | Phase 8 |
|---|---|---|
| Cloudflare API as tunnel control plane | Yes (create tunnel, set ingress, run) | No |
| DNS CNAME for the MCS-created tunnel | Yes (the only DNS write) | No |
| General DNS/domain management (zones, records UI, provider abstraction) | **No** | Later |
| `access_mode` semantics | Never touched (MODEL B) | — |
| Frontend | None in 7.2a (Batch 7.4) | — |

---

## 9. Remaining Design Blockers

| # | Blocker | Status |
|---|---|---|
| 1 | ~~No stable no-DNS URL~~ → resolved by **Decision 1** (custom-domain-only) | **RESOLVED** |
| 2 | ~~No schema home for Cloudflare token~~ → resolved by **Decision 2** (two `panel_exposure` fields) | **RESOLVED** |
| 3 | ~~Implicit :8000 bind~~ → resolved by **Decision 3** (`panel_bind_host/port` config) | **RESOLVED** |
| 4 | ~~Panel route not strictly Owner-only~~ → resolved by **Decision 4** (`require_owner()`) | **RESOLVED** |
| 5 | *New (from §1):* `--token-file` vs `--token` hardened path | Incorporated (2.8) |
| 6 | **Not a blocker:** live Cloudflare API tests require real account/credentials — scheme verified against primary docs; concrete API response diffs verified live at implementation time | noted |

**No genuine unresolved design blockers remain.**

---

## 10. Final Verdict

**DESIGN READY FOR IMPLEMENTATION.**