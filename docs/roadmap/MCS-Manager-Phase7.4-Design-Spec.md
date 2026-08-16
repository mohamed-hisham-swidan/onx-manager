# BATCH 7.4 — DESIGN SPECIFICATION
# Frontend Panel Access Exposure UI

**Status:** DESIGN READY FOR REVIEW (INDEPENDENT REVIEW COMPLETE)  
**Date:** 2026-08-16  
**Governing Roadmap:** `docs/roadmap/MCS-Manager-Phase7-Network-Access-Roadmap-v3.1.md` (§3.3, §5A, §6b, §6c, §10 Batch 7.4)  
**Prerequisites:** Batches 7.1, 7.2a, 7.2b (Backend Panel & Agent Exposure APIs committed: `56cd384`, `b357a5a`, `ab2c2785`)  
**Scope:** Frontend UI for Panel Access exposure only (Settings → Access tab). Game Server exposure is deferred to Batch 7.5.

---

## 1. Scope & Boundaries

### 1.1 In-Scope (Batch 7.4 Deliverables)
1. **Access Settings Page Integration:** Extend the existing Settings → Access tab (`AccessSection.tsx`) to mount a dedicated `PanelExposureSection` subcomponent directly below the existing `AccessModeCard` (Model B: strictly separating registration policy from network reachability).
2. **Panel Exposure Method Selector:** Interactive method switcher supporting four explicit states:
   - `none` — Panel exposure disabled (default / local network only).
   - `cloudflare_tunnel` — Cloudflare Named Tunnel (Recommended for web traffic; automatic HTTPS).
   - `playit_http` — playit.gg HTTP tunnel via shared host agent.
   - `port_forward` — Local IGD / UPnP port mapping over HTTP.
   - *Draft selection policy:* Selecting or switching method cards in the UI modifies local draft state only; no network call or exposure modification is persisted until the user explicitly clicks the "Enable" / "Save Configuration" primary button.
3. **Method-Specific Configuration Forms:**
   - **Cloudflare Tunnel Form:** Masked Cloudflare API token input (`type="password"` with accessible "Show/Hide token" reveal toggle), required FQDN custom domain hostname input with inline regex validation and authoritative server fallback, and token rotation support when in `RECLAIM_REQUIRED` state.
   - **playit.gg Setup Flow:** Integration with the reusable `PlayitClaimCard` to display claim link, claim code, countdown timer with milestone-only screen reader announcements, explicit user-triggered regeneration on expiry, and claim-refresh polling when unclaimed.
   - **Port Forwarding Form:** Optional external port input (1–65535, defaulting to backend detection), display of UPnP last result (`upnp_last_result`), and actionable `BIND_MISMATCH` auto-fix restart advisory.
4. **Live Status & Address Display:**
   - Real-time status badge rendering with full 9-state vocabulary (`DISABLED`, `STARTING`, `ACTIVE`, `STOPPING`, `STOPPED`, `DEGRADED`, `ERROR`, `RECLAIM_REQUIRED`, `CLAIM_REQUIRED`).
   - Clickable and copyable public address link with protocol/TLS indicator (`https://` vs `http://`).
   - One-click copy integration via existing `useClipboard` hook.
5. **Reusable `PlayitClaimCard` Component:** Fully decoupled, generic claim-code/URL/countdown/refresh component structured for 100% reuse by Batch 7.5 (Game Server Exposure UI) without modification.
6. **Smart Polling Data Hook (`usePanelExposure`):** TanStack React Query custom hook with adaptive `refetchInterval` function (2.5s while transitioning, 10s steady state, disabled when stopped) and non-blocking error handling that keeps forms fully editable on failure.
7. **Advisory & Error Banner System:** Differentiated security advisory banner (LOCAL vs GLOBAL reachability warning from backend) and unified error banner with `error_code`, `error_message`, and `fix_hint`.
8. **Owner-Gating & Focus Management:** Single, non-duplicated Owner permission gate matching existing `AccessSection.tsx` standards, accompanied by accessible focus traps in modals and programmatic focus restoration.
9. **Full Vitest Component & Unit Test Suites:** Comprehensive coverage of all states, forms, edge cases, error recoveries, and polling behaviors (21 acceptance tests: `T-74-01` through `T-74-21`).

### 1.2 Out-of-Scope (Deferred to Later Batches)
- **Batch 7.5 (Game Server Exposure UI):** Per-server exposure, companion ports (Bedrock, Simple Voice Chat, BlueMap), multi-target tables, single-method-per-server enforcement, and global Owner actions (Reset Agent, Stop All, Remove Credentials).
- **i18n / Localization:** Codebase contains no i18n framework; all UI copy is hardcoded English matching existing conventions.
- **Backend Modifications:** Zero backend changes (.py / Alembic). All required backend endpoints and schemas are already committed in master.

---

## 2. Component Architecture & File Plan

### 2.1 Component Hierarchy Diagram

