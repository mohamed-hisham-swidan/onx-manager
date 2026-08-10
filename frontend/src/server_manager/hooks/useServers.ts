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

export function useDeleteServer() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => api.deleteServer(serverId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.servers.all }),
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

export function useServerDetail(serverId: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.servers.detail(serverId),
    queryFn: () => api.getServer(serverId),
    enabled: !!serverId,
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
    mutationFn: ({ serverId, body }: { serverId: string; body: import("@/server_manager/types").ServerUpdateRequest }) =>
      api.updateServer(serverId, body),
    onSuccess: (_data, { serverId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
      qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
    },
  });
}