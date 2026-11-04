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
 * Task 4: Graphite True Neutrality Verification
 *
 * Enforces that all neutral tokens (surfaces, text, borders, hover, active, muted, terminal)
 * in BOTH graphite:dark and graphite:light have R=G=B (0% blue chroma, max(R,G,B) - min(R,G,B) == 0).
 */

export const GRAPHITE_COLORED_EXCLUSIONS = [
  "--text-accent",
  "--border-focus",
  "--accent-primary",
  "--accent-hover",
  "--accent-active",
  "--accent-contrast-text",
  "--status-success",
  "--status-warning",
  "--status-danger",
  "--status-info",
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

describe("Graphite True Neutrality (Task 4)", () => {
  const cssPath = path.resolve(process.cwd(), "src/index.css");
  const css = fs.readFileSync(cssPath, "utf8");

  const graphiteDarkTokens = parseBlockTokens(
    css,
    '\\[data-skin=["\']graphite["\']\\]\\s*,\\s*\\[data-skin=["\']graphite["\']\\]\\[data-mode=["\']dark["\']\\]\\s*,\\s*\\[data-skin=["\']graphite["\']\\]\\.dark',
  );

  const graphiteLightTokens = parseBlockTokens(
    css,
    '\\[data-skin=["\']graphite["\']\\]\\[data-mode=["\']light["\']\\]',
  );

  const excludedSet = new Set<string>(GRAPHITE_COLORED_EXCLUSIONS);

  it("enforces max(R,G,B) - min(R,G,B) === 0 for all neutral tokens in graphite:dark", () => {
    const neutralTokens = Object.entries(graphiteDarkTokens).filter(
      ([key, val]) => !excludedSet.has(key) && !val.startsWith("rgba"),
    );

    expect(neutralTokens.length).toBeGreaterThanOrEqual(14);

    for (const [key, val] of neutralTokens) {
      const [r, g, b] = parseHexRgb(val);
      const diff = Math.max(r, g, b) - Math.min(r, g, b);
      expect(
        diff,
        `Graphite dark neutral token ${key} (${val}) has blue chroma: R=${r}, G=${g}, B=${b} (diff=${diff})`,
      ).toBe(0);
    }
  });

  it("enforces max(R,G,B) - min(R,G,B) === 0 for all neutral tokens in graphite:light", () => {
    const neutralTokens = Object.entries(graphiteLightTokens).filter(
      ([key, val]) => !excludedSet.has(key) && !val.startsWith("rgba"),
    );

    expect(neutralTokens.length).toBeGreaterThanOrEqual(14);

    for (const [key, val] of neutralTokens) {
      const [r, g, b] = parseHexRgb(val);
      const diff = Math.max(r, g, b) - Math.min(r, g, b);
      expect(
        diff,
        `Graphite light neutral token ${key} (${val}) has blue chroma: R=${r}, G=${g}, B=${b} (diff=${diff})`,
      ).toBe(0);
    }
  });

  it("documents explicit list of excluded colored accent and status tokens", () => {
    expect(GRAPHITE_COLORED_EXCLUSIONS).toEqual([
      "--text-accent",
      "--border-focus",
      "--accent-primary",
      "--accent-hover",
      "--accent-active",
      "--accent-contrast-text",
      "--status-success",
      "--status-warning",
      "--status-danger",
      "--status-info",
    ]);
  });
});
