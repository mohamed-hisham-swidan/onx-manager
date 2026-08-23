import { useCallback, useEffect } from "react";
import { queryClient } from "@/services/queryClient";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuthStore } from "@/stores/authStore";
import { useActivityStore, toActivityEvent } from "@/stores/activityStore";
import { useProvisionProgressStore, toProvisionProgressEvent } from "@/stores/provisionProgressStore";
import type { MetricsSnapshot } from "@/services/api";
import { MAX_POINTS } from "@/server_manager/components/ServerMetricsCharts";

const WS_KEY_MAP: Record<string, string[]> = {
  "servers:list": ["servers", "list"],
  "backups:list": ["backups", "list"],
  "plugins:list": ["plugins", "list"],
  "auth:me": ["auth", "me"],
  "auth:api-keys": ["auth", "api-keys"],
};

function toQueryKey(key: string): string[] {
  const mapped = WS_KEY_MAP[key];
  if (mapped) return mapped;
  if (key.startsWith("server:")) return ["servers", "detail", key.slice(7)];
  if (key.startsWith("metrics:")) return ["monitoring", "metrics", key.slice(8)];
  if (key.startsWith("metrics_batch:")) return ["monitoring", "metrics", key.slice(14)];
  return [key];
}

export function WebSocketManager() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const addEvent = useActivityStore((s) => s.addEvent);
  const setEvents = useActivityStore((s) => s.setEvents);

  const onCacheUpdate = useCallback(
    (update: { key: string; data: unknown; action: "set" | "update" | "invalidate" | "merge" }) => {
      const queryKey = toQueryKey(update.key);
      if (update.action === "invalidate") {
        queryClient.invalidateQueries({ queryKey });
      } else if (update.action === "merge") {
        const { samples } = update.data as { samples: Array<{ ts: number; tps: number; players: number; ram_mb: number; cpu: number }> };
        const existing = queryClient.getQueryData<MetricsSnapshot[]>(queryKey) ?? [];
        const mapped: MetricsSnapshot[] = samples.map((s) => ({
          tps: s.tps,
          players: s.players,
          ram_used_mb: s.ram_mb,
          cpu_percent: s.cpu,
          timestamp: new Date(s.ts * 1000).toISOString(),
        }));
        const merged = [...existing, ...mapped]
          .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
          .slice(-MAX_POINTS);
        queryClient.setQueryData(queryKey, merged);
      } else {
        queryClient.setQueryData(queryKey, update.data);
      }
    },
    [],
  );

  const onEvent = useCallback(
    (event: Record<string, unknown>) => {
      addEvent(toActivityEvent(event));
      const provisionEvent = toProvisionProgressEvent(event);
      if (provisionEvent) {
        useProvisionProgressStore.getState().setProgress(event.server_id as string, provisionEvent);
      }
    },
    [addEvent],
  );

  const onStateSync = useCallback(
    (events: Array<Record<string, unknown>>) => {
      setEvents(events.map(toActivityEvent));
    },
    [setEvents],
  );

  const { subscribe } = useWebSocket({
    url: `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`,
    onCacheUpdate,
    onEvent,
    onStateSync,
    autoConnect: isAuthenticated,
  });

  useEffect(() => {
    if (!isAuthenticated) return;
    subscribe(["server:*"]);
  }, [isAuthenticated, subscribe]);

  return null;
}
