# MCS Manager — Phase 7 Engineering Roadmap: Network Access & Exposure

**Status:** DRAFT v3 — incorporates two Hard Review passes; design reviewed and approved at the concept level; RECON not yet started
**Base commit / prerequisite:** Phase 4 (Owner Bootstrap / Invitation / RBAC / Access Mode system) — COMPLETE
**Source:** v1 derived from the Phase 7 network-design review (Arabic original). v2 incorporated a Hard Review pass that re-verified playit.gg's integration surface and added lifecycle/credential handling. v3 incorporates a second Hard Review pass that corrects the playit agent architecture (host-level, not per-server), expands the state machine, and adds concrete process-supervision, claim-flow, UPnP, Cloudflare-Panel, and security-hardening detail.
**Scope of this document:** Phase 7 only. Nothing from Phases 5, 6, 8, 9, 10 is included.
**Changelog:** see §11 for v1→v2, and §12 for v2→v3.

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
6. **One playit.gg agent per host, not per server. (New in v3 — see §6c.)** MCS Manager supervises a single agent process/secret-key pair at the instance level; every server's playit targets are tunnels under that one agent, never a second agent process.
7. **One exposure method per server in Phase 7. (New in v3 — see §4.2.)** Mixing methods across targets on the same server (e.g. playit for Java, UPnP for Bedrock) is deferred to a later phase.

---

## 3. Panel Access Design

### 3.1 Modes

| Mode | Description | Typical use |
|---|---|---|
| **Local Mode** | Panel only reachable on `localhost` / LAN | Default, everyday home use |
| **Global Mode** | Panel reachable from the public internet | Remote access, or granting access to someone outside the LAN |

### 3.2 Global Mode exposure methods

| Method | Tier | Notes |
|---|---|---|
| **Port Forwarding + UPnP** | Basic | Manual or automatic port opening on the router |
| **Cloudflare Tunnel** | **Recommended** | Ready-made HTTPS, relatively stable address, best fit for a web frontend |
| **playit.gg (HTTP Tunnel)** | Alternative | Usable, but less flexible than Cloudflare specifically for the Panel. A stable/custom HTTPS address on playit.gg's HTTP tunnel tier is gated behind their paid plan — Cloudflare remains the recommended default for exactly this reason. |

**Design decision:** Cloudflare Tunnel is the primary/recommended path for Panel exposure, because it provides HTTPS out of the box and a reasonably stable address with minimal setup friction for a web UI, and because the Panel is HTTP-only traffic — exactly Cloudflare's strong case (see §6b for the full flow).

### 3.3 Relationship to the existing Phase 4 Access Mode setting

Phase 4 already shipped a Local ↔ Global **Access Mode** toggle under Settings → Access, with an explicit confirmation warning on switching to Global, as part of the Owner/Invitation system. Phase 7 does not duplicate this setting — it **extends it** with the actual exposure mechanics (Port Forwarding/UPnP, Cloudflare Tunnel, playit.gg) that make "Global" mean something concrete on the network layer, rather than just changing registration/auth policy as it does today. This relationship must be explicitly confirmed during Batch 7.0 RECON (see open questions, §8) before any schema work begins — treat "extend the existing setting" as the working assumption, not a settled fact.

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

A single Minecraft server is frequently more than one exposed port: Java (25565/TCP), Bedrock (19132/UDP), and optionally companion services like a voice-chat plugin or a BlueMap web viewer. Exposure config must support a **list of targets** per server, each independently tracked:

- `protocol`: `tcp` / `udp` / `both`
- `local_port`
- `public_address` (once active)
- `status` (see expanded state machine, §6a)

This is a data-model decision, not just a UI one — see §8.6 and §9 (Batch 7.1).

### 4.2 One method per server, multiple targets under it (new in v3)

v2 left it implicit whether a server could mix exposure methods across its targets (e.g. playit for Java, UPnP for Bedrock). v3 makes this explicit: **Phase 7 does not support mixed methods on the same server.** A server picks exactly one method (`none` / `playit` / `port_forward` / `cloudflare_tcp`), and every target on that server uses that method:

```
ServerExposure
  method: none | playit | port_forward | cloudflare_tcp
  desired_state: ENABLED | DISABLED
  targets[]:
    - protocol, local_port, public_address, status, ...
```

