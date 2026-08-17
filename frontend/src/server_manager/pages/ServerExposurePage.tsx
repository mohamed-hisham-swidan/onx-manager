import { useState, useMemo, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { useServerDetail } from "@/server_manager/hooks/useServers";
import { useServerExposure } from "@/server_manager/hooks/useServerExposure";
import { ServerExposureMethodSelector } from "@/server_manager/components/ServerExposureMethodSelector";
import { TargetListSection } from "@/server_manager/components/TargetListSection";
import { GlobalExposureActionsCard } from "@/server_manager/components/GlobalExposureActionsCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Skeleton } from "@/components/Skeleton";
import { Icon } from "@/components/ui/Icon";
import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import type {
  ExposureMethodType,
  ServerExposureResponse,
  ClaimResponse,
} from "@/types";

export function ServerExposurePage() {
  const { serverId } = useParams<{ serverId: string }>();
  const api = useMemo(() => createAuthenticatedApi(), []);

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

  const { data: server, isLoading: isServerLoading } = useServerDetail(serverId ?? "");
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
  } = useServerExposure(serverId ?? "");

  // Form Draft State
  const [draftMethod, setDraftMethod] = useState<ExposureMethodType>("none");
  const [isConfirmDisableOpen, setIsConfirmDisableOpen] = useState(false);
  const [isGeneratingClaim, setIsGeneratingClaim] = useState(false);
  const [isResettingAgent, setIsResettingAgent] = useState(false);
  const [claimData, setClaimData] = useState<ClaimResponse | null>(null);

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

  const handleGenerateClaim = async (): Promise<ClaimResponse | void> => {
    try {
      setIsGeneratingClaim(true);
      const res = await api.generateClaim();
      setClaimData(res);
      await refetch();
      toast("success", "Claim Link Generated", "Authorize with playit.gg to complete setup.");
      return res;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to generate claim link";
      toast("error", "Claim Generation Failed", msg);
    } finally {
      setIsGeneratingClaim(false);
    }
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

  const handleSaveExposure = (params: {
    method: ExposureMethodType;
    desired_state: "ENABLED" | "DISABLED";
    cloudflare_token?: string;
    hostname?: string;
    acknowledged_warning?: boolean;
  }) => {
    setExposure(params);
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

  if (isServerLoading || isExposureLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-6 w-24" />
        </div>
        <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 p-6 space-y-4">
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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-gray-200 pb-4 dark:border-gray-700">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Link
              to={`/servers/${serverId}/console`}
              className="text-xs text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100 flex items-center gap-1 transition-colors"
            >
              <Icon name="chevron-left" size={14} />
              <span>{server?.name || "Server"}</span>
            </Link>
            <span className="text-gray-300 dark:text-gray-600">/</span>
            <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
              Network & Exposure
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">
              Network & Public Exposure
            </h2>
            <StatusBadge status={aggregateStatus} />
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => refetch()}
            className="p-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
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
              className="px-3.5 py-2 rounded-lg border border-red-300 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/20 transition-colors shadow-xs"
            >
              Disable Exposure
            </button>
          )}
        </div>
      </div>

      {/* Aggregate Error Banner */}
      {aggregateStatus === "ERROR" && (
        <div
          role="alert"
          className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 space-y-2"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-red-700 dark:text-red-300 font-semibold text-xs">
              <Icon name="alert" size={16} />
              <span>{exposure?.error_message || "Exposure service encountered an error"}</span>
            </div>
            {exposure?.error_code && (
              <span className="font-mono text-[10px] bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-300 px-2 py-0.5 rounded">
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
          className="p-4 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-800 space-y-1"
        >
          <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300 font-semibold text-xs">
            <Icon name="alert" size={16} />
            <span>Exposure Credentials Revoked or Invalidated</span>
          </div>
          <p className="text-xs text-amber-700 dark:text-amber-300 pl-6">
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
        serverGamePort={server?.port || 25565}
        onCreateTarget={(data) => createTarget(data)}
        onUpdateTargetAddress={(params) => updateTargetAddress(params)}
        onDeleteTarget={(targetId) => deleteTarget(targetId)}
        isCreatingTarget={isCreatingTarget}
        isUpdatingTargetAddress={isUpdatingTargetAddress}
        isDeletingTarget={isDeletingTarget}
        isReadOnly={isReadOnly}
      />

      {/* 3. Instance Owner Global Exposure Actions (Owner-Only) */}
      <GlobalExposureActionsCard />

      {/* Disable Exposure Confirmation Modal */}
      {isConfirmDisableOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="server-disable-modal-title"
        >
          <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-800 space-y-4">
            <h3
              id="server-disable-modal-title"
              className="text-base font-semibold text-gray-900 dark:text-gray-100"
            >
              Disable Server Exposure?
            </h3>
            <p className="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
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
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDisable}
                disabled={isSettingExposureState}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
              >
                {isSettingExposureState ? "Disabling..." : "Confirm Disable"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
