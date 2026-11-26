import { useEffect, useMemo } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi, type MetricsSnapshot } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { subscribeChannels, unsubscribeChannels } from "@/hooks/useWebSocket";
import { useWSStore } from "@/stores/wsStore";
import type { ServerResponse } from "@/server_manager/types";
import type { HostResourceBudget } from "@/types";
import type { ServerLiveTelemetry } from "./serversUtils";

export interface UseFleetMetricsOptions {
  historyLimit?: number;
}

export interface FleetMetricsSummary {
  metricsByServerId: Record<string, ServerLiveTelemetry>;
  snapshotsByServerId: Record<string, MetricsSnapshot[]>;
  runningCount: number;
  totalOnlinePlayers: number;
  totalOnlineCapacity: number;
}

function pickLatestSnapshot(snapshots: MetricsSnapshot[] | undefined): MetricsSnapshot | undefined {
  if (!Array.isArray(snapshots) || snapshots.length === 0) return undefined;
  let latest = snapshots[0];
  for (let i = 1; i < snapshots.length; i += 1) {
    if (snapshots[i].timestamp > latest.timestamp) {
      latest = snapshots[i];
    }
  }
  return latest;
}

export function useFleetMetrics(
  servers: ServerResponse[],
  hostBudget?: HostResourceBudget,
  options?: UseFleetMetricsOptions,
): FleetMetricsSummary {
  const historyLimit = options?.historyLimit ?? 1;
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const isWsConnected = useWSStore((s) => s.connected);

  const runningServers = useMemo(
    () => servers.filter((s) => s.status === "running"),
    [servers],
  );
  const runningServerIds = useMemo(
    () => runningServers.map((s) => s.server_id),
    [runningServers],
  );
  const runningIdsKey = runningServerIds.join(",");

  const canFetchMetrics = typeof api?.getMetrics === "function";

  const metricQueries = useQueries({
    queries: runningServerIds.map((id) => ({
      queryKey: queryKeys.monitoring.metrics(id),
      queryFn: () => api.getMetrics(id, historyLimit),
      enabled: canFetchMetrics && Boolean(id),
      refetchInterval: isWsConnected ? false : 2000,
      refetchIntervalInBackground: false,
      staleTime: 1000,
      retry: false,
    })),
  });

  const metricQueriesKey = metricQueries
    .map(
      (q, idx) =>
        `${runningServerIds[idx]}:${q.dataUpdatedAt}:${q.data?.length ?? 0}:${q.data?.[q.data.length - 1]?.timestamp ?? ""}`,
    )
    .join("|");

  useEffect(() => {
    if (!runningIdsKey) return;
    const ids = runningIdsKey.split(",");
    const channels = ids.map((id) => `metrics:${id}`);
    subscribeChannels(channels);
    if (isWsConnected && canFetchMetrics) {
      for (const id of ids) {
        queryClient.invalidateQueries({
          queryKey: queryKeys.monitoring.metrics(id),
        });
      }
    }
    return () => unsubscribeChannels(channels);
  }, [runningIdsKey, isWsConnected, canFetchMetrics, queryClient]);

  return useMemo(() => {
    const budgetAllocMap = new Map<string, number>();
    for (const alloc of hostBudget?.allocations ?? []) {
      if (alloc.kind === "server") {
        budgetAllocMap.set(alloc.id, alloc.ram_mb);
      }
    }

    const queryDataById = new Map<string, MetricsSnapshot[] | undefined>();
    if (metricQueriesKey) {
      runningServerIds.forEach((id) => {
        const fromCache = queryClient.getQueryData<MetricsSnapshot[]>(
          queryKeys.monitoring.metrics(id),
        );
        queryDataById.set(id, fromCache);
      });
    }

    const metricsByServerId: Record<string, ServerLiveTelemetry> = {};
    const snapshotsByServerId: Record<string, MetricsSnapshot[]> = {};
    let totalOnlinePlayers = 0;
    let totalOnlineCapacity = 0;

    for (const server of servers) {
      const ramLimitMb =
        server.max_memory_mb ?? budgetAllocMap.get(server.server_id) ?? null;

      if (server.status === "running") {
        const snapshots = queryDataById.get(server.server_id) ?? [];
        snapshotsByServerId[server.server_id] = snapshots;
        const latest = pickLatestSnapshot(snapshots);
        const players = latest?.players ?? null;
        if (players !== null) {
          totalOnlinePlayers += players;
        }
        totalOnlineCapacity += server.max_players || 20;

        metricsByServerId[server.server_id] = {
          players,
          tps: latest?.tps ?? null,
          ramUsedMb: latest?.ram_used_mb ?? null,
          ramLimitMb,
          cpuPercent: latest?.cpu_percent ?? null,
          hasLiveMetrics: Boolean(latest),
        };
      } else {
        snapshotsByServerId[server.server_id] = [];
        metricsByServerId[server.server_id] = {
          players: null,
          tps: null,
          ramUsedMb: null,
          ramLimitMb,
          cpuPercent: null,
          hasLiveMetrics: false,
        };
      }
    }

    return {
      metricsByServerId,
      snapshotsByServerId,
      runningCount: runningServers.length,
      totalOnlinePlayers,
      totalOnlineCapacity,
    };
  }, [servers, runningServers.length, runningServerIds, metricQueriesKey, hostBudget, queryClient]);
}
