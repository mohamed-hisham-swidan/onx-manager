import { describe, it, expect } from "vitest";

interface NodeFs {
  readFileSync: (path: string, encoding: "utf8") => string;
  existsSync: (path: string) => boolean;
}

interface NodePath {
  resolve: (...args: string[]) => string;
  join: (...args: string[]) => string;
}

declare const require: (mod: string) => NodeFs & NodePath;
declare const process: { cwd: () => string };
const fs: NodeFs = require("node:fs");
const path: NodePath = require("node:path");

/**
 * WCAG 2.1 AA Contrast Ratio Computation Test (Real CSS Parser)
 *
 * Programmatically computes relative luminance according to the W3C WCAG 2.1 specifications:
 *   L = 0.2126 * R_lin + 0.7152 * G_lin + 0.0722 * B_lin
 * Contrast Ratio = (L_lighter + 0.05) / (L_darker + 0.05)
 *
 * Requirements:
 * - Text contrast >= 4.5:1 (WCAG AA normal text)
 * - Non-text UI boundaries & focus rings >= 3.0:1 (WCAG AA non-text contrast)
 * - Reads real tokens from frontend/src/index.css (no hardcoded palette mock)
 */

export function sRGBtoLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function parseHexToRgb(hex: string): [number, number, number] {
  if (!hex || typeof hex !== "string") {
    throw new Error(`Unparseable color value: ${hex}`);
  }
  let clean = hex.replace("#", "").trim();
  if (clean.length === 3) {
    clean = clean.split("").map((c) => c + c).join("");
  }
  if (!/^[0-9a-fA-F]{6}$/.test(clean)) {
    throw new Error(`Invalid hex color value: ${hex}`);
  }
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  if (isNaN(r) || isNaN(g) || isNaN(b)) {
    throw new Error(`Could not parse RGB channels from hex: ${hex}`);
  }
  return [r, g, b];
}

export function calculateLuminance(hex: string): number {
  const [r, g, b] = parseHexToRgb(hex);
  return 0.2126 * sRGBtoLinear(r) + 0.7152 * sRGBtoLinear(g) + 0.0722 * sRGBtoLinear(b);
}

export function calculateContrastRatio(colorA: string, colorB: string): number {
  const lumA = calculateLuminance(colorA);
  const lumB = calculateLuminance(colorB);
  const lighter = Math.max(lumA, lumB);
  const darker = Math.min(lumA, lumB);
  return (lighter + 0.05) / (darker + 0.05);
}

export interface SkinPalette {
  page: string;
  card: string;
  elevated: string;
  hover: string;
  active: string;
  muted: string;
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  borderSubtle: string;
  borderDefault: string;
  borderStrong: string;
  borderFocus: string;
  accentPrimary: string;
  accentContrastText: string;
}

/**
 * Explicit exclusion list for decorative tokens per Task 2 requirements.
 */
export const DECORATIVE_EXCLUSIONS = [
  {
    token: "--border-subtle",
    reason: "Purely decorative container/table hairline divider with no state or boundary affordance requirement under WCAG 2.1 SC 1.4.11.",
  },
] as const;

export function parseCssBlock(cssText: string, selectorPattern: string): Record<string, string> {
  const regex = new RegExp(selectorPattern + "\\s*\\{([^}]+)\\}", "m");
  const match = cssText.match(regex);
  if (!match) {
    throw new Error(`Failed to parse CSS block matching selector: ${selectorPattern}`);
  }
  const block = match[1];
  const tokens: Record<string, string> = {};
  for (const line of block.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("/*")) continue;
    const colonIdx = trimmed.indexOf(":");
    if (colonIdx === -1) continue;
    const prop = trimmed.slice(0, colonIdx).trim();
    let val = trimmed.slice(colonIdx + 1).trim();
    if (val.endsWith(";")) val = val.slice(0, -1).trim();
    tokens[prop] = val;
  }
  return tokens;
}

const SELECTOR_PATTERNS = {
  "graphite:dark": '\\[data-skin=["\']graphite["\']\\]\\s*,\\s*\\[data-skin=["\']graphite["\']\\]\\[data-mode=["\']dark["\']\\]\\s*,\\s*\\[data-skin=["\']graphite["\']\\]\\.dark',
  "graphite:light": '\\[data-skin=["\']graphite["\']\\]\\[data-mode=["\']light["\']\\]',
  "azure:dark": '\\[data-skin=["\']azure["\']\\]\\s*,\\s*\\[data-skin=["\']azure["\']\\]\\[data-mode=["\']dark["\']\\]\\s*,\\s*\\[data-skin=["\']azure["\']\\]\\.dark',
  "azure:light": '\\[data-skin=["\']azure["\']\\]\\[data-mode=["\']light["\']\\]',
} as const;

