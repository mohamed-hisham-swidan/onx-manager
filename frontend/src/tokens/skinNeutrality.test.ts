import { describe, it, expect } from "vitest";

interface NodeFs {
  readFileSync: (path: string, encoding: "utf8") => string;
}

interface NodePath {
  resolve: (...args: string[]) => string;
}

declare const require: (mod: string) => NodeFs & NodePath;
declare const process: { cwd: () => string };
const fs: NodeFs = require("node:fs");
const path: NodePath = require("node:path");

/**
 * Skin Neutrality Verification for Crimson and Emerald
 *
 * Enforces that surfaces in Crimson and Emerald skins remain near-neutral
 * (chroma <= 16) in both dark and light modes, and accent-primary has a moderate
 * saturation (HSL saturation < 0.55).
 */

export const SURFACE_TOKENS = [
  "--surface-page",
  "--surface-card",
  "--surface-hover",
  "--surface-active",
  "--surface-elevated",
  "--surface-muted",
] as const;

function parseBlockTokens(cssText: string, selectorPattern: string): Record<string, string> {
  const regex = new RegExp(selectorPattern + "\\s*\\{([^}]+)\\}", "m");
  const match = cssText.match(regex);
  if (!match) {
    throw new Error(`Failed to find CSS block matching: ${selectorPattern}`);
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

function parseHexRgb(hex: string): [number, number, number] {
  let clean = hex.replace("#", "").trim();
  if (clean.length === 3) {
    clean = clean.split("").map((c) => c + c).join("");
  }
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  return [r, g, b];
}

export function calculateHslSaturation(hex: string): number {
  const [r255, g255, b255] = parseHexRgb(hex);
  const r = r255 / 255;
  const g = g255 / 255;
  const b = b255 / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta === 0) return 0;
  const l = (max + min) / 2;
  return l > 0.5 ? delta / (2 - 2 * l) : delta / (2 * l);
}

describe("Skin Neutrality (Crimson and Emerald)", () => {
  const cssPath = path.resolve(
    process.cwd().endsWith("frontend") ? "src/index.css" : "frontend/src/index.css",
  );
  const css = fs.readFileSync(cssPath, "utf8");

  const palettes = {
    "crimson:dark": parseBlockTokens(
      css,
      '\\[data-skin=["\']crimson["\']\\]\\s*,\\s*\\[data-skin=["\']crimson["\']\\]\\[data-mode=["\']dark["\']\\]\\s*,\\s*\\[data-skin=["\']crimson["\']\\]\\.dark',
    ),
    "crimson:light": parseBlockTokens(
      css,
      '\\[data-skin=["\']crimson["\']\\]\\[data-mode=["\']light["\']\\]',
    ),
    "emerald:dark": parseBlockTokens(
      css,
      '\\[data-skin=["\']emerald["\']\\]\\s*,\\s*\\[data-skin=["\']emerald["\']\\]\\[data-mode=["\']dark["\']\\]\\s*,\\s*\\[data-skin=["\']emerald["\']\\]\\.dark',
    ),
    "emerald:light": parseBlockTokens(
      css,
      '\\[data-skin=["\']emerald["\']\\]\\[data-mode=["\']light["\']\\]',
    ),
  };

  const skinEntries = Object.entries(palettes) as [keyof typeof palettes, Record<string, string>][];

  for (const [skinMode, tokens] of skinEntries) {
    describe(`${skinMode} neutrality and saturation constraints`, () => {
      it(`enforces surface chroma <= 16 for all 6 surfaces in ${skinMode}`, () => {
        for (const token of SURFACE_TOKENS) {
          const val = tokens[token];
          expect(val, `Missing token ${token} in ${skinMode}`).toBeDefined();
          const [r, g, b] = parseHexRgb(val);
          const chroma = Math.max(r, g, b) - Math.min(r, g, b);
          expect(
            chroma,
            `Surface token ${token} (${val}) in ${skinMode} exceeds max neutral chroma (16): R=${r}, G=${g}, B=${b} (chroma=${chroma})`,
          ).toBeLessThanOrEqual(16);
        }
      });

      it(`enforces accent-primary HSL saturation < 0.55 in ${skinMode}`, () => {
        const accent = tokens["--accent-primary"];
        expect(accent, `Missing --accent-primary in ${skinMode}`).toBeDefined();
        const sat = calculateHslSaturation(accent);
        expect(
          sat,
          `--accent-primary (${accent}) in ${skinMode} exceeds saturation limit (0.55): saturation=${sat.toFixed(4)}`,
        ).toBeLessThan(0.55);
      });
    });
  }
});
