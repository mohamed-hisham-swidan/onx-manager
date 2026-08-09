import { create } from "zustand";

export type MarketplaceSource = "modrinth" | "curseforge";

const STORAGE_KEY = "mcs_marketplace_source";

function loadMarketplaceSource(): MarketplaceSource {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "modrinth" || raw === "curseforge") return raw;
  } catch {
    /* ignore storage errors */
  }
  return "modrinth";
}

interface MarketplaceSourceState {
  source: MarketplaceSource;
  setSource: (source: MarketplaceSource) => void;
}

export const useMarketplaceSourceStore = create<MarketplaceSourceState>((set) => ({
  source: loadMarketplaceSource(),

  setSource: (source) => {
    try {
      localStorage.setItem(STORAGE_KEY, source);
    } catch {
      /* ignore storage errors */
    }
    set({ source });
  },
}));
