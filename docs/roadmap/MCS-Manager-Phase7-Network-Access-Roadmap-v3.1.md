# MCS Manager — Phase 7 Engineering Roadmap: Network Access & Exposure

**Status:** DRAFT v3.2 — BATCH 7.0 RECON COMPLETE; PHASE 7.1 DESIGN DECISIONS RECORDED; READY FOR BATCH 7.1 DESIGN
**Base commit / prerequisite:** Phase 4 (Owner Bootstrap / Invitation / RBAC / Access Mode system) — COMPLETE
**Source:** v1 derived from the Phase 7 network-design review (Arabic original). v2 incorporated a Hard Review pass that re-verified playit.gg's integration surface and added lifecycle/credential handling. v3 incorporated a second Hard Review pass that corrects the playit agent architecture (host-level, not per-server), expands the state machine, and adds concrete process-supervision, claim-flow, UPnP, Cloudflare-Panel, and security-hardening detail. **v3.1** is a design-repair revision that closes the remaining implementation ambiguity identified in the final release review: concrete host-level data model, a decided Access Mode relationship (MODEL B), deterministic aggregate-status precedence, a companion-port policy, playit quota handling, testable DEGRADED semantics, an explicit Windows supervision limitation, a 7.2 split, a Phase 7 RBAC matrix, and a hard Batch 7.0 evidence gate. **v3.2** records the Batch 7.0 RECON results and the explicit Phase 7.1 design decisions (AES-GCM credential encryption, Java-port-only v1 exposure scope, aioUPnP library) that unblock Batch 7.1.
**Scope of this document:** Phase 7 only. Nothing from Phases 5, 6, 8, 9, 10 is included.
**Changelog:** see §11 for v1→v2, §12 for v2→v3, and §13 for v3→v3.1 and v3.1→v3.2.

---

## 1. Objective

Phase 7 gives MCS Manager real network-exposure mechanics, split into two fully independent subsystems:

1. **Panel Access Exposure** — exposing the MCS Manager web UI itself beyond the local network.
2. **Game Server Exposure** — exposing individual Minecraft servers so players can connect from the internet.

These two subsystems must never share state, configuration, or code paths. A user exposing their Panel globally does not imply any game server is exposed, and vice versa.

---

## 2. Core Design Principles

These are non-negotiable constraints carried directly from the design review and must hold for every batch below:

1. **Total separation** between Panel exposure and Game Server exposure — different settings surfaces, different backend modules, different data model entries.
2. **No exposure is ever automatic.** Every exposure method is strictly opt-in; the default for both Panel and every server is "not exposed."
3. **Every state must be explicit and visible to the user** in the UI — no silent background exposure.
4. **Self-hosted, no centralized MCS-Manager-operated service.** All exposure works through infrastructure the user controls or accounts they own (their router, their Cloudflare account, their playit.gg account).
5. **User intent survives a restart, silent re-exposure does not.** MCS Manager persists what the user *asked for* (`desired_state`), and only ever restores a tunnel that was actively `ENABLED` before restart. Anything the user had turned off stays off. Any failure to restore surfaces as `ERROR`, never a silent flip to `ACTIVE`.
6. **One playit.gg agent per host, not per server.** MCS Manager supervises a single agent process/secret-key pair at the instance level; every server's playit targets are tunnels under that one agent, never a second agent process. (New in v3 — see §6c.)
7. **One exposure method per server in Phase 7.** Mixing methods across targets on the same server (e.g. playit for Java, UPnP for Bedrock) is deferred to a later phase. (New in v3 — see §4.2.)

---

## 3. Panel Access Design

### 3.1 Modes

| Mode | Description | Typical use |
|---|---|---|
| **Local Mode** | Panel only reachable on `localhost` / LAN | Default, everyday home use |
| **Global Mode** | Panel reachable from the public internet | Remote access, or granting access to someone outside the LAN |

> **v3.1 clarification:** these "modes" describe *reachability intent*, not mechanics. The mechanics that realize reachability are provided by Panel Exposure (§3.2, §3.4). The Phase 4 `access_mode` field (§3.3) remains a **registration/auth policy** flag and is deliberately **not** the network-exposure switch. See §3.3 for the decided relationship.

### 3.2 Global Mode exposure methods

| Method | Tier | Notes |
|---|---|---|
| **Port Forwarding + UPnP** | Basic | Manual or automatic port opening on the router |
| **Cloudflare Tunnel** | **Recommended** | Ready-made HTTPS, relatively stable address, best fit for a web frontend |
| **playit.gg (HTTP Tunnel)** | Alternative | Usable, but less flexible than Cloudflare specifically for the Panel. A stable/custom HTTPS address on playit.gg's HTTP tunnel tier is gated behind their paid plan — Cloudflare remains the recommended default for exactly this reason. |

**Design decision:** Cloudflare Tunnel is the primary/recommended path for Panel exposure, because it provides HTTPS out of the box and a reasonably stable address with minimal setup friction for a web UI, and because the Panel is HTTP-only traffic — exactly Cloudflare's strong case (see §6b for the full flow).

### 3.3 Relationship to the existing Phase 4 Access Mode setting — **MODEL B: SEPARATE PANEL EXPOSURE (v3.1 DECISION)**

**Chosen model: MODEL B.** Access Mode remains an **auth/registration-policy** setting only. A separate **PanelExposure** setting controls actual network exposure.

**Why MODEL B (not "extend in place"):**

Evidence from the current codebase (verified during this v3.1 design repair, read-only):

- `UpdateAccessModeCommand` (`backend/app/modules/auth/application/commands/update_access_mode.py`) only flips an enum on `SystemState`; it performs **no network action whatsoever**.
- The only behavioral effect of `GLOBAL` today is in `POST /api/v1/users` (`backend/app/api/v1/routers/users.py:46`): public self-registration is disabled and an invitation token is required. `LOCAL` leaves self-registration open.
- There is **no host, port, tunnel, or exposure binding anywhere** tied to `access_mode` in the codebase.

Because the Phase 4 flag is auth/registration policy and nothing else, extending it in place (MODEL A) would overload a policy flag with an operational network action, and would make "toggle GLOBAL" simultaneously mean "change registration policy" **and** "open the Panel to the internet." That violates the security rule below by construction. MODEL B keeps the two concerns orthogonal and keeps exposure strictly opt-in through a dedicated control.

**Exact effect on current behavior (MODEL B):**

- `access_mode` (`LOCAL` / `GLOBAL`) keeps doing **exactly** what it does today: it is the single authority for registration/auth policy (self-registration allowed vs invite-only). Owner-only via `global.settings` / `require_owner()`.
- The Settings → Access page keeps its existing Access Mode control and its confirmation warning on switching to GLOBAL — **unchanged**.
- A new, separate **PanelExposure** control appears on the same Settings → Access page, but is a **distinct setting** with its own values (`none` = default / `cloudflare_tunnel` / `playit_http` / `port_forward`).
- No existing API response schema or permission is changed; `SystemStatus` continues to report `access_mode`.

**Can changing Access Mode ever cause exposure by itself?** **NEVER.** Flipping `LOCAL`↔`GLOBAL` cannot start or stop a tunnel, open a port, or change PanelExposure. It changes policy only. This is enforced by design: no code path shared between `UpdateAccessModeCommand` and any exposure mechanism.

**Can Panel exposure exist while Access Mode is LOCAL or GLOBAL?** **YES.** PanelExposure is fully independent of `access_mode`. A user may expose the Panel while `access_mode=LOCAL` or `GLOBAL`. In either combination the registration/auth policy is still fully governed by `access_mode`.

**Authoritative settings per concern:**

| Concern | Authoritative setting |
|---|---|
| Registration/auth policy (self-register vs invite-only, Owner control) | `access_mode` (`LOCAL`/`GLOBAL`) — Phase 4, unchanged |
| Panel network exposure (method, on/off) | `panel_exposure` (`none`/`cloudflare_tunnel`/`playit_http`/`port_forward`) — new in Phase 7 |
| Per-server game exposure | `ServerExposure.method` + `desired_state` — new in Phase 7 |

**SECURITY RULE (mandatory):** Changing auth/registration policy must **never** silently publish the Panel. With MODEL B this is structural — no path from the policy flag to any exposure action exists. Additionally, because exposing the Panel with `access_mode=LOCAL` leaves self-registration open to anyone who can reach the Panel, the UI **must** show a one-time advisory (non-blocking) when PanelExposure is enabled while `access_mode=LOCAL`, recommending GLOBAL. This advisory is informational only and never auto-flips the policy flag.

### 3.4 PanelExposure lifecycle (v3.1)

`panel_exposure` uses the same `desired_state` (`ENABLED`/`DISABLED`) + status semantics as game-server exposure, with a single method active per instance:

