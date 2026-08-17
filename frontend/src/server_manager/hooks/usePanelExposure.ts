import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import type {
  PanelExposureUpdateRequest,
  PanelExposureResponse,
  AgentStatusResponse,
} from "@/types";

export function usePanelExposure(draftMethod?: string) {
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

  // 2. Host Agent Status Query (enabled when playit is actively configured or selected)
  const isPlayitActive =
    panelQuery.data?.method === "playit_http" || draftMethod === "playit_http";

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
      toast(
        "success",
        "Panel Exposure Updated",
        `Panel exposure successfully ${action} (${updated.method}).`,
      );
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
