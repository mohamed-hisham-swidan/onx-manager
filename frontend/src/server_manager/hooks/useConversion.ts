import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type { ConvertToSimpleRequest } from "@/types";

function useApi() {
  return createAuthenticatedApi();
}

export function useConvertToAdvanced() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverId: string) => api.convertToAdvanced(serverId),
    onSuccess: (_data, serverId) => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
      qc.invalidateQueries({ queryKey: queryKeys.backups.all });
    },
  });
}

export function useConvertToSimple() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ serverId, body }: { serverId: string; body: ConvertToSimpleRequest }) =>
      api.convertToSimple(serverId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.servers.all });
    },
  });
}