export function loadPalettesFromCss(cssText: string): Record<keyof typeof SELECTOR_PATTERNS, SkinPalette> {
  const palettes: Partial<Record<keyof typeof SELECTOR_PATTERNS, SkinPalette>> = {};

  for (const [key, pattern] of Object.entries(SELECTOR_PATTERNS)) {
    const rawTokens = parseCssBlock(cssText, pattern);
    const requiredKeys = [
      "--surface-page",
      "--surface-card",
      "--surface-elevated",
      "--surface-hover",
      "--surface-active",
      "--surface-muted",
      "--text-primary",
      "--text-secondary",
      "--text-muted",
      "--border-subtle",
      "--border-default",
      "--border-strong",
      "--border-focus",
      "--accent-primary",
      "--accent-contrast-text",
    ];

    for (const req of requiredKeys) {
      if (!rawTokens[req]) {
        throw new Error(`Missing required token ${req} in CSS block for ${key}`);
      }
    }

    palettes[key as keyof typeof SELECTOR_PATTERNS] = {
      page: rawTokens["--surface-page"],
      card: rawTokens["--surface-card"],
      elevated: rawTokens["--surface-elevated"],
      hover: rawTokens["--surface-hover"],
      active: rawTokens["--surface-active"],
      muted: rawTokens["--surface-muted"],
      textPrimary: rawTokens["--text-primary"],
      textSecondary: rawTokens["--text-secondary"],
      textMuted: rawTokens["--text-muted"],
      borderSubtle: rawTokens["--border-subtle"],
      borderDefault: rawTokens["--border-default"],
      borderStrong: rawTokens["--border-strong"],
      borderFocus: rawTokens["--border-focus"],
      accentPrimary: rawTokens["--accent-primary"],
      accentContrastText: rawTokens["--accent-contrast-text"],
    };
  }

  return palettes as Record<keyof typeof SELECTOR_PATTERNS, SkinPalette>;
}

export function checkPaletteViolations(
  skinKey: string,
  palette: SkinPalette,
  options?: { ignorePairs?: Set<string> },
): string[] {
  const violations: string[] = [];
  const surfaces = [
    { name: "page", hex: palette.page },
    { name: "card", hex: palette.card },
    { name: "elevated", hex: palette.elevated },
    { name: "hover", hex: palette.hover },
    { name: "active", hex: palette.active },
    { name: "muted", hex: palette.muted },
  ];
  const texts = [
    { name: "textPrimary", hex: palette.textPrimary },
    { name: "textSecondary", hex: palette.textSecondary },
    { name: "textMuted", hex: palette.textMuted },
  ];

  // 1. Text contrast (>= 4.5:1) on EVERY surface
  for (const text of texts) {
    for (const surface of surfaces) {
      const pairId = `${skinKey}:${text.name}:${surface.name}`;
      if (options?.ignorePairs?.has(pairId)) continue;
      const ratio = calculateContrastRatio(text.hex, surface.hex);
      if (ratio < 4.5) {
        violations.push(
          `${skinKey}: ${text.name} (${text.hex}) on ${surface.name} (${surface.hex}) ratio ${ratio.toFixed(2)}:1 < 4.5:1`,
        );
      }
    }
  }

  // 2. Borders (>= 3.0:1) on page and card
  const borders = [
    { name: "borderDefault", hex: palette.borderDefault },
    { name: "borderStrong", hex: palette.borderStrong },
    { name: "borderFocus", hex: palette.borderFocus },
  ];
  const boundarySurfaces = [
    { name: "page", hex: palette.page },
    { name: "card", hex: palette.card },
  ];

  for (const border of borders) {
    for (const surface of boundarySurfaces) {
      const ratio = calculateContrastRatio(border.hex, surface.hex);
      if (ratio < 3.0) {
        violations.push(
          `${skinKey}: ${border.name} (${border.hex}) on ${surface.name} (${surface.hex}) ratio ${ratio.toFixed(2)}:1 < 3.0:1`,
        );
      }
    }
  }

  // 3. Accent text on accent background (>= 4.5:1)
  const accentRatio = calculateContrastRatio(palette.accentContrastText, palette.accentPrimary);
  if (accentRatio < 4.5) {
    violations.push(
      `${skinKey}: accent text (${palette.accentContrastText}) on accent bg (${palette.accentPrimary}) ratio ${accentRatio.toFixed(2)}:1 < 4.5:1`,
    );
  }

  // 4. Dark mode surface ladder strictly increasing
  if (skinKey.endsWith(":dark")) {
    const lumPage = calculateLuminance(palette.page);
    const lumCard = calculateLuminance(palette.card);
    const lumElevated = calculateLuminance(palette.elevated);

    if (!(lumPage < lumCard && lumCard < lumElevated)) {
      violations.push(
        `${skinKey}: dark mode surface ladder violation: page (${lumPage.toFixed(4)}) < card (${lumCard.toFixed(4)}) < elevated (${lumElevated.toFixed(4)})`,
      );
    }
    if (palette.page === "#000000" || palette.page === "#000") {
      violations.push(`${skinKey}: page surface must not be pure #000000`);
    }
    if (palette.textPrimary.toLowerCase() === "#ffffff" || palette.textPrimary.toLowerCase() === "#fff") {
      violations.push(`${skinKey}: textPrimary must not be pure #ffffff in dark mode`);
    }
  }

  return violations;
}

