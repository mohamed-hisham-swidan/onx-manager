import { create } from "zustand";
import type { ProvisioningSnapshot } from "@/server_manager/types";

export interface ProvisionProgressEvent {
  serverId: string;
  stage: string;
  percent: number | null;
  message: string;
  timestamp: number;
  snapshot?: ProvisioningSnapshot | null;
}

interface ProvisionProgressState {
  progress: Map<string, ProvisionProgressEvent>;
  setProgress: (serverId: string, event: Omit<ProvisionProgressEvent, "serverId">) => void;
  setSnapshot: (serverId: string, snapshot: ProvisioningSnapshot) => void;
  clearProgress: (serverId: string) => void;
  clear: () => void;
  getProgress: (serverId: string) => ProvisionProgressEvent | undefined;
}

function generateTimestamp(): number {
  return Date.now();
}

export const useProvisionProgressStore = create<ProvisionProgressState>((set, get) => ({
  progress: new Map(),

  setProgress: (serverId, event) =>
    set((state) => {
      const newProgress = new Map(state.progress);
      const prev = newProgress.get(serverId);
      newProgress.set(serverId, {
        ...event,
        serverId,
        timestamp: generateTimestamp(),
        snapshot: event.snapshot !== undefined ? event.snapshot : prev?.snapshot ?? null,
      });
      return { progress: newProgress };
    }),

  setSnapshot: (serverId, snapshot) =>
    set((state) => {
      const newProgress = new Map(state.progress);
      const stage =
        snapshot.status === "completed"
          ? "success"
          : snapshot.status === "failed"
            ? "failed"
            : snapshot.current_step_id || "download_core";
      newProgress.set(serverId, {
        serverId,
        stage,
        percent: snapshot.percent ?? null,
        message: snapshot.message || "",
        timestamp: generateTimestamp(),
        snapshot,
      });
      return { progress: newProgress };
    }),

  clearProgress: (serverId) =>
    set((state) => {
      const newProgress = new Map(state.progress);
      newProgress.delete(serverId);
      return { progress: newProgress };
    }),

  clear: () => set({ progress: new Map() }),

  getProgress: (serverId) => get().progress.get(serverId),
}));

export function toProvisionProgressEvent(
  raw: Record<string, unknown>,
): Omit<ProvisionProgressEvent, "serverId"> | null {
  if (raw.event_type !== "ForgeProvisionProgressEvent") return null;

  const rawSnap = raw.snapshot;
  const snapshot =
    rawSnap && typeof rawSnap === "object" && !Array.isArray(rawSnap)
      ? (rawSnap as ProvisioningSnapshot)
      : null;

  return {
    stage: (raw.stage as string) ?? snapshot?.current_step_id ?? "unknown",
    percent:
      typeof raw.percent === "number"
        ? raw.percent
        : typeof snapshot?.percent === "number"
          ? snapshot.percent
          : null,
    message: (raw.message as string) ?? snapshot?.message ?? "",
    timestamp: generateTimestamp(),
    snapshot,
  };
}
