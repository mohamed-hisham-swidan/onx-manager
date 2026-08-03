import { useCallback } from "react";
import { queryClient } from "@/services/queryClient";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuthStore } from "@/stores/authStore";
import { useActivityStore, toActivityEvent } from "@/stores/activityStore";

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
    (update: { key: string; data: unknown; action: "set" | "update" | "invalidate" }) => {
      const queryKey = toQueryKey(update.key);
      if (update.action === "invalidate") {
        queryClient.invalidateQueries({ queryKey });
      } else {
        queryClient.setQueryData(queryKey, update.data);
      }
    },
    [],
  );

  const onEvent = useCallback(
    (event: Record<string, unknown>) => {
      addEvent(toActivityEvent(event));
    },
    [addEvent],
  );

  const onStateSync = useCallback(
    (events: Array<Record<string, unknown>>) => {
      setEvents(events.map(toActivityEvent));
    },
    [setEvents],
  );

  useWebSocket({
    url: `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`,
    onCacheUpdate,
    onEvent,
    onStateSync,
    autoConnect: isAuthenticated,
  });

  return null;
}