```
SettingsPage.tsx (ActiveTab = "access")
  └── AccessSection.tsx (Single Owner-Gate: require Owner role)
        ├── [Section 1] AccessModeCard.tsx (Extracted from AccessSection — Local vs Global registration)
        └── [Section 2] PanelExposureSection.tsx (NEW: Panel Network Ingress Switcher)
              ├── PanelExposureSkeleton (Rendered while initial panelQuery.isLoading is true)
              ├── PanelExposureHeader (Title, subtitle, overall status badge)
              ├── AdvisoryBanner (Role="alert", renders security_advisory e.g. LOCAL unencrypted warning)
              ├── ErrorFixBanner (Role="alert", renders error_code, error_message, and fix_hint)
              ├── MethodSelectorGrid (Cards for None, Cloudflare, playit.gg, Port Forward)
              │     ├── MethodCard: "none"
              │     ├── MethodCard: "cloudflare_tunnel" (Recommended badge)
              │     ├── MethodCard: "playit_http"
              │     └── MethodCard: "port_forward"
              ├── MethodConfigPanel (Conditional based on selected/draft method)
              │     ├── CloudflareConfigForm (Token password input, Hostname FQDN input, Save button)
              │     ├── PlayitPanelConfig (Claim status check, mounts PlayitClaimCard if unclaimed)
              │     │     └── PlayitClaimCard.tsx (GENERIC / REUSABLE: claim code, URL, timer, copy)
              │     └── PortForwardConfigForm (External port input, UPnP status badge, Save button)
              └── ActiveExposureCard (Visible when desired_state=ENABLED & status=ACTIVE/DEGRADED)
                    ├── PublicAddressLink (Clickable URL with protocol badge https/http)
                    ├── CopyAddressButton (Reuses useClipboard hook)
                    └── DisableExposureButton (Sets desired_state=DISABLED with confirmation modal)
```

### 2.2 File Inventory & Responsibilities

| File Path | Action | Responsibility | Target Size |
|---|---|---|---|
| `frontend/src/types/index.ts` | Modify | Add TypeScript interfaces for Panel Exposure contracts (`PanelExposureResponse`, `PanelExposureUpdateRequest`, `AgentStatusResponse`, `ClaimResponse`). | +60 lines |
| `frontend/src/services/api.ts` | Modify | Add typed API methods (`getPanelExposure`, `setPanelExposure`, `getAgentStatus`, `generateClaim`, `resetAgent`). | +35 lines |
| `frontend/src/services/queryClient.ts` | Modify | Add `queryKeys.exposure.panel()` and `queryKeys.exposure.agent()` keys. | +10 lines |
| `frontend/src/server_manager/types.ts` | Modify | Add `EXPOSURE_STATUS_MAP` and merge into `STATUS_MAP` for `StatusBadge` compatibility. | +35 lines |
| `frontend/src/server_manager/hooks/usePanelExposure.ts` | Create | Custom TanStack Query hook managing server state, adaptive polling interval, mutations, and derived flags. | ~110 lines |
| `frontend/src/server_manager/components/PlayitClaimCard.tsx` | Create | Generic, self-contained playit.gg claim UI component reusable by Batches 7.4 & 7.5. | ~160 lines |
| `frontend/src/server_manager/components/PanelExposureSection.tsx` | Create | Main container for panel exposure selector, method forms, active status display, and advisories. | ~280 lines |
| `frontend/src/server_manager/components/AccessModeCard.tsx` | Create | Refactored standalone component for Instance Access Mode (LOCAL vs GLOBAL registration), extracted cleanly from `AccessSection.tsx`. | ~140 lines |
| `frontend/src/server_manager/components/AccessSection.tsx` | Modify | Orchestrator container mounting `AccessModeCard` and `PanelExposureSection` behind the single Owner gate. | ~80 lines |
| `frontend/src/server_manager/components/PlayitClaimCard.test.tsx` | Create | Vitest test suite for claim card rendering, countdown, copy actions, and callbacks. | ~180 lines |
| `frontend/src/server_manager/components/PanelExposureSection.test.tsx` | Create | Comprehensive Vitest suite for all panel exposure methods, form validation, error banners, and state transitions. | ~360 lines |

### 2.3 State Ownership Architecture

1. **Server State (TanStack Query via `usePanelExposure`):**
   - Panel exposure configuration & live status (`queryKeys.exposure.panel()`).
   - Host playit agent status (`queryKeys.exposure.agent()`).
   - Background re-fetch and adaptive interval polling.
   - Cache invalidation and optimistic updates on `setPanelExposure` mutation.
2. **Local Form State (React `useState` in `PanelExposureSection`):**
   - `draftMethod`: The currently selected method tab/card before save (`"none" | "cloudflare_tunnel" | "playit_http" | "port_forward"`).
   - `cloudflareToken`: String draft for Cloudflare API token.
   - `hostname`: String draft for Cloudflare hostname (with real-time FQDN validation).
   - `showToken`: Boolean for toggling password visibility on the token field.
   - `externalPort`: Number or null for custom Port Forwarding external port.
   - `isConfirmDisableOpen`: Boolean controlling confirmation modal when disabling active exposure.
3. **Transient UI State (Hooks & Primitives):**
   - Clipboard copy feedback via `useClipboard`.
   - Toast alerts via `toastStore`.
   - No Zustand store required for Panel Exposure (server state is strictly query-driven).

---

## 3. TypeScript Contract Types

Add the following exact contract interfaces to `frontend/src/types/index.ts` and `frontend/src/server_manager/types.ts`:

### 3.1 Backend Contract Types (`frontend/src/types/index.ts`)

```typescript
export type PanelExposureMethodType = "none" | "cloudflare_tunnel" | "playit_http" | "port_forward";

export type DesiredStateType = "ENABLED" | "DISABLED";

export type ExposureStatusType =
  | "DISABLED"
  | "STARTING"
  | "ACTIVE"
  | "STOPPING"
  | "STOPPED"
  | "DEGRADED"
  | "ERROR"
  | "RECLAIM_REQUIRED"
  | "CLAIM_REQUIRED";

export interface PanelExposureResponse {
  method: PanelExposureMethodType;
  desired_state: DesiredStateType;
  status: ExposureStatusType;
  public_address: string | null;
  tls: boolean;
  protocol: "http" | "https";
  external_port: number | null;
  cloudflare_tunnel_id: string | null;
  playit_tunnel_id: string | null;
  upnp_last_result: string | null;
  error_code: string | null;
  error_message: string | null;
  fix_hint: string | null;
  auto_fixed: boolean;
  security_advisory: string | null;
}

export interface PanelExposureUpdateRequest {
  method: PanelExposureMethodType;
  desired_state: DesiredStateType;
  cloudflare_token?: string;
  hostname?: string;
  external_port?: number | null;
}

export interface AgentStatusResponse {
  claimed: boolean;
  process_status: string; // "RUNNING" | "STOPPED" | "STARTING" | "ERROR"
  desired_agent_running: boolean;
  last_health_at: string | null;
  claim_active: boolean;
  claim_expires_at: string | null;
}

export interface ClaimResponse {
  claim_code: string;
  claim_url: string;
  expires_at: string;
}
```

