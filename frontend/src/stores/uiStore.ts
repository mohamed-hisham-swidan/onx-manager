import { create } from "zustand";
import { updateDynamicFavicon } from "@/tokens/dynamicFavicon";
import {
  THEME_KEY,
  SKIN_KEY,
  ACCENT_KEY,
  CORNER_STYLE_KEY,
  DEFAULT_THEME,
  DEFAULT_SKIN,
  DEFAULT_ACCENT,
  DEFAULT_CORNER_STYLE,
  type Theme,
  type Skin,
  type AccentColor,
  type CornerStyle,
} from "@/tokens/storageKeys";

export {
  THEME_KEY,
  SKIN_KEY,
  ACCENT_KEY,
  CORNER_STYLE_KEY,
  DEFAULT_THEME,
  DEFAULT_SKIN,
  DEFAULT_ACCENT,
  DEFAULT_CORNER_STYLE,
};
export type { Theme, Skin, AccentColor, CornerStyle };

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

function loadAccent(): AccentColor {
  try {
    const raw = localStorage.getItem(ACCENT_KEY);
    if (raw === "default") {
      localStorage.setItem(ACCENT_KEY, DEFAULT_ACCENT);
      return DEFAULT_ACCENT;
    }
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

function loadCornerStyle(): CornerStyle {
  try {
    const raw = localStorage.getItem(CORNER_STYLE_KEY);
    if (raw === "rounded" || raw === "sharp") return raw;
  } catch { /* ignore */ }
  return DEFAULT_CORNER_STYLE;
}

export function applyTheme(theme: Theme) {
  if (typeof document !== "undefined") {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.setAttribute("data-mode", theme);
    updateDynamicFavicon();
  }
}

export function applySkin(skin: Skin) {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-skin", skin);
    updateDynamicFavicon();
  }
}

export function applyAccent(accent: AccentColor) {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-accent", accent);
    updateDynamicFavicon();
  }
}

export function applyCornerStyle(cornerStyle: CornerStyle) {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-corners", cornerStyle);
  }
}

function saveStorage(key: string, val: string) {
  try {
    localStorage.setItem(key, val);
  } catch (err) {
    console.warn(`Failed to persist ${key} to localStorage:`, err);
  }
}

const SHOW_FULL_VPS_CONTROLS_KEY = "onx_show_full_vps_controls";

function loadShowFullVpsControls(): boolean {
  try {
    return localStorage.getItem(SHOW_FULL_VPS_CONTROLS_KEY) === "true";
  } catch {
    return false;
  }
}

export interface UIState {
  theme: Theme;
  skin: Skin;
  accent: AccentColor;
  cornerStyle: CornerStyle;
  sidebarOpen: boolean;
  sidebarSavedBeforeRightPanel: boolean | null;
  changeVersionOpen: boolean;
  mobileSidebarOpen: boolean;
  showFullVpsControls: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setSkin: (skin: Skin) => void;
  setAccent: (accent: AccentColor) => void;
  setCornerStyle: (cornerStyle: CornerStyle) => void;
  toggleCornerStyle: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  setChangeVersionOpen: (open: boolean) => void;
  syncRightPanelSidebarCollapse: (rightPanelOpen: boolean) => void;
  setMobileSidebarOpen: (open: boolean) => void;
  toggleMobileSidebar: () => void;
  setShowFullVpsControls: (show: boolean) => void;
  toggleShowFullVpsControls: () => void;
}

export const useUIStore = create<UIState>((set) => {
  const initialTheme = loadTheme();
  const initialSkin = loadSkin();
  const initialAccent = loadAccent();
  const initialCornerStyle = loadCornerStyle();
  const initialShowFullVpsControls = loadShowFullVpsControls();

  applyTheme(initialTheme);
  applySkin(initialSkin);
  applyAccent(initialAccent);
  applyCornerStyle(initialCornerStyle);

  return {
    theme: initialTheme,
    skin: initialSkin,
    accent: initialAccent,
    cornerStyle: initialCornerStyle,
    sidebarOpen: true,
    sidebarSavedBeforeRightPanel: null,
    changeVersionOpen: false,
    mobileSidebarOpen: false,
    showFullVpsControls: initialShowFullVpsControls,

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

    setAccent: (accent) => {
      saveStorage(ACCENT_KEY, accent);
      applyAccent(accent);
      set({ accent });
    },

    setCornerStyle: (cornerStyle) => {
      saveStorage(CORNER_STYLE_KEY, cornerStyle);
      applyCornerStyle(cornerStyle);
      set({ cornerStyle });
    },

    toggleCornerStyle: () =>
      set((state) => {
        const next = state.cornerStyle === "rounded" ? "sharp" : "rounded";
        saveStorage(CORNER_STYLE_KEY, next);
        applyCornerStyle(next);
        return { cornerStyle: next };
      }),

    setSidebarOpen: (sidebarOpen) => set({ sidebarOpen, sidebarSavedBeforeRightPanel: null }),

    toggleSidebar: () =>
      set((state) => ({
        sidebarOpen: !state.sidebarOpen,
        sidebarSavedBeforeRightPanel: null,
      })),

    setChangeVersionOpen: (changeVersionOpen) => set({ changeVersionOpen }),

    syncRightPanelSidebarCollapse: (rightPanelOpen) =>
      set((state) => {
        if (rightPanelOpen) {
          if (state.sidebarSavedBeforeRightPanel !== null) return state;
          return {
            sidebarSavedBeforeRightPanel: state.sidebarOpen,
            sidebarOpen: false,
          };
        }
        if (state.sidebarSavedBeforeRightPanel === null) return state;
        return {
          sidebarOpen: state.sidebarSavedBeforeRightPanel,
          sidebarSavedBeforeRightPanel: null,
        };
      }),

    setMobileSidebarOpen: (mobileSidebarOpen) => set({ mobileSidebarOpen }),

    toggleMobileSidebar: () => set((state) => ({ mobileSidebarOpen: !state.mobileSidebarOpen })),

    setShowFullVpsControls: (showFullVpsControls) => {
      saveStorage(SHOW_FULL_VPS_CONTROLS_KEY, String(showFullVpsControls));
      set({ showFullVpsControls });
    },

    toggleShowFullVpsControls: () =>
      set((state) => {
        const next = !state.showFullVpsControls;
        saveStorage(SHOW_FULL_VPS_CONTROLS_KEY, String(next));
        return { showFullVpsControls: next };
      }),
  };
});
