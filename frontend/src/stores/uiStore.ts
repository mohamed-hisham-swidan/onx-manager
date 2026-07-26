import { create } from "zustand";

const THEME_KEY = "mcs_theme";

type Theme = "light" | "dark";

function loadTheme(): Theme {
  try {
    const raw = localStorage.getItem(THEME_KEY);
    if (raw === "dark" || raw === "light") return raw;
  } catch { /* ignore parse errors */ }
  if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) return "dark";
  return "light";
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

interface UIState {
  theme: Theme;
  sidebarOpen: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
}

export const useUIStore = create<UIState>((set) => {
  const initialTheme = loadTheme();
  applyTheme(initialTheme);

  return {
    theme: initialTheme,
    sidebarOpen: true,

    setTheme: (theme) => {
      localStorage.setItem(THEME_KEY, theme);
      applyTheme(theme);
      set({ theme });
    },

    toggleTheme: () =>
      set((state) => {
        const next = state.theme === "light" ? "dark" : "light";
        localStorage.setItem(THEME_KEY, next);
        applyTheme(next);
        return { theme: next };
      }),

    setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),

    toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  };
});
