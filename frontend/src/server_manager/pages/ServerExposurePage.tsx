import { useState, useMemo, useRef } from "react";
import { useParams } from "react-router-dom";
import { useServerDetail } from "@/server_manager/hooks/useServers";
import { useServerExposure } from "@/server_manager/hooks/useServerExposure";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { useClipboard } from "@/hooks/useClipboard";
import { ServerExposureMethodSelector } from "@/server_manager/components/ServerExposureMethodSelector";
import { TargetListSection } from "@/server_manager/components/TargetListSection";
import { GlobalExposureActionsCard } from "@/server_manager/components/GlobalExposureActionsCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Modal } from "@/components/ui/Modal";
import { ConfigureCredentialsModal } from "@/components/auth/ConfigureCredentialsModal";
import { Skeleton } from "@/components/Skeleton";
import { Icon } from "@/components/ui/Icon";
import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import { useDeploymentProfile } from "@/hooks/useDeploymentProfile";
import type {
  ExposureMethodType,
  ServerExposureResponse,
  ClaimResponse,
} from "@/types";

function isPasswordRequiredError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  return (err as { code?: unknown }).code === "PASSWORD_REQUIRED_FOR_EXPOSURE";
}

export function ServerExposurePage() {
  const { serverId } = useParams<{ serverId: string }>();
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { isLocal, isLocalZeroLogin, showFullControls, toggleShowFullVpsControls } = useDeploymentProfile();

  // 1. Fetch Current User Identity for RBAC (Spec §7, F-75-09)
  const { data: currentUser } = useQuery({
    queryKey: ["currentUser"],
    queryFn: () => api.getMe(),
  });

  const isOwner = Boolean(currentUser?.roles?.includes("owner"));
  const isAdmin = Boolean(currentUser?.roles?.includes("admin"));
  const isMember = Boolean(currentUser?.roles?.includes("member"));
  const hasManagerPerm = isOwner || isAdmin || isMember;
  const isReadOnly = Boolean(currentUser && !hasManagerPerm);

  const branchCtx = useServerBranchContext();
  const gitBacked = Boolean(branchCtx?.gitBacked);
  const activeBranch = gitBacked ? branchCtx?.branch : undefined;
  const isNonMainBranch = Boolean(gitBacked && activeBranch && activeBranch !== "main");
  const { copy } = useClipboard();

  const { data: server, isLoading: isServerLoading } = useServerDetail(
    serverId ?? "",
    activeBranch,
  );
  const {
    exposure,
    isLoading: isExposureLoading,
    refetch,
    agent,
    setExposure,
    isSettingExposure,
    setExposureState,
    isSettingExposureState,
    createTarget,
    isCreatingTarget,
    updateTargetAddress,
    isUpdatingTargetAddress,
    deleteTarget,
    isDeletingTarget,
  } = useServerExposure(serverId ?? "", activeBranch);

  // Form Draft State
  const [draftMethod, setDraftMethod] = useState<ExposureMethodType>("none");
  const [isConfirmDisableOpen, setIsConfirmDisableOpen] = useState(false);
  const [isGeneratingClaim, setIsGeneratingClaim] = useState(false);
  const [isResettingAgent, setIsResettingAgent] = useState(false);
  const [claimData, setClaimData] = useState<ClaimResponse | null>(null);
  const [isCredentialsModalOpen, setIsCredentialsModalOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => Promise<void> | void) | null>(null);

  const disableButtonRef = useRef<HTMLButtonElement>(null);
  const modalCancelButtonRef = useRef<HTMLButtonElement>(null);

  // Render-phase state synchronization pattern avoiding setState-in-useEffect (F-75-15)
  const [syncedExposure, setSyncedExposure] = useState<ServerExposureResponse | null | undefined>(null);
  if (exposure && syncedExposure !== exposure) {
    setSyncedExposure(exposure);
    setDraftMethod(exposure.method);
  }
  if (agent?.claimed && claimData) {
    setClaimData(null);
  }

  const executeGenerateClaim = async (): Promise<ClaimResponse | void> => {
    try {
      setIsGeneratingClaim(true);
      const res = await api.generateClaim();
      setClaimData(res);
      await refetch();
      toast("success", "Claim Link Generated", "Authorize with playit.gg to complete setup.");
      return res;
    } catch (err: unknown) {
      if (isPasswordRequiredError(err)) {
        setPendingAction(() => async () => { await executeGenerateClaim(); });
        setIsCredentialsModalOpen(true);
        return;
      }
      const msg = err instanceof Error ? err.message : "Failed to generate claim link";
      toast("error", "Claim Generation Failed", msg);
    } finally {
      setIsGeneratingClaim(false);
    }
  };

  const handleGenerateClaim = async (): Promise<ClaimResponse | void> => {
    if (isLocalZeroLogin) {
      setPendingAction(() => async () => { await executeGenerateClaim(); });
      setIsCredentialsModalOpen(true);
      return;
    }
    return executeGenerateClaim();
  };

  const handleResetAgent = async () => {
    try {
      setIsResettingAgent(true);
      await api.resetAgent();
      await refetch();
      toast("success", "Agent Reset", "Playit agent credentials cleared.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to reset agent";
      toast("error", "Reset Failed", msg);
    } finally {
      setIsResettingAgent(false);
    }
  };

  const executeSaveExposure = (params: {
    method: ExposureMethodType;
    desired_state: "ENABLED" | "DISABLED";
    cloudflare_mode?: "quick" | "subdomain" | "tcp" | null;
    cloudflare_token?: string;
    hostname?: string;
    subdomain_prefix?: string | null;
    base_domain?: string | null;
    srv_record_enabled?: boolean;
    external_port?: number | null;
    acknowledged_warning?: boolean;
  }) => {
    setExposure(params, {
      onError: (err) => {
        if (isPasswordRequiredError(err)) {
          setPendingAction(() => () => executeSaveExposure(params));
          setIsCredentialsModalOpen(true);
        }
      },
    });
  };

  const handleSaveExposure = (params: {
    method: ExposureMethodType;
    desired_state: "ENABLED" | "DISABLED";
    cloudflare_mode?: "quick" | "subdomain" | "tcp" | null;
    cloudflare_token?: string;
    hostname?: string;
    subdomain_prefix?: string | null;
    base_domain?: string | null;
    srv_record_enabled?: boolean;
    external_port?: number | null;
    acknowledged_warning?: boolean;
  }) => {
    const requiresCredentials = params.desired_state === "ENABLED" && params.method !== "none";
    if (requiresCredentials && isLocalZeroLogin) {
      setPendingAction(() => () => executeSaveExposure(params));
      setIsCredentialsModalOpen(true);
      return;
    }
    executeSaveExposure(params);
  };

  const handleConfirmDisable = () => {
    setExposureState(
      { desired_state: "DISABLED" },
      {
        onSuccess: () => {
          setIsConfirmDisableOpen(false);
          setDraftMethod("none");
          disableButtonRef.current?.focus();
        },
      }
    );
  };

  if (isServerLoading || (isExposureLoading && !exposure)) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-6 w-24" />
        </div>
        <div className="rounded-xl border border-border-subtle bg-surface-card p-6 space-y-4">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-28 w-full" />
        </div>
      </div>
    );
  }

  const isEnabled = exposure?.desired_state === "ENABLED";
  const aggregateStatus = exposure?.aggregate_status || "DISABLED";
  const isReclaimRequired = aggregateStatus === "RECLAIM_REQUIRED";

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border-subtle pb-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-xl font-bold text-text-primary">
              Network & Public Exposure
            </h2>
            <StatusBadge status={aggregateStatus} />
            {gitBacked && activeBranch && (
              <span
                data-testid="exposure-branch-badge"
                className="inline-flex items-center gap-1 rounded-md border border-accent-primary/30 bg-accent-primary/10 px-2.5 py-0.5 font-mono text-xs font-semibold text-accent-primary"
              >
                Branch: {activeBranch}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => refetch()}
            className="p-2 rounded-lg border border-border-default bg-surface-page text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
            title="Refresh status"
            aria-label="Refresh status"
          >
            <Icon name="activity" size={16} />
          </button>

          {!isReadOnly && isEnabled && (
            <button
              ref={disableButtonRef}
              type="button"
              onClick={() => setIsConfirmDisableOpen(true)}
              className="px-3.5 py-2 rounded-lg border border-status-danger/40 bg-status-danger-bg text-xs font-semibold text-status-danger hover:bg-status-danger-bg/80 transition-colors shadow-xs cursor-pointer"
            >
              Disable Exposure
            </button>
          )}
        </div>
      </div>

      {isNonMainBranch && (
        <div
          data-testid="branch-exposure-port-set-banner"
          className="rounded-xl border border-border-default bg-surface-card p-4 text-xs shadow-2xs flex flex-wrap items-center justify-between gap-3"
        >
          <div className="space-y-1">
            <p className="font-semibold text-text-primary">
              Isolated Exposure for Branch &ldquo;{activeBranch}&rdquo;
            </p>
            {exposure?.allocated_port_set ? (
              <p className="font-mono text-text-secondary">
                Host Port Set: Game {exposure.allocated_port_set.game_port} · RCON{" "}
                {exposure.allocated_port_set.rcon_port}
                {exposure.allocated_port_set.query_port
                  ? ` · Query ${exposure.allocated_port_set.query_port}`
                  : ""}
                {exposure.branch_runtime_status
                  ? ` (Container: ${exposure.branch_runtime_status})`
                  : ""}
              </p>
            ) : (
              <p className="text-text-muted">
                Container not created / stopped — start the branch container to allocate or expose its isolated Host Port Set.
              </p>
            )}
          </div>
        </div>
      )}

      {exposure?.upnp_status === "CGNAT_DETECTED" && (
        <div
          data-testid="server-cgnat-detected-banner"
          role="alert"
          className="rounded-xl border border-status-warning-border bg-status-warning-bg p-4 text-xs space-y-1"
        >
          <div className="flex items-center gap-2 font-semibold text-status-warning">
            <Icon name="alert" size={16} />
            <span>CGNAT Detected — Router Port Forwarding Unavailable</span>
          </div>
          <p className="text-text-secondary">
            Router reported private/CGNAT WAN IP{" "}
            <code className="font-mono">{exposure.detected_wan_ip || "unknown"}</code>. External traffic will be dropped by your ISP; switch to <strong>playit.gg</strong> or <strong>Cloudflare Tunnel</strong>.
          </p>
        </div>
      )}

      {exposure?.srv_record_hint && (
        <div
          data-testid="server-srv-record-helper"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-info-border bg-status-info-bg p-3.5 text-xs"
        >
          <div className="min-w-0">
            <p className="font-semibold text-status-info">Minecraft DNS SRV Record Helper</p>
            <code className="block truncate font-mono text-[11px] text-text-primary mt-0.5">
              {exposure.srv_record_hint}
            </code>
          </div>
          <button
            type="button"
            onClick={() => copy(exposure.srv_record_hint!, "SRV record copied")}
            className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-card px-2.5 py-1 text-xs font-medium text-text-primary hover:bg-surface-hover cursor-pointer"
          >
            <Icon name="copy" size={12} />
            Copy SRV
          </button>
        </div>
      )}

      {/* Passwordless Local Mode Gate Notice */}
      {isLocalZeroLogin && (
        <div
          data-testid="passwordless-exposure-banner"
          role="alert"
          className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-status-warning-border bg-status-warning-bg p-4"
        >
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-status-warning">
              <Icon name="lock" size={14} />
              <span>Security Setup Required for Public Exposure</span>
            </div>
            <p className="text-xs text-text-secondary">
              You are running in passwordless local mode. Set an administrator username and password before enabling external tunnels or remote access.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setPendingAction(null);
              setIsCredentialsModalOpen(true);
            }}
            className="shrink-0 rounded-lg bg-accent-primary px-3.5 py-2 text-xs font-medium text-accent-contrast-text hover:bg-accent-hover transition-colors cursor-pointer"
          >
            Set Username &amp; Password
          </button>
        </div>
      )}

      {/* Quick-Share Guidance in Local Mode vs Full Topology in VPS Mode */}
      {isLocal && !showFullControls ? (
        <div
          data-testid="local-quick-share-banner"
          className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-card p-4 shadow-2xs"
        >
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
              <Icon name="globe" size={16} className="text-accent-primary" />
              <span>Quick Share with Friends (Local Mode)</span>
            </div>
            <p className="text-xs text-text-secondary">
              Use <strong>Playit.gg</strong> or a <strong>Cloudflare Tunnel</strong> below to share this server without router port forwarding.
            </p>
          </div>
          <button
            type="button"
            onClick={toggleShowFullVpsControls}
            className="shrink-0 rounded-lg border border-border-default bg-surface-elevated px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            Show VPS / routing topology details
          </button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border-subtle bg-surface-card p-4 sm:p-5 shadow-2xs">
        <div className="mb-3.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon name="activity" size={14} className="text-accent-primary" />
            <span className="text-xs font-bold uppercase tracking-wider text-text-secondary">
              Connection Flow &amp; Routing Topology
            </span>
          </div>
          <span className="font-mono text-xs text-text-muted">
            Container Port: {exposure?.allocated_game_port || server?.port || 25565}
          </span>
        </div>

        <div className="grid grid-cols-1 items-center gap-3 md:grid-cols-7">
          {/* Node 1: Docker Container */}
          <div className="flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-page p-3 md:col-span-2">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-primary/10 text-accent-primary">
              <Icon name="server" size={18} />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-bold text-text-primary">Docker Container</p>
              <p className="font-mono text-[11px] text-text-muted">
                :{exposure?.allocated_game_port || server?.port || 25565} / TCP
              </p>
            </div>
          </div>

          {/* Connector 1 */}
          <div className="hidden items-center justify-center md:flex">
            <div className="flex items-center gap-1 text-text-muted">
              <div className="h-0.5 w-6 bg-border-default" />
              <Icon name="chevron-right" size={14} />
            </div>
          </div>

          {/* Node 2: Exposure Engine */}
          <div className="flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-page p-3 md:col-span-2">
            <div
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                isEnabled
                  ? "bg-status-success-bg text-status-success border border-status-success/30"
                  : "bg-surface-elevated text-text-muted border border-border-subtle"
              }`}
            >
              <Icon name="external" size={18} />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-bold text-text-primary capitalize">
                {exposure?.method === "none" ? "Local Host" : exposure?.method || "None"}
              </p>
              <p className="truncate text-[11px] text-text-muted">
                {isEnabled ? "Tunnel active" : "No public route"}
              </p>
            </div>
          </div>

          {/* Connector 2 */}
          <div className="hidden items-center justify-center md:flex">
            <div className="flex items-center gap-1 text-text-muted">
              <div className="h-0.5 w-6 bg-border-default" />
              <Icon name="chevron-right" size={14} />
            </div>
          </div>

          {/* Node 3: Public Internet Endpoint */}
          <div className="flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-page p-3 md:col-span-2">
            <div
              className={`relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                isEnabled && aggregateStatus === "ACTIVE"
                  ? "bg-status-success-bg text-status-success border border-status-success/30"
                  : "bg-surface-elevated text-text-muted border border-border-subtle"
              }`}
            >
              <Icon name="globe" size={18} />
              {isEnabled && aggregateStatus === "ACTIVE" && (
                <span className="absolute -top-0.5 -right-0.5 flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-success opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-status-success" />
                </span>
              )}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-bold text-text-primary">Public Endpoint</p>
              <p className="truncate font-mono text-[11px] text-text-muted">
                {exposure?.targets?.[0]?.public_address
                  ? `Active: ${exposure.targets[0].public_address}`
                  : isEnabled
                  ? "Resolving..."
                  : "Offline"}
              </p>
            </div>
          </div>
        </div>
        </div>
      )}

      {/* Aggregate Error Banner */}
      {aggregateStatus === "ERROR" && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-status-danger-bg border border-status-danger/30 space-y-2"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-status-danger font-semibold text-xs">
              <Icon name="alert" size={16} />
              <span>{exposure?.error_message || "Exposure service encountered an error"}</span>
            </div>
            {exposure?.error_code && (
              <span className="font-mono text-[10px] bg-surface-card text-status-danger border border-status-danger/30 px-2 py-0.5 rounded">
                {exposure.error_code}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Token Reclaim Notice Banner */}
      {isReclaimRequired && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-status-warning-bg border border-status-warning/30 space-y-1"
        >
          <div className="flex items-center gap-2 text-status-warning font-semibold text-xs">
            <Icon name="alert" size={16} />
            <span>Exposure Credentials Revoked or Invalidated</span>
          </div>
          <p className="text-xs text-text-secondary pl-6">
            The stored Cloudflare token or playit authorization is no longer valid. Please enter a fresh token or re-authorize to restore public access.
          </p>
        </div>
      )}

      {/* 1. Method Selector Card Grid & Form Panel */}
      <ServerExposureMethodSelector
        exposure={exposure}
        agent={agent}
        draftMethod={draftMethod}
        onSelectMethod={(m) => setDraftMethod(m)}
        onSaveExposure={handleSaveExposure}
        onGenerateClaim={handleGenerateClaim}
        onResetAgent={handleResetAgent}
        claimData={claimData}
        isUpdating={isSettingExposure || isSettingExposureState}
        isGeneratingClaim={isGeneratingClaim}
        isResettingAgent={isResettingAgent}
        isReadOnly={isReadOnly}
      />

      {/* 2. Multi-Target List Section */}
      <TargetListSection
        exposure={exposure}
        serverGamePort={exposure?.allocated_game_port || server?.port || 25565}
        onCreateTarget={(data) => createTarget(data)}
        onUpdateTargetAddress={(params) => updateTargetAddress(params)}
        onDeleteTarget={(targetId) => deleteTarget(targetId)}
        isCreatingTarget={isCreatingTarget}
        isUpdatingTargetAddress={isUpdatingTargetAddress}
        isDeletingTarget={isDeletingTarget}
        isReadOnly={isReadOnly}
      />

      {/* 3. Instance Owner Global Exposure Actions (Owner-Only, VPS or Expanded) */}
      {showFullControls && <GlobalExposureActionsCard />}

      {/* Disable Exposure Confirmation Modal */}
      <Modal
        open={isConfirmDisableOpen}
        onClose={() => {
          if (isSettingExposureState) return;
          setIsConfirmDisableOpen(false);
          disableButtonRef.current?.focus();
        }}
        title="Disable Server Exposure?"
        size="md"
        closeOnBackdrop={false}
        closeOnEscape={!isSettingExposureState}
        closeButtonAriaLabel="Close dialog"
      >
        <div className="space-y-4">
          <p className="text-xs text-text-secondary leading-relaxed">
            Disabling network exposure will disconnect all public tunnels and port mappings for this Minecraft server. Players on the internet will no longer be able to connect.
          </p>
          <div className="flex justify-end gap-3 pt-2">
            <button
              ref={modalCancelButtonRef}
              type="button"
              onClick={() => {
                setIsConfirmDisableOpen(false);
                disableButtonRef.current?.focus();
              }}
              disabled={isSettingExposureState}
              className="px-4 py-2 rounded-lg border border-border-default text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirmDisable}
              disabled={isSettingExposureState}
              className="px-4 py-2 rounded-lg bg-status-danger bg-red-600 hover:bg-red-700 text-text-inverse text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
            >
              {isSettingExposureState ? "Disabling..." : "Confirm Disable"}
            </button>
          </div>
        </div>
      </Modal>

      <ConfigureCredentialsModal
        open={isCredentialsModalOpen}
        onClose={() => {
          setIsCredentialsModalOpen(false);
          setPendingAction(null);
        }}
        onSuccess={async () => {
          const action = pendingAction;
          setPendingAction(null);
          if (action) {
            await action();
          }
        }}
      />
    </div>
  );
}