### 3.2 UI Helper Types & StatusBadge Integration (`frontend/src/server_manager/types.ts`)

To ensure complete compatibility with existing `StatusBadge.tsx` without modifying `StatusBadge.tsx`, `STATUS_MAP` in `frontend/src/server_manager/types.ts` is extended to include uppercase `ExposureStatusType` keys mapped to their respective badge definitions:

```typescript
import type { ExposureStatusType } from "@/types";

export interface ExposureStatusBadgeConfig {
  label: string;
  color: string;
  dotColor: string;
  iconName?: "check" | "alert" | "info" | "restart";
}

export const EXPOSURE_STATUS_MAP: Record<ExposureStatusType, ExposureStatusBadgeConfig> = {
  ACTIVE: {
    label: "Active",
    color: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300 border-green-200 dark:border-green-800",
    dotColor: "bg-green-500",
    iconName: "check",
  },
  STARTING: {
    label: "Starting...",
    color: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 border-blue-200 dark:border-blue-800",
    dotColor: "bg-blue-500 animate-pulse",
  },
  STOPPING: {
    label: "Stopping...",
    color: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300 border-orange-200 dark:border-orange-800",
    dotColor: "bg-orange-500 animate-pulse",
  },
  STOPPED: {
    label: "Stopped",
    color: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border-gray-200 dark:border-gray-700",
    dotColor: "bg-gray-400",
  },
  DISABLED: {
    label: "Disabled",
    color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 border-gray-200 dark:border-gray-700",
    dotColor: "bg-gray-400",
  },
  DEGRADED: {
    label: "Degraded",
    color: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 border-amber-200 dark:border-amber-800",
    dotColor: "bg-amber-500",
    iconName: "alert",
  },
  ERROR: {
    label: "Error",
    color: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-800",
    dotColor: "bg-red-500",
    iconName: "alert",
  },
  RECLAIM_REQUIRED: {
    label: "Token Revoked",
    color: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border-red-200 dark:border-red-800",
    dotColor: "bg-red-500",
    iconName: "alert",
  },
  CLAIM_REQUIRED: {
    label: "Claim Required",
    color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800",
    dotColor: "bg-yellow-500 animate-pulse",
    iconName: "info",
  },
};

// Merged STATUS_MAP ensuring backward compatibility with server states and full support for exposure states
export const STATUS_MAP: Record<string, { label: string; color: string }> = {
  // Existing server states
  running: { label: "Online", color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" },
  stopped: { label: "Offline", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400" },
  created: { label: "Not Started", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400" },
  starting: { label: "Starting", color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400" },
  stopping: { label: "Stopping", color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400" },
  crashed: { label: "Crashed", color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" },
  // Exposure states
  ...Object.fromEntries(
    Object.entries(EXPOSURE_STATUS_MAP).map(([k, v]) => [k, { label: v.label, color: v.color }])
  ),
};
```

---

## 4. API Client Layer

### 4.1 Methods in `frontend/src/services/api.ts`

Add the following methods to the object returned by `createApiClient`:

```typescript
// Exposure - Panel & Agent
getPanelExposure: () =>
  request<PanelExposureResponse>("/api/v1/exposure/panel"),

setPanelExposure: (body: PanelExposureUpdateRequest) =>
  request<PanelExposureResponse>("/api/v1/exposure/panel", {
    method: "PUT",
    body,
  }),

getAgentStatus: () =>
  request<AgentStatusResponse>("/api/v1/exposure/agent"),

generateClaim: () =>
  request<ClaimResponse>("/api/v1/exposure/agent/claim", {
    method: "POST",
  }),

resetAgent: () =>
  request<AgentStatusResponse>("/api/v1/exposure/agent/reset", {
    method: "POST",
  }),
```

### 4.2 Query Keys in `frontend/src/services/queryClient.ts`

Extend `queryKeys` with the `exposure` namespace:

```typescript
export const queryKeys = {
  // ... existing keys ...
  exposure: {
    all: ["exposure"] as const,
    panel: () => ["exposure", "panel"] as const,
    agent: () => ["exposure", "agent"] as const,
  },
};
```

---

## 5. Data-Fetching Hook Design (`usePanelExposure`)

### 5.1 Hook Specification (`frontend/src/server_manager/hooks/usePanelExposure.ts`)

The custom hook coordinates panel exposure data fetching, adaptive polling, mutation execution, and agent claim status.

