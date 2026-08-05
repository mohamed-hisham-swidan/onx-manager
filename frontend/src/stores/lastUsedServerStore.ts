import { create } from "zustand";

const STORAGE_KEY = "mcs_last_used_server";

function loadLastUsedServer(): string {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return raw;
  } catch { /* ignore storage errors */ }
  return "";
}

interface LastUsedServerState {
  lastUsedServerId: string;
  setLastUsedServer: (serverId: string) => void;
}

export const useLastUsedServerStore = create<LastUsedServerState>((set) => ({
  lastUsedServerId: loadLastUsedServer(),

  setLastUsedServer: (serverId) => {
    try {
      localStorage.setItem(STORAGE_KEY, serverId);
    } catch { /* ignore storage errors */ }
    set({ lastUsedServerId: serverId });
  },
}));
