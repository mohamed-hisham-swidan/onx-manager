import { describe, it, expect } from "vitest";

interface DirEntry {
  name: string;
  isDirectory: () => boolean;
}

interface NodeFs {
  readdirSync: (path: string, options: { withFileTypes: true }) => DirEntry[];
  readFileSync: (path: string, encoding: "utf8") => string;
  existsSync: (path: string) => boolean;
}

interface NodePath {
  resolve: (...args: string[]) => string;
  relative: (from: string, to: string) => string;
  join: (...args: string[]) => string;
}

declare const require: (mod: string) => NodeFs & NodePath;
declare const process: { cwd: () => string };
const fs: NodeFs = require("node:fs");
const path: NodePath = require("node:path");

/**
 * Palette Ratchet Test (Phase 5)
 *
 * Enforces migration from hardcoded Tailwind color utilities (e.g. bg-blue-600,
 * text-gray-500) and raw hex color literals to semantic design tokens.
 *
 * All files not explicitly allowlisted MUST have 0 raw hex literals and 0 raw palette classes.
 * Allowlisted files have strictly capped maximum counts and must include a documented reason.
 */

interface AllowlistEntry {
  maxHex: number;
  maxPalette: number;
  reason: string;
}

// In Vitest (Node runtime), process.cwd() is the repository root or frontend directory
const SRC_ROOT = path.resolve(process.cwd().endsWith("frontend") ? "src" : "frontend/src");

// Explicit allowlist mapping relative paths to allowed bounds and justifications.
const ALLOWLIST: Record<string, AllowlistEntry> = {
  // Syntax highlighting & loader badges
  "components/CodeEditor.tsx": {
    maxHex: 0,
    maxPalette: 55,
    reason: "CodeEditor syntax highlighting token classes and gutter line numbers",
  },
  "components/ui/LoaderBadge.tsx": {
    maxHex: 0,
    maxPalette: 60,
    reason: "Vanilla loader badge style variants (teal, purple, sky) tested in LoaderBadge.test.tsx",
  },

  // Brand Assets & Visual Identity
  "components/brand/BrandLogo.tsx": {
    maxHex: 10,
    maxPalette: 0,
    reason: "Brand SVG gradient stops and fallback colors",
  },
  "components/brand/VoxelBanner.tsx": {
    maxHex: 15,
    maxPalette: 0,
    reason: "Voxel artwork geometric gradient stops",
  },

  // Preserved strictly for unit test class assertions
  "server_manager/components/PanelExposureSection.tsx": {
    maxHex: 0,
    maxPalette: 1,
    reason: "Preserved bg-red-600 for PanelExposureSection.test.tsx and ServerExposurePage.test.tsx button.bg-red-600 selector",
  },
  "server_manager/components/ServerConsole.tsx": {
    maxHex: 0,
    maxPalette: 4,
    reason: "Preserved 4 log severity classes (text-rose-400, text-amber-400, text-sky-300, text-gray-300) asserted in ServerConsole.test.tsx",
  },
  "server_manager/components/versioning/CommitTimeline.tsx": {
    maxHex: 0,
    maxPalette: 1,
    reason: "Preserved dark:bg-gray-800 for ServerVersioningPage.test.tsx assertions",
  },
  "server_manager/components/versioning/TestRunList.tsx": {
    maxHex: 0,
    maxPalette: 1,
    reason: "Preserved dark:bg-gray-800 for ServerVersioningPage.test.tsx assertions",
  },
  "server_manager/pages/ServerExposurePage.tsx": {
    maxHex: 0,
    maxPalette: 2,
    reason: "Preserved bg-red-600 hover:bg-red-700 for ServerExposurePage.test.tsx button.bg-red-600 selector",
  },

  // Data constants & mock fallbacks
  "server_manager/data/platforms.ts": {
    maxHex: 20,
    maxPalette: 0,
    reason: "Server platform official branding colors (Paper, Purpur, Forge, Fabric, etc.)",
  },
  "services/api.ts": {
    maxHex: 5,
    maxPalette: 0,
    reason: "Default mock API fallback palette data",
  },
};

function getAllSourceFiles(dir: string): string[] {
  let files: string[] = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files = files.concat(getAllSourceFiles(full));
    } else if (
      (entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")) &&
      !entry.name.endsWith(".test.ts") &&
      !entry.name.endsWith(".test.tsx") &&
      !entry.name.includes("paletteRatchet")
    ) {
      files.push(full);
    }
  }
  return files;
}

