import { useEffect, useMemo } from "react";
import { subscribeChannels, unsubscribeChannels } from "@/hooks/useWebSocket";
import { createAuthenticatedApi } from "@/services/api";
import { useProvisionProgressStore } from "@/stores/provisionProgressStore";
import type { ProvisioningSnapshot } from "@/server_manager/types";

export interface ProvisionProgress {
  serverId: string;
  stage: string;
  percent: number | null;
  message: string;
  timestamp: number;
  snapshot?: ProvisioningSnapshot | null;
}

export interface UseProvisionProgressOptions {
  enablePollingFallback?: boolean;
  pollIntervalMs?: number;
}

export function useProvisionProgress(
  serverId: string | null,
  options: UseProvisionProgressOptions = {},
): ProvisionProgress | null {
  const { enablePollingFallback = false, pollIntervalMs = 1500 } = options;
  const api = useMemo(() => createAuthenticatedApi(), []);
  const storeProgress = useProvisionProgressStore((s) =>
    serverId ? s.progress.get(serverId) : null,
  );

  const isTerminal =
    storeProgress?.stage === "success" ||
    storeProgress?.stage === "failed" ||
    storeProgress?.stage === "timeout" ||
    storeProgress?.snapshot?.status === "completed" ||
    storeProgress?.snapshot?.status === "failed";

  // Subscribe/unsubscribe to provision channel
  useEffect(() => {
    if (!serverId) {
      return;
    }

    const channel = `provision:${serverId}`;
    subscribeChannels([channel]);

    return () => {
      unsubscribeChannels([channel]);
    };
  }, [serverId]);

  // Optional HTTP polling fallback (e.g., on page refresh mid-provisioning or WS offline)
  useEffect(() => {
    if (!serverId || !enablePollingFallback || isTerminal) return;
    if (typeof api.getServer !== "function") return;

    let cancelled = false;
    const poll = async () => {
      try {
        const detail = await api.getServer(serverId);
        if (cancelled || !detail) return;
        if (detail.provisioning_progress) {
          useProvisionProgressStore
            .getState()
            .setSnapshot(serverId, detail.provisioning_progress);
        } else if (
          detail.status === "provisioning_failed" &&
          detail.provisioning_error
        ) {
          useProvisionProgressStore.getState().setProgress(serverId, {
            stage: "failed",
            percent: null,
            message: detail.provisioning_error,
            timestamp: Date.now(),
          });
        } else if (
          detail.status === "created" ||
          detail.status === "stopped" ||
          detail.status === "running"
        ) {
          const prev = useProvisionProgressStore.getState().getProgress(serverId);
          if (prev && prev.stage !== "success") {
            useProvisionProgressStore.getState().setProgress(serverId, {
              stage: "success",
              percent: 100,
              message: "Server created and ready to start",
              timestamp: Date.now(),
              snapshot: prev.snapshot
                ? {
                    ...prev.snapshot,
                    status: "completed",
                    percent: 100,
                    steps: prev.snapshot.steps.map((st) =>
                      st.status === "pending" || st.status === "running"
                        ? { ...st, status: "completed" }
                        : st,
                    ),
                  }
                : null,
            });
          }
        }
      } catch {
        // Ignore transient polling failures
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, pollIntervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [api, enablePollingFallback, isTerminal, pollIntervalMs, serverId]);

  if (!storeProgress) return null;

  return {
    serverId: storeProgress.serverId,
    stage: storeProgress.stage,
    percent: storeProgress.percent,
    message: storeProgress.message,
    timestamp: storeProgress.timestamp,
    snapshot: storeProgress.snapshot ?? null,
  };
}
