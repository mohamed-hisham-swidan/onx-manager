export const THEME_KEY = "onx_theme";
export const SKIN_KEY = "onx_skin";
export const DENSITY_KEY = "onx_density";
export const ACCENT_KEY = "onx_accent";

export type Theme = "light" | "dark";
export type Skin = "graphite" | "azure" | "emerald" | "amethyst" | "amber" | "crimson";
export type Density = "comfortable" | "compact";
export type AccentColor = "theme" | "blue" | "emerald" | "violet" | "amber" | "rose" | "cyan";

export const DEFAULT_THEME: Theme = "dark";
export const DEFAULT_SKIN: Skin = "graphite";
export const DEFAULT_DENSITY: Density = "comfortable";
export const DEFAULT_ACCENT: AccentColor = "theme";

export interface SkinPreset {
  id: Skin;
  name: string;
  tagline: string;
  preview: {
    bg: string;
    card: string;
    accent: string;
  };
}

export const SKIN_PRESETS: SkinPreset[] = [
  {
    id: "graphite",
    name: "Graphite",
    tagline: "Pure neutral monochrome carbon",
    preview: { bg: "rgb(20, 20, 20)", card: "rgb(26, 26, 26)", accent: "rgb(37, 99, 235)" },
  },
  {
    id: "azure",
    name: "Azure",
    tagline: "Deep ocean slate & sky blue",
    preview: { bg: "rgb(11, 18, 34)", card: "rgb(15, 23, 42)", accent: "rgb(2, 132, 199)" },
  },
  {
    id: "emerald",
    name: "Emerald",
    tagline: "Obsidian forest & matrix green",
    preview: { bg: "rgb(9, 22, 18)", card: "rgb(15, 34, 28)", accent: "rgb(5, 150, 105)" },
  },
  {
    id: "amethyst",
    name: "Amethyst",
    tagline: "Cosmic nebula & royal violet",
    preview: { bg: "rgb(19, 15, 30)", card: "rgb(27, 22, 42)", accent: "rgb(124, 58, 237)" },
  },
  {
    id: "amber",
    name: "Amber",
    tagline: "Warm carbon & industrial gold",
    preview: { bg: "rgb(23, 19, 13)", card: "rgb(33, 27, 19)", accent: "rgb(180, 83, 9)" },
  },
  {
    id: "crimson",
    name: "Crimson",
    tagline: "Volcanic basalt & ruby rose",
    preview: { bg: "rgb(24, 14, 18)", card: "rgb(34, 20, 25)", accent: "rgb(190, 18, 60)" },
  },
];

export interface AccentPreset {
  id: AccentColor;
  name: string;
  swatch: string;
}

export const ACCENT_PRESETS: AccentPreset[] = [
  { id: "theme", name: "Default Theme", swatch: "transparent" },
  { id: "blue", name: "Sky Blue", swatch: "rgb(37, 99, 235)" },
  { id: "emerald", name: "Emerald", swatch: "rgb(5, 150, 105)" },
  { id: "violet", name: "Violet", swatch: "rgb(124, 58, 237)" },
  { id: "amber", name: "Amber", swatch: "rgb(217, 119, 6)" },
  { id: "rose", name: "Rose", swatch: "rgb(225, 29, 72)" },
  { id: "cyan", name: "Cyan", swatch: "rgb(8, 145, 178)" },
];

export function initPrePaintAttributes(): { mode: Theme; skin: Skin; density: Density; accent: AccentColor } {
  let mode: Theme = DEFAULT_THEME;
  let skin: Skin = DEFAULT_SKIN;
  let density: Density = DEFAULT_DENSITY;
  let accent: AccentColor = DEFAULT_ACCENT;

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
    if (
      rawSkin === "graphite" ||
      rawSkin === "azure" ||
      rawSkin === "emerald" ||
      rawSkin === "amethyst" ||
      rawSkin === "amber" ||
      rawSkin === "crimson"
    ) {
      skin = rawSkin;
    }

    const rawDensity = localStorage.getItem(DENSITY_KEY);
    if (rawDensity === "comfortable" || rawDensity === "compact") {
      density = rawDensity;
    }

    const rawAccent = localStorage.getItem(ACCENT_KEY);
    if (
      rawAccent === "theme" ||
      rawAccent === "blue" ||
      rawAccent === "emerald" ||
      rawAccent === "violet" ||
      rawAccent === "amber" ||
      rawAccent === "rose" ||
      rawAccent === "cyan"
    ) {
      accent = rawAccent;
    }

    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-mode", mode);
      document.documentElement.setAttribute("data-skin", skin);
      document.documentElement.setAttribute("data-density", density);
      document.documentElement.setAttribute("data-accent", accent);
      if (mode === "dark") {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    }
  } catch {
    // Graceful fallback if localStorage is unavailable
  }

  const result = { mode, skin, density } as {
    mode: Theme;
    skin: Skin;
    density: Density;
    accent: AccentColor;
  };
  Object.defineProperty(result, "accent", {
    value: accent,
    enumerable: false,
    writable: true,
    configurable: true,
  });

  return result;
}
