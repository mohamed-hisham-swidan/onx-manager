import { create } from "zustand";

export interface ProvisionProgressEvent {
  serverId: string;
  stage: string;
  percent: number | null;
  message: string;
  timestamp: number;
}

interface ProvisionProgressState {
  progress: Map<string, ProvisionProgressEvent>;
  setProgress: (serverId: string, event: Omit<ProvisionProgressEvent, "serverId">) => void;
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
      newProgress.set(serverId, { ...event, serverId, timestamp: generateTimestamp() });
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

export function toProvisionProgressEvent(raw: Record<string, unknown>): Omit<ProvisionProgressEvent, "serverId"> | null {
  if (raw.event_type !== "ForgeProvisionProgressEvent") return null;

  return {
    stage: (raw.stage as string) ?? "unknown",
    percent: (raw.percent as number) ?? null,
    message: (raw.message as string) ?? "",
    timestamp: generateTimestamp(),
  };
}