import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useWSStore } from "@/stores/wsStore";

function useApi() {
  return createAuthenticatedApi();
}

export const MAX_POINTS = 120;

export function useServerMetrics(serverId: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  const isWsConnected = useWSStore((s) => s.connected);

  useEffect(() => {
    if (isWsConnected && serverId) {
      queryClient.invalidateQueries({
        queryKey: queryKeys.monitoring.metrics(serverId),
      });
    }
  }, [isWsConnected, serverId, queryClient]);

  return useQuery({
    queryKey: queryKeys.monitoring.metrics(serverId),
    queryFn: () => api.getMetrics(serverId, MAX_POINTS),
    refetchInterval: isWsConnected ? false : 2000,
    refetchIntervalInBackground: false,
    enabled: !!serverId,
    staleTime: 1000,
  });
}