```typescript
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import type { PanelExposureUpdateRequest, PanelExposureResponse, AgentStatusResponse } from "@/types";

export function usePanelExposure() {
  const api = createAuthenticatedApi();
  const queryClient = useQueryClient();

  // 1. Panel Exposure Query with Adaptive Polling
  const panelQuery = useQuery<PanelExposureResponse>({
    queryKey: queryKeys.exposure.panel(),
    queryFn: () => api.getPanelExposure(),
    staleTime: 5_000,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return 10_000;
      // Fast polling during active asynchronous state transitions
      if (["STARTING", "CLAIM_REQUIRED", "STOPPING"].includes(status)) {
        return 2_500;
      }
      // Disable background polling when completely disabled or stopped
      if (["DISABLED", "STOPPED"].includes(status)) {
        return false;
      }
      // Steady-state health poll for ACTIVE / DEGRADED / ERROR / RECLAIM_REQUIRED
      return 10_000;
    },
  });

  // 2. Host Agent Status Query (strictly enabled only when playit is actively selected)
  const isPlayitActive =
    panelQuery.data?.method === "playit_http" && panelQuery.data?.desired_state === "ENABLED";

  const agentQuery = useQuery<AgentStatusResponse>({
    queryKey: queryKeys.exposure.agent(),
    queryFn: () => api.getAgentStatus(),
    enabled: Boolean(isPlayitActive),
    staleTime: 5_000,
    refetchInterval: (query) => {
      if (!isPlayitActive) return false;
      const claimActive = query.state.data?.claim_active;
      const claimed = query.state.data?.claimed;
      if (claimActive || !claimed) return 2_500; // Poll fast while waiting for claim authorization
      return 10_000;
    },
  });

  // 3. Set Panel Exposure Mutation
  const updateMutation = useMutation({
    mutationFn: (body: PanelExposureUpdateRequest) => api.setPanelExposure(body),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.exposure.panel(), updated);
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.panel() });
      if (updated.method === "playit_http") {
        queryClient.invalidateQueries({ queryKey: queryKeys.exposure.agent() });
      }
      const action = updated.desired_state === "ENABLED" ? "enabled" : "disabled";
      toast("success", "Panel Exposure Updated", `Panel exposure successfully ${action} (${updated.method}).`);
    },
    onError: (err: Error) => {
      // Non-blocking error handling: fires toast and leaves form inputs editable for immediate user retry
      toast("error", "Exposure Update Failed", err.message || "Failed to update panel exposure");
    },
  });

  return {
    panel: panelQuery.data,
    isLoading: panelQuery.isLoading,
    isError: panelQuery.isError,
    error: panelQuery.error,
    refetch: panelQuery.refetch,

    agent: agentQuery.data,
    isLoadingAgent: agentQuery.isLoading,

    updateExposure: updateMutation.mutate,
    updateExposureAsync: updateMutation.mutateAsync,
    isUpdating: updateMutation.isPending,

    // Derived State Flags
    isExposed: panelQuery.data?.desired_state === "ENABLED" && panelQuery.data?.status === "ACTIVE",
    isDegraded: panelQuery.data?.status === "DEGRADED",
    isStarting: panelQuery.data?.status === "STARTING",
    isClaimRequired:
      panelQuery.data?.status === "CLAIM_REQUIRED" ||
      (panelQuery.data?.method === "playit_http" && !agentQuery.data?.claimed),
    isReclaimRequired: panelQuery.data?.status === "RECLAIM_REQUIRED",
    hasError: panelQuery.data?.status === "ERROR" || Boolean(panelQuery.data?.error_code),
  };
}
```

---

## 6. UI State Matrix (Every Method × Every Status)

| Exposure Method | Status | Primary Action / Form State | Visible UI Components | Badge / Indicator |
|---|---|---|---|---|
| **`none`** | `DISABLED` / `STOPPED` | Save/Enable disabled. Cards selectable. | Method selector cards (None selected). "Panel is accessible only via local network." | Gray "Disabled" |
| **`none`** | Any other status | N/A (Switching to `none` immediately persists `desired_state=DISABLED`). | Same as `none` + `DISABLED`. | Gray "Disabled" |
| **`cloudflare_tunnel`** | `DISABLED` / `STOPPED` | Token + Hostname inputs enabled. "Enable Cloudflare Tunnel" primary button. | Cloudflare config form. Token masked input with reveal toggle, Hostname input with FQDN help text. | Gray "Disabled" |
| **`cloudflare_tunnel`** | `STARTING` | Inputs disabled/read-only. Spinner on primary button ("Establishing Tunnel..."). | Form disabled with loading skeleton overlay; fast polling active (2.5s). | Blue "Starting..." (pulsing) |
| **`cloudflare_tunnel`** | `ACTIVE` | Form hidden/collapsed. "Disable" button + "Rotate Token" secondary button. | Public address card (`https://<hostname>`), copy button, external link icon, protocol badge (HTTPS / TLS Encrypted). | Green "Active" |
| **`cloudflare_tunnel`** | `DEGRADED` | Same as `ACTIVE`. | Public address card + Amber Alert Banner ("Tunnel health check reporting intermittent packet loss; auto-recovering"). | Amber "Degraded" |
| **`cloudflare_tunnel`** | `ERROR` | Form re-enabled with current values prefilled. "Retry / Reconfigure" button. | Red Error Banner displaying `error_message`, `error_code` (e.g. `CLOUDFLARE_AUTH_FAILED`), and `fix_hint`. | Red "Error" |
| **`cloudflare_tunnel`** | `RECLAIM_REQUIRED` | Fresh Cloudflare Token input highlighted in red (placeholder cleared). "Update Token & Reconnect" button. | Red Banner ("Cloudflare API Token was invalidated or revoked. Enter a fresh token to restore tunnel."). | Red "Token Revoked" |
| **`cloudflare_tunnel`** | `CLAIM_REQUIRED` | N/A (Cloudflare uses API tokens, not claim codes). | N/A | N/A |
| **`playit_http`** | `CLAIM_REQUIRED` (Unclaimed) | "Generate Claim Link" or automatic claim display. | `PlayitClaimCard` mounted: Claim code, clickable claim URL, countdown timer, copy button. | Yellow "Claim Required" (pulsing) |
| **`playit_http`** | `STARTING` | "Connecting to playit edge..." with progress indicator. | `PlayitClaimCard` showing "Claim Verified — Launching Agent"; fast polling active (2.5s). | Blue "Starting..." (pulsing) |
| **`playit_http`** | `ACTIVE` | "Disable" button + "Reset Agent" danger button. | Public address card (`https://*.ply.gg`), copy button, protocol badge (HTTPS / playit Edge TLS). | Green "Active" |
| **`playit_http`** | `DEGRADED` | Same as `ACTIVE`. | Public address card + Amber Banner ("Agent alive but tunnel inventory stale > 90s"). | Amber "Degraded" |
| **`playit_http`** | `ERROR` | "Retry / Reset Agent" button. | Red Error Banner (`error_message`, `error_code`, `fix_hint` e.g. `PLAYIT_QUOTA_EXCEEDED`). | Red "Error" |
| **`playit_http`** | `RECLAIM_REQUIRED` | "Start New Claim" button. | Red Banner ("Playit credentials expired or reset. Reclaim required.") + `PlayitClaimCard`. | Red "Token Revoked" |
| **`port_forward`** | `DISABLED` / `STOPPED` | External port input (optional, placeholder: "Auto (8000)"). "Enable Port Forwarding" button. | Port forward form. Warning notice that HTTP traffic is unencrypted. | Gray "Disabled" |
| **`port_forward`** | `STARTING` | Inputs disabled. "Configuring UPnP IGD Mapping..." | Progress bar / spinner; fast polling active (2.5s). | Blue "Starting..." (pulsing) |
| **`port_forward`** | `ACTIVE` | "Disable" button. | Public address card (`http://<ip>:<port>`), unencrypted HTTP warning badge, copy button. If Access Mode is `LOCAL`, Amber Security Advisory Banner appears. | Green "Active" |
| **`port_forward`** | `ERROR` (General) | "Retry Port Forwarding" button. | Red Error Banner (`UPNP_DISCOVERY_FAILED`, `UPNP_CONFLICT`). | Red "Error" |
| **`port_forward`** | `ERROR` (`BIND_MISMATCH`) | "Restart MCS Manager" guidance. | Purple/Amber Action Banner: "Auto-repaired bind address to 0.0.0.0. Please restart the backend process to activate." | Red "Error" (Auto-Fixed) |

