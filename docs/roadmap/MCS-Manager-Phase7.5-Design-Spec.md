# BATCH 7.5 — DESIGN SPECIFICATION
# Game Server Network Exposure & Target UI (Frontend)

**Status:** DESIGN READY FOR BUILD (INDEPENDENT REVIEW COMPLETE)  
**Date:** 2026-08-16  
**Governing Roadmap:** `docs/roadmap/MCS-Manager-Phase7-Network-Access-Roadmap-v3.1.md` (§2, §4, §5B, §6a, §6c, §6d, §8.6, §10 Batch 7.5)  
**Prerequisites:** Batches 7.1–7.3d (All Backend Exposure APIs committed: `7d1c52a` $\to$ `71bb9f2`), Batch 7.4 (Frontend Panel Exposure committed: `6bdea17`)  
**Scope:** Frontend UI for Game Server network exposure (`/servers/:serverId/network`), multi-target management, playit Assisted Setup handoff, Cloudflare TCP player software warning, UPnP port forwarding, and global Owner exposure actions.

---

## 1. Scope & Boundaries

### 1.1 In-Scope (Batch 7.5 Deliverables)
1. **Server Network & Exposure Navigation & Route Integration:**
   - Extend `ServerShell.tsx` navigation with a first-class `"Network & Exposure"` nav item (icon: `globe`, path: `/servers/:serverId/network`).
   - Register route `/servers/:serverId/network` in `App.tsx` mounting `ServerExposurePage.tsx`.
   - Update `ServerDetailPage.tsx` ("Network & Deployment" info section) with a live exposure status badge and quick-link into the Network & Exposure page.
2. **Single-Method-Per-Server Selector:**
   - Method switcher supporting 4 explicit states:
     - `none` / Not Exposed (default).
     - `playit` — playit.gg edge tunnel (**Recommended**; supports TCP Java + UDP Bedrock/Voice).
     - `port_forward` — Direct router port forwarding via UPnP IGD.
     - `cloudflare_tcp` — Cloudflare Named Tunnel TCP stream (**Advanced**; requires player-side `Modflared`).
   - *No-Auto-Save Draft Policy:* Selecting or switching method cards updates local component draft state only. Persisted changes require clicking the primary *"Save & Apply Exposure"* button.
   - *Method-Switch Safety Guard:* Switching an active exposure method when the server is currently `ENABLED` and any target status is `ACTIVE` requires **typed confirmation** (`MethodSwitchConfirmModal` requiring user to type `"SWITCH"` before confirming) explaining that existing active tunnels will be disconnected and re-provisioned under the new method.
3. **Multi-Target List & Management:**
   - Multi-target list rendering under the active method displaying all configured targets (`java`, `bedrock`, `voice`, `bluemap`).
   - Each target card renders:
     - Service Type & Protocol badge (e.g. `Java (TCP)`, `Bedrock (UDP)`).
     - Local Port $\to$ Public Address display with 1-click clipboard copy (`useClipboard`).
     - Real-time status badge with 9-state vocabulary (`DISABLED`, `STARTING`, `ACTIVE`, `STOPPING`, `STOPPED`, `DEGRADED`, `ERROR`, `RECLAIM_REQUIRED`, `CLAIM_REQUIRED`).
     - Playit Assisted Setup dashboard handoff scaffold: Fixed numbered 3-step scaffold (*"1. Open Dashboard → 2. Create Tunnel → 3. Paste Address"*) wrapping the dynamic `setup_instructions` string, with explicit format examples/placeholders on the address input field.
     - Manual public address editor (`PUT /api/v1/servers/{server_id}/exposure/targets/{target_id}`) with `<host>:<port>` format validation.
     - Target removal action (for secondary/companion targets).
4. **Companion Target Addition & Port Registration Modal:**
   - Modal to add companion services (`bedrock` on UDP 19132, `voice` on UDP 24454, `bluemap` on TCP 8100).
   - Client-side validation: port range 1–65535, forbidden port deny-list (`DENY_LIST_PORTS`: 25575, 3306, 5432, 6379, 27017, 9090, 9100), and protocol-to-service affinity enforcement.
5. **Mandatory Cloudflare TCP Player Software Warning:**
   - Prominent amber warning banner explaining that Minecraft game traffic is raw TCP and requires players to run `Modflared` client mod or `cloudflared access tcp`.
   - Mandatory acknowledgement checkbox (`acknowledged_warning`) gating the *"Enable Cloudflare Tunnel"* button.
