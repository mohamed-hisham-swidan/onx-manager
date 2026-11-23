import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { InstallModrinthPluginRequest } from "@/types";

function useApi() {
  return createAuthenticatedApi();
}

export function usePluginsList(serverId: string, branch?: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.plugins.list(serverId, branch),
    queryFn: () => api.listPlugins(serverId, branch),
    enabled: !!serverId,
  });
}

export const MARKETPLACE_PAGE_SIZE = 20;

export interface MarketplaceSearchOptions {
  enabled?: boolean;
  projectType?: string;
  offset?: number;
  loader?: string;
}

export function useMarketplaceSearch(
  serverId: string,
  query: string,
  options?: MarketplaceSearchOptions,
) {
  const api = useApi();
  const projectType = options?.projectType;
  const offset = options?.offset ?? 0;
  const loader = options?.loader;
  return useQuery({
    queryKey: queryKeys.plugins.marketplace.search(serverId, query, projectType, offset, loader),
    queryFn: () =>
      api.searchMarketplace(serverId, query, projectType, MARKETPLACE_PAGE_SIZE, offset, loader),
    enabled: (options?.enabled ?? true) && !!serverId,
  });
}

export function useMarketplaceSearchGlobal(
  query: string,
  options?: MarketplaceSearchOptions,
) {
  const api = useApi();
  const projectType = options?.projectType;
  const offset = options?.offset ?? 0;
  const loader = options?.loader;
  return useQuery({
    queryKey: queryKeys.plugins.marketplace.global(query, projectType, offset, loader),
    queryFn: () =>
      api.searchMarketplaceGlobal(query, projectType, MARKETPLACE_PAGE_SIZE, offset, loader),
    enabled: options?.enabled ?? true,
  });
}

export function useMarketplaceProject(
  projectId: string,
  options?: MarketplaceSearchOptions,
) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.plugins.marketplace.project(projectId),
    queryFn: () => api.getMarketplaceProject(projectId),
    enabled: (options?.enabled ?? true) && !!projectId,
  });
}

export function useMarketplaceProjectVersions(
  projectId: string,
  opts?: { enabled?: boolean; offset?: number },
) {
  const api = useApi();
  const offset = opts?.offset ?? 0;
  return useQuery({
    queryKey: queryKeys.plugins.marketplace.projectVersions(projectId, offset),
    queryFn: () => api.getMarketplaceProjectVersions(projectId, MARKETPLACE_PAGE_SIZE, offset),
    enabled: (opts?.enabled ?? true) && !!projectId,
  });
}

export function useProjectVersions(
  serverId: string,
  projectId: string,
  options?: MarketplaceSearchOptions,
) {
  const api = useApi();
  const offset = options?.offset ?? 0;
  return useQuery({
    queryKey: queryKeys.plugins.marketplace.versions(serverId, projectId, offset),
    queryFn: () => api.getProjectVersions(serverId, projectId, MARKETPLACE_PAGE_SIZE, offset),
    enabled: (options?.enabled ?? true) && !!serverId && !!projectId,
  });
}

export function useInstallFromMarketplace(serverId: string, branch?: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: InstallModrinthPluginRequest) => api.installFromMarketplace(serverId, body, branch),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId, branch) }),
  });
}

export function useEnablePlugin(serverId: string, branch?: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pluginId: string) => api.enablePlugin(serverId, pluginId, branch),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId, branch) }),
  });
}

export function useDisablePlugin(serverId: string, branch?: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pluginId: string) => api.disablePlugin(serverId, pluginId, branch),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId, branch) }),
  });
}

export function useUninstallPlugin(serverId: string, branch?: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (pluginId: string) => api.uninstallPlugin(serverId, pluginId, branch),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId, branch) }),
  });
}

export function useUploadPluginOrMod(serverId: string, branch?: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.uploadPluginOrMod(serverId, file, branch),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId, branch) }),
  });
}

export function useToggleModState(serverId: string, branch?: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { mod_id?: string | null; plugin_id?: string | null; enabled: boolean }) =>
      api.toggleModState(serverId, payload, branch),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId, branch) }),
  });
}

