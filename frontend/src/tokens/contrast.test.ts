import { describe, it, expect } from "vitest";

/**
 * WCAG AA Contrast Ratio Computation Test (Phase 6)
 *
 * Programmatically computes relative luminance according to the W3C WCAG 2.1 specifications:
 *   L = 0.2126 * R_lin + 0.7152 * G_lin + 0.0722 * B_lin
 * Contrast Ratio = (L_lighter + 0.05) / (L_darker + 0.05)
 *
 * Requirements:
 * - Text contrast >= 4.5:1 (WCAG AA normal text)
 * - Non-text UI boundaries & focus rings >= 3.0:1 (WCAG AA non-text contrast)
 */

export function sRGBtoLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function parseHexToRgb(hex: string): [number, number, number] {
  let clean = hex.replace("#", "").trim();
  if (clean.length === 3) {
    clean = clean.split("").map((c) => c + c).join("");
  }
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
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
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  borderDefault: string;
  borderFocus: string;
  accentPrimary: string;
  accentText: string;
  statusSuccess: string;
  statusWarning: string;
  statusDanger: string;
}

export const SKIN_PALETTES: Record<string, SkinPalette> = {
  "graphite:dark": {
    page: "#141518",
    card: "#1a1b1f",
    elevated: "#22242a",
    textPrimary: "#f0f2f5",
    textSecondary: "#b8bcc6",
    textMuted: "#989ea9",
    borderDefault: "#626773",
    borderFocus: "#60a5fa",
    accentPrimary: "#2563eb",
    accentText: "#ffffff",
    statusSuccess: "#22c55e",
    statusWarning: "#eab308",
    statusDanger: "#ef4444",
  },
  "graphite:light": {
    page: "#f3f4f6",
    card: "#ffffff",
    elevated: "#ffffff",
    textPrimary: "#111827",
    textSecondary: "#374151",
    textMuted: "#6b7280",
    borderDefault: "#737a85",
    borderFocus: "#2563eb",
    accentPrimary: "#2563eb",
    accentText: "#ffffff",
    statusSuccess: "#15803d",
    statusWarning: "#b45309",
    statusDanger: "#b91c1c",
  },
  "azure:dark": {
    page: "#0b1222",
    card: "#0f172a",
    elevated: "#1e293b",
    textPrimary: "#f8fafc",
    textSecondary: "#cbd5e1",
    textMuted: "#94a3b8",
    borderDefault: "#606b7d",
    borderFocus: "#38bdf8",
    accentPrimary: "#0369a1",
    accentText: "#ffffff",
    statusSuccess: "#22c55e",
    statusWarning: "#eab308",
    statusDanger: "#ef4444",
  },
  "azure:light": {
    page: "#f0f7ff",
    card: "#ffffff",
    elevated: "#ffffff",
    textPrimary: "#0f172a",
    textSecondary: "#334155",
    textMuted: "#64748b",
    borderDefault: "#6b7c93",
    borderFocus: "#0284c7",
    accentPrimary: "#0369a1",
    accentText: "#ffffff",
    statusSuccess: "#15803d",
    statusWarning: "#b45309",
    statusDanger: "#b91c1c",
  },
};

describe("WCAG AA Contrast Computation (Phase 6)", () => {
  const pairs = Object.entries(SKIN_PALETTES);

  it("has defined palettes for graphite and azure in both dark and light modes", () => {
    expect(pairs).toHaveLength(4);
  });

  for (const [skinKey, palette] of pairs) {
    describe(`Skin: ${skinKey}`, () => {
      it("meets WCAG AA (>= 4.5:1) for primary text on card surface", () => {
        const ratio = calculateContrastRatio(palette.textPrimary, palette.card);
        expect(ratio, `${skinKey} textPrimary vs card ratio was ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
      });

      it("meets WCAG AA (>= 4.5:1) for primary text on page background", () => {
        const ratio = calculateContrastRatio(palette.textPrimary, palette.page);
        expect(ratio, `${skinKey} textPrimary vs page ratio was ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
      });

      it("meets WCAG AA (>= 4.5:1) for secondary text on card surface", () => {
        const ratio = calculateContrastRatio(palette.textSecondary, palette.card);
        expect(ratio, `${skinKey} textSecondary vs card ratio was ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
      });

      it("meets WCAG AA (>= 4.5:1) for muted text on card surface", () => {
        const ratio = calculateContrastRatio(palette.textMuted, palette.card);
        expect(ratio, `${skinKey} textMuted vs card ratio was ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
      });

      it("meets WCAG AA (>= 3.0:1) for UI boundary input/panel border on card surface", () => {
        const ratio = calculateContrastRatio(palette.borderDefault, palette.card);
        expect(ratio, `${skinKey} borderDefault vs card ratio was ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(3.0);
      });

      it("meets WCAG AA (>= 3.0:1) for focus rings on card surface", () => {
        const ratio = calculateContrastRatio(palette.borderFocus, palette.card);
        expect(ratio, `${skinKey} borderFocus vs card ratio was ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(3.0);
      });

      it("meets WCAG AA (>= 4.5:1) for accent button text on primary accent background", () => {
        const ratio = calculateContrastRatio(palette.accentText, palette.accentPrimary);
        expect(ratio, `${skinKey} accentText vs accentPrimary ratio was ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
      });

      it("respects surface ladder hierarchy (canvas < card < elevated in dark mode)", () => {
        if (skinKey.endsWith(":dark")) {
          const lumPage = calculateLuminance(palette.page);
          const lumCard = calculateLuminance(palette.card);
          const lumElevated = calculateLuminance(palette.elevated);

          expect(lumPage, "Page canvas should be darker than or equal to card").toBeLessThanOrEqual(lumCard);
          expect(lumCard, "Card surface should be darker than elevated").toBeLessThan(lumElevated);
          expect(palette.page, "Dark canvas must not be pure #000000").not.toBe("#000000");
          expect(palette.textPrimary, "Text must not be harsh pure #ffffff in graphite").not.toBe("#ffffff");
        }
      });
    });
  }
});