describe("WCAG 2.1 AA Contrast Computation (Real CSS Parser - Task 2)", () => {
  const cssPath = path.resolve(process.cwd(), "src/index.css");
  const cssContent = fs.readFileSync(cssPath, "utf8");
  const palettes = loadPalettesFromCss(cssContent);

  it("parses all 4 skin/mode combinations from index.css with 100% required tokens", () => {
    expect(Object.keys(palettes)).toEqual([
      "graphite:dark",
      "graphite:light",
      "azure:dark",
      "azure:light",
    ]);
  });

  it("documents explicit decorative token exclusion for border-subtle", () => {
    expect(DECORATIVE_EXCLUSIONS).toHaveLength(1);
    expect(DECORATIVE_EXCLUSIONS[0].token).toBe("--border-subtle");
    expect(DECORATIVE_EXCLUSIONS[0].reason).toContain("decorative");
  });

  it("enforces UI boundary and focus borders >= 3.0:1 on page and card across all palettes", () => {
    for (const [key, palette] of Object.entries(palettes)) {
      const borders = [
        { name: "borderDefault", hex: palette.borderDefault },
        { name: "borderStrong", hex: palette.borderStrong },
        { name: "borderFocus", hex: palette.borderFocus },
      ];
      for (const border of borders) {
        const ratioPage = calculateContrastRatio(border.hex, palette.page);
        const ratioCard = calculateContrastRatio(border.hex, palette.card);
        expect(ratioPage, `${key} ${border.name} on page`).toBeGreaterThanOrEqual(3.0);
        expect(ratioCard, `${key} ${border.name} on card`).toBeGreaterThanOrEqual(3.0);
      }
    }
  });

  it("enforces accent contrast text on accent primary >= 4.5:1 across all palettes", () => {
    for (const [key, palette] of Object.entries(palettes)) {
      const ratio = calculateContrastRatio(palette.accentContrastText, palette.accentPrimary);
      expect(ratio, `${key} accent contrast`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("enforces strictly increasing surface ladder in dark mode (page < card < elevated)", () => {
    for (const darkKey of ["graphite:dark", "azure:dark"] as const) {
      const pal = palettes[darkKey];
      const lumPage = calculateLuminance(pal.page);
      const lumCard = calculateLuminance(pal.card);
      const lumElevated = calculateLuminance(pal.elevated);

      expect(lumPage, `${darkKey} page < card`).toBeLessThan(lumCard);
      expect(lumCard, `${darkKey} card < elevated`).toBeLessThan(lumElevated);
      expect(pal.page).not.toBe("#000000");
      expect(pal.textPrimary.toLowerCase()).not.toBe("#ffffff");
    }
  });

  it("enforces textPrimary, textSecondary, and textMuted >= 4.5:1 on ALL 6 surfaces across all palettes (Task 3 fix)", () => {
    for (const [key, palette] of Object.entries(palettes)) {
      const surfaces = [
        { name: "page", hex: palette.page },
        { name: "card", hex: palette.card },
        { name: "elevated", hex: palette.elevated },
        { name: "hover", hex: palette.hover },
        { name: "active", hex: palette.active },
        { name: "muted", hex: palette.muted },
      ];
      for (const surface of surfaces) {
        expect(
          calculateContrastRatio(palette.textPrimary, surface.hex),
          `${key} textPrimary on ${surface.name}`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          calculateContrastRatio(palette.textSecondary, surface.hex),
          `${key} textSecondary on ${surface.name}`,
        ).toBeGreaterThanOrEqual(4.5);
        expect(
          calculateContrastRatio(palette.textMuted, surface.hex),
          `${key} textMuted on ${surface.name}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("enforces zero contrast violations across all palettes using checkPaletteViolations", () => {
    for (const [key, palette] of Object.entries(palettes)) {
      const violations = checkPaletteViolations(key, palette);
      expect(violations, `${key} had contrast violations:\n${violations.join("\n")}`).toEqual([]);
    }
  });

  it("mutation self-check: reports violation when a token is mutated to a failing value", () => {
    const testPalette = { ...palettes["azure:dark"] };
    // Mutate textPrimary to match card background exactly (1:1 ratio)
    testPalette.textPrimary = testPalette.card;

    const violations = checkPaletteViolations("azure:dark", testPalette);
    expect(violations.length).toBeGreaterThan(0);
    expect(violations.some((v) => v.includes("textPrimary"))).toBe(true);
  });
});
