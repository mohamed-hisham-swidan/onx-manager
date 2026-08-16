import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import type {
  ServerExposureResponse,
  ServerExposureUpdateRequest,
  ServerExposureStateUpdateRequest,
  TargetCreateRequest,
  RegisteredPortResponse,
  RegisteredPortCreateRequest,
  AgentStatusResponse,
} from "@/types";

export function useServerExposure(serverId: string) {
  const api = createAuthenticatedApi();
  const queryClient = useQueryClient();

  // 1. Server Exposure Query with Adaptive Polling (Spec §5.1)
  const serverExposureQuery = useQuery<ServerExposureResponse>({
    queryKey: queryKeys.exposure.server(serverId),
    queryFn: () => api.getServerExposure(serverId),
    enabled: Boolean(serverId),
    staleTime: 5_000,
    refetchInterval: (query) => {
      const status = query.state.data?.aggregate_status;
      const desiredState = query.state.data?.desired_state;

      if (!status) return 10_000;
      // Fast polling during active asynchronous state transitions (2,500ms)
      if (["STARTING", "CLAIM_REQUIRED", "STOPPING"].includes(status)) {
        return 2_500;
      }
      // Disable background polling when completely disabled or stopped
      if (desiredState === "DISABLED" || status === "STOPPED" || status === "DISABLED") {
        return false;
      }
      // Steady-state health poll for ACTIVE / DEGRADED / ERROR / RECLAIM_REQUIRED (10,000ms)
      return 10_000;
    },
  });

  // 2. Host Agent Status Query (Spec §5.1)
  const isPlayitActive =
    serverExposureQuery.data?.method === "playit" &&
    serverExposureQuery.data?.desired_state === "ENABLED";

  const agentStatusQuery = useQuery<AgentStatusResponse>({
    queryKey: queryKeys.exposure.agent(),
    queryFn: () => api.getAgentStatus(),
    enabled: Boolean(serverId),
    staleTime: 5_000,
    refetchInterval: (query) => {
      if (!isPlayitActive) return false;
      const claimActive = query.state.data?.claim_active;
      const claimed = query.state.data?.claimed;
      if (claimActive || !claimed) return 2_500; // Poll fast while waiting for claim authorization
      return 10_000;
    },
  });

  // 3. Registered Ports Query
  const portsQuery = useQuery<RegisteredPortResponse[]>({
    queryKey: queryKeys.exposure.ports(serverId),
    queryFn: () => api.listServerPorts(serverId),
    enabled: Boolean(serverId),
    staleTime: 10_000,
  });

  // 4. Mutations
  const setExposureMutation = useMutation({
    mutationFn: (body: ServerExposureUpdateRequest) => api.setServerExposure(serverId, body),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.exposure.server(serverId), updated);
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.server(serverId) });
      if (updated.method === "playit") {
        queryClient.invalidateQueries({ queryKey: queryKeys.exposure.agent() });
      }
      const action = updated.desired_state === "ENABLED" ? "enabled" : "disabled";
      toast(
        "success",
        "Server Exposure Updated",
        `Network exposure successfully ${action} (${updated.method}).`,
      );
    },
    onError: (err: Error) => {
      toast("error", "Exposure Update Failed", err.message || "Failed to update server exposure.");
    },
  });

  const setExposureStateMutation = useMutation({
    mutationFn: (body: ServerExposureStateUpdateRequest) => api.setServerExposureState(serverId, body),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.exposure.server(serverId), updated);
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.server(serverId) });
      const action = updated.desired_state === "ENABLED" ? "enabled" : "disabled";
      toast(
        "success",
        "Exposure State Updated",
        `Server exposure successfully ${action}.`,
      );
    },
    onError: (err: Error) => {
      toast("error", "State Update Failed", err.message || "Failed to update exposure state.");
    },
  });

  const removeExposureMutation = useMutation({
    mutationFn: () => api.removeServerExposure(serverId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.server(serverId) });
      toast("success", "Exposure Removed", "Server network exposure has been cleared.");
    },
    onError: (err: Error) => {
      toast("error", "Removal Failed", err.message || "Failed to remove exposure.");
    },
  });

  const createTargetMutation = useMutation({
    mutationFn: (body: TargetCreateRequest) => api.createExposureTarget(serverId, body),
    onSuccess: (newTarget) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.server(serverId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.targets(serverId) });
      toast("success", "Target Added", `Companion target '${newTarget.service_type}' created.`);
    },
    onError: (err: Error) => {
      toast("error", "Target Creation Failed", err.message || "Failed to create target.");
    },
  });

  const updateTargetAddressMutation = useMutation({
    mutationFn: ({ targetId, publicAddress }: { targetId: string; publicAddress: string }) =>
      api.updateExposureTarget(serverId, targetId, { public_address: publicAddress }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.server(serverId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.targets(serverId) });
      toast("success", "Address Updated", "Public address saved successfully.");
    },
    onError: (err: Error) => {
      toast("error", "Update Failed", err.message || "Failed to update public address.");
    },
  });

  const deleteTargetMutation = useMutation({
    mutationFn: (targetId: string) => api.deleteExposureTarget(serverId, targetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.server(serverId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.targets(serverId) });
      toast("success", "Target Removed", "Companion target removed successfully.");
    },
    onError: (err: Error) => {
      toast("error", "Deletion Failed", err.message || "Failed to delete target.");
    },
  });

  const registerPortMutation = useMutation({
    mutationFn: (body: RegisteredPortCreateRequest) => api.registerServerPort(serverId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.ports(serverId) });
      toast("success", "Port Registered", "Companion port registered successfully.");
    },
    onError: (err: Error) => {
      toast("error", "Registration Failed", err.message || "Failed to register port.");
    },
  });

  const deletePortMutation = useMutation({
    mutationFn: (portId: string) => api.deleteServerPort(serverId, portId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.ports(serverId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.exposure.server(serverId) });
      toast("success", "Port Deleted", "Registered port removed successfully.");
    },
    onError: (err: Error) => {
      toast("error", "Deletion Failed", err.message || "Failed to delete port.");
    },
  });

  const exposure = serverExposureQuery.data;
  const isEnabled = exposure?.desired_state === "ENABLED";
  const status = exposure?.aggregate_status;

  return {
    exposure,
    isLoading: serverExposureQuery.isLoading,
    isError: serverExposureQuery.isError,
    error: serverExposureQuery.error,
    refetch: serverExposureQuery.refetch,

    agent: agentStatusQuery.data,
    isLoadingAgent: agentStatusQuery.isLoading,
    refetchAgent: agentStatusQuery.refetch,

    ports: portsQuery.data || [],
    isLoadingPorts: portsQuery.isLoading,
    refetchPorts: portsQuery.refetch,

    // Mutation triggers
    setExposure: setExposureMutation.mutate,
    setExposureAsync: setExposureMutation.mutateAsync,
    isSettingExposure: setExposureMutation.isPending,

    setExposureState: setExposureStateMutation.mutate,
    setExposureStateAsync: setExposureStateMutation.mutateAsync,
    isSettingExposureState: setExposureStateMutation.isPending,

    removeExposure: removeExposureMutation.mutate,
    isRemovingExposure: removeExposureMutation.isPending,

    createTarget: createTargetMutation.mutate,
    createTargetAsync: createTargetMutation.mutateAsync,
    isCreatingTarget: createTargetMutation.isPending,

    updateTargetAddress: updateTargetAddressMutation.mutate,
    updateTargetAddressAsync: updateTargetAddressMutation.mutateAsync,
    isUpdatingTargetAddress: updateTargetAddressMutation.isPending,

    deleteTarget: deleteTargetMutation.mutate,
    deleteTargetAsync: deleteTargetMutation.mutateAsync,
    isDeletingTarget: deleteTargetMutation.isPending,

    registerPort: registerPortMutation.mutate,
    isRegisteringPort: registerPortMutation.isPending,

    deletePort: deletePortMutation.mutate,
    isDeletingPort: deletePortMutation.isPending,

    // Derived States
    isExposed: isEnabled && status === "ACTIVE",
    isStarting: status === "STARTING",
    isStopping: status === "STOPPING",
    isDegraded: status === "DEGRADED",
    hasError: status === "ERROR" || Boolean(exposure?.error_code),
    isClaimRequired:
      status === "CLAIM_REQUIRED" ||
      (exposure?.method === "playit" && isEnabled && !agentStatusQuery.data?.claimed),
    isReclaimRequired: status === "RECLAIM_REQUIRED",
  };
}
