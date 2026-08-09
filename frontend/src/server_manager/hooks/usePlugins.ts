import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { InstallModrinthPluginRequest } from "@/types";

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

export interface MarketplaceSearchOptions {
  enabled?: boolean;
  projectType?: string;
}

export function useMarketplaceSearch(
  serverId: string,
  query: string,
  options?: MarketplaceSearchOptions,
) {
  const api = useApi();
  const projectType = options?.projectType;
  return useQuery({
    queryKey: queryKeys.plugins.marketplace.search(serverId, query, projectType),
    queryFn: () => api.searchMarketplace(serverId, query, projectType),
    enabled: (options?.enabled ?? true) && !!serverId,
  });
}

export function useMarketplaceSearchGlobal(
  query: string,
  options?: MarketplaceSearchOptions,
) {
  const api = useApi();
  const projectType = options?.projectType;
  return useQuery({
    queryKey: queryKeys.plugins.marketplace.global(query, projectType),
    queryFn: () => api.searchMarketplaceGlobal(query, projectType),
    enabled: options?.enabled ?? true,
  });
}

export function useProjectVersions(
  serverId: string,
  projectId: string,
  options?: MarketplaceSearchOptions,
) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.plugins.marketplace.versions(serverId, projectId),
    queryFn: () => api.getProjectVersions(serverId, projectId),
    enabled: (options?.enabled ?? true) && !!serverId && !!projectId,
  });
}

export function useInstallFromMarketplace(serverId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: InstallModrinthPluginRequest) => api.installFromMarketplace(serverId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId) }),
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
