import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { ServerCreateRequest } from "@/server_manager/types";

function useApi() {
  return createAuthenticatedApi();
}

export function useServersList() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.servers.list(),
    queryFn: () => api.listServers(),
    refetchInterval: 5000,
  });
}

export function useCreateServer() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ServerCreateRequest) => api.createServer(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.servers.all }),
  });
}

const inFlightServerDeletes = new Map<string, Promise<void>>();

export function useDeleteServer() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => {
      const existing = inFlightServerDeletes.get(serverId);
      if (existing) {
        return existing;
      }
      const req = api.deleteServer(serverId).finally(() => {
        inFlightServerDeletes.delete(serverId);
      });
      inFlightServerDeletes.set(serverId, req);
      return req;
    },
    onSuccess: (_data, serverId) => {
      qc.setQueryData<Array<{ server_id: string }> | undefined>(
        queryKeys.servers.list(),
        (old) => (Array.isArray(old) ? old.filter((s) => s.server_id !== serverId) : old),
      );
      qc.removeQueries({ queryKey: queryKeys.servers.detail(serverId) });
      qc.invalidateQueries({ queryKey: queryKeys.servers.list() });
    },
  });
}

export function useStartServer() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => api.startServer(serverId),
    onSuccess: (_data, serverId) => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
      qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
    },
  });
}

export function useStopServer() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => api.stopServer(serverId),
    onSuccess: (_data, serverId) => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
      qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
    },
  });
}

export function useServerDetail(serverId: string, branch?: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.servers.detail(serverId, branch),
    queryFn: () => api.getServer(serverId, branch),
    enabled: !!serverId,
    refetchInterval: 5000,
  });
}

export function useServerRuntime(serverId: string) {
  const api = useApi();
  return useQuery({
    queryKey: [...queryKeys.servers.detail(serverId), "runtime"],
    queryFn: () => api.getServerRuntime(serverId),
    enabled: !!serverId,
    refetchInterval: 10000,
  });
}

export function useRestartServer() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => api.restartServer(serverId),
    onSuccess: (_data, serverId) => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
      qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
    },
  });
}

export function useUpdateServer() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      serverId,
      body,
      branch,
    }: {
      serverId: string;
      body: import("@/server_manager/types").ServerUpdateRequest;
      branch?: string;
    }) => api.updateServer(serverId, body, branch),
    onSuccess: (_data, { serverId, branch }) => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
      qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId, branch) });
      qc.invalidateQueries({ queryKey: queryKeys.versioning.branches(serverId) });
      qc.invalidateQueries({ queryKey: queryKeys.versioning.commits(serverId) });
    },
  });
}

export function useDiscardPendingSettings() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => api.discardPendingSettings(serverId),
    onSuccess: (_data, serverId) => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
      qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId, "main") });
      qc.invalidateQueries({ queryKey: queryKeys.versioning.branches(serverId) });
    },
  });
}

export function useRetryProvisioningServer() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => api.retryProvisioning(serverId),
    onSuccess: (_data, serverId) => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
      qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
    },
  });
}