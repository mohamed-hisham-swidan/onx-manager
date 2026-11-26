export const THEME_KEY = "onx_theme";
export const SKIN_KEY = "onx_skin";
export const ACCENT_KEY = "onx_accent";
export const CORNER_STYLE_KEY = "onx_corner_style";

export type Theme = "light" | "dark";
export type Skin = "graphite" | "azure" | "emerald" | "amethyst" | "amber" | "crimson";
export type ThemeSkin = Skin;
export type AccentColor = "theme" | "blue" | "emerald" | "violet" | "amber" | "rose" | "cyan";
export type CornerStyle = "rounded" | "sharp";

export const DEFAULT_THEME: Theme = "dark";
export const DEFAULT_SKIN: Skin = "graphite";
export const DEFAULT_ACCENT: AccentColor = "theme";
export const DEFAULT_CORNER_STYLE: CornerStyle = "rounded";

export interface SkinPreset {
  id: Skin;
  name: string;
  legacyName?: string;
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
    name: "Obsidian Graphite",
    legacyName: "Graphite",
    tagline: "Deep obsidian carbon & engineering cobalt",
    preview: { bg: "rgb(8, 9, 14)", card: "rgb(17, 20, 31)", accent: "rgb(37, 99, 235)" },
  },
  {
    id: "azure",
    name: "Midnight Nord",
    legacyName: "Azure",
    tagline: "Deep arctic slate & ice cyan",
    preview: { bg: "rgb(9, 13, 22)", card: "rgb(17, 25, 39)", accent: "rgb(56, 189, 248)" },
  },
  {
    id: "emerald",
    name: "Cyber Matrix",
    legacyName: "Emerald",
    tagline: "Deep pine obsidian & mint teal",
    preview: { bg: "rgb(13, 15, 15)", card: "rgb(21, 24, 24)", accent: "rgb(79, 168, 155)" },
  },
  {
    id: "amethyst",
    name: "Tokyo Night",
    legacyName: "Amethyst",
    tagline: "Deep night indigo & soft periwinkle",
    preview: { bg: "rgb(13, 14, 23)", card: "rgb(21, 23, 38)", accent: "rgb(129, 140, 248)" },
  },
  {
    id: "amber",
    name: "Titanium Monolith",
    legacyName: "Amber",
    tagline: "Warm gunmetal & crisp silver platinum",
    preview: { bg: "rgb(12, 12, 14)", card: "rgb(21, 21, 25)", accent: "rgb(203, 213, 225)" },
  },
  {
    id: "crimson",
    name: "Deep Rosé / Wine",
    legacyName: "Crimson",
    tagline: "Muted dark plum & soft coral rosé",
    preview: { bg: "rgb(16, 14, 18)", card: "rgb(24, 21, 27)", accent: "rgb(199, 125, 137)" },
  },
];

export interface ThemeSkinDefinition {
  id: Skin;
  name: string;
  legacyName?: string;
  tagline: string;
  description: string;
  paletteBadge: string;
  canvasColor: string;
  surfaceColor: string;
  elevatedColor: string;
  borderColor: string;
  accentColor: string;
  badgeColor: string;
}

