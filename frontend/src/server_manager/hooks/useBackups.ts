import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { CreateBackupRequest, CreateScheduleRequest } from "@/types";

function useApi() {
  return createAuthenticatedApi();
}

export function useBackupsList(serverId?: string, tier?: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.backups.list(serverId, tier),
    queryFn: () => api.listBackups(serverId, tier),
    refetchInterval: (query) => {
      const items = query.state.data;
      if (!Array.isArray(items)) return false;
      const hasActive = items.some(
        (b) =>
          b.status === "pending" ||
          b.status === "in_progress" ||
          b.status === "running",
      );
      return hasActive ? 3000 : false;
    },
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

export function useSchedulesList() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.schedules.list(),
    queryFn: () => api.listSchedules(),
  });
}

export function useCreateSchedule() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateScheduleRequest) => api.createSchedule(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.schedules.all }),
  });
}

export function useDeleteSchedule() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId: string) => api.deleteSchedule(scheduleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.schedules.all }),
  });
}