---

## 7. Method-Specific Form Design

### 7.1 Port Forwarding Form (`PortForwardConfigForm`)
- **External Port Input:**
  - Optional numerical input (`min=1`, `max=65535`).
  - Helper label: *"Requested External Port (Leave blank to use default panel port: 8000)"*.
  - Client-side validation: must be an integer between 1 and 65535 if entered.
- **UPnP Result Display:**
  - Displays `upnp_last_result` string if present (e.g. `UPNP_SUCCESS`, `UPNP_DISABLED`, `CONFLICT`).
- **`BIND_MISMATCH` Handling:**
  - When `error_code === "BIND_MISMATCH"`, backend returns `auto_fixed: true` and `fix_hint`.
  - The UI renders an alert banner:
    ```tsx
    <div role="alert" className="p-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-800 space-y-2">
      <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300 font-semibold text-sm">
        <Icon name="alert" size={18} />
        <span>Action Required: Restart Panel to Complete Port Forwarding</span>
      </div>
      <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
        {panel.fix_hint || "Panel bind address updated to 0.0.0.0 in config/settings.yaml. Restart the panel service for changes to take effect."}
      </p>
    </div>
    ```

### 7.2 Cloudflare Tunnel Form (`CloudflareConfigForm`)
- **Token Input (`cloudflare_token`):**
  - `<input type={showToken ? "text" : "password"} />` with reveal toggle button.
  - Reveal toggle button includes explicit accessible name: `aria-label={showToken ? "Hide API token" : "Show API token"}`.
  - Helper label: *"Cloudflare API Token (Requires Zone.DNS:Edit and Account.Cloudflare Tunnel:Edit permissions)"*.
  - Placeholder: `"••••••••••••••••••••••••••••••••"` if token is already persisted; otherwise `"Enter Cloudflare API token..."`.
  - **Token Rotation Flow:** When rotating token or responding to `RECLAIM_REQUIRED`, the form clears any masked placeholder value and requires explicit entry of a fresh token before enabling save.
- **Hostname Input (`hostname`):**
  - Text input with FQDN validation.
  - Helper label: *"Custom Domain / Hostname for Panel (e.g. panel.yourdomain.com)"*.
  - **FQDN Validation Rule & Known Scope:**
    ```typescript
    const FQDN_REGEX = /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/;
    function isValidFQDN(val: string): boolean {
      const clean = val.trim().toLowerCase();
      return clean.length >= 4 && clean.length <= 253 && FQDN_REGEX.test(clean);
    }
    ```
    *Known Regex Scope:* `FQDN_REGEX` validates standard RFC 1123 ASCII hostnames. It intentionally rejects trailing root dots (`.`), IDN/punycode (`xn--`), and underscores. In all cases where the client-side regex passes but the backend rejects the hostname (e.g. invalid zone ownership, Cloudflare API validation), the backend's validation error is surfaced authoritatively in the error banner.
  - Inline error text: *"Please enter a valid fully-qualified domain name (e.g. panel.example.com). Quick tunnels (*.trycloudflare.com) are not supported."*
  - Save button is disabled (`disabled={!isValidFQDN(hostname) || !token}`) until valid inputs are provided.

### 7.3 playit.gg Panel Configuration (`PlayitPanelConfig`)
- Mounts `<PlayitClaimCard />` whenever the host agent is unclaimed (`agent.claimed === false` or `panel.status === "CLAIM_REQUIRED"`).
- Once claimed, displays agent status (`RUNNING`), tunnel ID (`panel.playit_tunnel_id`), and edge public address URL (`https://*.ply.gg`).
- Surfaces a "Reset Agent" modal option calling `POST /api/v1/exposure/agent/reset` to revoke/clear credentials if needed.

