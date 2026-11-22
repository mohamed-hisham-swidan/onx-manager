import { useEffect } from "react";
import { subscribeChannels, unsubscribeChannels } from "@/hooks/useWebSocket";
import { useProvisionProgressStore } from "@/stores/provisionProgressStore";

export interface ProvisionProgress {
  serverId: string;
  stage: string;
  percent: number | null;
  message: string;
  timestamp: number;
}

export function useProvisionProgress(serverId: string | null): ProvisionProgress | null {
  const storeProgress = useProvisionProgressStore((s) => (serverId ? s.progress.get(serverId) : null));

  // Subscribe/unsubscribe to provision channel
  useEffect(() => {
    if (!serverId) {
      return;
    }

    const channel = `provision:${serverId}`;
    subscribeChannels([channel]);

    return () => {
      unsubscribeChannels([channel]);
      // Don't clear progress immediately - let it persist briefly
      // The store will clear when the server status changes
    };
  }, [serverId]);

  if (!storeProgress) return null;

  return {
    serverId: storeProgress.serverId,
    stage: storeProgress.stage,
    percent: storeProgress.percent,
    message: storeProgress.message,
    timestamp: storeProgress.timestamp,
  };
}