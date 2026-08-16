# MCS Manager — Phase 7.3d Design Specification
# Backend: Bedrock/UDP Targets & Companion-Service Ports

**Authoritative Governing Plan:** `docs/roadmap/MCS-Manager-Phase7-Network-Access-Roadmap-v3.1.md` (§4.2, §4.3, §10 Batch 7.3d)  
**Status:** DESIGN ONLY — PENDING INDEPENDENT REVIEW  
**Date:** 2026-08-15  
**Version:** 1.0.0  

---

## 1. Scope and Boundary

### 1.1 Objective
Extend the game-server exposure subsystem to support Minecraft Bedrock (UDP) and roadmap-approved companion services (Simple Voice Chat, BlueMap) across multiple targets on a single server, while strictly maintaining:
1. The **"no arbitrary ports"** security invariant (Roadmap §4.3).
2. The **single-method-per-server** architectural invariant (Roadmap §4.2).
3. The **port deny-list** enforcement (RCON, database, internal metrics).
4. The **provider transport capability matrix** (e.g. Cloudflare Named Tunnels reject UDP targets).
5. **100% backward compatibility** for all existing Java/TCP exposure behavior and tests (Batches 7.1–7.3c).

### 1.2 In-Scope
1. **Multi-Row Port Registry (`server_registered_ports`):** Store non-primary ports (Bedrock, Voice Chat, BlueMap) in a dedicated database table (Decision A) without altering `ServerModel.port` as the primary Java port authority.
2. **Domain Enum Extensions:**
   - Extend `TargetProtocol` to include `UDP = "udp"`.
   - Extend `ServiceType` to include `BEDROCK = "bedrock"`, `VOICE = "voice"`, and `BLUEMAP = "bluemap"`.
3. **Aggregate Multi-Target Relaxation (Decision B):**
   - Relax the 1-target limit in `ServerExposure` to allow multiple concurrent targets per server bounded by the registered service allow-list.
   - Generalize `validate_target_port()` to validate ports against `ServerModel.port` (for Java) or `server_registered_ports` (for companions), while enforcing `DENY_LIST_PORTS`.
4. **Provider Capability Matrix Enforcement:**
   - **playit.gg (`playit`):** Supports both TCP and UDP targets via the shared host agent.
   - **Port Forwarding (`port_forward` / UPnP):** Supports both TCP and UDP mappings via `AsyncUPnPService`.
   - **Cloudflare TCP (`cloudflare_tcp`):** Strictly TCP-only; rejects UDP targets at API and handler layers with HTTP 422 `METHOD_PROTOCOL_INCOMPATIBLE`.
5. **API Schemas & Endpoints:**
   - Extend `TargetCreateRequest` with optional `service_type`, `protocol`, and `local_port` fields with safe backward-compatible defaults (`java`/`tcp`/`ServerModel.port`).
   - Add port registration management endpoints: `GET /servers/{id}/ports`, `POST /servers/{id}/ports`, `DELETE /servers/{id}/ports/{port_id}`.
6. **Alembic Migration (`b1e2100000005`):** Create `server_registered_ports` table chaining from `b1e2100000004`.
7. **Comprehensive Test Suite:** 24+ isolated acceptance tests covering multi-target lifecycle, UDP Bedrock exposure, companion validation, capability rejections, and zero-regression verification for 7.1–7.3c.

### 1.3 Out-of-Scope (Hard Boundaries)
- **Arbitrary Port Forwarding:** User-defined unclassified ports are strictly prohibited (§4.3).
- **Mixed Methods per Server:** A single server cannot expose Java via playit and Bedrock via UPnP simultaneously (Roadmap §4.2); all targets on a server share the server's selected exposure method.
- **Frontend UI (Batches 7.4 & 7.5):** All web UI forms, companion port pickers, and status cards belong to Batches 7.4 and 7.5.
- **General DNS Management (Phase 8):** No custom DNS records, SRV records, or zone management products.
- **Automatic Filesystem Mod Discovery:** Parsing server configuration files or jar files for port discovery is deferred to future plugin management; 7.3d manages ports via the explicit database registry.

---

## 2. Port Storage Model (`server_registered_ports`)

