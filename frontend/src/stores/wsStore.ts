import { create } from "zustand";
import type { ConnectionState } from "@/websocket/types";

interface WSState {
  connectionState: ConnectionState;
  connected: boolean;
  setConnectionState: (state: ConnectionState) => void;
}

export const useWSStore = create<WSState>((set) => ({
  connectionState: "disconnected" as ConnectionState,
  connected: false,
  setConnectionState: (connectionState) =>
    set({ connectionState, connected: connectionState === "connected" }),
}));
