export const THEME_KEY = "onx_theme";
export const SKIN_KEY = "onx_skin";
export const DENSITY_KEY = "onx_density";

export type Theme = "light" | "dark";
export type Skin = "graphite" | "azure";
export type Density = "comfortable" | "compact";

export const DEFAULT_THEME: Theme = "dark";
export const DEFAULT_SKIN: Skin = "graphite";
export const DEFAULT_DENSITY: Density = "comfortable";

export function initPrePaintAttributes(): { mode: Theme; skin: Skin; density: Density } {
  let mode: Theme = DEFAULT_THEME;
  let skin: Skin = DEFAULT_SKIN;
  let density: Density = DEFAULT_DENSITY;

  try {
    const rawMode = localStorage.getItem(THEME_KEY);
    if (rawMode === "light" || rawMode === "dark") {
      mode = rawMode;
    } else if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
      mode = "dark";
    } else if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: light)").matches) {
      mode = "light";
    }

    const rawSkin = localStorage.getItem(SKIN_KEY);
    if (rawSkin === "graphite" || rawSkin === "azure") {
      skin = rawSkin;
    }

    const rawDensity = localStorage.getItem(DENSITY_KEY);
    if (rawDensity === "comfortable" || rawDensity === "compact") {
      density = rawDensity;
    }

    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-mode", mode);
      document.documentElement.setAttribute("data-skin", skin);
      document.documentElement.setAttribute("data-density", density);
      if (mode === "dark") {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    }
  } catch {
    // Graceful fallback if localStorage is unavailable
  }

  return { mode, skin, density };
}