### 2.1 Coexistence with `ServerModel.port` (Decision A)
To ensure clean single-source-of-truth semantics and future extensibility:
1. **Primary Java Port:** `ServerModel.port` remains the sole authoritative source for the Minecraft Java game server port (`service_type == ServiceType.JAVA`, `protocol == TargetProtocol.TCP`).
2. **Secondary / Companion Ports:** All non-primary services (`BEDROCK`, `VOICE`, `BLUEMAP`) are stored in `server_registered_ports`.
3. **No Duplicate Java Port Records:** `server_registered_ports` prohibits `service_type == 'java'` to prevent conflicting sources of truth.

### 2.2 Table Schema

```sql
CREATE TABLE server_registered_ports (
    id VARCHAR(36) PRIMARY KEY,
    server_id VARCHAR(36) NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    service_type VARCHAR(32) NOT NULL,
    protocol VARCHAR(8) NOT NULL,
    port INTEGER NOT NULL,
    name VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_server_service_type UNIQUE (server_id, service_type),
    CONSTRAINT uq_server_port_protocol UNIQUE (server_id, port, protocol)
);

CREATE INDEX ix_server_registered_ports_server_id ON server_registered_ports (server_id);
```

### 2.3 Field Specifications

| Column | Type | Nullable | Description |
|---|---|:---:|---|
| `id` | `VARCHAR(36)` | No | Unique UUID primary key. |
| `server_id` | `VARCHAR(36)` | No | Owning server foreign key (`servers.id`), CASCADE on delete. |
| `service_type` | `VARCHAR(32)` | No | Service identifier (`bedrock`, `voice`, `bluemap`). |
| `protocol` | `VARCHAR(8)` | No | Transport protocol (`tcp`, `udp`). |
| `port` | `INTEGER` | No | Local service port (1..65535, outside deny-list). |
| `name` | `VARCHAR(64)` | Yes | Optional human-readable display label. |
| `created_at` | `TIMESTAMP` | No | Creation timestamp (UTC). |
| `updated_at` | `TIMESTAMP` | No | Last update timestamp (UTC). |

---

## 3. Domain Model Extensions

### 3.1 Value Objects Extension

```python
# backend/app/modules/exposure/domain/value_objects.py

class TargetProtocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"


class ServiceType(StrEnum):
    JAVA = "java"
    BEDROCK = "bedrock"
    VOICE = "voice"
    BLUEMAP = "bluemap"
```

### 3.2 Protocol-to-Service Affinity Rules

Every service type is bound to an authoritative default transport protocol and port policy:

| Service Type | Protocol | Default Port | Storage Location | Notes |
|---|:---:|:---:|:---:|---|
| **`JAVA`** | `TCP` | `ServerModel.port` (25565) | `ServerModel.port` | Authoritative Java game port. |
| **`BEDROCK`** | `UDP` | `19132` | `server_registered_ports` | Bedrock RakNet protocol. |
| **`VOICE`** | `UDP` | `24454` | `server_registered_ports` | Simple Voice Chat voice stream. |
| **`BLUEMAP`** | `TCP` | `8100` | `server_registered_ports` | BlueMap web map viewer. |

### 3.3 Domain Aggregate Hierarchy

```
+--------------------------------------------------------------------------+
|                              ServerExposure                              |
|  - server_id: UUID                                                       |
|  - method: ExposureMethod (playit | port_forward | cloudflare_tcp)       |
|  - desired_state: DesiredState (ENABLED | DISABLED)                      |
|  - aggregate_status: ExposureStatus                                      |
|  - targets: list[ServerExposureTarget]                                   |
+--------------------------------------------------------------------------+
                                     | 1
                                     |
                                     | owns 1..N targets
                                     v
+--------------------------------------------------------------------------+
|                           ServerExposureTarget                           |
|  - id: UUID                                                              |
|  - service_type: ServiceType (JAVA | BEDROCK | VOICE | BLUEMAP)          |
|  - protocol: TargetProtocol (TCP | UDP)                                  |
|  - local_port: int (validated against ServerModel / registered_ports)   |
|  - public_address: str | None                                            |
|  - status: ExposureStatus                                                |
|  - error_code: str | None                                                |
|  - error_message: str | None                                             |
+--------------------------------------------------------------------------+
```

---

## 4. Aggregate Target Validation & Multiplicity Rules