- `panel_exposure = none` (default) → nothing is exposed; no process runs.
- Enabling a method persists `desired_state=ENABLED` and drives the Cloudflare / playit / UPnP mechanics of §6b/§6c/§7. Disabling sets `desired_state=DISABLED` and tears the tunnel/mapping down.
- On restart, an `ENABLED` PanelExposure is re-established; a `DISABLED` one stays down (Core Principle #5).
- PanelExposure state is a **single row** (instance-wide), `owner`-scoped (`exposure.panel.manage`, §8.6). It never shares state or code paths with game-server exposure (Core Principle #1).

---

## 4. Game Server Exposure Design

Fully separate from Panel access. Configured **per server**.

| Method | Ease of use | Player action needed? | Notes |
|---|---|---|---|
| **Port Forwarding + UPnP** | Medium | No | Best raw performance, but needs a public IP and/or a router that supports it |
| **playit.gg** | Very easy | No | **Recommended primary method** — purpose-built for game traffic, players connect with no extra software |
| **Cloudflare Tunnel (TCP)** | Medium–Hard | Yes (mod or `cloudflared` on the player's side) | Not practical for most players — advanced/optional only |

**Design decision:** playit.gg is the primary/recommended method for exposing game servers.

**Mandatory UI warning for Cloudflare TCP on game servers:** because this path requires the *player*, not the host, to install extra software (either the [Modflared](https://modrinth.com/mod/modflared) client mod for Fabric/Forge/NeoForge, or run `cloudflared access tcp` themselves), the UI must show this warning verbatim (or an equivalent localized string) before a user can enable it:

> "Players must install Modflared (or run cloudflared) to connect. This is not a normal public address."

This method must never be labeled "Recommended" anywhere in the UI for Game Server Exposure — Recommended is reserved for playit.gg.

### 4.1 Multiple exposure targets per server

A single Minecraft server is frequently more than one exposed port: Java (25565/TCP), Bedrock (19132/UDP), and optionally companion services (restricted — see §4.3). Exposure config must support a **list of targets** per server, each independently tracked:

- `protocol`: `tcp` / `udp` / `both`
- `local_port`
- `public_address` (once active)
- `status` (see expanded state machine, §6a)

This is a data-model decision, not just a UI one — see §6c.3 (schema) and §10 (Batch 7.1).

### 4.2 One method per server, multiple targets under it

Phase 7 does **not** support mixed methods on the same server. A server picks exactly one method (`none` / `playit` / `port_forward` / `cloudflare_tcp`), and every target on that server uses that method:

```
ServerExposure
  method: none | playit | port_forward | cloudflare_tcp
  desired_state: ENABLED | DISABLED
  targets[]:
    - protocol, local_port, public_address, status, error fields, ...
```

Rationale: mixed methods multiply UI, state-machine, and permission complexity for limited real-world benefit in v1. Revisit as a later-phase enhancement if there's demand.

### 4.3 Target-type & companion-port policy (v3.2 — explicit decisions)

**Phase 7 v1 = JAVA GAME PORT ONLY (v3.2 user decision).** The open-ended "other"/companion idea from v3 §4.3, and the broader Java+Bedrock scope of v3.1, are replaced by an explicit decision:

**ALLOWED PRIMARY TARGET (v1 — the only one):**
- **Minecraft Java** — TCP. `local_port` MUST equal `ServerModel.port` (the single authoritative game port persisted from `server.properties`). No other port is a valid exposure target in v1.

**DEFERRED (explicitly, until a future approved registry — v3.2 user decision):**
- **Minecraft Bedrock** — UDP (`19132`). **NOT** a v1 exposure target. The data model may reserve the schema shape, but Bedrock target creation is blocked until a later approved registry.
- **Companion services** — **remain disabled.** No `server_registered_ports` table is created in 7.1. Bedrock/companion port registration is deferred entirely.
- **Simple Voice Chat** — NOT automatically exposable; requires a future RECON-approved registry entry.
- **BlueMap** — a web viewer. **Never** becomes public merely because it exists; requires a future approved registry entry and its own target row. Default: not exposed.

**CRITICAL RULE — no arbitrary ports.** "Any port the user types" is not a valid design. Every v1 target must satisfy **all** of:

1. `local_port == ServerModel.port` for the owning `server_id` (the only valid v1 target — no registry needed because there is exactly one authoritative port).
2. `protocol` is `tcp` (Java v1 only).
3. `service_type` is `java` (v1 only; `bedrock`/companion types are rejected).
4. The port deny-list is enforced server-side (§7, §8).
5. The target cannot resolve to any management / RCON / database / metrics / internal Panel port (§7 deny-list).

**Companion/`server_registered_ports` registry:** NOT PRESENT in v1. **Phase 7.3d is optional and blocked on RECON-approved companion registry.** Batch 7.3a–c do not depend on the companion registry.

---

## 5. Proposed UI

Two clearly separated settings surfaces:

### A. Panel Access (Settings → Access)
```
Access Mode (auth/registration policy — Phase 4, unchanged):
□ Local Mode (default)          │  Registration: open for local use
○ Global Mode                   │  Registration: invite-only, Owner-gated
   (one-time warning on switch to Global — existing Phase 4 behavior)

Panel Exposure (network mechanics — NEW in Phase 7, independent of Access Mode):
□ None (default)
○ Cloudflare Tunnel   ← Recommended
○ playit.gg (HTTP)
○ Port Forwarding / UPnP
   (informational advisory when exposed while Access Mode = Local:
    "Self-registration is still open. Consider Global mode.")
```

### B. Game Server Exposure (per server — new Network/Exposure section)
```
Per server, independently:
□ Not exposed (default)
○ Port Forwarding
○ playit.gg               ← Recommended
○ Cloudflare Tunnel (Advanced)
     ⚠ Players must install Modflared (or run cloudflared) to connect.
       This is not a normal public address.

One method active per server. Each enabled method may expose multiple
targets (Java / Bedrock / RECON-approved companions), shown as a list with
protocol, port, address, and per-target status. Server-level status is an
aggregate of all enabled targets (deterministic precedence — §6a.2).

[Reset agent]  [Stop all exposures]  [Remove credentials]   ← §6c.2, §6d
```
All three actions are **Owner-only** (permission strings in §8.6).

---

## 6. User Flows

### Flow 1 — User selects playit.gg for a server ("Assisted Setup")

There is no officially-documented, guaranteed one-click tunnel-creation path for playit.gg. The tools that do this in practice (MineColab, Block-Suite, mcctl, Cliff-style integrations) all follow the same underlying pattern: the user obtains a **secret key** from the playit.gg dashboard (or a one-time claim), a single agent runs locally against that key, and tunnels are created either via the official agent CLI (`playit tunnels prepare --type tcp/udp/both`, `playit tunnels list`) or via the dashboard directly. Phase 7 adopts this as a two-phase strategy:

| Phase | Description | When |
|---|---|---|
| **v1 (this Phase 7 release)** | **Assisted Setup** — user completes a one-time Claim; MCS Manager attempts to create each tunnel automatically via the agent CLI, and if that fails, falls back to ready-made instructions/links to the playit.gg dashboard | Phase 7 |
| **v1.1 / later** | **Full Automation** — drive tunnel creation entirely through `tunnels/create` + `tunnels/prepare` once that surface is confirmed stable across playit.gg's supported integration API | Post-Phase-7 |

**The agent is host-level, not per-server (see §6c).** The claim and secret-key steps happen once per MCS Manager instance, not once per server. A server enabling playit.gg for the first time triggers the *host* agent to start (if not already running) and then requests tunnels under it.

Revised flow:

1. Backend checks whether the host-level playit agent binary is present; downloads it if missing.
2. If no secret key is stored yet for this host → UI surfaces a one-time **Claim Link** flow (§6c.2) so the user can authorize the agent against their playit.gg account.
3. Once claimed, the secret key is stored **encrypted at rest** (§6d) and the backend starts the single host-level agent process against it, if it isn't already running.
4. Backend attempts to create the tunnel automatically via the agent CLI (`playit tunnels prepare --type ...`) for the requested target(s) on this server (Java and/or Bedrock — §4.1, §4.3).
5. **If automatic creation succeeds:** UI displays the resulting public address (e.g. `something.at.ply.gg:xxxxx`) per target.
6. **If automatic creation fails:** UI shows an "Open playit.gg Dashboard" button with ready-made instructions for creating the tunnel manually, and polls/reads back the resulting address once the user has created it on their end.

### Flow 2 — User selects Cloudflare Tunnel for the Panel (expanded — see §6b for full detail)
1. User is prompted once for a Cloudflare API Token (Tunnel Edit scope **and** DNS Edit — both required per §6b.1) and a **Cloudflare-managed hostname/domain** for the Panel.
2. Backend creates a **Named Tunnel**, points its ingress at the Panel's local bind (localhost-only, §6b.3), and creates ONLY the tunnel CNAME for the user's hostname.
3. UI displays the resulting user hostname (no `*.cfargotunnel.com` default — §6b.1).

### 6a. Tunnel Lifecycle & State Machine

MCS Manager persists **user intent**, not just runtime status: a `desired_state` field (`ENABLED` / `DISABLED`) alongside a live `status`.

On MCS Manager restart:
- If `desired_state = ENABLED` → attempt to re-establish the tunnel automatically.
- If `desired_state = DISABLED` → **no** automatic restart; the tunnel stays down, silently, exactly as the user left it.
- Any failure to re-establish surfaces in the UI as `ERROR` — it never silently flips to `ACTIVE`, and it never silently re-exposes something the user doesn't expect.

**Expanded per-target state machine (v3, retained):**

```
DISABLED → CLAIM_REQUIRED → STARTING → ACTIVE → STOPPING → STOPPED
                                ↓          ↓
                             DEGRADED    ERROR
                                ↓          ↓
                          RECLAIM_REQUIRED (credential revoked/reset upstream)
```

- `DEGRADED` — target was `ACTIVE` but a health check now indicates a problem (e.g. agent process alive but tunnel unreachable) without a hard failure. Distinct from `ERROR` so the UI can show "degraded, may recover" rather than "broken." Objectively testable definition in §6a.1.
- `RECLAIM_REQUIRED` — the stored secret/token was invalidated upstream (e.g. the user ran `playit reset`, revoked the Cloudflare token from their dashboard, or the playit claim expired without completion). Requires the user to go through the claim/token flow again; MCS Manager never silently attempts to mint a new credential on the user's behalf.
- Quota/limit failures register as `ERROR` with a structured error code (`PLAYIT_QUOTA_EXCEEDED`), not a bespoke state — see §6a.3.

#### 6a.1 Health / DEGRADED semantics (v3.1 — objectively testable)

**Health evidence tiers:**

| Tier | Conditions (ALL must hold for the tier to apply) |
|---|---|
| **HEALTHY (ACTIVE)** | agent process alive; provider/tunnel inventory query succeeds within the freshness threshold; the expected target exists in the inventory; the target has a public address; no recent transport failure |
| **DEGRADED** — at least one of: | agent process alive but provider inventory is stale beyond threshold; expected target **missing** from the provider inventory; public address exists but the target is reported unhealthy; partial multi-target success/failure (some targets healthy, some not); repeated transient provider errors below the hard-error threshold |
| **ERROR** | agent cannot start; credentials invalid/revoked (→ transitions to `RECLAIM_REQUIRED`); provider reports a hard failure; target cannot be created; **no valid tunnel exists** for an enabled target |

**Process alive ≠ tunnel usable.** The two are never conflated in the state logic: agent-process-aliveness is one evidence source; provider-inventory truth is the deciding one for `ACTIVE`.

**Freshness thresholds (fixed for Phase 7):**
- Health-check interval: **30 seconds** (consistent with §6c.1).
- Stale threshold: **90 seconds** (three consecutive missed/never-refreshed inventory checks) → the affected target is `DEGRADED`.
- Consecutive-failure threshold for transient errors: **3** consecutive failed inventory queries → `DEGRADED`.

**Transitions (deterministic, no frontend-side decisions):**
- **One failed health check:** no state change (tolerated transient; internal error counter increments). UI continues to show `ACTIVE`.
- **Repeated failed checks** (3 consecutive) or inventory stale > 90s → `DEGRADED`.
- **Hard failure** (agent won't start, provider hard error, credential invalid) → `ERROR` immediately (or `RECLAIM_REQUIRED` if the evidence is credential revocation), without waiting for the 3-check threshold.
- **Recovery:** one fully successful health check (all HEALTHY conditions met) returns the target directly to `ACTIVE`. `DEGRADED` never requires manual intervention to clear; `ERROR` requires the underlying cause to be resolved (agent restart, reclaim, quota, etc.).

#### 6a.2 Server-level aggregate status — deterministic precedence (v3.1)

`desired_state = DISABLED` is an **override**: the server aggregate is `DISABLED` regardless of target history.

For `desired_state = ENABLED`, the aggregate is the highest-precedence status **among all enabled targets**, using this fixed order (highest → lowest):

```
RECLAIM_REQUIRED
  > CLAIM_REQUIRED
  > ERROR
  > DEGRADED
  > STOPPING
  > STARTING
  > ACTIVE
  > STOPPED
```

Precedence rationale: user-required actions (reclaim/claim) outrank all runtime failures because nothing on that server can function until the user acts; hard `ERROR` outranks soft `DEGRADED`; active transitions (`STOPPING`/`STARTING`) outrank steady states; `ACTIVE` outranks `STOPPED`.

**Exact cases (mandatory semantics):**

| Target state(s) | Server aggregate |
|---|---|
| `desired_state = DISABLED` (any targets) | `DISABLED` |
| enabled + **all** targets `CLAIM_REQUIRED` | `CLAIM_REQUIRED` |
| enabled + one `CLAIM_REQUIRED` + one `ACTIVE` | `CLAIM_REQUIRED` |
| enabled + one `STARTING` + one `ACTIVE` | `STARTING` |
| enabled + one `ERROR` + one `ACTIVE` | `ERROR` |
| enabled + one `RECLAIM_REQUIRED` + otherwise `ACTIVE` | `RECLAIM_REQUIRED` |
| enabled + **all** targets `ERROR` | `ERROR` |
| enabled + **all** targets `ACTIVE` | `ACTIVE` |
| **no targets** + `desired_state=DISABLED` | `DISABLED` (normal, nothing exposed) |
| **no targets** + `desired_state=ENABLED` | Contract violation — the API must reject enabling an exposure with zero targets. If observed in data, the aggregate is `ERROR` with code `NO_TARGETS`. |

**Persisted vs derived:** aggregate status is **derived at read time** from the target set plus `desired_state`, using the precedence function above. It is **not** a second accepted source of truth. The `ServerExposure.aggregate_status` column (when present) is a **derived cache** recomputed by the read/reconcile path; it is never accepted as write input and never treated as authoritative. Exactly one authority exists: per-target status + `desired_state`, folded by the precedence function.

#### 6a.3 playit free-tier quota / limit handling (v3.1 — deterministic)

**Authoritative source:** the backend **must** treat playit CLI/API quota and limit responses as authoritative. The backend does **not** guess or fabricate a numeric free-tier limit in policy; no hardcoded "4 TCP + 4 UDP" figure is enforced locally unless it is verified during Batch 7.0 RECON. Any numeric surfacing must come from the provider.

**Behavior on a recognizable quota/limit failure** during tunnel `prepare`/creation:

- State: `ERROR` with structured error data. No new top-level state is added.
- Error code: **`PLAYIT_QUOTA_EXCEEDED`** (part of the target's `error_code`).
- Scope: **target-level failure by default** (only the target that hit the quota is `ERROR`; the rest of the exposure and the host agent are unaffected). If the provider response is explicitly host/agent-level (e.g. agent/port ceiling reached), then the host agent lifecycle is informed and the affected playit exposures reflect it — but never the Panel or other-method servers.
- UI behavior:
  - Clear user-facing message (localized).
  - Lists the **affected target(s)**.
  - Two actions offered: **"Reduce enabled targets"** and **"Upgrade playit plan"**.
  - If the provider returns structured quota information, it is preserved and displayed (current ports / ceiling).
- If the provider returns a quota failure in an unrecognizable shape, the backend surfaces `ERROR` + `PLAYIT_QUOTA_EXCEEDED` with the provider's verbatim message rather than inventing guidance.

### 6b. Cloudflare Panel Tunnel — full flow detail

v2 left this under-specified. v3 concrete flow, **revised to CUSTOM-DOMAIN-ONLY by the 7.2a RECON (2026-08-14)** — see §6b.1:

1. User enters a Cloudflare API Token scoped to Tunnel Edit **plus DNS Edit** (DNS Edit is now **required**, not optional — see §6b.1).
2. Backend creates a **Named Tunnel** (`config_src: cloudflare`) rather than a Quick Tunnel, since Named Tunnels are what supports a stable address. **Quick Tunnels / `trycloudflare.com` are NOT used as a fallback (7.2a Decision 1).**
3. Ingress rule is scoped to exactly one route: `http://127.0.0.1:<PANEL_PORT>`. Nothing else on the host is ever put behind this ingress.
4. **Single address option:** the user-provided Cloudflare-managed hostname. MCS creates ONLY the tunnel CNAME (`CNAME proxied:true` → `<tunnel_id>.cfargotunnel.com`) required for the MCS-created tunnel. MCS never implements general DNS management.
5. Backend runs `cloudflared tunnel run --token-file <path>` as an orchestrated subprocess (orchestrate-only — see §8.5; MCS Manager does not bundle the binary in Phase 7). `--token-file` is used instead of `--token` so the credential never appears in the process table (cloudflared security fix, VULN-118896).
6. `cloudflare_tunnel_id` and the token (AES-GCM encrypted — §6d, §6b.2) are persisted along with `desired_state` on the `panel_exposure` singleton row.
7. If the token is revoked externally (from the Cloudflare dashboard), the tunnel surfaces as `ERROR` transitioning to `RECLAIM_REQUIRED` — never a silent retry loop against a dead token. The owner must explicitly provide a new token.

Since the Panel is HTTP-only traffic, there is no TCP-tunnel variant to consider here — that complexity is scoped entirely to Game Server Exposure (§4).

#### 6b.1 Custom-domain-only decision (7.2a RECON — DESIGN FIX)

**No stable no-DNS named-tunnel URL exists.** The `*.cfargotunnel.com` subdomain is a virtual CNAME **target**, not a browsable address; Cloudflare only proxies traffic for a DNS record pointing at it. The only zone-less option is a Quick Tunnel (`trycloudflare.com`), which is random, ephemeral (dies on every restart), 200-concurrent-request limited, SSE-less, and explicitly testing-only — unsuitable as a stable product flow. Therefore:

- **7.2a REQUIRES a user-provided Cloudflare-managed hostname/domain input.** There is no "quick path" default.
- MCS may: create the Named Tunnel, configure tunnel ingress, create ONLY the tunnel CNAME required for the MCS-created tunnel.
- MCS must **not** implement general DNS management. The `*.cfargotunnel.com` target is never surfaced as the user-facing stable public URL.
- Phase 8 remains responsible for broader DNS/domain management.

#### 6b.2 Cloudflare credential storage (7.2a RECON — DESIGN FIX)

**Extend `PanelExposure` rather than creating a generic encrypted-credentials subsystem.** Two new fields on the `panel_exposure` singleton:

| Field | Type | Purpose |
|---|---|---|
| `cloudflare_tunnel_id` | String | Non-secret tunnel UUID metadata (never encrypted) |
| `cloudflare_token_ciphertext` | LargeBinary | AES-GCM(nonce\|ciphertext) of the Cloudflare tunnel token |

Rules (7.2a Decision 2):
- Encryption reuses the approved **AES-GCM `BackupEncryption`** / `load_or_create_backup_key` (`backend/app/modules/storage/encryption.py`). Fernet is excluded.
- Plaintext token is never persisted, never returned by any API, never logged.
- `cloudflare_tunnel_id` is non-secret metadata (safe to surface in status responses).
- Credential rotation = replace the ciphertext with a freshly encrypted value.
- Deleting/removing Cloudflare exposure clears the stored secret.
- Revoked/invalid token → `RECLAIM_REQUIRED`; no auto-reissuance; owner must explicitly provide a new token.
- **No generic credentials table is created.**

#### 6b.3 Panel bind address (7.2a RECON — DESIGN FIX)

The Cloudflare ingress target is derived from a **single authoritative Panel-bind configuration source** — see `MCS-Manager-Phase7.2-Design-Spec.md` §3 (Decision 3). No `:8000` literals are scattered through Cloudflare code. The ingress target is **localhost-only**; `0.0.0.0` is never used as the tunnel ingress target.

#### 6b.4 Panel exposure authorization (7.2a RECON — DESIGN FIX)

**Owner-only, enforced at the route dependency, not inferred from permission grants.** The RECON verified that `exposure.panel.manage` alone is insufficient: the current `require_permission("exposure.panel.manage")` short-circuits on `admin:full`, which would let an ordinary admin toggle Panel exposure — broader than Owner-only. Per 7.2a Decision 4, the Panel GET/PUT routes use the existing **`require_owner()`** dependency (owner role or `global.*` claim). `admin:full` alone is NOT sufficient. The `exposure.panel.manage` contract string remains documented but the route-level enforcement is `require_owner()`.

### 6c. playit Agent Architecture — Host-Level, Not Per-Server

**This is the most significant correction in v3.** v2 implicitly modeled the playit agent as something tied to a server. That's wrong. Community and integration evidence (playit's own forum guidance for multi-server setups, and every serious integration — Geyser-adjacent tooling, Railway templates, Block-Suite, mcctl) converges on one pattern:

```
Host-level (once per MCS Manager instance):
  1× playit agent process
  1× secret key

Per server / per target (many, under that same agent):
  N tunnels — Java TCP, Bedrock UDP, RECON-approved companions, etc.
```

Consequences for the design:

- MCS Manager owns **instance-level supervision** of a single agent process, independent of any individual server's lifecycle.
- If no target across any server currently has `desired_state = ENABLED` for the playit method, the agent may be stopped.
- If at least one target anywhere has `desired_state = ENABLED`, the agent must stay running.
- playit's free tier is itself agent/port-limited (Premium raises agent and port ceilings) — this reinforces the one-agent design rather than arguing against it.

#### 6c.1 Agent process supervision

| Platform | Strategy |
|---|---|
| Linux | Prefer a `systemd` unit (`systemctl start/enable playit`, `Restart=always` or `Restart=on-failure`) when systemd is available — playit has supported this natively since v0.15. Falls back to subprocess supervision if systemd isn't present. |
| Windows | Subprocess under MCS Manager with an auto-restart policy in Phase 7; a proper Windows Service is a candidate for a later phase. |
| Docker | Sidecar container or same-compose-network process with `restart: unless-stopped`. |

Rules:
- Periodic health check every **30s** via `tunnels list` or a process-alive check (§6a.1).
- If the agent process dies while any target has `desired_state = ENABLED` → attempt restart, with the affected targets showing `STARTING` and then `ACTIVE` or `ERROR` depending on outcome.
- If MCS Manager itself shuts down: under `systemd` supervision the agent can keep running independently; under plain-subprocess supervision the agent dies with it.

**Known limitation — Windows process supervision (v3.1, explicit):**

- **Windows, Phase 7 v1:** the playit agent and `cloudflared` run as **child subprocesses under MCS Manager**. If MCS Manager exits, those subprocesses **terminate** with it. Automatic restart is possible only while MCS Manager itself remains alive. A proper **Windows Service** integration is **deferred to a later phase** and must be recorded in SECURITY.md/known-limitations; it is not a hidden implementation assumption.
- **Linux:** systemd is preferred when available; subprocess fallback otherwise (systemd keeps the agent alive independently of the Panel process).
- **Docker:** sidecar / same-compose-network supervision with `restart: unless-stopped`.
- The same limitation applies to **both** supervised providers — playit **and** cloudflared — wherever system-level supervision is unavailable (i.e., both die with the panel on Windows subprocess supervision; both ride systemd independently on Linux when configured).

#### 6c.2 Claim flow — races, timeouts, and reset

Based on the official CLI surface (`playit claim generate`, `playit claim url <code>`, `playit claim exchange <code> [--wait N]`, `playit reset`):

```
CLAIM_REQUIRED
  → generate claim code + show URL
  → exchange with a bounded timeout (e.g. 10–15 min)
  → on success: store the encrypted secret, verify by briefly starting
    the agent or calling the API
  → on timeout/failure: stay in CLAIM_REQUIRED, allow retry
  → explicit "Reset agent" action → runs `playit reset` and clears the
    stored secret (see §6d)
```

Fields to persist during this flow: `claim_code` (transient), `claim_expires_at` (transient), `secret_key` (encrypted, written only after a successful exchange).

**Reset semantics (v3.1):** the **Reset agent** action (Owner-only) clears the locally stored encrypted secret, runs `playit reset` if the agent is reachable, clears the transient claim fields, and returns **every** playit target to `CLAIM_REQUIRED`. The **Stop all exposures** action sets `desired_state=DISABLED` across every exposure **without deleting credentials**. The **Remove credentials** action deletes the encrypted secret/token and stops the associated agent/tunnel process. All three are idempotent and audit-logged (§8).

#### 6c.3 Host-level playit data model — concrete schema (v3.1)

The agent is an instance-level entity. **It has no `server_id`.** The relationship between the host agent and servers is indirect: a server's playit exposure emits playit targets, and any enabled playit target anywhere requires the single host agent to be running.

**Conceptual tables:**

```
HostPlayitAgent (one row per MCS Manager instance)
  id                  PK
  secret_ciphertext   NOT NULL after claim; stores the encrypted playit secret key
  claim_code          nullable, transient — only present during an in-progress claim
  claim_expires_at    nullable, transient — only present during an in-progress claim
  process_status      STOPPED | RUNNING | STARTING | STOPPING | ERROR   (live, reconciled)
  last_health_at      nullable — timestamp of last successful provider inventory query
  desired_agent_running  bool — DERIVED state, see semantics below
  created_at
  updated_at

ServerExposure (one row per server that has an exposure config)
  id                PK
  server_id         FK → servers.id, NOT NULL  (belongs to exactly one server)
  method            none | playit | port_forward | cloudflare_tcp   (exactly one)
  desired_state     ENABLED | DISABLED
  aggregate_status  DERIVED CACHE — computed by the precedence function (§6a.2), never a write input
  created_at
  updated_at

ServerExposureTarget (one row per exposed port under a ServerExposure)
  id              PK
  exposure_id     FK → ServerExposure.id, NOT NULL
  protocol        tcp | udp | both
  service_type    java | bedrock | <RECON-approved companion>
  local_port      validated against ports registered to the owning server_id (§8)
  public_address  nullable — populated once the provider assigns one
  status          DISABLED | CLAIM_REQUIRED | STARTING | ACTIVE | STOPPING |
                  STOPPED | DEGRADED | ERROR | RECLAIM_REQUIRED
  error_code      nullable — structured code, incl. PLAYIT_QUOTA_EXCEEDED (§6a.3)
  error_message   nullable — provider/CLI message for UI display
  created_at
  updated_at
```

**Relationships (explicit):**

- `HostPlayitAgent` → `ServerExposure`: **1 ──── N indirect.** An exposure `belongs to` the playit method iff `ServerExposure.method = playit`. The host agent does not reference servers directly; the agent's accuracy is kept by the derived `desired_agent_running` (below).
- `ServerExposure` → `ServerExposureTarget`: **1 ──── N.**
- A `ServerExposure` belongs to **exactly one** server (`server_id NOT NULL`).
- A `ServerExposure` has **exactly one** `method`.
- **All** targets under a `ServerExposure` use that exposure's `method` (enforced at the aggregate boundary; mixed-method requests are rejected, §4.2).
- `HostPlayitAgent` is **instance/host-level and MUST NOT contain `server_id`.**

**`desired_agent_running` semantics (v3.1 — definitive):**

- It is **derived** from the current set of playit targets/exposures whose `desired_state = ENABLED`:
  `desired_agent_running ⇔ EXISTS(ServerExposure e WHERE e.method = 'playit' AND e.desired_state = 'ENABLED')`.
- It is **not** an independent source of truth and is **not** user-authored. It is a cached/reconciled field recomputed whenever any playit exposure's `desired_state` changes and on every reconcile pass. The authoritative expression is the `EXISTS` query above.
- Lifecycle consequences (definitive):

| Event | Behavior |
|---|---|
| **Last playit exposure disabled** | `desired_agent_running` becomes false → the agent **may** be stopped (graceful stop with bounded drain); all its playit targets settle to `STOPPED` (or `DISABLED` if that exposure's `desired_state` is `DISABLED`). |
| **First playit exposure enabled** | `desired_agent_running` becomes true → binary presence ensured, agent started (if not running); if unclaimed, the exposure stays `CLAIM_REQUIRED` and the agent waits; tunnels are then prepared per Flow 1. |
| **Credentials removed** | `secret_ciphertext` wiped, claim fields cleared, agent process stopped, every playit target → `CLAIM_REQUIRED` (then `DISABLED` if the user disables). Never re-claims automatically. |
| **Agent crashes** (while any playit target enabled) | Supervisor restarts with backoff; enabled playit targets → `STARTING` → `ACTIVE` or `ERROR` per §6a.1 evidence. |
| **Host restarts** | Startup reconcile recomputes `desired_agent_running` from persisted `desired_state`. If `ENABLED` → start agent + re-establish tunnels (failures surface as `ERROR`, never silent re-exposure, Core Principle #5). If none → agent stays stopped. |

### 6d. Credential Storage & Reset/Uninstall Paths

| Credential | Decision |
|---|---|
| Cloudflare API Token / Tunnel Token | **DECIDED (v3.2): Encrypted at rest with the existing AES-GCM `BackupEncryption` in `backend/app/modules/storage/encryption.py` (key-file lifecycle via `load_or_create_backup_key`)**. Fernet helpers in `backend/app/core/security.py` are explicitly **excluded** — no new Fernet usage is introduced in Phase 7. The AES-GCM path reuses the already production-wired backup-encryption key lifecycle so exactly one key-management flow exists for secrets. |
| playit.gg Secret Key | Same: encrypted at rest, never stored in plaintext in the DB |
| Access scope | Owner-only, mapping to the new `exposure.credentials.manage` permission node (§8.6) |
| Storage location | A dedicated encrypted secrets/settings table — not a plaintext column on `ServerModel` or the Panel settings row |

**Required UI actions (Owner-only, §8.6):**

- **Reset playit agent** — clears the locally stored secret, runs `playit reset` if the agent is reachable, and returns every target under that method to `CLAIM_REQUIRED` (or `DISABLED`).
- **Stop all exposures** — sets `desired_state = DISABLED` across every exposure, **without** deleting stored credentials.
- **Remove credentials** — securely deletes the encrypted secret/token and stops the associated agent/tunnel process.

---

## 7. UPnP / Port Forwarding — Implementation Detail

v2 treated UPnP as a single "attempt and report" step. v3 specifies the actual mechanics, based on known IGD failure modes:

**Library decision (v3.2 — explicit user decision): `aioUPnP`.** The `aioupnp` dependency is **added only at Batch 7.3b implementation time** — it is deliberately **not** introduced during Batch 7.1 schema work. No other UPnP library (`miniupnpc`, `upnpy`, etc.) is used; this decision is locked unless future RECON evidence forces a change. `aioupnp` is async-native and async-SQLAlchemy-friendly, matching the existing backend runtime.

| Aspect | Decision |
|---|---|
| External port default | Same as `local_port` |
| On conflict (`ConflictInMappingEntry`) | Try a small number of alternate ports in a bounded range; if all fail, report an explicit failure and let the user choose the external port manually |
| Status vocabulary | `Not Attempted` / `Succeeded` / `Failed` / `Unsupported by router` — the same four states used for both Panel and Game Server UPnP |
| Public address | Reported as `external_ip:external_port` after a successful mapping, with `external_ip` read back via `GetExternalIPAddress` |
| Double NAT | Not solvable via UPnP — reported as `Failed`/`Unsupported`, with the UI pointing the user toward playit.gg instead |
| IPv6 | Out of scope for Phase 7 |

**Hard rule — port deny-list:** UPnP/port-forwarding must never be usable to expose RCON, the Panel's own internal port (outside the dedicated Panel Access subsystem), database/metrics ports, or any port not explicitly registered as a game or companion-service port for that `server_id`. This deny-list is enforced **server-side**, not just hidden in the UI.

**Deny-list baseline (v3.1, minimum — RECON should extend with actual registered port data):**

| Denied |
|---|
| RCON port (default `25575`) wherever it is configured for a server |
| The Panel's own HTTP/bind port (outside the Panel subsystem) |
| Database ports (default SQLite path / configured DB) and any DB backend port |
| Metrics / Prometheus scrape ports (the Phase 7 `GET /metrics` endpoint is a Panel-subsystem concern, not a game-exposure target) |
| Any management/internal API port |
| Any port not registered to the owning `server_id` (§8 "Arbitrary port exposure") |

---

## 8. Security Hardening

| Gap | Fix |
|---|---|
| Unbounded claim/token-intake attempts | Rate limit per Owner (e.g. 5/hour) on claim generation and credential intake endpoints |
| No audit trail for exposure changes | Every Enable / Disable / Claim / Reset / Remove-credentials action emits an audit-log event |
| RCON / management ports reachable via game-exposure path | Explicit deny-list (§7) — these must never be selectable as a game exposure target |
| Arbitrary port exposure | `local_port` must validate against a port actually owned by/registered to that `server_id` before a target can be created |
| Files API IDOR | Hard gate — no exposure subsystem may be merged/shipped until this is confirmed closed (carried over from v1/v2, §9 open question 2). **Status note:** the Files API permission gap was resolved during Phase 4/Phase 6 work (`require_server_permission` on all 7 file routes + `server.properties` sensitive-file guard). Batch 7.0 must still re-confirm this as a RECON fact before sign-off. |

### 8.5 Cloudflare binary strategy

**Orchestrate-only.** Phase 7 ships without bundling `cloudflared`; the user installs it, or MCS Manager drives an already-installed binary. Bundling is deferred to a later phase pending cross-platform stability. RECON must confirm this against current platform-support reality (§9 Q5).

### 8.6 Phase 7 authorization / RBAC matrix (v3.1 — design contract)

The following permission strings are **proposed design contracts** for the new Phase 7 API. They do not exist in the codebase yet (verified in review — no such permission is currently registered). They are to be introduced as implemented permissions **by Batch 7.1/7.2** and enforced in the API layer at contract-authoring time.

| Operation | Proposed permission `string` | Default grantee |
|---|---|---|
| Global Panel exposure: enable/disable/choose method | `exposure.panel.manage` | **Owner only** |
| Instance-wide "stop all exposures" | `exposure.global.stop` | **Owner only** |
| Reset playit agent / clear secret | `exposure.credentials.manage` | **Owner only** |
| Remove credentials | `exposure.credentials.manage` | **Owner only** |
| View claim code / claim link | `exposure.credentials.manage` | **Owner only** (a claim link authorizes an account — sensitive) |
| Create/edit/delete a game exposure target | `server.{id}.exposure` | Owner + roles **explicitly granted** this permission (see rule below) |
| Enable/disable a server's exposure | `server.{id}.exposure` | Owner + explicitly granted roles |
| View public address(es) of a server | `server.{id}.exposure.view` | Any authenticated member holding this read permission (viewer-eligible **only if** the product decision explicitly grants it; not inferred) |
| View provider/tunnel status (read-only) | `server.{id}.exposure.view` | Same as above |

**Rules that cannot be inferred (v3.1):**

- **No exposure privilege is inferred from membership roles.** A role (`admin`/`dev`/`viewer`) does **not** automatically grant `server.{id}.exposure` or `server.{id}.exposure.view`. All three Phase 4 invitation roles inherit **no** exposure privilege automatically. Granting exposure access requires an explicit, deliberate grant in the membership/exposure permission model.
- **`server.{id}.settings` does not imply exposure.** Because `server.{id}.settings` already controls per-server settings mutation, it must never be used as a proxy for `server.{id}.exposure`; the exposure permission is a separate node with its own explicit grant.
- **`global.settings` (Phase 4) does not become a panel-exposure grant by itself.** Panel exposure controls use the new `exposure.panel.manage` node; `global.settings` retains its existing meaning. (The existing `update_access_mode` handler continues to use `require_owner()`, unchanged.)

**The contract authoring gate:** Batch 7.1 must add these strings to `contracts/permissions.yaml` with status `enforced` and wire them into the route contract checker — as part of the contract deliverable, not as a post-hoc addition.

---

## 9. Open Questions to Resolve in RECON (Batch 7.0)

These are the **only** remaining open questions. Design decisions that v3.1 has already closed (§3.3, §4.3, §6a, §6c.3, §7, §8.6) are **not** re-opened here; RECON's job is to **verify** them against evidence and to **answer the genuinely unresolved evidence questions** below.

1. **Access Mode integration surface — VERIFY MODEL B.** Confirmed by the v3.1 review that `access_mode` is auth/registration policy with no network binding and that your chosen relationship is MODEL B (§3.3). Batch 7.0 must confirm the exact integration points (handler, `users.py` registration gate, `AccessSection.tsx` UI) so 7.1 touches nothing outside that surface.
2. **Files API IDOR gap — confirm as RECON FACT.** The permission gap is believed resolved (all 7 file routes now use `require_server_permission`, and `server.properties` has a sensitive-file guard). Batch 7.0 must confirm this before sign-off; it remains a **hard blocker** if not closed.
3. **Existing network-related code** — does the backend already contain any tunnel-management, UPnP, or port-related modules/dependencies to build on, or is this greenfield? (v3.1 repo scan found none — verify.)
4. **playit.gg integration mechanism** — confirm whether the official agent CLI's `tunnels prepare`/`tunnels list` commands are viable as the primary automated path, with the dashboard as documented fallback. This directly determines the Assisted Setup flow in §6. Also verify the **claim** subcommands (`claim generate`/`url`/`exchange`/`reset`) surface and their timeout semantics.
5. **Cloudflare `cloudflared` dependency** — Phase 7 ships as **orchestrate-only** (user installs `cloudflared`, or MCS Manager drives an already-installed binary); bundling deferred to a later phase pending cross-platform stability. RECON should confirm this against current platform-support reality.
6. **Data model placement** — new tables (`exposure` + `exposure_targets` + host-agent record) as specified in §6c.3. Confirm the concrete table naming/foreign-keys against the actual Alembic/SQLAlchemy patterns used by Phase 4 (`system_state`/`invitations`/`server_memberships`), and confirm `ServerModel` port fields are sufficient for port-registration validation (§8 "arbitrary port exposure").
7. **Tunnel lifecycle on restart** — validate the §6a design (`desired_state`, precedence table) against the current process-management/startup code (scheduler/`main.py` lifecycle), and confirm where the reconcile pass hooks in.
8. **Credential storage — DECIDED (v3.2 user decision):** reuse the existing AES-GCM `BackupEncryption` in `backend/app/modules/storage/encryption.py` with its `load_or_create_backup_key` key-file lifecycle. **Fernet helpers in `backend/app/core/security.py` are excluded.** No third mechanism is introduced. (Resolves the Fernet-vs-AES-GCM question; §6d row updated accordingly.)
9. **Multiple ports/targets per server — DECIDED (v3.2 user decision).** **Phase 7 v1 = JAVA GAME PORT ONLY.** `ServerModel.port` is the sole valid exposure target; **no `server_registered_ports` table is created in 7.1**; Bedrock/companion target types are rejected in v1 and deferred to a future approved registry. `server_exposure_targets` (if created for v1) is constrained to exactly one `java` target per server, so per-target status is trivially independent in v1. (§4.3 updated accordingly.)
10. **playit agent process-supervision environment** — confirm systemd availability/version on the target Linux deployments, and confirm what subprocess-supervision infrastructure MCS Manager already has (if any) to reuse for Windows/Docker per §6c.1. Record the Windows child-subprocess limitation (§6c.1) as a known limitation.
11. **UPnP library choice — DECIDED (v3.2 user decision): `aioupnp`.** Added only at Batch 7.3b implementation; deliberately **not** introduced during Batch 7.1 schema work. `miniupnpc`/`upnpy` not used. (§7 updated accordingly.)
12. **Companion registry feasibility (new in v3.1)** — confirm whether a companion-service registry (service_type enum, port/protocol allow-list records) can be added to the data model in 7.1, and verify the Simple Voice Chat protocol/port model (§4.3). If not verifiable, 7.3d stays **blocked on RECON approval**.
13. **playit quota/lifecycle surface (new in v3.1)** — confirm the concrete provider responses for quota/limit exceeded (to map `PLAYIT_QUOTA_EXCEEDED` reliably) and confirm agent-claim timeout boundaries (10–15 min) against real CLI behavior.

> Batch 7.1 **must not begin** until every question above answers as **VERIFIED FACT** or an **EXPLICIT USER DECISION** is recorded (see §10, Batch 7.0 exit criteria). **v3.2 status:** all §9 questions are now resolved — the three that required an explicit user decision (Q8 credential encryption, Q9 port scope, Q11 UPnP library) were **DECIDED by the user on 2026-08-13**; all remaining questions were answered as **VERIFIED FACT** in the Batch 7.0 RECON report.

---

## 10. Batch Breakdown

Following the project's standard discipline: **RECON (evidence only, no code) → design decision → Build (diffs + tests, no commit) → independent review by a different agent → user approval → commit.** Never commit without explicit user go-ahead.

### Batch 7.0 — RECON
- **Objective:** Answer all open questions in §9 with evidence from the actual codebase; no code changes.
- **Status (v3.2): COMPLETE — "READY WITH EXPLICIT USER DECISIONS."** RECON answered all §9 questions; the user then supplied the three required decisions (2026-08-13). No §9 question remains open.
- **Deliverables:** RECON report covering: Access Mode integration surface (MODEL B verification), Files API IDOR gap status, any existing network/tunnel code, dependency feasibility for playit.gg (CLI `tunnels prepare`/claim commands) and `cloudflared`, current `ServerModel`/settings schema shape, feasibility of the §6c.3 multi-table structure, systemd/process-supervision environment survey (incl. the Windows limitation being recorded), UPnP library feasibility, **credential-encryption decision (Fernet vs existing AES-GCM, §9 Q8 — decided: AES-GCM)**, and **companion-registry feasibility (§9 Q12)**.
- **Exit criteria — the gate for Batch 7.1 (v3.1):** every question in §9 has a confirmed answer or an explicit user decision, **and** these Batch 7.1-blocking inputs are each either **VERIFIED FACT** or **EXPLICIT USER DECISION**:
  1. Actual Phase-4 Access Mode integration surface (MODEL B). — **VERIFIED FACT** (RECON)
  2. Exact encryption mechanism to reuse (Fernet helper in `core/security.py` vs `BackupEncryption` AES-GCM). — **EXPLICIT USER DECISION: AES-GCM `BackupEncryption`** (2026-08-13)
  3. Exact `ServerModel`/settings structure (for `server_id` FK + port-registration validation). — **VERIFIED FACT** (RECON; v1 scope = `ServerModel.port` only, user decision)
  4. Existing process-supervision capabilities (what to reuse for subprocess/`systemd`/Docker supervision). — **VERIFIED FACT** (RECON)
  5. playit CLI/API feasibility (`tunnels prepare`/`list`, claim flow). — **EXTERNAL** (must be verified live at Batch 7.3a implementation; RECON confirmed subprocess infra exists)
  6. Cloudflare orchestration feasibility (`cloudflared` orchestrate-only). — **VERIFIED FACT** (RECON)
  7. UPnP library feasibility. — **EXPLICIT USER DECISION: `aioupnp`** (2026-08-13)
  8. Actual available/registered server ports (feeds the deny-list §7 and port-registration validation §8). — **VERIFIED FACT** (RECON; Java port only in v1)
  9. Actual dependency-installation feasibility (binary download/installation for playit agent, `cloudflared`). — **EXTERNAL** (must be verified live; no bundling in v1)
  10. Whether a companion-port registry exists / can be modeled (§9 Q12). — **EXPLICIT USER DECISION: deferred** — no `server_registered_ports` table in 7.1; companion registry deferred to a future approved phase (2026-08-13)
- **Files API IDOR:** explicit confirmation that it is closed is a hard prerequisite for any subsequent batch (not merely preferred). — **VERIFIED FACT** (RECON: Files gate PASS). Note: `docs/architecture/SECURITY.md:118-120` is stale (claims `server.properties` writes return 403; actually reads are blocked, writes intentionally allowed) — correction scheduled in Batch 7.6, not this task.

### Batch 7.1 — Data Model & Contracts
- **Objective:** Design first, code second — same discipline used for the Phase 4 Owner/Invite system.
- **Deliverables:**
  - DB schema per §6c.3: `host_playit_agent`, `server_exposure`, `server_exposure_target` (host-level agent record distinct from any single server's data, with **no `server_id`** on the host record).
  - Multi-target structure with a single `method` per server (§4.2), explicit `desired_state`, derived-cache `aggregate_status` (§6a.2), and the `error_code`/`error_message` fields (§6a.3).
  - REST API contracts for both subsystems, covering per-target and server-aggregate status reporting, and the new permission strings from **§8.6** registered in `contracts/permissions.yaml` with status `enforced`.
  - Full state machine per §6a: `DISABLED → CLAIM_REQUIRED → STARTING → ACTIVE → STOPPING → STOPPED`, with `DEGRADED`/`ERROR` branches and `RECLAIM_REQUIRED`, plus the deterministic aggregate precedence table (§6a.2) and the health thresholds (§6a.1).
  - Credential storage schema per §6d (encrypted secrets table, Owner-only via `exposure.credentials.manage`), using the **decided AES-GCM `BackupEncryption`** path (v3.2). **Companion registry is deferred** (user decision 2026-08-13); 7.1 creates **no `server_registered_ports` table**.
- **Dependencies:** Batch 7.0 answers on §9 — especially Q1 (Access Mode), Q6 (schema placement), Q8 (encryption mechanism — **decided**), Q10 (process supervision), Q12 (companion registry — **deferred by decision**). **v3.2 status: all satisfied.**
- **Hard scope rules for Batch 7.1 (v3.2 user decisions):** do **not** modify `access_mode` semantics (keep MODEL B — pure auth/registration policy); do **not** expose management/RCON/metrics/internal-Panel ports (keep §7 deny-list); do **not** start Phase 8; do **not** modify any implementation file until the 7.1 design is derived from these decisions. Companion ports remain disabled until a future approved registry; BlueMap and Simple Voice Chat are **not** auto-exposable.

### Batch 7.2a — Backend: Cloudflare Panel Exposure
- **Objective:** Implement Cloudflare as the **primary Panel** exposure method (§6b).
- **Deliverables:** Named-Tunnel orchestration per §6b (token intake, Custom-domain-only address model per §6b.1, ingress scoped to the authoritative Panel bind (§6b.3, localhost-only), `cloudflared` subprocess orchestration via `--token-file`, `RECLAIM_REQUIRED` handling for revoked tokens, credential storage on `panel_exposure` per §6b.2). Independent data/state, independent tests, independent review boundary. **Owner-only** (see §6b.4 — explicit `require_owner()` dependency).
- **Test plan:** unit tests per Cloudflare flow, missing/revoked-token failure paths, restart-recovery against `desired_state`, permission checks.

### Batch 7.2b — Backend: Panel Port Forwarding / UPnP + playit HTTP alternative
- **Objective:** Complete the remaining **Panel** exposure options (§3.2, §7).
- **Deliverables:** Port Forwarding/UPnP attempt-and-report logic per §7 for the Panel; the playit.gg HTTP-tunnel path for the Panel (Assisted Setup per Flow 1, sharing the host-level agent from §6c — depends on the host-agent core from Batch 7.3a). Independent data/state (separate from 7.2a and from all game-server exposure), independent tests, independent review boundary.
- **Test plan:** UPnP failure-path tests (unsupported by router, double NAT), deny-list enforcement for the Panel path, playit-HTTP reuse tests.
- **Sequencing note (v3.1):** 7.2b's UPnP half is independent of 7.2a; the playit-HTTP half depends on Batch 7.3a's host-agent core. If strict ordering is preferred, schedule the playit-HTTP sub-part after 7.3a without blocking 7.2b's UPnP portion.

### Batch 7.3a — Backend: playit Host Agent + Assisted Setup + Core Multi-Target (Java TCP first)
- **Objective:** Stand up the host-level agent architecture (§6c) correctly before anything else depends on it.
- **Deliverables:** single-agent-per-host supervision (§6c.1, platform-specific strategy incl. the recorded Windows limitation), claim flow with timeout/retry/reset (§6c.2), `desired_agent_running` derivation + lifecycle events (§6c.3), Assisted Setup tunnel creation (Flow 1) for Java TCP targets first, encrypted secret storage.
- **Test plan:** agent start/stop lifecycle tests (start when first target enables, stop when last target disables), claim-flow timeout and retry tests, crash/restart recovery tests, multi-server-same-agent tests (two servers both requesting playit tunnels must share one agent process), `desired_agent_running` derivation tests.

### Batch 7.3b — Backend: Port Forwarding / UPnP for Game Servers
- **Objective:** Implement the UPnP/port-forwarding mechanics from §7 for game server targets.
- **Deliverables:** conflict handling (bounded alternate-port retry), the four-state status vocabulary, deny-list enforcement (§7, §8) for RCON/management/DB/metrics/internal ports, port-registration validation per §8, double-NAT detection and graceful `Failed`/`Unsupported` reporting.
- **Test plan:** conflict-resolution tests, deny-list bypass attempts (must fail), external-IP reporting tests, port-registration validation tests.

### Batch 7.3c — Backend: Cloudflare TCP (Advanced) for Game Servers
- **Objective:** Implement the advanced/optional Cloudflare TCP path, gated behind the mandatory warning.
- **Deliverables:** Cloudflare TCP tunnel orchestration for game ports, the mandatory Modflared/`cloudflared` warning enforced server-side (not just UI-hidden), `RECLAIM_REQUIRED` handling for revoked tokens.
- **Test plan:** warning-acknowledgment-required tests, revoked-token transition tests.

### Batch 7.3d — Backend: Bedrock/UDP Targets + Companion Ports (optional, can slip to a later release without blocking 7.3a–c)
- **Objective:** Extend the multi-target and playit Assisted Setup work to UDP targets and RECON-approved companion services per §4.3.
- **Deliverables:** UDP tunnel creation via the same host agent, free-tier quota handling per §6a.3 (`PLAYIT_QUOTA_EXCEEDED`), companion-port policy (service_type allow-list per §4.3).
- **Test plan:** UDP-specific tunnel creation tests, `PLAYIT_QUOTA_EXCEEDED` UX/state tests.
- **Blocking condition:** **blocked on RECON-approved companion registry** (§9 Q12). If the registry is not approved, this batch is skipped/delayed without blocking 7.3a–c — this is a **hard statement**, not a preference.

### Batch 7.4 — Frontend: Panel Access UI
- **Objective:** Extend the existing Settings → Access page with the **PanelExposure** selector (distinct from the unchanged Access Mode toggle) and live status/link display described in §5A, including the LOCAL-mode advisory (§3.3).
- **Deliverables:** PanelExposure method selector, status indicator per method, one-time Cloudflare token entry flow with the **required hostname/domain input** (custom-domain-only per §6b.1; no quick-path/trycloudflare fallback), playit.gg claim-link + dashboard-fallback UI, resulting URL display with copy-to-clipboard (reuse the existing `useClipboard` hook from Part B).
- **Test plan:** component tests per method's UI state, error-state rendering, `DEGRADED`/`ERROR`/`RECLAIM_REQUIRED` displayed distinctly from `ACTIVE`, advisory-when-LOCAL test.

### Batch 7.5 — Frontend: Game Server Exposure UI
- **Objective:** New per-server Network/Exposure section as described in §5B, with multi-target list rendering and single-method-per-server enforcement (§4.2).
- **Deliverables:** method selector (single-select, not per-target), playit.gg first-run claim-link display with dashboard-fallback state, live public address display per target, "Not exposed" as the visible default state, the mandatory Cloudflare TCP warning gating that option, UPnP status display, server-level aggregate status badge (deterministic precedence, §6a.2), and the **Owner-only** Reset agent / Stop all exposures / Remove credentials actions from §6d.
- **Test plan:** component tests per method's UI state; confirm total isolation from the Panel Access UI/state; confirm the Cloudflare warning cannot be bypassed; multi-target list rendering tests; confirm the UI cannot construct a mixed-method request.

### Batch 7.6 — Security & Verification Pass
- **Objective:** Independent review across both new subsystems before anything is exposed to real traffic.
- **Deliverables:** confirm the Files API IDOR gap is resolved prior to sign-off; full regression suite run; SECURITY.md updated with the two new exposure surfaces, their permission requirements (§8.6), the credential-encryption approach, the port deny-list, rate limiting, audit logging from §8, the **Windows child-subprocess limitation (§6c.1)** recorded as a known limitation; explicit opt-in behavior verified end-to-end; explicit verification that a restart never silently re-exposes something the user had disabled; explicit verification that the deny-list cannot be bypassed via direct API calls (not just blocked in the UI); explicit verification that the aggregate-status precedence table (§6a.2) is correctly implemented (table-driven tests).
- **Exit criteria:** independent reviewer verdict SAFE TO COMMIT with evidence, not just builder claims.

---

## 11. Summary Table

| Element | Decision |
|---|---|
| Panel Access | Local / Global **reachability intent**; **PanelExposure** (MODEL B, §3.3) is the actual network switch; Cloudflare Named Tunnel is the primary supported method |
| Access Mode vs Exposure | **MODEL B — separated.** `access_mode` stays registration/auth policy (Phase 4, unchanged); `panel_exposure` is the new network switch. Changing Access Mode **never** publishes the Panel (§3.3) |
| Game Servers | playit.gg primary (Assisted Setup now, Full Automation later), Port Forwarding secondary, Cloudflare Tunnel advanced/optional with mandatory player-side-software warning |
| playit agent | **One per host**, shared across all servers/targets; MCS Manager supervises its lifecycle at the instance level; concrete `host_playit_agent` schema, derived `desired_agent_running` (§6c.3) |
| Method scope | One exposure method per server; multiple targets (Java/Bedrock/RECON-approved companions) under that one method |
| Targets per server | `server_exposure_target` rows with `service_type`, validated `local_port`, `error_code`/`error_message` (§4.3, §6c.3) |
| Target types / companions | Java + Bedrock always; companions only via RECON-approved registry; **no arbitrary ports** (§4.3) |
| UDP / Bedrock | First-class from day one, with documented player-network limitations |
| UPnP | Convenience only, never relied on exclusively; four-state status vocabulary; server-side deny-list (§7) |
| Tunnel lifecycle | `desired_state` persisted; deterministic aggregate-status precedence table (§6a.2); failures never silently become `ACTIVE` |
| Health / DEGRADED | Objectively testable tiers; 30s health interval; 90s stale threshold; 3-consecutive-failure → `DEGRADED`; hard failure → `ERROR`; single success → recovery to `ACTIVE` (§6a.1) |
| playit quota | Provider responses are authoritative; `ERROR` + `PLAYIT_QUOTA_EXCEEDED`; target-level scope; "Reduce enabled targets" / "Upgrade plan" (§6a.3) |
| Credentials | Encrypted at rest, Owner-only access (`exposure.credentials.manage`), dedicated secrets table; explicit Reset/Stop-all/Remove actions |
| Process supervision | systemd (Linux, preferred) / subprocess (fallback, and Windows v1) / sidecar (Docker); **Windows child-subprocess termination + deferred Service integration is a recorded known limitation** (§6c.1) |
| Exposure permissions | New design-contract strings `exposure.panel.manage`, `exposure.global.stop`, `exposure.credentials.manage`, `server.{id}.exposure`, `server.{id}.exposure.view`; no inference from roles or `server.{id}.settings` (§8.6) |
| Security | Rate limiting on claim/token intake, audit logging on all exposure changes, server-side port deny-list, RBAC from Phase 4 + §8.6 strings, Files API IDOR gap must be confirmed closed first |
| Any exposure | Must be explicit opt-in; nothing exposes itself automatically |

---

## 12. Changelog — v2 → v3 (carried forward)

1. **playit agent architecture corrected: one agent per host, not per server.** This was the most significant fix — v2 implicitly modeled per-server agents. v3 introduces host-level agent supervision (§6c) as its own data-model concern, independent of any single server. (§2 principle 6, §6c, §9 Q6, Q10, Batch 7.3a)
2. **One exposure method per server enforced.** Mixed methods across targets on the same server are explicitly out of scope for Phase 7. (§2 principle 7, §4.2, Batch 7.5)
3. **Agent process supervision specified per platform** — systemd on Linux, subprocess+auto-restart on Windows, sidecar/compose on Docker, with explicit health-check and restart rules. (§6c.1)
4. **Claim flow fully specified** — claim code generation, bounded exchange timeout, retry-on-failure, and an explicit "Reset agent" action tied to `playit reset`. (§6c.2)
5. **State machine expanded** — added `DEGRADED` (soft failure, may recover) and `RECLAIM_REQUIRED` (credential revoked upstream) as distinct states from `ERROR`, plus explicit `STOPPING`/`STOPPED` transitions. Added server-level aggregate status rules across multiple targets. (§6a)
 6. **Cloudflare Panel flow fully specified** — Named Tunnel (not Quick Tunnel), ingress scoped to the Panel bind only, orchestrate-only `cloudflared` subprocess (`--token-file`), explicit revoked-token handling. (§6b; **revised by the 7.2a RECON 2026-08-14:** custom-domain-only per §6b.1, PanelExposure credential fields per §6b.2, single Panel-bind config per §6b.3, explicit `require_owner()` per §6b.4)
7. **UPnP/port-forwarding mechanics specified concretely** — external-port-equals-local-port default, bounded conflict retry, four-state status vocabulary, double-NAT and IPv6 handling, and a hard server-side port deny-list for RCON/management ports. (§7)
8. **Security hardening section added** — rate limiting on claim/credential intake, audit logging on every exposure-state change, server-side `local_port` ownership validation, and the deny-list tied explicitly to security rather than just UX. (§8)
9. **UDP/Bedrock made explicitly first-class** — data model, Assisted Setup flow, and dashboard fallback all account for UDP targets from the start; free-tier port limits and player-network UDP blocking documented as known constraints. (§4.3)
10. **Reset/Stop-all/Remove-credentials UI actions added** as required, not optional, surfaces. (§6d, §5B, Batch 7.5)
11. **Batch 7.3 split into four sub-batches (7.3a–7.3d)** so each is independently reviewable: host agent + Assisted Setup core (a), UPnP/port-forwarding (b), Cloudflare TCP advanced (c), and UDP/Bedrock + companion ports (d, can slip without blocking the rest). (§10)
12. **Open Questions (§9) extended** with Q10 (process-supervision environment survey) and Q11 (UPnP library choice), both needed before Batch 7.3a/7.3b can start.

---

## 13. Changelog — v3 → v3.1 (design-repair revision)
1. **Host-level playit data model made concrete (§6c.3).** Defined `host_playit_agent` / `server_exposure` / `server_exposure_target` tables, explicit relationships (host agent has **no `server_id`**; 1─N indirect exposure link; 1─N targets; one method per exposure), derived `desired_agent_running` semantics with the authoritative `EXISTS` expression, and definitive behavior for last-disable / first-enable / credentials-removed / agent-crash / host-restart. (§§6c, 6c.3)
2. **Access Mode relationship decided — MODEL B (§3.3).** Access Mode is registration/auth policy only (verified: `GLOBAL` disables self-registration, no network binding exists); a separate `panel_exposure` setting controls network exposure. Swapping Access Mode can never expose the Panel; exposure can coexist with either mode; advisory shown when exposed while `LOCAL`. Security rule made structural. (§3.3, §3.4)
3. **Deterministic aggregate-status precedence (§6a.2).** Full precedence table (`RECLAIM_REQUIRED > CLAIM_REQUIRED > ERROR > DEGRADED > STOPPING > STARTING > ACTIVE > STOPPED`), `DISABLED` override, exact multi-target cases, "no targets + ENABLED = contract violation / `NO_TARGETS`", and aggregate status declared **derived at read time** (the `aggregate_status` column is a derived cache, never a second source of truth).
4. **Companion-port policy closed (§4.3).** Explicit allow-list (Java TCP + Bedrock UDP primary; Simple Voice Chat only if RECON-verified; BlueMap not auto-public; all others denied), five mandatory target checks, no arbitrary ports, and 7.3d **blocked on RECON-approved companion registry** as a hard statement.
5. **playit quota handling made deterministic (§6a.3).** Provider responses are authoritative; `ERROR` + `PLAYIT_QUOTA_EXCEEDED`; target-level scope (host-level only if provider evidence says so); UI shows affected targets + "Reduce enabled targets" / "Upgrade playit plan"; no locally-fabricated numeric limit.
6. **DEGRADED made objectively testable (§6a.1).** Health evidence tiers (HEALTHY/ACTIVE, DEGRADED, ERROR), fixed thresholds (30s interval, 90s stale, 3 consecutive failures), "process alive ≠ tunnel usable", and exact transition/recovery rules with no frontend-side status decisions.
7. **Windows supervision limitation made explicit (§6c.1).** Child-subprocess termination on exit, restart only while MCS Manager is alive, Windows Service deferred; applies to both playit and `cloudflared`.
8. **Batch 7.2 split into 7.2a (Cloudflare Panel) + 7.2b (Panel UPnP + playit HTTP)** with independent data/state/tests/review and a sequencing note for the playit-HTTP dependence on 7.3a. (§10)
9. **Phase 7 authorization matrix (§8.6).** Five proposed permission strings are defined as design contracts (`exposure.panel.manage`, `exposure.global.stop`, `exposure.credentials.manage`, `server.{id}.exposure`, `server.{id}.exposure.view`) with default grantees and the explicit rule that membership roles and `server.{id}.settings` infer nothing; Batch 7.1 must register them in `contracts/permissions.yaml`.
10. **RECON gate hardened (§9, §10).** Repaired questions are explicit inputs to Batch 7.0; Batch 7.1 must not begin until ten named blocking inputs are each VERIFIED FACT or EXPLICIT USER DECISION. Files API IDOR confirmation is a hard prerequisite.

---

## 13b. Changelog — v3.1 → v3.2 (Batch 7.0 RECON + Phase 7.1 design decisions)

1. **Batch 7.0 RECON recorded as COMPLETE** — all §9 questions answered; verdict **READY WITH EXPLICIT USER DECISIONS**. (§9, §10)
2. **Credential encryption decided (§6d, §9 Q8, §10 gate 2).** Explicit user decision (2026-08-13): reuse AES-GCM `BackupEncryption` + `load_or_create_backup_key` key-file lifecycle in `backend/app/modules/storage/encryption.py`. Fernet helpers in `core/security.py` are explicitly **excluded**; no third mechanism.
3. **Port-registration scope decided (§4.3, §9 Q9, §10 gate 3/8).** Explicit user decision (2026-08-13): **Phase 7 v1 = Java game port only** — `ServerModel.port` is the sole valid exposure target; **no `server_registered_ports` table in 7.1**; Bedrock/companion types rejected in v1 and deferred to a future approved registry. Companion-port policy updated accordingly; BlueMap / Simple Voice Chat remain not auto-exposable.
4. **UPnP library decided (§7, §9 Q11, §10 gate 7).** Explicit user decision (2026-08-13): **`aioupnp`**, added only at Batch 7.3b implementation time — deliberately **not** during Batch 7.1 schema work. `miniupnpc`/`upnpy` not used.
5. **Batch 7.1 hard scope rules recorded.** Do not modify `access_mode` semantics (MODEL B kept); do not expose management/RCON/metrics/internal-Panel ports; do not start Phase 8; do not modify implementation until the 7.1 design is derived from these decisions. (§10, Batch 7.1)
6. **RECON findings folded in.** Files API IDOR = hard prerequisite confirmed closed; `docs/architecture/SECURITY.md:118-120` flagged stale (writes to `server.properties` allowed, reads blocked) with correction scheduled for Batch 7.6. (§10, Batch 7.0)

---

## Appendix — Changelog v1 → v2 (carried forward for history)

1. **playit.gg integration model rewritten** from an implied one-click flow to an explicit two-phase strategy (Assisted Setup now, Full Automation later).
2. **Cloudflare TCP for game servers** given a mandatory UI warning about required player-side software, and barred from ever being labeled "Recommended."
3. **Multiple exposure targets per server** made a first-class requirement.
4. **Tunnel lifecycle on restart** given an initial `desired_state`-based design (later expanded in v3, §6a).
5. **Credential storage** given an initial encrypted-at-rest design (later expanded in v3, §6d).
6. **UPnP status vocabulary** standardized to four states (later given concrete mechanics in v3, §7).
7. **Cloudflare binary strategy** confirmed as orchestrate-only for Phase 7.
8. **Open Questions renumbered and sharpened**, with the multi-target question added.
9. **Batch Breakdown updated** across 7.0, 7.1, 7.3, 7.4, 7.5, 7.6 (7.3 later split further in v3).
10. **Panel §3.2 note added** on playit.gg's paid-tier gating for stable HTTP addresses.