---

## 8. `PlayitClaimCard` Component Contract

The `PlayitClaimCard` component is **100% decoupled and generic** so that Batch 7.5 (Game Server playit exposure) can reuse it without modification.

### 8.1 Props Interface (`frontend/src/server_manager/components/PlayitClaimCard.tsx`)

```typescript
export interface PlayitClaimCardProps {
  /** True when the agent is already claimed and verified */
  claimed: boolean;
  /** True when a claim code exchange is currently active and awaiting user claim in playit.gg */
  claimActive: boolean;
  /** The 6-character or token claim code from backend */
  claimCode?: string | null;
  /** The full claim URL (e.g. https://playit.gg/claim/xxxx) */
  claimUrl?: string | null;
  /** Expiration timestamp ISO string */
  claimExpiresAt?: string | null;
  /** Handler to generate a new claim */
  onGenerateClaim: () => void | Promise<void>;
  /** True while the claim creation API request is in-flight */
  isGenerating?: boolean;
  /** Optional handler to reset the host agent credentials */
  onResetAgent?: () => void | Promise<void>;
  /** True while agent reset is in-flight */
  isResetting?: boolean;
  /** Optional custom title (defaults to "playit.gg Account Authorization") */
  title?: string;
  /** Optional custom description */
  description?: string;
}
```

### 8.2 UX & Countdown Timer Behavior

1. **Unclaimed / Inactive:** Shows an *"Authorize with playit.gg"* primary button.
2. **Active Claim:**
   - Displays **Claim Code** in a styled monospaced badge with an instant copy button (`useClipboard`) and explicit `aria-label="Copy claim code to clipboard"`.
   - Displays a prominent *"Open playit.gg Authorization Page"* button linking directly to `claimUrl` (`target="_blank" rel="noopener noreferrer"`).
   - Shows an interactive **Countdown Timer** (e.g. *"Claim expires in 08:45"*):
     - Calculates remaining seconds: `Math.max(0, Math.floor((new Date(claimExpiresAt).getTime() - Date.now()) / 1000))`.
     - **Screen-Reader Milestone Announcements:** The visual timer uses `role="timer"` with `aria-live="off"` to prevent annoying per-second chatter. A separate off-screen element with `aria-live="polite"` (`className="sr-only"`) announces meaningful countdown milestones only: at 60 seconds remaining, 30 seconds remaining, 10 seconds remaining, and upon expiration.
3. **Claim Expiry & Regeneration Decision:**
   - When the countdown reaches `00:00`, the timer transitions to an explicit expired state: *"Claim expired. Click to generate a new claim."* with an enabled *"Generate New Claim"* button.
   - **No Silent Auto-Regeneration:** The component intentionally requires explicit user interaction to regenerate a claim code. Silent auto-generation in the background is disallowed because it risks triggering unexpected network calls and starting a ticking claim window before the user is paying attention.

---

## 9. Status & Error Display System

### 9.1 Advisory Banners (`security_advisory`)
- The backend dynamically computes and returns `security_advisory` on `PanelExposureResponse` (reflecting whether Access Mode is `LOCAL` or `GLOBAL`).
- **Visual Styling:**
  - If Access Mode is `LOCAL` and method is `port_forward`: Renders an **Amber Warning Banner** with high visual priority:
    ```tsx
    <div role="alert" className="p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-800 flex items-start gap-3">
      <Icon name="alert" size={20} className="text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
      <div className="space-y-1">
        <h4 className="text-xs font-semibold text-amber-800 dark:text-amber-300 uppercase tracking-wider">Security Advisory</h4>
        <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">{panel.security_advisory}</p>
      </div>
    </div>
    ```

### 9.2 Error & Fix-Hint Composition
- When `panel.status === "ERROR"` or `panel.error_code` is present, renders a unified error card:
  - **Headline:** `panel.error_message || "Failed to configure panel exposure"`
  - **Actionable Fix:** `panel.fix_hint` rendered in a sub-box with a lightbulb/info icon.
  - **Technical Detail:** Small badge displaying `error_code` (e.g. `CLOUDFLARE_AUTH_FAILED`, `BIND_MISMATCH`, `UPNP_DISCOVERY_FAILED`, `PLAYIT_QUOTA_EXCEEDED`).

---

## 10. Owner-Gating Architecture

