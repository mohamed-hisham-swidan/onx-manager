import { create } from "zustand";
import {
  THEME_KEY,
  SKIN_KEY,
  DENSITY_KEY,
  ACCENT_KEY,
  DEFAULT_THEME,
  DEFAULT_SKIN,
  DEFAULT_DENSITY,
  DEFAULT_ACCENT,
  type Theme,
  type Skin,
  type Density,
  type AccentColor,
} from "@/tokens/storageKeys";

export { THEME_KEY, SKIN_KEY, DENSITY_KEY, ACCENT_KEY, DEFAULT_THEME, DEFAULT_SKIN, DEFAULT_DENSITY, DEFAULT_ACCENT };
export type { Theme, Skin, Density, AccentColor };

function loadTheme(): Theme {
  try {
    const raw = localStorage.getItem(THEME_KEY);
    if (raw === "dark" || raw === "light") return raw;
  } catch { /* ignore parse errors */ }
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) return "dark";
  return "light";
}

function loadSkin(): Skin {
  try {
    const raw = localStorage.getItem(SKIN_KEY);
    if (
      raw === "graphite" ||
      raw === "azure" ||
      raw === "emerald" ||
      raw === "amethyst" ||
      raw === "amber" ||
      raw === "crimson"
    ) {
      return raw;
    }
  } catch { /* ignore */ }
  return "graphite";
}

function loadDensity(): Density {
  try {
    const raw = localStorage.getItem(DENSITY_KEY);
    if (raw === "comfortable" || raw === "compact") return raw;
  } catch { /* ignore */ }
  return "comfortable";
}

function loadAccent(): AccentColor {
  try {
    const raw = localStorage.getItem(ACCENT_KEY);
    if (
      raw === "theme" ||
      raw === "blue" ||
      raw === "emerald" ||
      raw === "violet" ||
      raw === "amber" ||
      raw === "rose" ||
      raw === "cyan"
    ) {
      return raw;
    }
  } catch { /* ignore */ }
  return DEFAULT_ACCENT;
}

export function applyTheme(theme: Theme) {
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.setAttribute("data-mode", theme);
  }
}

export function applySkin(skin: Skin) {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-skin", skin);
  }
}

export function applyDensity(density: Density) {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-density", density);
  }
}

export function applyAccent(accent: AccentColor) {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-accent", accent);
  }
}

function saveStorage(key: string, val: string) {
  try {
    localStorage.setItem(key, val);
  } catch (err) {
    console.warn(`Failed to persist ${key} to localStorage:`, err);
  }
}

export interface UIState {
  theme: Theme;
  skin: Skin;
  density: Density;
  accent: AccentColor;
  sidebarOpen: boolean;
  mobileSidebarOpen: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setSkin: (skin: Skin) => void;
  setDensity: (density: Density) => void;
  toggleDensity: () => void;
  setAccent: (accent: AccentColor) => void;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  setMobileSidebarOpen: (open: boolean) => void;
  toggleMobileSidebar: () => void;
}

export const useUIStore = create<UIState>((set) => {
  const initialTheme = loadTheme();
  const initialSkin = loadSkin();
  const initialDensity = loadDensity();
  const initialAccent = loadAccent();

  applyTheme(initialTheme);
  applySkin(initialSkin);
  applyDensity(initialDensity);
  applyAccent(initialAccent);

  return {
    theme: initialTheme,
    skin: initialSkin,
    density: initialDensity,
    accent: initialAccent,
    sidebarOpen: true,
    mobileSidebarOpen: false,

    setTheme: (theme) => {
      saveStorage(THEME_KEY, theme);
      applyTheme(theme);
      set({ theme });
    },

    toggleTheme: () =>
      set((state) => {
        const next = state.theme === "light" ? "dark" : "light";
        saveStorage(THEME_KEY, next);
        applyTheme(next);
        return { theme: next };
      }),

    setSkin: (skin) => {
      saveStorage(SKIN_KEY, skin);
      applySkin(skin);
      set({ skin });
    },

    setDensity: (density) => {
      saveStorage(DENSITY_KEY, density);
      applyDensity(density);
      set({ density });
    },

    toggleDensity: () =>
      set((state) => {
        const next = state.density === "comfortable" ? "compact" : "comfortable";
        saveStorage(DENSITY_KEY, next);
        applyDensity(next);
        return { density: next };
      }),

    setAccent: (accent) => {
      saveStorage(ACCENT_KEY, accent);
      applyAccent(accent);
      set({ accent });
    },

    setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),

    toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),

    setMobileSidebarOpen: (mobileSidebarOpen) => set({ mobileSidebarOpen }),

    toggleMobileSidebar: () => set((state) => ({ mobileSidebarOpen: !state.mobileSidebarOpen })),
  };
});
