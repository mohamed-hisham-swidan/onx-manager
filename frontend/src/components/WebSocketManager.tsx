import { useCallback, useEffect } from "react";
import { queryClient } from "@/services/queryClient";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuthStore } from "@/stores/authStore";
import { useDeploymentProfile } from "@/hooks/useDeploymentProfile";
import { useActivityStore, toActivityEvent } from "@/stores/activityStore";
import { useProvisionProgressStore, toProvisionProgressEvent } from "@/stores/provisionProgressStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import type { OperationEvent } from "@/operations/types";
import type { MetricsSnapshot } from "@/services/api";
import { MAX_POINTS } from "@/server_manager/components/ServerMetricsCharts";

const WS_KEY_MAP: Record<string, string[]> = {
  "servers:list": ["servers", "list"],
  "backups:list": ["backups", "list"],
  "plugins:list": ["plugins", "list"],
  "auth:me": ["auth", "me"],
  "auth:api-keys": ["auth", "api-keys"],
};

const OPERATION_EVENT_MAP: Record<string, string> = {
  OperationStartedEvent: "operation.started",
  OperationStepEvent: "operation.step",
  OperationLogEvent: "operation.log",
  OperationCompletedEvent: "operation.completed",
  OperationFailedEvent: "operation.failed",
  OperationCancelledEvent: "operation.cancelled",
};

function normalizeOperationEvent(event: Record<string, unknown>): OperationEvent | null {
  const rawType = event.event_type as string | undefined;
  if (!rawType) return null;
  const mappedType = rawType.startsWith("operation.")
    ? rawType
    : OPERATION_EVENT_MAP[rawType];
  if (!mappedType) return null;
  return {
    ...(event as unknown as OperationEvent),
    event_type: mappedType,
    line:
      typeof event.line === "string"
        ? event.line
        : typeof event.message === "string"
          ? event.message
          : undefined,
    step_status:
      (event.step_status as OperationEvent["step_status"]) ??
      (mappedType === "operation.step"
        ? (event.status as OperationEvent["step_status"])
        : undefined),
  };
}

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
  const { isLocalZeroLogin } = useDeploymentProfile();
  const canConnect = isAuthenticated || isLocalZeroLogin;
  const addEvent = useActivityStore((s) => s.addEvent);
  const setEvents = useActivityStore((s) => s.setEvents);

  const onCacheUpdate = useCallback(
    (update: { key: string; data: unknown; action: "set" | "update" | "invalidate" | "merge" }) => {
      const queryKey = toQueryKey(update.key);
      if (update.action === "invalidate") {
        queryClient.invalidateQueries({ queryKey });
      } else if (update.action === "merge") {
        const { samples } = update.data as { samples: Array<{ ts: number; tps: number | null; players: number; ram_mb: number; cpu: number }> };
        const rawExisting = queryClient.getQueryData<MetricsSnapshot[]>(queryKey);
        const existing = Array.isArray(rawExisting) ? rawExisting : [];
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
      } else if (update.key.startsWith("metrics:")) {
        // Guard against clobbering MetricsSnapshot[] cache with a single WS metrics object
        const payload = update.data as {
          tps?: number | null;
          players?: number;
          ram_mb?: number;
          ram_used_mb?: number;
          cpu?: number;
          cpu_percent?: number;
          timestamp?: string;
        } | null;
        if (payload && typeof payload === "object" && !Array.isArray(payload)) {
          const rawExisting = queryClient.getQueryData<MetricsSnapshot[]>(queryKey);
          const existing = Array.isArray(rawExisting) ? rawExisting : [];
          const prev = existing[existing.length - 1];
          const nextPoint: MetricsSnapshot = {
            tps: payload.tps ?? null,
            players: typeof payload.players === "number" ? payload.players : (prev?.players ?? 0),
            ram_used_mb:
              typeof payload.ram_used_mb === "number"
                ? payload.ram_used_mb
                : typeof payload.ram_mb === "number"
                  ? payload.ram_mb
                  : (prev?.ram_used_mb ?? 0),
            cpu_percent:
              typeof payload.cpu_percent === "number"
                ? payload.cpu_percent
                : typeof payload.cpu === "number"
                  ? payload.cpu
                  : (prev?.cpu_percent ?? 0),
            timestamp: payload.timestamp ?? new Date().toISOString(),
          };
          queryClient.setQueryData(queryKey, [...existing, nextPoint].slice(-MAX_POINTS));
        }
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
      const opEvent = normalizeOperationEvent(event);
      if (opEvent) {
        useOperationStore.getState().handleWsEvent(opEvent, (opId) => {
          queryClient.invalidateQueries({ queryKey: ["operations", "detail", opId] });
        });
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
    autoConnect: canConnect,
    allowAnonymous: isLocalZeroLogin,
  });

  useEffect(() => {
    if (!canConnect) return;
    subscribe(["server:*"]);
  }, [canConnect, subscribe]);

  return null;
}
