import { useMemo } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type {
  BotSettingsRequest,
  CreateBranchRequest,
  CreateCommitRequest,
  RefreshServerRequest,
  RollbackRefreshRequest,
  ConfirmUpgradeRequest,
} from "@/server_manager/types";

export async function invalidateVersioningScope(
  qc: QueryClient,
  serverId: string,
  branchName?: string,
): Promise<void> {
  const tasks: Array<Promise<unknown>> = [
    qc.invalidateQueries({ queryKey: queryKeys.versioning.branches(serverId) }),
    qc.invalidateQueries({ queryKey: queryKeys.versioning.commits(serverId) }),
    qc.invalidateQueries({ queryKey: queryKeys.versioning.tags(serverId) }),
    qc.invalidateQueries({ queryKey: queryKeys.versioning.refresh(serverId) }),
    qc.invalidateQueries({ queryKey: queryKeys.versioning.dataTemplates(serverId) }),
    qc.invalidateQueries({ queryKey: queryKeys.versioning.githubStatus(serverId) }),
    qc.invalidateQueries({ queryKey: queryKeys.servers.all }),
    qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) }),
  ];
  if (branchName && branchName !== "main") {
    tasks.push(
      qc.invalidateQueries({
        queryKey: queryKeys.versioning.branchRuntime(serverId, branchName),
      }),
      qc.invalidateQueries({
        queryKey: queryKeys.versioning.liveChanges(serverId, branchName),
      }),
    );
  }
  await Promise.all(tasks);
}

export function useVersioningBranches(serverId: string, enabled = true) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.branches(serverId),
    queryFn: () => api.getServerBranches(serverId),
    enabled: Boolean(serverId) && enabled,
  });
}

export function useVersioningCommits(
  serverId: string,
  branchName: string,
  enabled = true,
) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.commitsByBranch(serverId, branchName),
    queryFn: () => api.getServerCommits(serverId, undefined, 100, branchName),
    enabled: Boolean(serverId && branchName) && enabled,
  });
}

export function useVersioningTags(serverId: string, enabled = true) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.tags(serverId),
    queryFn: () =>
      typeof api.getServerTags === "function"
        ? api.getServerTags(serverId)
        : Promise.resolve([]),
    enabled: Boolean(serverId) && enabled,
  });
}

export function useVersioningRefreshState(serverId: string, enabled = true) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.refresh(serverId),
    queryFn: () =>
      typeof api.getRefreshState === "function"
        ? api.getRefreshState(serverId)
        : Promise.resolve(null),
    enabled: Boolean(serverId) && enabled,
  });
}

export function useVersioningSettings(serverId: string, enabled = true) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.settings(serverId),
    queryFn: () =>
      typeof api.getBotSettings === "function"
        ? api.getBotSettings(serverId)
        : Promise.resolve(null),
    enabled: Boolean(serverId) && enabled,
  });
}

export function useVersioningLiveChanges(
  serverId: string,
  branchName: string,
  enabled = true,
) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.liveChanges(serverId, branchName),
    queryFn: () =>
      typeof api.getLiveChanges === "function"
        ? api.getLiveChanges(serverId, branchName)
        : Promise.resolve({ changes: [], auto_commit: null }),
    enabled: Boolean(serverId && branchName && branchName !== "main") && enabled,
  });
}

export function useVersioningDataTemplates(serverId: string, enabled = true) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.dataTemplates(serverId),
    queryFn: () =>
      typeof api.listDataTemplates === "function"
        ? api.listDataTemplates(serverId)
        : Promise.resolve([]),
    enabled: Boolean(serverId) && enabled,
  });
}

export function useBranchRuntimeQuery(
  serverId: string,
  branchName: string,
  enabled = true,
) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.branchRuntime(serverId, branchName),
    queryFn: () =>
      typeof api.getBranchRuntime === "function"
        ? api.getBranchRuntime(serverId, branchName)
        : Promise.resolve(null),
    enabled: Boolean(serverId && branchName && branchName !== "main") && enabled,
  });
}

export function useGitHubStatusQuery(serverId: string, enabled = true) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  return useQuery({
    queryKey: queryKeys.versioning.githubStatus(serverId),
    queryFn: () =>
      typeof api.getGitHubStatus === "function"
        ? api.getGitHubStatus(serverId)
        : Promise.resolve(null),
    enabled: Boolean(serverId) && enabled,
  });
}

export function useVersioningMutations(serverId: string) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const qc = useQueryClient();

  const createBranch = useMutation({
    mutationFn: (body: CreateBranchRequest) =>
      api.createServerBranch(serverId, body),
    onSuccess: async () => {
      await invalidateVersioningScope(qc, serverId);
    },
  });

  const archiveBranch = useMutation({
    mutationFn: (branchName: string) => api.archiveBranch(serverId, branchName),
    onSuccess: async (_d, branchName) => {
      await invalidateVersioningScope(qc, serverId, branchName);
    },
  });

  const deleteBranch = useMutation({
    mutationFn: (branchName: string) =>
      api.deleteServerBranch(serverId, branchName),
    onSuccess: async (_d, branchName) => {
      await invalidateVersioningScope(qc, serverId, branchName);
    },
  });

  const createCommit = useMutation({
    mutationFn: (body: CreateCommitRequest) =>
      api.createServerCommit(serverId, body),
    onSuccess: async (_d, body) => {
      await invalidateVersioningScope(qc, serverId, body.branch_name);
    },
  });

  const refreshServer = useMutation({
    mutationFn: (body?: RefreshServerRequest) =>
      api.refreshServer(serverId, body),
    onSuccess: async () => {
      await invalidateVersioningScope(qc, serverId);
    },
  });

  const rollbackRefresh = useMutation({
    mutationFn: (body?: RollbackRefreshRequest) =>
      api.rollbackRefresh(serverId, body),
    onSuccess: async () => {
      await invalidateVersioningScope(qc, serverId);
    },
  });

  const confirmUpgrade = useMutation({
    mutationFn: (body?: ConfirmUpgradeRequest) =>
      api.confirmUpgrade(serverId, body),
    onSuccess: async () => {
      await invalidateVersioningScope(qc, serverId);
    },
  });

  const releasePins = useMutation({
    mutationFn: (body?: ConfirmUpgradeRequest) =>
      api.releaseRefreshPins(serverId, body),
    onSuccess: async () => {
      await invalidateVersioningScope(qc, serverId);
    },
  });

  const destroyBranch = useMutation({
    mutationFn: (branchName: string) =>
      api.destroyBranchRun(serverId, branchName),
    onSuccess: async (_d, branchName) => {
      await invalidateVersioningScope(qc, serverId, branchName);
    },
  });

  const updateSettings = useMutation({
    mutationFn: (body: BotSettingsRequest) =>
      api.updateBotSettings(serverId, body),
    onSuccess: async () => {
      await qc.invalidateQueries({
        queryKey: queryKeys.versioning.settings(serverId),
      });
      await qc.invalidateQueries({
        queryKey: queryKeys.versioning.refresh(serverId),
      });
    },
  });

  return {
    createBranch,
    archiveBranch,
    deleteBranch,
    createCommit,
    refreshServer,
    rollbackRefresh,
    confirmUpgrade,
    releasePins,
    destroyBranch,
    updateSettings,
  };
}