6. **Reusable `PlayitClaimCard` Mount:**
   - Mounts the decoupled [`PlayitClaimCard`](file:///mnt/D/files/server_manger/frontend/src/server_manager/components/PlayitClaimCard.tsx) (created in Batch 7.4) when `method === "playit"` and the host agent is unclaimed (`claimed === false` or `claimActive === true`).
7. **Instance Owner Global Exposure Actions:**
   - Global emergency control card visible only to Instance Owners (`exposure.credentials.manage` / Owner role):
     - **Reset Agent:** Clears host agent credentials and unclaims agent (`POST /api/v1/exposure/agent/reset`). Requires typed confirmation (typing `"RESET"`).
     - **Stop All Exposures:** Emergency shutdown disabling all exposures across all servers and panel without deleting credentials (`POST /api/v1/exposure/stop-all`). Requires typed confirmation (typing `"STOP ALL"`).
     - **Remove Credentials:** Deletes stored encrypted tokens and stops supervisors (`POST /api/v1/exposure/credentials/remove`). Requires typed confirmation (typing `"REMOVE CREDENTIALS"`).
8. **Adaptive Polling Hook (`useServerExposure`):**
   - TanStack Query hook managing server exposure (`queryKeys.exposure.server(id)`), targets (`queryKeys.exposure.targets(id)`), registered ports (`queryKeys.exposure.ports(id)`), and host agent status (`queryKeys.exposure.agent()`).
   - Adaptive polling: 2.5s during transitioning states (`STARTING`, `CLAIM_REQUIRED`, `STOPPING`), 10s steady state (`ACTIVE`, `DEGRADED`, `ERROR`, `RECLAIM_REQUIRED`), and disabled when `DISABLED` or `STOPPED`.
9. **RBAC Gating:**
   - Read-only users (`server.{id}.exposure.view`): Can view targets, copy addresses, and inspect statuses; all configuration forms and mutation buttons are disabled or hidden.
   - Managers (`server.{id}.exposure`): Can change exposure methods, add/remove companion targets, and update public addresses.
   - Instance Owners: Full management plus Global Exposure actions.
10. **Comprehensive Vitest Test Suite:**
    - Acceptance tests (`T-75-01` through `T-75-24`) covering method selection, target CRUD, port validation, Cloudflare warning acknowledgement, playit Assisted Setup handoff, RBAC view-only states, and adaptive polling.

### 1.2 Out-of-Scope (Deferred / Excluded)
- **Arbitrary Port Exposer:** Arbitrary un-registered ports outside the 4 approved services (`java`, `bedrock`, `voice`, `bluemap`) are strictly rejected by the backend and UI.
- **Backend Modifications:** Zero backend changes. All schemas, routers, and domain logic are committed and tested.
- **i18n:** Hardcoded English matching the rest of the frontend application.

---

## 2. Component Architecture & File Plan

### 2.1 Component Hierarchy Diagram

```
ServerShell.tsx (Nav item: "Network & Exposure" -> /servers/:serverId/network)
  └── ServerExposurePage.tsx (Container & RBAC Context)
        ├── ServerExposureSkeleton (Loading state)
        ├── ServerExposureHeader (Server name, aggregate status badge, quick actions)
        ├── ServerExposureMethodSelector.tsx (Grid: None, playit.gg, Port Forward, Cloudflare TCP)
        ├── MethodConfigurationPanel (Conditional per selected draft method)
        │     ├── PlayitMethodConfig
        │     │     ├── PlayitClaimCard.tsx [REUSED AS-IS FROM 7.4] (Mounted when host agent unclaimed)
        │     │     └── PlayitActiveNotice (Mounted when claimed)
        │     ├── PortForwardMethodConfig (UPnP status, external port override)
        │     └── CloudflareTcpMethodConfig (Hostname FQDN input, Token input, Mandatory Modflared Warning + Checkbox)
        ├── TargetListSection.tsx (Active targets list)
        │     ├── TargetListHeader (Target count, "Add Companion Target" button)
        │     ├── TargetCard.tsx (Per-target card)
        │     │     ├── ServiceProtocolBadge (e.g. "Java (TCP)" or "Bedrock (UDP)")
        │     │     ├── PublicAddressDisplay (Copyable URL/IP:Port via useClipboard)
        │     │     ├── StatusBadge (9-state vocabulary)
        │     │     ├── AssistedSetupBanner (Playit dashboard_url & setup_instructions handoff)
        │     │     ├── EditPublicAddressModal.tsx (Manual address entry for assisted setup)
        │     │     └── RemoveTargetButton (Confirmation dialog)
        │     └── AddCompanionTargetModal.tsx (Modal: pick service type, local port validation vs DENY_LIST)
        ├── GlobalExposureActionsCard.tsx [Owner-Only]
        │     ├── StopAllExposuresButton (Confirmation modal)
        │     ├── ResetAgentButton (Confirmation modal)
        │     └── RemoveCredentialsButton (Confirmation modal)
        └── MethodSwitchConfirmModal.tsx (Warns about target de-provisioning on method change)
```

### 2.2 Already-Built / Reused vs. New Components

| Component / Artifact | Status | Source / Location | Notes |
|---|---|---|---|
| [`PlayitClaimCard.tsx`](file:///mnt/D/files/server_manger/frontend/src/server_manager/components/PlayitClaimCard.tsx) | **REUSED AS-IS** | `frontend/src/server_manager/components/PlayitClaimCard.tsx` | 100% decoupled props contract; identical host agent claim endpoints. |
| [`StatusBadge.tsx`](file:///mnt/D/files/server_manger/frontend/src/components/ui/StatusBadge.tsx) | **REUSED AS-IS** | `frontend/src/components/ui/StatusBadge.tsx` | Uses `STATUS_MAP` which already includes `EXPOSURE_STATUS_MAP`. |
| [`useClipboard.ts`](file:///mnt/D/files/server_manger/frontend/src/hooks/useClipboard.ts) | **REUSED AS-IS** | `frontend/src/hooks/useClipboard.ts` | One-click address copy to clipboard. |
| [`Icon.tsx`](file:///mnt/D/files/server_manger/frontend/src/components/ui/Icon.tsx) | **REUSED AS-IS** | `frontend/src/components/ui/Icon.tsx` | UI icons (`globe`, `external`, `alert`, `copy`, `trash`, `edit`, `check`). |
| [`Skeleton.tsx`](file:///mnt/D/files/server_manger/frontend/src/components/Skeleton.tsx) | **REUSED AS-IS** | `frontend/src/components/Skeleton.tsx` | Loading state placeholder. |
| `useServerExposure.ts` | **NEW** | `frontend/src/server_manager/hooks/useServerExposure.ts` | Custom TanStack Query hook for per-server exposure & target state. |
| `ServerExposurePage.tsx` | **NEW** | `frontend/src/server_manager/pages/ServerExposurePage.tsx` | Main server exposure route view. |
| `ServerExposureMethodSelector.tsx` | **NEW** | `frontend/src/server_manager/components/ServerExposureMethodSelector.tsx` | Single-method switcher grid. |
| `TargetListSection.tsx` | **NEW** | `frontend/src/server_manager/components/TargetListSection.tsx` | Container for target cards & companion target creation. |
| `TargetCard.tsx` | **NEW** | `frontend/src/server_manager/components/TargetCard.tsx` | Individual target card with address, status, copy, assisted setup handoff. |
| `AddCompanionTargetModal.tsx` | **NEW** | `frontend/src/server_manager/components/AddCompanionTargetModal.tsx` | Modal to create Bedrock/Voice/BlueMap companion targets. |
| `EditPublicAddressModal.tsx` | **NEW** | `frontend/src/server_manager/components/EditPublicAddressModal.tsx` | Modal to update public address manually during assisted setup. |
| `GlobalExposureActionsCard.tsx` | **NEW** | `frontend/src/server_manager/components/GlobalExposureActionsCard.tsx` | Owner-only Reset/Stop-all/Remove-credentials actions. |
| `ServerShell.tsx` | **MODIFY** | `frontend/src/layouts/ServerShell.tsx` | Add `"Network & Exposure"` navigation item. |
| `App.tsx` | **MODIFY** | `frontend/src/App.tsx` | Register `servers/:serverId/network` route. |
| `ServerDetailPage.tsx` | **MODIFY** | `frontend/src/server_manager/pages/ServerDetailPage.tsx` | Add exposure summary badge & link in Network & Deployment section. |
| `types/index.ts` | **MODIFY** | `frontend/src/types/index.ts` | Add Server Exposure & Target TypeScript interfaces. |
| `services/api.ts` | **MODIFY** | `frontend/src/services/api.ts` | Add per-server exposure, targets, ports, and global exposure API methods. |
| `services/queryClient.ts` | **MODIFY** | `frontend/src/services/queryClient.ts` | Add `exposure.server`, `exposure.targets`, `exposure.ports` query keys. |

---

## 3. Data Contracts & Type Definitions

### 3.1 `frontend/src/types/index.ts` Extensions

```typescript
export type ExposureMethodType = "playit" | "port_forward" | "cloudflare_tcp";

export type TargetProtocolType = "tcp" | "udp";

export type ServiceType = "java" | "bedrock" | "voice" | "bluemap";

export interface TargetResponse {
  id: string;
  exposure_id: string;
  protocol: TargetProtocolType;
  service_type: ServiceType;
  local_port: number;
  public_address: string | null;
  status: ExposureStatusType;
  error_code: string | null;
  error_message: string | null;
  dashboard_url: string | null;
  setup_instructions: string | null;
}

export interface ServerExposureResponse {
  server_id: string;
  method: ExposureMethodType;
  desired_state: DesiredStateType;
  aggregate_status: ExposureStatusType;
  error_code: string | null;
  error_message: string | null;
  cloudflare_tunnel_id: string | null;
  has_cloudflare_credentials: boolean;
  targets: TargetResponse[];
}

export interface ServerExposureUpdateRequest {
  method: ExposureMethodType;
  desired_state: DesiredStateType;
  cloudflare_token?: string;
  hostname?: string;
  acknowledged_warning?: boolean;
}

export interface ServerExposureStateUpdateRequest {
  desired_state: DesiredStateType;
  cloudflare_token?: string;
  hostname?: string;
  acknowledged_warning?: boolean;
}

export interface TargetCreateRequest {
  service_type: ServiceType;
  protocol?: TargetProtocolType;
  local_port?: number;
  public_address?: string;
}

export interface TargetUpdateRequest {
  public_address: string;
}

export interface RegisteredPortResponse {
  id: string;
  server_id: string;
  service_type: ServiceType;
  protocol: TargetProtocolType;
  port: number;
  name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RegisteredPortCreateRequest {
  service_type: Exclude<ServiceType, "java">;
  protocol: TargetProtocolType;
  port: number;
  name?: string;
}

export interface StopAllResponse {
  disabled_count: int;
}
```

### 3.2 Service Affinity & Default Ports Mapping

```typescript
export const SERVICE_METADATA: Record<ServiceType, {
  label: string;
  defaultProtocol: TargetProtocolType;
  defaultPort: number;
  description: string;
  isPrimary: boolean;
}> = {
  java: {
    label: "Java Edition",
    defaultProtocol: "tcp",
    defaultPort: 25565,
    description: "Standard Minecraft Java game protocol (TCP). Port bound to Server Configuration.",
    isPrimary: true,
  },
  bedrock: {
    label: "Bedrock Edition (Geyser)",
    defaultProtocol: "udp",
    defaultPort: 19132,
    description: "Minecraft Bedrock RakNet protocol (UDP) for cross-play.",
    isPrimary: false,
  },
  voice: {
    label: "Simple Voice Chat",
    defaultProtocol: "udp",
    defaultPort: 24454,
    description: "In-game proximity voice chat protocol (UDP).",
    isPrimary: false,
  },
  bluemap: {
    label: "BlueMap Web Map",
    defaultProtocol: "tcp",
    defaultPort: 8100,
    description: "3D browser map viewer (HTTP/TCP).",
    isPrimary: false,
  },
};
```

---

## 4. API & Query Client Extensions

### 4.1 `frontend/src/services/api.ts` Methods

```typescript
// Per-Server Exposure
getServerExposure: (serverId: string) =>
  request<ServerExposureResponse>(`/api/v1/servers/${serverId}/exposure`),
setServerExposure: (serverId: string, body: ServerExposureUpdateRequest) =>
  request<ServerExposureResponse>(`/api/v1/servers/${serverId}/exposure`, {
    method: "PUT",
    body,
  }),
setServerExposureState: (serverId: string, body: ServerExposureStateUpdateRequest) =>
  request<ServerExposureResponse>(`/api/v1/servers/${serverId}/exposure`, {
    method: "PATCH",
    body,
  }),
removeServerExposure: (serverId: string) =>
  request<void>(`/api/v1/servers/${serverId}/exposure`, {
    method: "DELETE",
  }),

// Exposure Targets
listExposureTargets: (serverId: string) =>
  request<TargetResponse[]>(`/api/v1/servers/${serverId}/exposure/targets`),
createExposureTarget: (serverId: string, body: TargetCreateRequest) =>
  request<TargetResponse>(`/api/v1/servers/${serverId}/exposure/targets`, {
    method: "POST",
    body,
  }),
updateExposureTarget: (serverId: string, targetId: string, body: TargetUpdateRequest) =>
  request<TargetResponse>(`/api/v1/servers/${serverId}/exposure/targets/${targetId}`, {
    method: "PUT",
    body,
  }),

// Registered Ports
listServerPorts: (serverId: string) =>
  request<RegisteredPortResponse[]>(`/api/v1/servers/${serverId}/ports`),
registerServerPort: (serverId: string, body: RegisteredPortCreateRequest) =>
  request<RegisteredPortResponse>(`/api/v1/servers/${serverId}/ports`, {
    method: "POST",
    body,
  }),
deleteServerPort: (serverId: string, portId: string) =>
  request<void>(`/api/v1/servers/${serverId}/ports/${portId}`, {
    method: "DELETE",
  }),

// Global Exposure Actions (Owner-Only)
stopAllExposures: () =>
  request<StopAllResponse>("/api/v1/exposure/stop-all", {
    method: "POST",
  }),
removeCredentials: () =>
  request<{ status: string }>("/api/v1/exposure/credentials/remove", {
    method: "POST",
  }),
```

### 4.2 `frontend/src/services/queryClient.ts` Keys

```typescript
export const queryKeys = {
  // ... existing keys ...
  exposure: {
    all: ["exposure"] as const,
    panel: () => ["exposure", "panel"] as const,
    agent: () => ["exposure", "agent"] as const,
    server: (serverId: string) => ["exposure", "server", serverId] as const,
    targets: (serverId: string) => ["exposure", "targets", serverId] as const,
    ports: (serverId: string) => ["exposure", "ports", serverId] as const,
  },
};
```

---

## 5. Hook Design: `useServerExposure.ts`

### 5.1 Query & Polling Architecture
The `useServerExposure(serverId: string)` hook coordinates 4 queries and standard mutations:

1. **`serverExposureQuery` (`queryKeys.exposure.server(serverId)`):**
   - Fetches the `ServerExposureResponse` for the specified server.
   - Adaptive `refetchInterval`:
     - `2_500ms` if `aggregate_status` is in `["STARTING", "CLAIM_REQUIRED", "STOPPING"]`.
     - `false` if `desired_state === "DISABLED"` or `aggregate_status === "STOPPED"`.
     - `10_000ms` steady-state for `["ACTIVE", "DEGRADED", "ERROR", "RECLAIM_REQUIRED"]`.
2. **`agentStatusQuery` (`queryKeys.exposure.agent()`):**
   - Enabled only when `serverExposure.method === "playit"` and `desired_state === "ENABLED"`.
   - Adaptive `refetchInterval`: `2_500ms` while waiting for claim (`claim_active === true` or `claimed === false`), `10_000ms` once claimed.
3. **`portsQuery` (`queryKeys.exposure.ports(serverId)`):**
   - Fetches companion registered ports for the server (`GET /api/v1/servers/{server_id}/ports`).
4. **Mutations:**
   - `setExposure`: Calls `api.setServerExposure(serverId, body)`. Invalidates `exposure.server(serverId)` and `exposure.agent()`.
   - `disableExposure`: Calls `api.setServerExposureState(serverId, { desired_state: "DISABLED" })`.
   - `createTarget`: Calls `api.createExposureTarget(serverId, body)`. Optimistically refreshes target list.
   - `updateTargetAddress`: Calls `api.updateExposureTarget(serverId, targetId, { public_address })`.
   - `deletePort`: Calls `api.deleteServerPort(serverId, portId)`. Refreshes ports and exposure.

---

## 6. User Experience & Detailed Interaction Flows

### 6.1 Method Selector & No-Auto-Save Draft UX
- The method switcher presents 4 cards:
  1. **Not Exposed (`none`):** Server is reachable only via local LAN or VPN.
  2. **playit.gg (`playit` — Recommended):** Public tunnel via shared host agent. Supports Java TCP and Bedrock/Voice UDP. Works behind CGNAT.
  3. **Port Forwarding (`port_forward`):** Router port forwarding via UPnP IGD. Direct public IP access.
  4. **Cloudflare Tunnel (`cloudflare_tcp` — Advanced):** Encrypted TCP tunnel via Cloudflare.
- Selecting a card alters `draftMethod` in component state.
- **Method-Switch Guard Modal (`MethodSwitchConfirmModal`):**
  - If the server is currently `ENABLED` and any target status is `ACTIVE`, switching to a different method requires **typed confirmation** (not just a standard confirm/cancel dialog) to protect live game sessions.
  - The modal displays:
    > *"Changing exposure method will disconnect active tunnels and re-provision targets under the new method. Type **SWITCH** to confirm."*
  - The user must enter the exact string `"SWITCH"` into a confirmation input box before the *"Switch Method"* button is enabled.
  - If the exposure is currently `DISABLED` or no targets are `ACTIVE`, a standard one-click confirmation dialog is sufficient.

### 6.2 Cloudflare TCP Warning & Acknowledgement Gate
- When `draftMethod === "cloudflare_tcp"`:
  - Form displays `hostname` input (validated with `FQDN_REGEX`) and `cloudflare_token` input (with password reveal toggle).
  - Prominent amber warning callout:
    > ⚠️ **Player Client Requirement:** Unlike web websites, Minecraft game traffic cannot be proxied natively over standard DNS through Cloudflare. To connect, all players must either install the **Modflared** client mod or run `cloudflared access tcp` locally.
  - Mandatory checkbox:
    - `[ ] I understand that players must use Modflared or cloudflared to connect.`
  - The primary submit button *"Enable Cloudflare Tunnel"* remains **disabled** until:
    1. Valid FQDN hostname is provided.
    2. Cloudflare API token is provided (or previously stored).
    3. The acknowledgement checkbox is checked (`acknowledged_warning === true`).

### 6.3 playit.gg Assisted Setup & Dashboard Handoff UX
- When `method === "playit"`:
  - If the host agent is unclaimed, the embedded [`PlayitClaimCard`](file:///mnt/D/files/server_manger/frontend/src/server_manager/components/PlayitClaimCard.tsx) prompts for account authorization with copyable claim URL, countdown timer, and milestone screen reader announcements.
  - Once claimed, the backend attempts automated tunnel creation.
  - **Assisted Setup Dashboard Fallback:** If automated tunnel creation fails or requires manual routing, the target card displays a structured fixed numbered 3-step scaffold wrapping the dynamic `setup_instructions` from the backend:
    1. **Step 1: Open Dashboard** — Action button with external icon linking directly to `dashboard_url` (`https://playit.gg/manage`, opening in a new tab with `target="_blank" rel="noopener noreferrer"`).
    2. **Step 2: Create Tunnel** — Displays dynamic backend `setup_instructions` string (e.g. *"Create a TCP tunnel on playit.gg pointing to 127.0.0.1:25565"*).
    3. **Step 3: Paste Public Address** — Manual public address input field with placeholder / format example (`e.g. custom.ply.gg:12345` or `147.185.221.16:25565`), client-side `<host>:<port>` format validation, and a *"Save Address"* button calling `PUT /api/v1/servers/{server_id}/exposure/targets/{target_id}`.

### 6.4 Companion Target Creation & Port Deny-List Validation
- Clicking *"Add Companion Target"* opens `AddCompanionTargetModal`:
  1. **Service Type Selector:** Radio/Card selection for `Bedrock Edition (Geyser)`, `Simple Voice Chat`, or `BlueMap Web Map`.
  2. **Local Port Input:** Pre-populated with recommended default (`19132` for Bedrock, `24454` for Voice, `8100` for BlueMap).
  3. **Client-Side Validation:**
     - Must be an integer between `1` and `65535`.
     - Cannot be in `DENY_LIST_PORTS` (`25575`, `3306`, `5432`, `6379`, `27017`, `9090`, `9100`).
     - Cannot equal the server's primary Java game port (which is reserved for the primary `java` target).
     - Inline error message displays immediately if a denied or invalid port is entered, disabling the *"Create Target"* button.

### 6.5 Global Exposure Emergency Controls (Owner-Only)
- At the bottom of the page, a collapsible `"Instance Exposure Controls"` section is rendered **only** when `currentUser.roles.includes("owner")`:
  - **Stop All Exposures:** Triggers `POST /api/v1/exposure/stop-all` to disable all server and panel exposures in an emergency without deleting credentials. Requires typing `"STOP ALL"` into a confirmation text input before the action button is enabled.
  - **Reset playit Agent:** Triggers `POST /api/v1/exposure/agent/reset` to clear host credentials and unclaim the agent. Requires typed confirmation: user must enter `"RESET"` into the confirmation text input to enable the action button.
  - **Remove Credentials:** Triggers `POST /api/v1/exposure/credentials/remove` to delete encrypted token secrets and stop active supervisors. Requires typed confirmation: user must enter `"REMOVE CREDENTIALS"` into the confirmation text input to enable the action button.
  - *Safety Policy:* High-impact destructive operations MUST require explicit typed string confirmation to prevent catastrophic accidental disruption or loss of encrypted secrets.

---

## 7. RBAC & Permission Enforcement Contract

| UI Element / Action | `server.{id}.exposure.view` (Viewer) | `server.{id}.exposure` (Manager) | Instance Owner (`exposure.credentials.manage`) |
|---|:---:|:---:|:---:|
| View Exposure Status & Targets | ✅ Visible | ✅ Visible | ✅ Visible |
| Copy Public Address Link | ✅ Enabled | ✅ Enabled | ✅ Enabled |
| Switch Method / Change Desired State | ❌ Hidden / Read-only | ✅ Enabled | ✅ Enabled |
| Add / Remove Companion Target | ❌ Hidden | ✅ Enabled | ✅ Enabled |
| Edit Target Public Address (Assisted Setup) | ❌ Hidden | ✅ Enabled | ✅ Enabled |
| Cloudflare Token / Warning Inputs | ❌ Hidden | ✅ Enabled | ✅ Enabled |
| Global Reset / Stop-All / Remove Credentials | ❌ Hidden | ❌ Hidden | ✅ Enabled |

---

## 8. Client-Side Port Validation Rules (`DENY_LIST_PORTS`)

The frontend mirrors backend `DENY_LIST_PORTS` in [`aggregate.py:31-41`](file:///mnt/D/files/server_manger/backend/app/modules/exposure/domain/aggregate.py#L31-L41):

```typescript
export const DENY_LIST_PORTS: ReadonlySet<number> = new Set([
  25575, // RCON default
  3306,  // MySQL
  5432,  // PostgreSQL
  6379,  // Redis
  27017, // MongoDB
  9090,  // Prometheus metrics
  9100,  // Node exporter
]);

export function validateLocalPort(port: number, serverGamePort: number): { valid: boolean; error?: string } {
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return { valid: false, error: "Port must be a valid number between 1 and 65535." };
  }
  if (DENY_LIST_PORTS.has(port)) {
    return { valid: false, error: `Port ${port} is reserved for internal management/database services and cannot be exposed.` };
  }
  if (port === serverGamePort) {
    return { valid: false, error: `Port ${port} is already assigned to the primary Java game server.` };
  }
  return { valid: true };
}
```

---

## 9. Navigation & Page Integration

### 9.1 `ServerShell.tsx` Navigation
Add `"Network & Exposure"` to `navItems` in [`ServerShell.tsx`](file:///mnt/D/files/server_manger/frontend/src/layouts/ServerShell.tsx):

```typescript
const navItems = [
  { to: `/servers/${serverId}/console`, label: "Console", icon: "dashboard" as const },
  { to: `/servers/${serverId}/files`, label: "Files", icon: "folder" as const },
  { to: `/servers/${serverId}/network`, label: "Network & Exposure", icon: "globe" as const },
  ...(supportsMods ? [{ to: `/servers/${serverId}/mods`, label: "Mods", icon: "plugin" as const }] : []),
  ...(supportsPlugins ? [{ to: `/servers/${serverId}/plugins`, label: "Plugins", icon: "plugin" as const }] : []),
];
```

### 9.2 `App.tsx` Routing
Register the route under `servers/:serverId`:

```tsx
<Route path="servers/:serverId" element={<ServerShell />}>
  <Route index element={<Navigate to="console" replace />} />
  <Route path="console" element={<ServerDetailPage />} />
  <Route path="files" element={<ServerFilesPage />} />
  <Route path="network" element={<ServerExposurePage />} />
  <Route path="mods" element={<ServerModsPage />} />
  <Route path="plugins" element={<PluginListPage />} />
</Route>
```

### 9.3 `ServerDetailPage.tsx` Summary Row
In the "Network & Deployment" info section of [`ServerDetailPage.tsx`](file:///mnt/D/files/server_manger/frontend/src/server_manager/pages/ServerDetailPage.tsx), render the live exposure status and public address with a link to `/servers/${serverId}/network`:

```tsx
<DetailRow label="Public Exposure">
  {exposure?.desired_state === "ENABLED" && exposure.targets[0]?.public_address ? (
    <div className="flex items-center gap-2">
      <StatusBadge status={exposure.aggregate_status} />
      <span className="font-mono text-xs">{exposure.targets[0].public_address}</span>
      <Link to={`/servers/${serverId}/network`} className="text-blue-600 dark:text-blue-400 hover:underline text-xs">
        Manage
      </Link>
    </div>
  ) : (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-500">Not Exposed</span>
      <Link to={`/servers/${serverId}/network`} className="text-blue-600 dark:text-blue-400 hover:underline text-xs">
        Configure
      </Link>
    </div>
  )}
</DetailRow>
```

---

## 10. Acceptance Test Plan

All tests will be authored in Vitest with Testing Library (`frontend/src/server_manager/pages/ServerExposurePage.test.tsx`):

| Test ID | Test Name | Intent / Expected Assertion |
|---|---|---|
| **T-75-01** | `renders_not_exposed_default_state_cleanly` | When `desired_state="DISABLED"`, displays method selector with "Not Exposed" selected and "Not Exposed" summary banner. |
| **T-75-02** | `switching_method_cards_updates_draft_without_autosaving` | Clicking "playit.gg" card highlights the card and displays form without triggering PUT mutation. |
| **T-75-03** | `cloudflare_tcp_warning_checkbox_gates_save_button` | When selecting Cloudflare TCP, the save button is disabled until valid FQDN, token, and `acknowledged_warning` checkbox is checked. |
| **T-75-04** | `renders_multi_target_list_with_protocols_and_public_addresses` | Renders Java (TCP), Bedrock (UDP), and Voice (UDP) target cards with corresponding port numbers and live public addresses. |
| **T-75-05** | `copy_target_address_writes_to_clipboard_and_fires_toast` | Clicking copy button on target card calls `navigator.clipboard.writeText` and fires success toast. |
| **T-75-06** | `playit_assisted_setup_renders_numbered_scaffold_and_manual_edit_flow` | When target has `dashboard_url` and `setup_instructions`, renders 3-step numbered scaffold ("1. Open Dashboard", "2. Create Tunnel", "3. Paste Address"), format placeholder, and allows saving manual address. |
| **T-75-07** | `companion_target_modal_validates_port_range_and_deny_list` | Entering port 25575 (RCON) or 3306 (MySQL) in add target modal displays validation error and disables submit button. |
| **T-75-08** | `companion_target_modal_creates_new_bedrock_target` | Submitting valid Bedrock companion target triggers `POST /api/v1/servers/{id}/exposure/targets` with `service_type="bedrock"`. |
| **T-75-09** | `removing_companion_target_opens_confirmation_and_deletes` | Clicking remove target button opens confirmation modal and deletes target upon confirmation. |
| **T-75-10** | `adaptive_polling_frequency_matches_state_transitions` | Verifies hook polls at 2500ms during `STARTING`/`CLAIM_REQUIRED` and switches to 10000ms during `ACTIVE`. |
| **T-75-11** | `view_only_user_cannot_see_mutate_buttons_or_forms` | When user has `server.{id}.exposure.view` only, configuration forms, add target, and edit buttons are hidden/disabled. |
| **T-75-12** | `owner_actions_card_only_visible_to_instance_owner` | Global emergency actions card is visible only when user has Owner role (`currentUser.roles.includes("owner")`). |
| **T-75-13** | `owner_stop_all_exposures_requires_typed_confirmation_and_triggers_api` | Typing "STOP ALL" into confirmation input enables confirm button, calls `POST /api/v1/exposure/stop-all`, and invalidates exposure queries. |
| **T-75-14** | `owner_reset_agent_requires_typed_confirmation_and_clears_agent_credentials` | Typing "RESET" into confirmation input enables confirm button, calls `POST /api/v1/exposure/agent/reset`, and invalidates agent status query. |
| **T-75-15** | `method_switch_with_active_targets_requires_typed_confirmation` | Switching methods while targets are `ACTIVE` displays `MethodSwitchConfirmModal` requiring typing "SWITCH" before applying. |
| **T-75-16** | `disabling_exposure_opens_modal_and_patches_disabled_state` | Disabling active exposure opens confirm modal and calls `PATCH /api/v1/servers/{id}/exposure` with `desired_state="DISABLED"`. |
| **T-75-17** | `reclaim_required_status_renders_token_revoked_prompt` | When `aggregate_status="RECLAIM_REQUIRED"`, displays Token Revoked alert and token re-entry form. |
| **T-75-18** | `error_status_renders_error_banner_with_fix_hint` | When `aggregate_status="ERROR"` and `fix_hint` is present, renders actionable error banner. |
| **T-75-19** | `playit_claim_card_mounts_when_host_agent_unclaimed` | When `method="playit"` and `agent.claimed=false`, mounts `PlayitClaimCard` component. |
| **T-75-20** | `playit_claim_card_unmounts_once_agent_becomes_claimed` | Once `agent.claimed` becomes true, `PlayitClaimCard` unmounts and active targets are displayed. |
| **T-75-21** | `server_shell_nav_renders_network_and_exposure_link` | Verifies `ServerShell` renders `"Network & Exposure"` link pointing to `/servers/:serverId/network`. |
| **T-75-22** | `server_detail_page_renders_exposure_status_row_and_link` | Verifies `ServerDetailPage` displays exposure status badge and navigation link in Network section. |
| **T-75-23** | `non_blocking_mutation_error_leaves_inputs_editable` | Failed PUT/POST requests display error toast while leaving inputs fully editable. |
| **T-75-24** | `aggregate_status_precedence_renders_correct_top_badge` | Simulates multi-target statuses (one ERROR, one ACTIVE) and confirms server aggregate renders ERROR. |

---

## 11. Accessibility & UI Consistency

1. **Semantic HTML & ARIA:**
   - Error, warning, and advisory callouts use `role="alert"`.
   - Modals use `role="dialog" aria-modal="true" aria-labelledby="..."`.
   - External links (`dashboard_url`) include `target="_blank" rel="noopener noreferrer"` and visual `<Icon name="external" />`.
   - Copy buttons provide clear `aria-label="Copy <service> public address to clipboard"`.
2. **Focus Management:**
   - Modal open/close traps focus inside the modal and restores focus to trigger buttons on dismiss.
   - Programmatic focus shifting to public address cards upon successful exposure configuration.
3. **Responsive Layout:**
   - Fluid multi-column target grid on large screens collapsing cleanly to single-column cards on mobile viewports.
   - Dark mode styling using standard Tailwind palette (`dark:bg-gray-800`, `dark:text-gray-100`, `dark:border-gray-700`).

---

## 12. Findings Ledger

| ID | Finding / Decision | Classification | Documentation Location | Code/Test Impact | Status |
|---|---|---|---|---|---|
| **F-75-01** | Host-Level Agent Shared State | `[ARCHITECTURAL FACT]` | Roadmap §6c; Spec §2.2 | Host playit agent is instance-level; `PlayitClaimCard` reused with identical query keys. | ✅ Recorded |
| **F-75-02** | Single-Method Multi-Target Contract | `[DOMAIN CONSTRAINT]` | Roadmap §4.2; Spec §1.1, §6.1 | Top-level UI selects single method (`playit`/`port_forward`/`cloudflare_tcp`), sub-section manages multiple target rows. | ✅ Recorded |
| **F-75-03** | Cloudflare TCP Acknowledgement Mandate | `[SECURITY CONTROL]` | Spec §6.2 | Enforces `acknowledged_warning` checkbox before enabling Cloudflare TCP to inform users of Modflared client requirements. | ✅ Recorded |
| **F-75-04** | Port Deny-List Client-Side Mirroring | `[SECURITY CONTROL]` | Spec §8 | Prohibits ports 25575, 3306, 5432, 6379, 27017, 9090, 9100 on companion forms before API dispatch. | ✅ Recorded |
| **F-75-05** | playit Assisted Setup Dashboard Handoff | `[UX DESIGN]` | Spec §6.3 | Renders manual setup instructions & editable public address when playit automated tunnel creation requires manual fallback. | ✅ Recorded |
| **F-75-06** | Decoupled Reusable `PlayitClaimCard` Zero-Modification Reuse | `[ARCHITECTURAL DECISION]` | Spec §2.2 | Validates that `PlayitClaimCard.tsx` from Batch 7.4 requires zero code changes for Batch 7.5. | ✅ Recorded |
| **F-75-07** | Method-Switch Safety Warning Dialog | `[UX DESIGN]` | Spec §6.1 | Prompts user confirmation when switching exposure methods on an already-enabled server to prevent accidental tunnel teardown. | ✅ Recorded |
| **F-75-08** | Client-Side Protocol Affinity Mapping | `[TECHNICAL FACT]` | Spec §3.2 | Automatically assigns default transport protocols (`java` $\to$ TCP, `bedrock` $\to$ UDP, `voice` $\to$ UDP, `bluemap` $\to$ TCP). | ✅ Recorded |
| **F-75-09** | Three-Tier RBAC Surface (Viewer vs Manager vs Instance Owner) | `[SECURITY CONTROL]` | Spec §7 | Differentiates read-only viewers (`server.{id}.exposure.view`), server managers (`server.{id}.exposure`), and Instance Owners. | ✅ Recorded |
| **F-75-10** | Deterministic Aggregate Status Precedence Folding | `[TECHNICAL FACT]` | Spec §3.2, §10 | Renders top-level aggregate badge matching Roadmap §6a.2 precedence folding rules. | ✅ Recorded |
| **F-75-11** | First-Class Navigation & Detail Page Integration | `[UX DESIGN]` | Spec §9 | Adds `/servers/:serverId/network` route in `ServerShell.tsx` and summary badge in `ServerDetailPage.tsx`. | ✅ Recorded |
| **F-75-12** | 24-Test Acceptance Matrix with Isolation Guarantees | `[TEST STRATEGY]` | Spec §10 | Defines test cases `T-75-01` through `T-75-24` covering all interaction flows, error states, and permissions. | ✅ Recorded |
| **F-75-13** | Primary Java Target Immutability | `[DOMAIN CONSTRAINT]` | Spec §6.1, §6.3 | Primary `java` target cannot be deleted via the companion delete action; lifecycle tied strictly to overall exposure `desired_state`. | ✅ Recorded |
| **F-75-14** | Assisted Setup Manual Address Format Validation | `[SECURITY CONTROL]` | Spec §6.3 | Enforces `<host>:<port>` or FQDN string validation (max 512 chars) before calling `PUT .../targets/{target_id}`. | ✅ Recorded |
| **F-75-15** | React 19 Render-Phase State Synchronization for Forms | `[IMPLEMENTATION FINDING]` | `ServerExposurePage.tsx` | Applies render-phase adjustment pattern (`prevValue !== value`) avoiding `setState` in `useEffect` and preventing cascading re-renders. | ✅ Recorded |
| **F-75-16** | Accessible Focus Management & Modal Trapping | `[DESIGN DECISION]` | Spec §11 | Focus trapped in companion/address/switch modals and programmatically restored to trigger buttons upon dismissal. | ✅ Recorded |
| **F-75-17** | Method-Switch Typed Confirmation Guard | `[UX / SECURITY CONTROL]` | Spec §1.1, §6.1 | Switching exposure methods when `desired_state="ENABLED"` and any target is `ACTIVE` requires typing `"SWITCH"` in `MethodSwitchConfirmModal` to prevent accidental disconnection. | ✅ Recorded |
| **F-75-18** | Global Destructive Actions Typed Confirmation | `[SECURITY CONTROL]` | Spec §1.1, §6.5 | Destructive global actions (`agent/reset`, `credentials/remove`, `stop-all`) require typed confirmation strings (`"RESET"`, `"REMOVE CREDENTIALS"`, `"STOP ALL"`) to prevent catastrophic operational errors. | ✅ Recorded |
| **F-75-19** | playit Assisted Setup Fixed Numbered Scaffold & Format Example | `[UX DESIGN]` | Spec §1.1, §6.3 | Wraps dynamic backend `setup_instructions` in a fixed 3-step numbered scaffold (*"1. Open Dashboard → 2. Create Tunnel → 3. Paste Address"*) with `<host>:<port>` format placeholder on address input. | ✅ Recorded |

---

## 13. Implementation Boundary

### Files to be created during authorized implementation:
- `docs/roadmap/MCS-Manager-Phase7.5-Design-Spec.md` (This spec)
- `frontend/src/server_manager/hooks/useServerExposure.ts`
- `frontend/src/server_manager/pages/ServerExposurePage.tsx`
- `frontend/src/server_manager/components/ServerExposureMethodSelector.tsx`
- `frontend/src/server_manager/components/TargetListSection.tsx`
- `frontend/src/server_manager/components/TargetCard.tsx`
- `frontend/src/server_manager/components/AddCompanionTargetModal.tsx`
- `frontend/src/server_manager/components/EditPublicAddressModal.tsx`
- `frontend/src/server_manager/components/GlobalExposureActionsCard.tsx`
- `frontend/src/server_manager/pages/ServerExposurePage.test.tsx`

### Files to be modified during authorized implementation:
- `frontend/src/types/index.ts` (Add server exposure & target TypeScript contracts)
- `frontend/src/services/api.ts` (Add server exposure, target, port, and global action API methods)
- `frontend/src/services/queryClient.ts` (Add `exposure.server`, `exposure.targets`, `exposure.ports` query keys)
- `frontend/src/layouts/ServerShell.tsx` (Add `"Network & Exposure"` navigation item)
- `frontend/src/App.tsx` (Register `/servers/:serverId/network` route)
- `frontend/src/server_manager/pages/ServerDetailPage.tsx` (Add exposure status badge & quick-link in Network section)
- `.ai/CURRENT_STATE.json` (State tracking)
- `.ai/PROJECT_STATE.json` (State tracking)
