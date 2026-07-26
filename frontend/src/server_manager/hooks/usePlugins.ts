import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { InstallPluginRequest } from "@/types";

function useApi() {
  return createAuthenticatedApi();
}

export function usePluginsList(serverId: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.plugins.list(serverId),
    queryFn: () => api.listPlugins(serverId),
    enabled: !!serverId,
  });
}

export function useEnablePlugin(serverId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pluginId: string) => api.enablePlugin(serverId, pluginId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId) }),
  });
}

export function useDisablePlugin(serverId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pluginId: string) => api.disablePlugin(serverId, pluginId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId) }),
  });
}

export function useUninstallPlugin(serverId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pluginId: string) => api.uninstallPlugin(serverId, pluginId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId) }),
  });
}

export function useInstallPlugin(serverId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: InstallPluginRequest) => api.installPlugin(serverId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId) }),
  });
}