export const THEME_SKINS: ThemeSkinDefinition[] = [
  {
    id: "graphite",
    name: "Obsidian Graphite",
    legacyName: "Graphite",
    tagline: "Deep obsidian carbon & engineering cobalt",
    description: "Pure obsidian canvas with deep navy-carbon elevations and high-contrast cobalt accents.",
    paletteBadge: "Obsidian Graphite",
    canvasColor: "rgb(8, 9, 14)",
    surfaceColor: "rgb(17, 20, 31)",
    elevatedColor: "rgb(23, 27, 41)",
    borderColor: "rgb(100, 116, 139)",
    accentColor: "rgb(37, 99, 235)",
    badgeColor: "rgb(59, 130, 246)",
  },
  {
    id: "azure",
    name: "Midnight Nord",
    legacyName: "Azure",
    tagline: "Deep arctic slate & ice cyan",
    description: "Sub-zero arctic slate architecture with crystalline cyan telemetry highlights.",
    paletteBadge: "Midnight Nord",
    canvasColor: "rgb(9, 13, 22)",
    surfaceColor: "rgb(17, 25, 39)",
    elevatedColor: "rgb(24, 35, 56)",
    borderColor: "rgb(95, 121, 158)",
    accentColor: "rgb(56, 189, 248)",
    badgeColor: "rgb(2, 132, 199)",
  },
  {
    id: "emerald",
    name: "Cyber Matrix",
    legacyName: "Emerald",
    tagline: "Deep pine obsidian & mint teal",
    description: "Bio-synthetic obsidian canvas with glowing terminal mint-teal vectors.",
    paletteBadge: "Cyber Matrix",
    canvasColor: "rgb(13, 15, 15)",
    surfaceColor: "rgb(21, 24, 24)",
    elevatedColor: "rgb(26, 30, 30)",
    borderColor: "rgb(102, 117, 111)",
    accentColor: "rgb(79, 168, 155)",
    badgeColor: "rgb(67, 143, 132)",
  },
  {
    id: "amethyst",
    name: "Tokyo Night",
    legacyName: "Amethyst",
    tagline: "Deep night indigo & soft periwinkle",
    description: "Cyberpunk midnight atmospheric indigo with electric periwinkle-violet accents.",
    paletteBadge: "Tokyo Night",
    canvasColor: "rgb(13, 14, 23)",
    surfaceColor: "rgb(21, 23, 38)",
    elevatedColor: "rgb(29, 32, 51)",
    borderColor: "rgb(107, 117, 158)",
    accentColor: "rgb(129, 140, 248)",
    badgeColor: "rgb(99, 102, 241)",
  },
  {
    id: "amber",
    name: "Titanium Monolith",
    legacyName: "Amber",
    tagline: "Warm gunmetal & crisp silver platinum",
    description: "Precision engineered gunmetal monolith surfaces with high-clarity platinum-silver luster.",
    paletteBadge: "Titanium Monolith",
    canvasColor: "rgb(12, 12, 14)",
    surfaceColor: "rgb(21, 21, 25)",
    elevatedColor: "rgb(30, 30, 36)",
    borderColor: "rgb(100, 116, 139)",
    accentColor: "rgb(203, 213, 225)",
    badgeColor: "rgb(148, 163, 184)",
  },
  {
    id: "crimson",
    name: "Deep Rosé / Wine",
    legacyName: "Crimson",
    tagline: "Muted dark plum & soft coral rosé",
    description: "Opulent dark plum baseline paired with soft neon coral-rosé focal highlights.",
    paletteBadge: "Deep Rosé / Wine",
    canvasColor: "rgb(16, 14, 18)",
    surfaceColor: "rgb(24, 21, 27)",
    elevatedColor: "rgb(30, 26, 34)",
    borderColor: "rgb(114, 102, 115)",
    accentColor: "rgb(199, 125, 137)",
    badgeColor: "rgb(181, 107, 120)",
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

export function initPrePaintAttributes(): {
  mode: Theme;
  skin: Skin;
  accent: AccentColor;
  cornerStyle: CornerStyle;
} {
  let mode: Theme = DEFAULT_THEME;
  let skin: Skin = DEFAULT_SKIN;
  let accent: AccentColor = DEFAULT_ACCENT;
  let cornerStyle: CornerStyle = DEFAULT_CORNER_STYLE;

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

    const rawCorners = localStorage.getItem(CORNER_STYLE_KEY);
    if (rawCorners === "rounded" || rawCorners === "sharp") {
      cornerStyle = rawCorners;
    }

    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-mode", mode);
      document.documentElement.setAttribute("data-skin", skin);
      document.documentElement.setAttribute("data-accent", accent);
      document.documentElement.setAttribute("data-corners", cornerStyle);
      if (mode === "dark") {
        document.documentElement.classList.add("dark");
      } else {
        document.documentElement.classList.remove("dark");
      }
    }
  } catch {
    // Graceful fallback if localStorage is unavailable
  }

  const result = { mode, skin } as {
    mode: Theme;
    skin: Skin;
    accent: AccentColor;
    cornerStyle: CornerStyle;
  };
  Object.defineProperty(result, "accent", {
    value: accent,
    enumerable: false,
    writable: true,
    configurable: true,
  });
  Object.defineProperty(result, "cornerStyle", {
    value: cornerStyle,
    enumerable: false,
    writable: true,
    configurable: true,
  });

  return result;
}