### 4.1 Target Multiplicity (Decision B)
1. An exposure may hold **up to 1 target per registered `(service_type, protocol)` pair**.
2. An exposure may hold multiple different service targets simultaneously (e.g. `1x JAVA (TCP)` + `1x BEDROCK (UDP)` + `1x VOICE (UDP)`).
3. Attempting to add a duplicate target for an existing `(service_type, protocol)` raises `DuplicateTargetError` (HTTP 409).

### 4.2 Generalized Port Validation (`validate_target_port`)
The validation rule enforces:
1. **Deny-List Check:** `local_port not in DENY_LIST_PORTS` (25575, 3306, 5432, 6379, 27017, 9090, 9100).
2. **Range Check:** `1 <= local_port <= 65535`.
3. **Registration Authority:**
   - If `service_type == ServiceType.JAVA`: `local_port` MUST equal `ServerModel.port`.
   - If `service_type in (BEDROCK, VOICE, BLUEMAP)`: `local_port` MUST match the active record in `server_registered_ports` for `(server_id, service_type)`.
4. **Protocol Match:** `protocol` MUST match the service type's affinity rule (§3.2).

### 4.3 Method-Level Invariant (Roadmap §4.2)
All targets under `ServerExposure` share the single active `exposure.method`:
- If `method == ExposureMethod.PLAYIT`: all targets receive playit tunnel allocations.
- If `method == ExposureMethod.PORT_FORWARD`: all targets are mapped via UPnP IGD.
- If `method == ExposureMethod.CLOUDFLARE_TCP`: only `TCP` targets are permitted.

---

## 5. Provider Transport Capability Matrix

| Exposure Method | Transport Support | Allowed Services | Prohibited Services | Failure Behavior |
|---|:---:|---|---|---|
| **`playit`** | TCP & UDP | `JAVA`, `BEDROCK`, `VOICE`, `BLUEMAP` | None | Provisions TCP or UDP edge tunnels via host agent. |
| **`port_forward`** | TCP & UDP | `JAVA`, `BEDROCK`, `VOICE`, `BLUEMAP` | None | Maps internal port to external port via `AsyncUPnPService(protocol="TCP"|"UDP")`. |
| **`cloudflare_tcp`** | TCP Only | `JAVA`, `BLUEMAP` | `BEDROCK`, `VOICE` (UDP) | Rejects target creation / enable with HTTP 422 `METHOD_PROTOCOL_INCOMPATIBLE`. |

### 5.1 Cloudflare UDP Fail-Fast Guard
In `SetServerExposureHandler`, `EnableServerExposureHandler`, and `CreateExposureTargetHandler`:
```python
if exposure.method == ExposureMethod.CLOUDFLARE_TCP and target.protocol == TargetProtocol.UDP:
    raise MethodProtocolIncompatibleError(
        "Cloudflare TCP exposure does not support UDP targets (Bedrock / Voice Chat). "
        "Use playit.gg or Port Forwarding instead."
    )
```

---

## 6. UPnP & playit Protocol Implementation

### 6.1 UPnP Infrastructure (`upnp.py`)
`AsyncUPnPService` already supports a `protocol: str = "TCP"` argument. In Batch 7.3d:
1. `_attempt_server_upnp_mapping` passes `protocol=target.protocol.value.upper()` (e.g. `"UDP"` or `"TCP"`).
2. Deletion on disable / switch passes `protocol=target.protocol.value.upper()`.
3. Auto-fix conflict retry preserves the requested protocol across attempts.

### 6.2 playit Host Agent Orchestration
1. Target creation for `BEDROCK` or `VOICE` assigns public address format `{tunnel_alias}.gl.at.ply.gg:{port}`.
2. Quota handling: Provider `PLAYIT_QUOTA_EXCEEDED` is recorded per-target if free-tier tunnel limits are reached.

---

## 7. API Contract & Schemas

### 7.1 Target Creation (`POST /servers/{id}/exposure/targets`)

#### Request Schema (`TargetCreateRequest`)
```python
class TargetCreateRequest(BaseModel):
    service_type: str = Field(default="java", pattern="^(java|bedrock|voice|bluemap)$")
    protocol: str | None = Field(default=None, pattern="^(tcp|udp)$")
    local_port: int | None = Field(default=None, ge=1, le=65535)
    public_address: str | None = Field(default=None, max_length=512)
```

#### Backward Compatibility Guarantees:
- If `service_type` is omitted or `"java"`, `protocol` defaults to `"tcp"` and `local_port` defaults to `ServerModel.port`.
- Existing tests and API clients sending `{}` or `{"public_address": "..."}` continue to create the primary Java target identically.

