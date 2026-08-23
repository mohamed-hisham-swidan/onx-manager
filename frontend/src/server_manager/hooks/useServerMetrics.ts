import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";

function useApi() {
  return createAuthenticatedApi();
}

export const MAX_POINTS = 120;

export function useServerMetrics(serverId: string) {
  const api = useApi();

  return useQuery({
    queryKey: queryKeys.monitoring.metrics(serverId),
    queryFn: () => api.getMetrics(serverId, MAX_POINTS),
    refetchInterval: 2000,
    refetchIntervalInBackground: true,
    enabled: !!serverId,
    staleTime: 1000,
  });
}