const HEX_COLOR_REGEX = /#[0-9a-fA-F]{3,8}\b/g;
const PALETTE_CLASS_REGEX =
  /\b(bg|text|border|ring|fill|stroke|outline|divide|from|via|to|shadow|accent|caret|decoration)-(gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-[0-9]{2,3}(?:\/[0-9]+)?\b/g;

describe("Phase 5: Palette Ratchet & Semantic Token Compliance", () => {
  const sourceFiles = getAllSourceFiles(SRC_ROOT);
  const allowlistCount = Object.keys(ALLOWLIST).length;

  it("finds source files to scan", () => {
    expect(sourceFiles.length).toBeGreaterThan(30);
  });

  it("requires every allowlist entry to have a non-empty justification reason", () => {
    for (const [filePath, entry] of Object.entries(ALLOWLIST)) {
      expect(entry.reason, `Missing justification for allowlist entry: ${filePath}`).toBeTruthy();
      expect(entry.reason.length).toBeGreaterThan(8);
    }
  });

  it(`ensures zero unallowlisted raw color classes; ${allowlistCount} allowlisted files with caps`, () => {
    const violations: { file: string; hexCount: number; paletteCount: number; sample: string[] }[] = [];

    for (const file of sourceFiles) {
      const rel = path.relative(SRC_ROOT, file).replace(/\\/g, "/");
      if (ALLOWLIST[rel]) continue;

      const content = fs.readFileSync(file, "utf8");
      const hexMatches = content.match(HEX_COLOR_REGEX) || [];
      const paletteMatches = content.match(PALETTE_CLASS_REGEX) || [];

      if (hexMatches.length > 0 || paletteMatches.length > 0) {
        violations.push({
          file: rel,
          hexCount: hexMatches.length,
          paletteCount: paletteMatches.length,
          sample: [...hexMatches.slice(0, 3), ...paletteMatches.slice(0, 3)],
        });
      }
    }

    expect(
      violations,
      `Found unallowlisted raw colors in files:\n${violations.map((v) => `  ${v.file}: ${v.hexCount} hex, ${v.paletteCount} palette (${v.sample.join(", ")})`).join("\n")}`
    ).toHaveLength(0);
  });

  it("ensures allowlisted files do not exceed their ratcheted upper bounds", () => {
    const regressions: { file: string; type: "hex" | "palette"; actual: number; max: number }[] = [];

    for (const [rel, entry] of Object.entries(ALLOWLIST)) {
      const full = path.join(SRC_ROOT, rel);
      if (!fs.existsSync(full)) continue;

      const content = fs.readFileSync(full, "utf8");
      const hexMatches = content.match(HEX_COLOR_REGEX) || [];
      const paletteMatches = content.match(PALETTE_CLASS_REGEX) || [];

      if (hexMatches.length > entry.maxHex) {
        regressions.push({ file: rel, type: "hex", actual: hexMatches.length, max: entry.maxHex });
      }
      if (paletteMatches.length > entry.maxPalette) {
        regressions.push({ file: rel, type: "palette", actual: paletteMatches.length, max: entry.maxPalette });
      }
    }

    expect(
      regressions,
      `Color ratchet regressions detected:\n${regressions.map((r) => `  ${r.file} exceeded ${r.type} limit: ${r.actual} > ${r.max}`).join("\n")}`
    ).toHaveLength(0);
  });

  it("verifies that core UI primitives and layouts are completely free of raw colors", () => {
    const coreDirs = ["components/ui", "layouts", "tokens"];
    for (const file of sourceFiles) {
      const rel = path.relative(SRC_ROOT, file).replace(/\\/g, "/");
      const isCore = coreDirs.some((dir) => rel.startsWith(dir));
      if (!isCore) continue;
      if (rel === "components/ui/LoaderBadge.tsx") continue; // Documented exception for vanilla test contract

      const content = fs.readFileSync(file, "utf8");
      const hex = content.match(HEX_COLOR_REGEX) || [];
      const pal = content.match(PALETTE_CLASS_REGEX) || [];

      expect(hex.length, `Core file ${rel} contains raw hex colors: ${hex.join(", ")}`).toBe(0);
      expect(pal.length, `Core file ${rel} contains raw palette classes: ${pal.join(", ")}`).toBe(0);
    }
  });
});