### 7.2 Port Registry Endpoints

#### 1. List Registered Ports
- **Route:** `GET /api/v1/servers/{id}/ports`
- **Permission:** `server.{id}.exposure.view`
- **Response:** `list[RegisteredPortResponse]`
  ```json
  [
    {
      "id": "port-uuid-1",
      "server_id": "srv-1",
      "service_type": "bedrock",
      "protocol": "udp",
      "port": 19132,
      "name": "Bedrock Edition"
    }
  ]
  ```

#### 2. Register Port
- **Route:** `POST /api/v1/servers/{id}/ports`
- **Permission:** `server.{id}.exposure`
- **Request Body:**
  ```json
  {
    "service_type": "bedrock",
    "protocol": "udp",
    "port": 19132,
    "name": "Bedrock Edition"
  }
  ```
- **Validation:**
  - `service_type` must be in `(bedrock, voice, bluemap)` (rejects `java`).
  - `port` must not be in `DENY_LIST_PORTS`.
  - Duplicate `(server_id, service_type)` or `(server_id, port, protocol)` returns HTTP 409 `PORT_ALREADY_REGISTERED`.

#### 3. Delete Registered Port
- **Route:** `DELETE /api/v1/servers/{id}/ports/{port_id}`
- **Permission:** `server.{id}.exposure`
- **Behavior:** Removes port registration. If an active exposure target exists for this port, target is removed and torn down.

---

## 8. State Machine & Precedence Impact

### 8.1 Aggregate Precedence Evaluation
The aggregate precedence fold defined in `aggregate_precedence(statuses: list[ExposureStatus])` (from Phase 7 Roadmap §6a.2 and 7.3c §10.2) operates over a list of `ExposureStatus`:
```python
_PRECEDENCE = [
    ExposureStatus.RECLAIM_REQUIRED,
    ExposureStatus.CLAIM_REQUIRED,
    ExposureStatus.ERROR,
    ExposureStatus.DEGRADED,
    ExposureStatus.STOPPING,
    ExposureStatus.STARTING,
    ExposureStatus.ACTIVE,
    ExposureStatus.STOPPED,
    ExposureStatus.DISABLED,
]
```
With N targets (e.g. Java Active + Bedrock Error), the fold deterministically computes `ERROR` as the aggregate status.
**Conclusion:** The state machine requires **zero mathematical changes**; it already handles arbitrary lists of target statuses natively.

---

## 9. Migration Plan

### 9.1 Revision Specification
- **Revision ID:** `b1e2100000005`
- **Down Revision:** `b1e2100000004` (verified head from Batch 7.3c)
- **Table Added:** `server_registered_ports`
- **Safety:** Additive only, zero downtime, zero data transformation required for existing tables.
- **Rollback:** `op.drop_table('server_registered_ports')`.

---

## 10. Test Design & Acceptance Matrix (24 Tests)

All tests must be hermetic, using `SAFE_SENTINEL_PID = 99999` and mocking external network boundaries.

