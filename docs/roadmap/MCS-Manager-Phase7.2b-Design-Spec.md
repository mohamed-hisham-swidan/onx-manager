# BATCH 7.2b — DESIGN SPECIFICATION
# Panel Exposure: Playit HTTP Tunnel + Port Forwarding / UPnP

**Status:** IMPLEMENTED & VERIFIED (Batch 7.2b)
**Date:** 2026-08-15
**Authoritative Phase-7 roadmap:** `docs/roadmap/MCS-Manager-Phase7-Network-Access-Roadmap-v3.1.md` (§3.2, §7, §8).
**Prerequisites:** Batch 7.1 (`56cd384`), Batch 7.2a (`b357a5a`), Batch 7.2b RECON.

---

## 1. Scope & Objective

Batch 7.2b delivers the two alternative **Panel** exposure methods:
1. **playit.gg HTTP Tunnel**: TLS-terminated edge HTTP tunnel bound to the local Panel port.
2. **Port Forwarding + UPnP**: Single-action 'scan & attempt' IGD port mapping with Double-NAT detection and auto-fix alternate port retry.

Strict scope boundaries:
- **Backend-only**: Panel settings schema and commands extended; frontend is deferred to Batch 7.4.
- **Panel-only**: Per-server game exposure remains in Batch 7.3.
- **Single active method**: Only one exposure method may be active on the Panel at any time.

---

## 2. Core Architectural Decisions

| # | Decision | Details |
|---|---|---|
| **2.1** | **playit.gg HTTP Tunnel** | Subprocess supervision via `PlayitAgentSupervisor`. Secrets passed via `0600` config file (never on CLI argv). Non-interactive claim link extraction from stdout/stderr. |
| **2.2** | **UPnP Single-Action Wizard** | `AsyncUPnPService` executes SSDP discovery (3s bounded timeout), retrieves external IP, detects CGNAT/Double-NAT, and attempts mapping with up to 3 alternate-port retries. |
| **2.3** | **Error Handling & Auto-Fix** | Actionable short error messages. Port conflict triggers automatic retry on adjacent ports (`auto_fixed: true`). Double-NAT or missing UPnP returns clear guidance. |
| **2.4** | **Data Model Extension** | Migration `b1e2100000003` adds `external_port`, `playit_tunnel_id`, `upnp_last_result`, and `upnp_last_mapped_at` to `panel_exposure`. |
| **2.5** | **Security & Unencrypted HTTP** | `tls: false` and `protocol: "http"` returned for `port_forward` with security advisory on unencrypted WAN traffic. `require_owner()` enforced on all mutating panel routes. |
| **2.6** | **Subprocess Test Safety** | Hermetic `os.kill`/`os.killpg` mocking with safe mock sentinel PID `99999` and guaranteed `try...finally: await supervisor.stop()` teardown. |

---

## 3. Data Model & Migration (`b1e2100000003`)

The `panel_exposure` table is extended with 4 nullable columns:
- `external_port`: `INTEGER` (for `port_forward`)
- `playit_tunnel_id`: `VARCHAR(64)` (for `playit_http`)
- `upnp_last_result`: `VARCHAR(32)` (`SUCCEEDED`, `UPNP_UNSUPPORTED`, `DOUBLE_NAT_DETECTED`, `PORT_CONFLICT`)
- `upnp_last_mapped_at`: `DATETIME(timezone=True)`

---

## 4. API & Schema Contract

Existing routes reused without adding new endpoints:
- `GET /api/v1/exposure/panel` (`require_owner`)
- `PUT /api/v1/exposure/panel` (`require_owner`)

Request:
```json
{
  "method": "port_forward",
  "desired_state": "ENABLED",
  "external_port": 8080
}
```

Response:
```json
{
  "method": "port_forward",
  "desired_state": "ENABLED",
  "status": "ACTIVE",
  "public_address": "http://93.184.216.34:8080",
  "tls": false,
  "protocol": "http",
  "external_port": 8080,
  "upnp_last_result": "SUCCEEDED",
  "auto_fixed": false,
  "security_advisory": "Port forwarding exposes the panel over unencrypted HTTP while Access Mode is LOCAL. Open self-registration is exposed to the public Internet! Switch to GLOBAL (Invite-Only) mode in Settings -> Access to secure the instance."
}
```

---

## 5. Findings Ledger

| ID | Finding / Decision | Classification | Documentation Location | Code/Test Impact | Status |
|---|---|---|---|---|---|
| **F-72B-01** | `panel_bind_host` loopback mismatch: short-circuits port_forward activation on loopback with `BIND_MISMATCH` (superseded/extended by F-72B-05 auto-fix remediation) | **Architecture Decision** | `MCS-Manager-Phase7.2b-Design-Spec.md` | [`commands.py:654-672`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/application/commands.py#L654-L672), [`test_panel_playit_upnp_commands.py`](file:///mnt/D/files/server_manger/backend/tests/application/test_panel_playit_upnp_commands.py) | **SUPERSEDED by F-72B-05** |
| **F-72B-02** | `security_advisory` tailored based on `system_state.access_mode`: distinguishes LOCAL (open registration) from GLOBAL | **Security Decision** | `MCS-Manager-Phase7.2b-Design-Spec.md` | [`commands.py:925-946`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/application/commands.py#L925-L946), [`queries.py:60-66`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/application/queries.py#L60-L66) | **RESOLVED** |
| **F-72B-03** | Python stdlib `ipaddress` flags RFC 5737 TEST-NET IPs (`198.51.100.x`, `203.0.113.x`) as private | **Resolved Finding** | `MCS-Manager-Phase7.2b-Design-Spec.md` | [`test_panel_playit_upnp_infra.py:38`](file:///mnt/D/files/server_manger/backend/tests/infrastructure/test_panel_playit_upnp_infra.py#L38) uses public IPs | **RESOLVED** |
| **F-72B-04** | Alembic migration runner `env.py` calls `asyncio.run()`, requiring synchronous `def test_...` tests | **Resolved Finding** | `test_migration_panel_playit_upnp.py` | [`test_migration_panel_playit_upnp.py`](file:///mnt/D/files/server_manger/backend/tests/infrastructure/test_migration_panel_playit_upnp.py) structured synchronously | **RESOLVED** |
| **F-72B-05** | Auto-fix `panel_bind_host`: Automatically persists `panel_bind_host = "0.0.0.0"` to `config/settings.yaml` on loopback `BIND_MISMATCH`, returns `auto_fixed=True` and action-oriented restart hint | **UX Enhancement** | `MCS-Manager-Phase7.2b-Design-Spec.md` | [`settings_store.py`](file:///mnt/D/files/server_manger/backend/app/core/settings_store.py), [`config.py`](file:///mnt/D/files/server_manger/backend/app/core/config.py), [`commands.py`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/application/commands.py) | **AMENDED by F-72B-06** |
| **F-72B-06** | Active socket bind vs live settings distinction: `_enable_port_forward` checks frozen `get_active_panel_bind()` rather than mutable `LiveSettings`, preventing false `ACTIVE` state on un-restarted retries | **Bug / Architecture Fix** | `MCS-Manager-Phase7.2b-Design-Spec.md` | [`config.py:170-200`](file:///mnt/D/files/server_manger/backend/app/core/config.py#L170-L200), [`commands.py:656`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/application/commands.py#L656), [`test_panel_playit_upnp_commands.py`](file:///mnt/D/files/server_manger/backend/tests/application/test_panel_playit_upnp_commands.py) | **RESOLVED** |