Rationale: mixed methods multiply UI, state-machine, and permission complexity for limited real-world benefit in v1. Revisit as a later-phase enhancement if there's demand.

### 4.3 Bedrock / UDP support (new in v3)

UDP targets (Bedrock, and raw UDP companion services) are supported from day one, not bolted on later:

- playit.gg supports both a dedicated "Minecraft Bedrock" tunnel type and raw UDP; the Assisted Setup flow (§6, Flow 1) requests `udp` or `both` per target as appropriate.
- If CLI-driven tunnel creation fails, the dashboard fallback includes Bedrock-specific instructions.
- playit's free tier has a limited number of concurrent ports (commonly cited as roughly 4 TCP + 4 UDP) — this should be surfaced to the user if they try to exceed it, not fail silently.
- Some player-side networks block UDP outright. This is outside MCS Manager's control and should be documented as a known limitation, not treated as a bug.

---

## 5. Proposed UI

Two clearly separated settings surfaces:

### A. Panel Access (Settings → Access, extends the Phase 4 Access page)
```
□ Local Mode (default)
○ Global Mode
   ├── Port Forwarding
   ├── Cloudflare Tunnel   ← Recommended
   └── playit.gg (HTTP)
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
targets (Java / Bedrock / other), shown as a list with protocol, port,
address, and per-target status. Server-level status is an aggregate of
all enabled targets (see §6a).

[Reset agent]  [Stop all exposures]  [Remove credentials]   ← §6d
```

---

## 6. User Flows

### Flow 1 — User selects playit.gg for a server ("Assisted Setup")

There is no officially-documented, guaranteed one-click tunnel-creation path for playit.gg. The tools that do this in practice (MineColab, Block-Suite, mcctl, Cliff-style integrations) all follow the same underlying pattern: the user obtains a **secret key** from the playit.gg dashboard (or a one-time claim), a single agent runs locally against that key, and tunnels are created either via the official agent CLI (`playit tunnels prepare --type tcp/udp/both`, `playit tunnels list`) or via the dashboard directly. Phase 7 adopts this as a two-phase strategy:

| Phase | Description | When |
|---|---|---|
| **v1 (this Phase 7 release)** | **Assisted Setup** — user completes a one-time Claim; MCS Manager attempts to create each tunnel automatically via the agent CLI, and if that fails, falls back to ready-made instructions/links to the playit.gg dashboard | Phase 7 |
| **v1.1 / later** | **Full Automation** — drive tunnel creation entirely through `tunnels/create` + `tunnels/prepare` once that surface is confirmed stable across playit.gg's supported integration API | Post-Phase-7 |

**Important correction from v2: the agent is host-level, not per-server (see §6c).** The claim and secret-key steps below happen once per MCS Manager instance, not once per server. A server enabling playit.gg for the first time triggers the *host* agent to start (if not already running) and then requests tunnels under it.

Revised flow:

1. Backend checks whether the host-level playit agent binary is present; downloads it if missing.
2. If no secret key is stored yet for this host → UI surfaces a one-time **Claim Link** flow (§6c.2) so the user can authorize the agent against their playit.gg account.
3. Once claimed, the secret key is stored **encrypted at rest** (§6b — credential storage) and the backend starts the single host-level agent process against it, if it isn't already running.
4. Backend attempts to create the tunnel automatically via the agent CLI (`playit tunnels prepare --type ...`) for the requested target(s) on this server (Java and/or Bedrock — §4.1, §4.3).
5. **If automatic creation succeeds:** UI displays the resulting public address (e.g. `something.at.ply.gg:xxxxx`) per target.
6. **If automatic creation fails:** UI shows an "Open playit.gg Dashboard" button with ready-made instructions for creating the tunnel manually, and polls/reads back the resulting address once the user has created it on their end.

### Flow 2 — User selects Cloudflare Tunnel for the Panel (expanded — see §6b for full detail)
1. User is prompted once for a Cloudflare API Token (Tunnel Edit scope, plus DNS Edit if they want a custom hostname).
2. Backend creates a **Named Tunnel** and points its ingress at the Panel's local port only.
3. UI displays the resulting `*.cfargotunnel.com` URL by default, or lets the user attach their own domain if their token has DNS Edit.

### 6a. Tunnel Lifecycle & State Machine (expanded in v3)