| # | Test Name | Description |
|---|---|---|
| 1 | `test_register_companion_port_success` | Valid port registration (Bedrock UDP 19132) persists correctly. |
| 2 | `test_register_companion_port_java_rejected` | Attempt to register `service_type='java'` in `server_registered_ports` is rejected (400). |
| 3 | `test_register_companion_port_deny_list_rejected` | Registering a deny-listed port (e.g. 25575 RCON) is rejected with 422. |
| 4 | `test_register_companion_port_duplicate_type_rejected` | Registering a duplicate service type on the same server returns 409. |
| 5 | `test_register_companion_port_duplicate_port_protocol_rejected` | Registering the same port/protocol twice on the same server returns 409. |
| 6 | `test_create_bedrock_udp_target_success` | Creating a Bedrock UDP target with registered port succeeds. |
| 7 | `test_create_bedrock_udp_target_unregistered_rejected` | Creating a Bedrock target without registering the port first is rejected (422). |
| 8 | `test_create_voice_chat_udp_target_success` | Creating a Simple Voice Chat UDP target succeeds with registered port. |
| 9 | `test_create_bluemap_tcp_target_success` | Creating a BlueMap TCP target succeeds with registered port. |
| 10 | `test_create_target_wrong_protocol_rejected` | Creating Bedrock with TCP or BlueMap with UDP is rejected (422). |
| 11 | `test_multi_target_coexistence_same_server` | Server with Java TCP + Bedrock UDP + Voice UDP targets exposes all three simultaneously. |
| 12 | `test_multi_target_duplicate_service_rejected` | Creating a second Bedrock target on a server that already has one returns 409. |
| 13 | `test_cloudflare_tcp_rejects_udp_target_at_creation` | Attempting to add a UDP target when method is `cloudflare_tcp` returns 422. |
| 14 | `test_cloudflare_tcp_rejects_enable_with_udp_target` | Enabling `cloudflare_tcp` on a server with existing UDP targets returns 422. |
| 15 | `test_cloudflare_tcp_allows_bluemap_tcp_target` | Cloudflare TCP successfully exposes Java TCP and BlueMap TCP targets. |
| 16 | `test_upnp_maps_udp_protocol_correctly` | UPnP port forward for Bedrock passes `protocol="UDP"` to `AsyncUPnPService`. |
| 17 | `test_upnp_multi_target_mapping_and_deletion` | Enabling UPnP maps both TCP and UDP ports; disabling deletes both mappings. |
| 18 | `test_playit_multi_target_allocation` | playit exposure provisions distinct target URLs for Java TCP and Bedrock UDP. |
| 19 | `test_delete_registered_port_cleans_active_target` | Deleting a registered port removes the associated active target and tears down mapping. |
| 20 | `test_backward_compat_target_create_omitted_fields` | Legacy `POST /targets` with empty payload auto-creates Java TCP target using `ServerModel.port`. |
| 21 | `test_aggregate_status_fold_multi_target` | Aggregate status folds 1 ACTIVE + 1 ERROR target into ERROR. |
| 22 | `test_single_method_per_server_enforced` | Changing server exposure method switches all targets to the new method simultaneously. |
| 23 | `test_stop_all_exposures_cleans_multi_targets` | Global stop action terminates all TCP and UDP mappings across all servers. |
| 24 | `test_port_registration_rbac_permissions` | Port registration endpoints enforce `server.{id}.exposure` permissions. |

---

## 11. Findings Ledger

| ID | Finding / Decision | Classification | Documentation Location | Code/Test Impact | Status |
|---|---|---|---|---|---|
| **F-73D-01** | Multi-Row `server_registered_ports` Model | `[ARCHITECTURAL DECISION]` | Spec §2.1 | Non-primary ports stored in `server_registered_ports`; `ServerModel.port` remains sole Java port authority. | ✅ Recorded |
| **F-73D-02** | Backward Compatibility Default in `TargetCreateRequest` | `[DESIGN DECISION]` | Spec §7.1 | Default `service_type="java"`, `protocol="tcp"`, `local_port=ServerModel.port` ensures zero regression for 7.1–7.3c callers. | ✅ Recorded |
| **F-73D-03** | Cloudflare UDP Fail-Fast Enforcement | `[SECURITY CONTROL]` | Spec §5.1 | Hard HTTP 422 rejection (`METHOD_PROTOCOL_INCOMPATIBLE`) when UDP target is requested with Cloudflare TCP. | ✅ Recorded |
| **F-73D-04** | Single-Method-Per-Server Invariant Reaffirmed | `[ROADMAP INVARIANT]` | Spec §1.3, §4.3 | Reaffirmed Roadmap §4.2: all targets on a server share the server's single active exposure method. | ✅ Recorded |
| **F-73D-05** | Service-Protocol Affinity Mapping | `[TECHNICAL FACT]` | Spec §3.2 | Strict mapping: `JAVA` $\to$ `TCP`, `BEDROCK` $\to$ `UDP`, `VOICE` $\to$ `UDP`, `BLUEMAP` $\to$ `TCP`. | ✅ Recorded |
| **F-73D-06** | Mathematical State Fold Multi-Target Generalization | `[TECHNICAL FACT]` | Spec §8.1 | `aggregate_precedence` natively handles N target statuses without algorithm modification. | ✅ Recorded |
| **F-73D-07** | Simple Voice Chat Authoritative Protocol & Default Port | `[TECHNICAL FACT]` | Spec §3.2, §11; verified against `modrepo.de/minecraft/voicechat/wiki/server_configuration` and `github.com/henkelmax/simple-voice-chat` | Confirmed via official mod documentation and source repository: Simple Voice Chat transmits audio exclusively over UDP and defaults to port 24454 (config key `port=` in `voicechat-server.properties`, Fabric/Forge/NeoForge at `config/voicechat/`, Paper/Spigot/Purpur at `plugins/voicechat/`). Port is configurable per-server. Note: the mod also supports `port=-1` to reuse the Minecraft server's own port, but this is explicitly discouraged by the mod author and is NOT the registration model this design uses — MCS Manager always registers an explicit UDP port via `POST /servers/{id}/ports`, defaulting the pre-filled value to 24454 for user convenience, never silently reusing the Java port. | ✅ Verified |
| **F-73D-08** | Aggregate Target Entity Synchronization & Orphan Purge in SQL Repository | `[ARCHITECTURAL DECISION]` | Spec §2.1, §9; repository.py (SQLServerExposureRepository.save) | On save, compares DB `ServerExposureTargetModel` rows against the domain aggregate's `exposure.targets` and deletes any orphan DB rows for targets that were removed from the domain aggregate. Prevents deleted targets from resurrecting on reload. | ✅ Recorded |
| **F-73D-09** | UPnP Protocol Pass-Through Mechanism | `[TECHNICAL FACT]` | Spec §4.1; upnp.py (AsyncUPnPService.attempt_mapping / delete_mapping) | `attempt_mapping`/`delete_mapping` accept `protocol: str = "TCP"` / `"UDP"` and pass it directly to aioupnp without schema mutation or translation, beyond the caller producing it via `target.protocol.value.upper()`. | ✅ Recorded |
| **F-73D-10** | Cascading Teardown on Registered Companion Port Deletion | `[SYSTEM INTEGRITY]` | Spec §2.1, §9; commands.py (DeleteServerPortHandler) | On companion-port deletion, the handler detects any active exposure target matching the deleted service type, schedules post-commit provider unmapping (e.g. UPnP `delete_mapping`), removes the target from `ServerExposure`, re-folds aggregate status via `aggregate_precedence`, and saves. | ✅ Recorded |