- **Single Gate Invariant:** Owner authorization gating is performed exclusively at the parent `<AccessSection />` container level via `currentUser.roles?.includes("owner")` ([`frontend/src/server_manager/components/AccessSection.tsx:28`](file:///mnt/D/files/server_manger/frontend/src/server_manager/components/AccessSection.tsx#L28)).
- If the current user is not an Owner, `<AccessSection />` immediately returns the standard "Access Denied" view; `PanelExposureSection` is not rendered.
- `PanelExposureSection` assumes caller is authorized and does not duplicate redundant role checks.

---

## 11. Concrete Test Plan

The frontend test suites must achieve 100% passing execution with comprehensive coverage of all UI states, form validations, polling behaviors, and error recoveries.

### 11.1 `PanelExposureSection.test.tsx` Acceptance Tests

| Test ID | Test Name | Intent / Expected Assertion |
|---|---|---|
| **T-74-01** | `renders_method_selector_cards_with_none_selected_by_default` | When backend returns `method="none"` and `desired_state="DISABLED"`, all 4 cards render with `None` card marked active. |
| **T-74-02** | `switching_to_cloudflare_displays_token_and_hostname_inputs` | Clicking Cloudflare card displays masked password token input and hostname input without saving immediately. |
| **T-74-03** | `cloudflare_form_disables_save_button_on_invalid_fqdn` | Typing invalid hostname (e.g. `invalid_domain` or `*.trycloudflare.com`) shows inline validation error and disables submit. |
| **T-74-04** | `cloudflare_form_enables_save_button_on_valid_fqdn_and_token` | Typing valid FQDN (`panel.example.com`) and token enables submit button; clicking triggers `PUT /api/v1/exposure/panel`. |
| **T-74-05** | `active_exposure_displays_clickable_url_and_protocol_badge` | When `status="ACTIVE"`, renders `https://panel.example.com` with HTTPS badge and copy button. |
| **T-74-06** | `copy_button_triggers_clipboard_write_and_toast` | Clicking copy button calls `navigator.clipboard.writeText` and triggers success toast. |
| **T-74-07** | `renders_security_advisory_banner_when_port_forward_active_in_local_mode` | When `method="port_forward"` and `security_advisory` is present, renders amber alert banner with advisory text. |
| **T-74-08** | `renders_bind_mismatch_banner_with_restart_instruction` | When `error_code="BIND_MISMATCH"` and `auto_fixed=true`, renders alert with restart panel fix hint. |
| **T-74-09** | `renders_token_revoked_state_with_reclaim_prompt` | When `status="RECLAIM_REQUIRED"`, renders red Token Revoked badge and prompts for token re-entry. |
| **T-74-10** | `disabling_exposure_opens_confirmation_modal` | Clicking "Disable Exposure" button opens confirmation dialog before calling API. |
| **T-74-11** | `port_forward_form_accepts_valid_custom_port` | Entering port `8080` in port forward form sends `external_port: 8080` in PUT payload. |
| **T-74-12** | `fast_polling_active_during_starting_state` | Hook polls at 2500ms when `status="STARTING"` and transitions to 10000ms when `status="ACTIVE"`. |
| **T-74-18** | `agent_status_query_only_enabled_when_playit_http_and_desired_enabled` | Verifies `usePanelExposure` disables agent polling when method is none, cloudflare, or port_forward. |
| **T-74-19** | `mutation_error_shows_toast_and_leaves_form_editable` | Verifies that when PUT returns an error (422/500), error toast is fired, loading state clears, and inputs remain editable. |
| **T-74-20** | `full_status_transition_claim_required_to_starting_to_active` | Simulates query data transition sequence `CLAIM_REQUIRED` $\to$ `STARTING` $\to$ `ACTIVE`, asserting correct UI changes at each stage. |
| **T-74-21** | `reclaim_required_on_cloudflare_highlights_token_field_and_blocks_resave_until_new_token_entered` | Verifies token input is highlighted red on `RECLAIM_REQUIRED` and save button is disabled until a fresh token is typed. |

### 11.2 `PlayitClaimCard.test.tsx` Acceptance Tests

| Test ID | Test Name | Intent / Expected Assertion |
|---|---|---|
| **T-74-13** | `renders_unclaimed_state_with_generate_claim_button` | When `claimed=false` and `claimActive=false`, displays "Authorize with playit.gg" button. |
| **T-74-14** | `renders_active_claim_code_and_direct_url_link` | When `claimActive=true`, renders claim code in monospaced badge and external link to `claimUrl`. |
| **T-74-15** | `claim_code_copy_button_copies_code` | Clicking copy button beside claim code copies the exact code string. |
| **T-74-16** | `countdown_timer_ticks_down_and_shows_expired_state` | Timer decrements each second; at 0s, displays "Claim expired" with refresh button (does not auto-regenerate). |
| **T-74-17** | `clicking_reset_agent_triggers_reset_callback` | Clicking "Reset Agent" calls `onResetAgent` callback. |

---

## 12. Accessibility & UI Consistency Checklist

1. **Semantic HTML & ARIA:**
   - All alert banners use `role="alert"` (matching `AccessSection.tsx` and `SetupPage.tsx`).
   - Every form input has an explicit `<label htmlFor="...">` pairing with descriptive helper texts.
   - External links use `target="_blank"` with `rel="noopener noreferrer"` and visual `<Icon name="external" />`.
   - Timer displays use `role="timer"` with `aria-live="off"` and an off-screen `aria-live="polite"` milestone announcer.
   - Password reveal toggle includes dynamic `aria-label="Show API token"` / `"Hide API token"`.
2. **Focus Management:**
   - When switching between method cards, focus moves into the first interactive element of the selected method's form panel.
   - When opening the Disable Confirmation Modal, focus is trapped inside the modal, placed initially on "Cancel", and returned to the trigger button upon dismissal.
   - After a successful form submit, focus shifts to the active public URL card or success confirmation banner.
3. **Color Redundancy & Contrast:**
   - Status badges use dual indicators: color + icon/dot + text label (never color alone).
   - Fully supports Tailwind CSS dark mode (`dark:bg-gray-800`, `dark:text-gray-100`, `dark:border-gray-700`).

---

## 13. Findings Ledger

| ID | Finding / Decision | Classification | Documentation Location | Code/Test Impact | Status |
|---|---|---|---|---|---|
| **F-74-01** | Subcomponent Extraction Architecture | `[ARCHITECTURAL DECISION]` | Spec §2.1, §2.2 | `PanelExposureSection.tsx` and `AccessModeCard.tsx` are separated into dedicated components to avoid a god-component in `AccessSection.tsx`. | ✅ Recorded |
| **F-74-02** | Decoupled Reusable `PlayitClaimCard` | `[ARCHITECTURAL DECISION]` | Spec §2.1, §8 | Generic props contract on `PlayitClaimCard` enables 100% component reuse by Batch 7.5 (Game Server Exposure) without duplication. | ✅ Recorded |
| **F-74-03** | Adaptive Query Polling Strategy | `[DESIGN DECISION]` | Spec §5.1 | Function-form `refetchInterval` (2.5s for `STARTING`/`CLAIM_REQUIRED`, 10s for `ACTIVE`/`DEGRADED`, `false` for `DISABLED`) provides responsive activation without server thrashing. | ✅ Recorded |
| **F-74-04** | Dedicated `EXPOSURE_STATUS_MAP` & `STATUS_MAP` Integration | `[TECHNICAL FACT]` | Spec §3.2, §9 | Merged `STATUS_MAP` in `types.ts` ensures `StatusBadge.tsx` supports all 9 exposure states without breaking existing server status badges. | ✅ Recorded |
| **F-74-05** | Strict FQDN Validation for Cloudflare Hostname | `[SECURITY CONTROL]` | Spec §7.2 | Client-side FQDN regex validation enforces custom-domain-only requirement (Roadmap §6b.1) before dispatching requests to the backend. | ✅ Recorded |
| **F-74-06** | Screen-Reader Milestone Announcement Strategy for Claim Timer | `[DESIGN DECISION]` | Spec §8.2, §12 | `role="timer"` with `aria-live="off"` + off-screen milestone-only `aria-live="polite"` announcer prevents disruptive per-second screen-reader chatter. | ✅ Recorded |
| **F-74-07** | Client-Side FQDN Regex Scope & Backend Fallback Invariant | `[TECHNICAL FACT]` | Spec §7.2 | Documents known boundaries of `FQDN_REGEX` (rejects trailing dots/punycode/underscores) and establishes backend validation as authoritative fallback. | ✅ Recorded |
| **F-74-08** | Accessible Focus Management Contract Across Panels and Modals | `[DESIGN DECISION]` | Spec §12 | Programmatic focus shift on card selection, focus trap on confirmation modal, and focus restoration upon modal dismiss. | ✅ Recorded |
| **F-74-09** | Explicit User-Triggered Claim Regeneration on Expiry | `[DESIGN DECISION]` | Spec §8.2, §14 | On timer expiry (00:00), UI halts and presents "Generate New Claim" button; silent auto-regeneration in background is prohibited. | ✅ Recorded |
| **F-74-10** | Comprehensive Failure and Transition Test Matrix Expansion | `[TEST STRATEGY]` | Spec §11 | Added tests `T-74-18` through `T-74-21` covering non-blocking mutation failures, query gating, multi-state polling transitions, and token rotation. | ✅ Recorded |
| **F-74-11** | React 19 State Synchronization Pattern for Forms & Timers | `[IMPLEMENTATION FINDING]` | `PanelExposureSection.tsx`, `PlayitClaimCard.tsx` | Avoids calling synchronous `setState` inside `useEffect` by using React 19 render-phase state adjustment (`prevValue !== value`), eliminating cascading renders and satisfying `react-hooks/set-state-in-effect`. | ✅ Recorded |
| **F-74-12** | Decoupled Agent Lifecycle & Ephemeral Claim Credential State | `[ARCHITECTURAL DECISION]` | `PanelExposureSection.tsx`, `PlayitClaimCard.tsx` | Distinguishes between persistent host agent process status (`AgentStatusResponse`) and ephemeral claim codes/URLs (`ClaimResponse`), capturing the claim response in local state on generation to supply generic card props until claimed. | ✅ Recorded |

---

## 14. Open Questions & Resolutions

### OQ-74-01: Component Placement & Architecture
- **Status:** Resolved.
- **Resolution:** `PanelExposureSection.tsx` is built as a separate, dedicated subcomponent mounted within `AccessSection.tsx` beneath `AccessModeCard.tsx`.

### OQ-74-02: playit.gg Claim UX Reusability
- **Status:** Resolved.
- **Resolution:** `PlayitClaimCard.tsx` is built with a generic, decoupled props contract containing no Panel-specific endpoints, allowing Batch 7.5 to reuse it directly.

### OQ-74-03: Polling Strategy During Tunnel Activation
- **Status:** Resolved.
- **Resolution:** Custom React Query hook uses a dynamic `refetchInterval` function: 2.5s while `STARTING` or `CLAIM_REQUIRED`, 10s steady state, disabled when `DISABLED` or `STOPPED`.

### OQ-74-04: Claim Expiry Behavior (User Action vs Auto-Regeneration)
- **Status:** Resolved.
- **Resolution:** Explicit user action (*"Generate New Claim"*) is chosen. Auto-regeneration without user presence is disallowed to prevent unexpected network requests and expired claim codes.

---

## 15. Implementation Boundary

### Files to be created during authorized implementation:
- `docs/roadmap/MCS-Manager-Phase7.4-Design-Spec.md` (This spec)
- `frontend/src/server_manager/hooks/usePanelExposure.ts`
- `frontend/src/server_manager/components/PlayitClaimCard.tsx`
- `frontend/src/server_manager/components/PanelExposureSection.tsx`
- `frontend/src/server_manager/components/AccessModeCard.tsx`
- `frontend/src/server_manager/components/PlayitClaimCard.test.tsx`
- `frontend/src/server_manager/components/PanelExposureSection.test.tsx`

### Files to be modified during authorized implementation:
- `frontend/src/types/index.ts` (Add exposure contract interfaces)
- `frontend/src/services/api.ts` (Add panel & agent exposure API methods)
- `frontend/src/services/queryClient.ts` (Add exposure query keys)
- `frontend/src/server_manager/types.ts` (Add `EXPOSURE_STATUS_MAP` and extend `STATUS_MAP`)
- `frontend/src/server_manager/components/AccessSection.tsx` (Mount extracted cards)
- `frontend/src/server_manager/components/AccessSection.test.tsx` (Update tests for extracted components)
