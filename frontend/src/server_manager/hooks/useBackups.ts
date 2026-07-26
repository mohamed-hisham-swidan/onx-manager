import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { CreateBackupRequest, BackupResponse } from "@/types";

function useApi() {
  return createAuthenticatedApi();
}

export function useBackupsList(serverId?: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.backups.list(serverId),
    queryFn: () => api.listBackups(serverId),
  });
}

export function useCreateBackup() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateBackupRequest) => api.createBackup(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.backups.all }),
  });
}

export function useRestoreBackup() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (backupId: string) => api.restoreBackup(backupId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.backups.all });
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
    },
  });
}

export function useVerifyBackup() {
  const api = useApi();
  return useMutation({
    mutationFn: (backupId: string) => api.verifyBackup(backupId),
  });
}

export function useDeleteBackup() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (backupId: string) => api.deleteBackup(backupId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.backups.all }),
  });
}