---

## 12. Open Questions & Resolutions

### OQ-73D-01: Cloudflare TCP Multi-Target Hostname Routing
- **Status:** Resolved for Batch 7.3d.
- **Context:** If a server exposes both Java TCP (port 25565) and BlueMap TCP (port 8100) under Cloudflare, can they share the same hostname?
- **Resolution:** Cloudflare Named Tunnels route ingress by hostname. Java TCP uses `mc.example.com` $\to$ `tcp://127.0.0.1:25565`, and BlueMap uses `map.example.com` $\to$ `http://127.0.0.1:8100` (or `tcp://`). Each secondary target can specify its own `public_address` hostname, and `CloudflareClient.configure_ingress` configures multiple ingress rules under the server's single tunnel.

---

## 13. Implementation Boundary

### Files to be created during authorized implementation:
- `docs/roadmap/MCS-Manager-Phase7.3d-Design-Spec.md` (This spec)
- `backend/alembic/versions/b1e2100000005_add_server_registered_ports.py` (New migration)
- `backend/tests/application/test_server_multi_target_commands.py` (Acceptance tests)

### Files to be modified during authorized implementation:
- `backend/app/modules/exposure/domain/value_objects.py` (Add `UDP`, `BEDROCK`, `VOICE`, `BLUEMAP`)
- `backend/app/modules/exposure/domain/exceptions.py` (Add `MethodProtocolIncompatibleError`, `DuplicateTargetError`, `PortAlreadyRegisteredError`)
- `backend/app/modules/exposure/domain/aggregate.py` (Relax `create_target`, generalize `validate_target_port`)
- `backend/app/modules/exposure/infrastructure/models.py` (Add `ServerRegisteredPortModel`)
- `backend/app/modules/exposure/infrastructure/repository.py` (Add `SQLServerRegisteredPortRepository`)
- `backend/app/modules/exposure/application/commands.py` (Update `CreateExposureTargetHandler`, add port registry handlers)
- `backend/app/api/v1/schemas/exposure.py` (Extend `TargetCreateRequest`, add registered port schemas)
- `backend/app/api/v1/routers/exposure.py` (Add registered port routes)
- `backend/app/api/errors.py` (Map new error codes)
- `backend/app/core/persistence/db_revision.py` (Update floor revision to `b1e2100000005`)