MCS Manager persists **user intent**, not just runtime status: a `desired_state` field (`ENABLED` / `DISABLED`) alongside a live `status`.

On MCS Manager restart:
- If `desired_state = ENABLED` → attempt to re-establish the tunnel automatically.
- If `desired_state = DISABLED` → **no** automatic restart; the tunnel stays down, silently, exactly as the user left it.
- Any failure to re-establish surfaces in the UI as `ERROR` — it never silently flips to `ACTIVE`, and it never silently re-exposes something the user doesn't expect.

**Expanded per-target state machine (v3):**

```
DISABLED → CLAIM_REQUIRED → STARTING → ACTIVE → STOPPING → STOPPED
                                ↓          ↓
                             DEGRADED    ERROR
                                ↓          ↓
                          RECLAIM_REQUIRED (credential revoked/reset upstream)
```

- `DEGRADED` — target was `ACTIVE` but a health check now indicates a problem (e.g. agent process alive but tunnel unreachable) without a hard failure. Distinct from `ERROR` so the UI can show "degraded, may recover" rather than "broken."
- `RECLAIM_REQUIRED` — the stored secret/token was invalidated upstream (e.g. the user ran `playit reset`, revoked the Cloudflare token from their dashboard, or the playit claim expired without completion). Requires the user to go through the claim/token flow again; MCS Manager never silently attempts to mint a new credential on the user's behalf.

**Server-level (aggregate) status**, since a server can have multiple targets under one method:

- All enabled targets `ACTIVE` → server shows `ACTIVE`.
- Some `ACTIVE`, some `ERROR`/`DEGRADED` → server shows `DEGRADED`.
- All enabled targets `ERROR` → server shows `ERROR`.
- `desired_state = DISABLED` → server shows `DISABLED`, regardless of individual target history.

This state machine applies independently per exposure target and independently between the Panel subsystem and each Game Server's subsystem — no shared state, per Core Design Principle #1.

### 6b. Cloudflare Panel Tunnel — full flow detail (new in v3)

v2 left this under-specified. v3 concrete flow:

1. User enters a Cloudflare API Token scoped to Tunnel Edit (and DNS Edit only if they intend to attach a custom hostname).
2. Backend creates a **Named Tunnel** (`config_src: cloudflare`) rather than a Quick Tunnel, since Named Tunnels are what supports a stable address and optional custom domain.
3. Ingress rule is scoped to exactly one route: `http://localhost:<PANEL_PORT>`. Nothing else on the host is ever put behind this ingress.
4. Two address options are surfaced:
   - **Quick path (default):** use the tunnel's own `*.cfargotunnel.com` address directly — no DNS Edit scope required.
   - **Custom domain (optional):** if the token has DNS Edit, create a CNAME record and surface the user's own hostname instead.
5. Backend runs `cloudflared tunnel run --token ...` as an orchestrated subprocess (orchestrate-only — see §8.5; MCS Manager does not bundle the binary in Phase 7).
6. `tunnel_id` and the token (encrypted — §6d) are persisted along with `desired_state`.
7. If the token is revoked externally (from the Cloudflare dashboard), the tunnel surfaces as `ERROR` transitioning to `RECLAIM_REQUIRED` — never a silent retry loop against a dead token.

Since the Panel is HTTP-only traffic, there is no TCP-tunnel variant to consider here — that complexity is scoped entirely to Game Server Exposure (§4).

### 6c. playit Agent Architecture — Host-Level, Not Per-Server (new in v3, corrects v2)

**This is the most significant correction in v3.** v2 implicitly modeled the playit agent as something tied to a server. That's wrong. Community and integration evidence (playit's own forum guidance for multi-server setups, and every serious integration — Geyser-adjacent tooling, Railway templates, Block-Suite, mcctl) converges on one pattern:

```
Host-level (once per MCS Manager instance):
  1× playit agent process
  1× secret key

Per server / per target (many, under that same agent):
  N tunnels — Java TCP, Bedrock UDP, voice, etc.
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
- Periodic health check (e.g. every 30s via `tunnels list` or a process-alive check).
- If the agent process dies while any target has `desired_state = ENABLED` → attempt restart, with the affected targets showing `STARTING` and then `ACTIVE` or `ERROR` depending on outcome.
- If MCS Manager itself shuts down: under `systemd` supervision the agent can keep running independently; under plain-subprocess supervision the agent dies with it. This is an accepted v1 limitation and must be documented as such, not silently glossed over.

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

### 6d. Credential Storage & Reset/Uninstall Paths (expanded in v3)

| Credential | Decision |
|---|---|
| Cloudflare API Token / Tunnel Token | Encrypted at rest (Fernet, or whatever symmetric-encryption mechanism the project's existing secrets handling already uses — confirm in RECON, §8) |
| playit.gg Secret Key | Same: encrypted at rest, never stored in plaintext in the DB |
| Access scope | Owner-only, matching the `global.settings` permission node from Phase 4 |
| Storage location | A dedicated secrets/settings table with encryption — not a plaintext column on `ServerModel` or the Panel settings row |

**Required UI actions (new in v3 — §5B):**

- **Reset playit agent** — clears the locally stored secret, runs `playit reset` if the agent is reachable, and returns every target under that method to `CLAIM_REQUIRED` or `DISABLED`.
- **Stop all exposures** — sets `desired_state = DISABLED` across every target, without deleting stored credentials.
- **Remove credentials** — securely deletes the encrypted secret/token and stops the associated agent/tunnel process.

---

## 7. UPnP / Port Forwarding — Implementation Detail (new in v3)

v2 treated UPnP as a single "attempt and report" step. v3 specifies the actual mechanics, based on common Python UPnP libraries (`miniupnpc`, `aioupnp`, `upnpy`) and known IGD failure modes:

| Aspect | Decision |
|---|---|
| External port default | Same as `local_port` |
| On conflict (`ConflictInMappingEntry`) | Try a small number of alternate ports in a bounded range; if all fail, report an explicit failure and let the user choose the external port manually |
| Status vocabulary | `Not Attempted` / `Succeeded` / `Failed` / `Unsupported by router` — the same four states used for both Panel and Game Server UPnP |
| Public address | Reported as `external_ip:external_port` after a successful mapping, with `external_ip` read back via `GetExternalIPAddress` |
| Double NAT | Not solvable via UPnP — reported as `Failed`/`Unsupported`, with the UI pointing the user toward playit.gg instead |
| IPv6 | Out of scope for Phase 7 |

**Hard rule — port deny-list:** UPnP/port-forwarding must never be usable to expose RCON, the Panel's own internal port (outside the dedicated Panel Access subsystem), database/metrics ports, or any port not explicitly registered as a game or companion-service port for that `server_id`. This deny-list is enforced server-side, not just hidden in the UI.

---

## 8. Security Hardening (new in v3)

| Gap | Fix |
|---|---|
| Unbounded claim/token-intake attempts | Rate limit per Owner (e.g. 5/hour) on claim generation and credential intake endpoints |
| No audit trail for exposure changes | Every Enable / Disable / Claim / Reset action emits an audit-log event |
| RCON / management ports reachable via game-exposure path | Explicit deny-list (§7) — these must never be selectable as a game exposure target |
| Arbitrary port exposure | `local_port` must validate against a port actually owned by/registered to that `server_id` before a target can be created |
| Files API IDOR | Hard gate — no exposure subsystem may be merged/shipped until this is confirmed closed (carried over from v1/v2, §8 open question 2) |

---

## 9. Open Questions to Resolve in RECON (Batch 7.0)

These are unresolved by the design review and must be answered with evidence before Batch 7.1 schema work starts:

1. **Access Mode relationship** — confirm Phase 7 extends the existing Phase 4 Local/Global Access Mode setting rather than introducing a second, competing setting (§3.3).
2. **Files API IDOR gap** — the prior documentation audit explicitly flagged the Files API read-route permission gap as *"must-resolve-before Phase 7 network exposure."* Confirm current status; if still open, treat it as a **hard blocker** — Panel/Game-server exposure should not ship while it's unresolved.
3. **Existing network-related code** — does the backend already contain any tunnel-management, UPnP, or port-related modules/dependencies to build on, or is this greenfield?
4. **playit.gg integration mechanism** — confirm whether the official agent CLI's `tunnels prepare`/`tunnels list` commands are viable as the primary automated path, with the dashboard as documented fallback. This directly determines the Assisted Setup flow in §6.
5. **Cloudflare `cloudflared` dependency** — Phase 7 ships as **orchestrate-only** (user installs `cloudflared`, or MCS Manager drives an already-installed binary); bundling deferred to a later phase pending cross-platform stability. RECON should confirm this against current platform-support reality.
6. **Data model placement** — new columns on `ServerModel`, or a new table (mirroring the `ServerMembership` pattern from Phase 4)? Must explicitly account for the multi-target structure (§4.1) — i.e., is this a `ServerExposure` parent row with a `server_exposure_targets` child table, or equivalent? Same question for Panel-level exposure state and for the host-level playit-agent record (§6c) that now sits outside any single server.
7. **Tunnel lifecycle on restart** — design proposed in §6a (`desired_state`, expanded state machine including `DEGRADED`/`RECLAIM_REQUIRED`). RECON should validate this is implementable against the current process-management/startup code.
8. **Credential storage** — design proposed in §6d. RECON should confirm which existing encryption mechanism in the codebase this should reuse.
9. **Multiple ports/targets per server** — confirm the concrete shape of `server_exposure_targets` against the actual `ServerModel` schema, and confirm each exposure method can independently report per-target status without cross-target coupling.
10. **playit agent process-supervision mechanism (new in v3)** — confirm systemd availability/version assumptions on the target Linux deployments, and confirm what subprocess-supervision infrastructure MCS Manager already has (if any) to reuse for Windows/Docker per §6c.1.
11. **UPnP library choice (new in v3)** — confirm which Python UPnP library (`miniupnpc`, `aioupnp`, `upnpy`, or other) is feasible given current dependencies and platform-support needs.

---

## 10. Batch Breakdown

Following the project's standard discipline: **RECON (evidence only, no code) → design decision → Build (diffs + tests, no commit) → independent review by a different agent → user approval → commit.** Never commit without explicit user go-ahead.

### Batch 7.0 — RECON
- **Objective:** Answer all open questions in §9 with evidence from the actual codebase; no code changes.
- **Deliverables:** RECON report covering: existing Access Mode implementation surface, Files API IDOR gap status, any existing network/tunnel code, dependency feasibility notes for playit.gg (CLI `tunnels prepare` viability specifically) and `cloudflared`, current `ServerModel`/settings schema shape, feasibility of the multi-target (`server_exposure_targets`) structure, systemd/process-supervision environment survey, and UPnP library feasibility.
- **Exit criteria:** every question in §9 has a confirmed answer or an explicit user decision recorded — including explicit confirmation (not assumption) that the Files API IDOR gap is closed before Batch 7.1 proceeds.

### Batch 7.1 — Data Model & Contracts
- **Objective:** Design first, code second — same discipline used for the Phase 4 Owner/Invite system.
- **Deliverables:**
  - DB schema for Panel exposure state, per-server exposure state, and the **host-level playit agent record** (§6c) — distinct from any single server's data.
  - Multi-target structure (`ServerExposure` + `server_exposure_targets` or equivalent) with a single `method` per server (§4.2) and an explicit `desired_state` field.
  - REST API contracts for both subsystems, covering per-target and server-aggregate status reporting.
  - Full state machine per §6a: `DISABLED → CLAIM_REQUIRED → STARTING → ACTIVE → STOPPING → STOPPED`, with `DEGRADED` and `ERROR` branches and `RECLAIM_REQUIRED` for revoked credentials.
  - Credential storage schema per §6d (encrypted secrets table, Owner-only scope), including the claim-flow transient fields from §6c.2.
- **Dependencies:** Batch 7.0 answers on schema placement, the multi-target question, credential storage, and process-supervision environment.

### Batch 7.2 — Backend: Panel Access Exposure Mechanics
- **Objective:** Implement the real exposure mechanics behind the existing Local/Global Access Mode setting.
- **Deliverables:** Cloudflare Named Tunnel orchestration per §6b (token intake, ingress scoped to the Panel port only, quick-path vs. custom-domain address, `cloudflared` subprocess orchestration), Port Forwarding/UPnP attempt-and-report logic per §7, playit.gg HTTP-tunnel path for the Panel as the alternative option (Assisted Setup pattern per §6, sharing the host-level agent from §6c).
- **Test plan:** unit tests per exposure method, failure-path tests (missing/revoked token → `RECLAIM_REQUIRED`, UPnP unsupported by router, agent download failure), permission checks (Owner-only, matching Phase 4's `global.settings` node), restart-recovery tests against `desired_state`.

### Batch 7.3a — Backend: playit Host Agent + Assisted Setup + Core Multi-Target (Java TCP first)
- **Objective:** Stand up the host-level agent architecture (§6c) correctly before anything else depends on it.
- **Deliverables:** single-agent-per-host supervision (§6c.1, platform-specific strategy), claim flow with timeout/retry/reset (§6c.2), Assisted Setup tunnel creation (§6, Flow 1) for Java TCP targets first, encrypted secret storage.
- **Test plan:** agent start/stop lifecycle tests (start when first target enables, stop when last target disables), claim-flow timeout and retry tests, multi-server-same-agent tests (two servers both requesting playit tunnels must share one agent process).

### Batch 7.3b — Backend: Port Forwarding / UPnP for Game Servers
- **Objective:** Implement the UPnP/port-forwarding mechanics from §7 for game server targets.
- **Deliverables:** conflict handling (bounded alternate-port retry), the four-state status vocabulary, deny-list enforcement (§8) for RCON/management ports, double-NAT detection and graceful `Failed`/`Unsupported` reporting.
- **Test plan:** conflict-resolution tests, deny-list bypass attempts (must fail), external-IP reporting tests.

### Batch 7.3c — Backend: Cloudflare TCP (Advanced) for Game Servers
- **Objective:** Implement the advanced/optional Cloudflare TCP path, gated behind the mandatory warning.
- **Deliverables:** Cloudflare TCP tunnel orchestration for game ports, the mandatory Modflared/`cloudflared` warning enforced server-side (not just UI-hidden), `RECLAIM_REQUIRED` handling for revoked tokens.
- **Test plan:** warning-acknowledgment-required tests, revoked-token transition tests.

### Batch 7.3d — Backend: Bedrock/UDP Targets + Companion Ports (optional, can slip to a later release without blocking 7.3a–c)
- **Objective:** Extend the multi-target and playit Assisted Setup work to UDP targets and companion services (voice chat, BlueMap, etc.) per §4.3.
- **Deliverables:** UDP tunnel creation via the same host agent, free-tier port-limit surfacing, companion-port policy (what's allowed to be exposed as a "companion" target vs. denied per §8).
- **Test plan:** UDP-specific tunnel creation tests, port-limit-exceeded UX tests.

### Batch 7.4 — Frontend: Panel Access UI
- **Objective:** Extend the existing Settings → Access page with the exposure-method selector and live status/link display described in §5A.
- **Deliverables:** method selector, status indicator per method, one-time Cloudflare token entry flow with quick-path/custom-domain choice, playit.gg claim-link + dashboard-fallback UI, resulting URL display with copy-to-clipboard (reuse the existing `useClipboard` hook from Part B).
- **Test plan:** component tests per method's UI state, error-state rendering, `DEGRADED`/`ERROR`/`RECLAIM_REQUIRED` displayed distinctly from `ACTIVE`.

### Batch 7.5 — Frontend: Game Server Exposure UI
- **Objective:** New per-server Network/Exposure section as described in §5B, with multi-target list rendering and single-method-per-server enforcement (§4.2).
- **Deliverables:** method selector (single-select, not per-target), playit.gg first-run claim-link display with dashboard-fallback state, live public address display per target, "Not exposed" as the visible default state, the mandatory Cloudflare TCP warning gating that option, UPnP status display, server-level aggregate status badge, and the **Reset agent / Stop all exposures / Remove credentials** actions from §6d.
- **Test plan:** component tests per method's UI state; confirm total isolation from the Panel Access UI/state; confirm the Cloudflare warning cannot be bypassed; multi-target list rendering tests; confirm the UI cannot construct a mixed-method request.

### Batch 7.6 — Security & Verification Pass
- **Objective:** Independent review across both new subsystems before anything is exposed to real traffic.
- **Deliverables:** confirm the Files API IDOR gap is resolved prior to sign-off; full regression suite run; SECURITY.md updated with the two new exposure surfaces, their permission requirements, the credential-encryption approach, the port deny-list, rate limiting, and audit logging from §8; explicit opt-in behavior verified end-to-end; explicit verification that a restart never silently re-exposes something the user had disabled; explicit verification that the deny-list cannot be bypassed via direct API calls (not just blocked in the UI).
- **Exit criteria:** independent reviewer verdict SAFE TO COMMIT with evidence, not just builder claims.

---

## 11. Summary Table

| Element | Decision |
|---|---|
| Panel Access | Local / Global, extending Phase 4's Access Mode; Cloudflare Named Tunnel is the primary supported Global method |
| Game Servers | playit.gg primary (Assisted Setup now, Full Automation later), Port Forwarding secondary, Cloudflare Tunnel advanced/optional with mandatory player-side-software warning |
| playit agent | **One per host**, shared across all servers/targets; MCS Manager supervises its lifecycle at the instance level |
| Method scope | One exposure method per server; multiple targets (Java/Bedrock/other) under that one method |
| UDP / Bedrock | First-class from day one, with documented free-tier and player-network limitations |
| UPnP | Convenience only, never relied on exclusively; four-state status vocabulary; deny-list enforced server-side |
| Tunnel lifecycle | `desired_state` persisted; expanded state machine with `DEGRADED` and `RECLAIM_REQUIRED`; failures never silently become `ACTIVE` |
| Credentials | Encrypted at rest, Owner-only access, dedicated secrets table; explicit Reset/Stop-all/Remove actions |
| Security | Rate limiting on claim/token intake, audit logging on all exposure changes, server-side port deny-list, RBAC from Phase 4, Files API IDOR gap must close first |
| Any exposure | Must be explicit opt-in; nothing exposes itself automatically |

---

## 12. Changelog — v2 → v3

1. **playit agent architecture corrected: one agent per host, not per server.** This was the most significant fix — v2 implicitly modeled per-server agents. v3 introduces host-level agent supervision (§6c) as its own data-model concern, independent of any single server. (§2 principle 6, §6c, §9 Q6, Q10, Batch 7.3a)
2. **One exposure method per server enforced.** Mixed methods across targets on the same server are explicitly out of scope for Phase 7. (§2 principle 7, §4.2, Batch 7.5)
3. **Agent process supervision specified per platform** — systemd on Linux, subprocess+auto-restart on Windows, sidecar/compose on Docker, with explicit health-check and restart rules. (§6c.1)
4. **Claim flow fully specified** — claim code generation, bounded exchange timeout, retry-on-failure, and an explicit "Reset agent" action tied to `playit reset`. (§6c.2)
5. **State machine expanded** — added `DEGRADED` (soft failure, may recover) and `RECLAIM_REQUIRED` (credential revoked upstream) as distinct states from `ERROR`, plus explicit `STOPPING`/`STOPPED` transitions. Added server-level aggregate status rules across multiple targets. (§6a)
6. **Cloudflare Panel flow fully specified** — Named Tunnel (not Quick Tunnel), ingress scoped to the Panel port only, quick-path `*.cfargotunnel.com` vs. optional custom-domain-via-DNS-Edit, orchestrate-only `cloudflared` subprocess, explicit revoked-token handling. (§6b)
7. **UPnP/port-forwarding mechanics specified concretely** — external-port-equals-local-port default, bounded conflict retry, four-state status vocabulary, double-NAT and IPv6 handling, and a hard server-side port deny-list for RCON/management ports. (§7)
8. **Security hardening section added** — rate limiting on claim/credential intake, audit logging on every exposure-state change, server-side `local_port` ownership validation, and the deny-list tied explicitly to security rather than just UX. (§8)
9. **UDP/Bedrock made explicitly first-class** — data model, Assisted Setup flow, and dashboard fallback all account for UDP targets from the start; free-tier port limits and player-network UDP blocking documented as known constraints. (§4.3)
10. **Reset/Stop-all/Remove-credentials UI actions added** as required, not optional, surfaces. (§6d, §5B, Batch 7.5)
11. **Batch 7.3 split into four sub-batches (7.3a–7.3d)** so each is independently reviewable: host agent + Assisted Setup core (a), UPnP/port-forwarding (b), Cloudflare TCP advanced (c), and UDP/Bedrock + companion ports (d, can slip without blocking the rest). (§10)
12. **Open Questions (§9) extended** with Q10 (process-supervision environment survey) and Q11 (UPnP library choice), both needed before Batch 7.3a/7.3b can start.

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
