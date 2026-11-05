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

export interface SemanticViolation {
  file: string;
  line: number;
  class: string;
  unknownColor: string;
}

const SRC_ROOT = path.resolve(process.cwd().endsWith("frontend") ? "src" : "frontend/src");
const CSS_PATH = path.resolve(process.cwd().endsWith("frontend") ? "src/index.css" : "frontend/src/index.css");

export function parseDefinedThemeColors(cssText: string): { definedColors: Set<string>; familyRoots: string[] } {
  const themeMatch = cssText.match(/@theme\s*\{([^}]+)\}/);
  if (!themeMatch) {
    throw new Error("Failed to find @theme block in index.css");
  }

  const themeBlock = themeMatch[1];
  const colorMatches = themeBlock.matchAll(/--color-([a-zA-Z0-9_-]+)\s*:/g);
  const definedColors = new Set<string>();

  for (const match of colorMatches) {
    definedColors.add(match[1]);
  }

  const familyRoots = Array.from(
    new Set(
      Array.from(definedColors)
        .filter((c) => c.includes("-"))
        .map((c) => c.split("-")[0] + "-"),
    ),
  ).sort();

  return { definedColors, familyRoots };
}

export function buildSemanticClassRegex(familyRoots: string[]): RegExp {
  const prefixes = [
    "bg",
    "text",
    "border",
    "ring",
    "fill",
    "stroke",
    "divide",
    "outline",
    "shadow",
    "from",
    "via",
    "to",
    "accent",
    "caret",
    "decoration",
  ];
  const prefPattern = prefixes.join("|");
  const familyPattern = familyRoots.map((r) => r.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");

  return new RegExp(
    `(?:^|[\\s"\`({[])` +
      `(?:[a-zA-Z0-9_:-]+:)?` +
      `(${prefPattern})-` +
      `((?:${familyPattern})[a-zA-Z0-9_-]*)` +
      `(?:/[0-9.]+)?(?=[\\s"\`)}\\],;:]|$)`,
    "g",
  );
}

export function scanContentForSemanticOrphans(
  content: string,
  filename: string,
  definedColors: Set<string>,
  regex: RegExp,
): SemanticViolation[] {
  const violations: SemanticViolation[] = [];
  const lines = content.split("\n");

  for (let lno = 0; lno < lines.length; lno++) {
    const line = lines[lno];
    // Reset regex state per line
    regex.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(line)) !== null) {
      const prefix = match[1];
      const colorName = match[2];
      if (!definedColors.has(colorName)) {
        violations.push({
          file: filename,
          line: lno + 1,
          class: `${prefix}-${colorName}`,
          unknownColor: colorName,
        });
      }
    }
  }

  return violations;
}

function collectSourceFiles(dir: string): string[] {
  const results: string[] = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectSourceFiles(fullPath));
    } else if (
      (entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")) &&
      !entry.name.endsWith(".test.ts") &&
      !entry.name.endsWith(".test.tsx")
    ) {
      results.push(fullPath);
    }
  }

  return results;
}

describe("Token Class Existence Verification", () => {
  const css = fs.readFileSync(CSS_PATH, "utf8");
  const { definedColors, familyRoots } = parseDefinedThemeColors(css);
  const regex = buildSemanticClassRegex(familyRoots);

  it("extracts defined @theme colors and non-empty family roots", () => {
    expect(definedColors.size).toBeGreaterThanOrEqual(30);
    expect(familyRoots).toContain("surface-");
    expect(familyRoots).toContain("text-");
    expect(familyRoots).toContain("border-");
    expect(familyRoots).toContain("accent-");
    expect(familyRoots).toContain("status-");
    expect(familyRoots).toContain("terminal-");
  });

  it("does not false-positive on standard Tailwind built-ins", () => {
    const safeContent = `
      <div className="text-sm border-2 bg-transparent ring-2 font-mono divide-y outline-none" />
      <span className="text-xs text-center border-t border-solid fill-current" />
    `;
    const violations = scanContentForSemanticOrphans(safeContent, "SafeComponent.tsx", definedColors, regex);
    expect(violations).toEqual([]);
  });

  it("flags injected unknown semantic classes in mutation self-check", () => {
    const fakeContent = `
      <div className="bg-surface-unknown text-status-bogus border-accent-faketoken hover:bg-surface-missing" />
    `;
    const violations = scanContentForSemanticOrphans(fakeContent, "FakeComponent.tsx", definedColors, regex);
    expect(violations).toHaveLength(4);
    expect(violations.map((v) => v.class)).toEqual([
      "bg-surface-unknown",
      "text-status-bogus",
      "border-accent-faketoken",
      "bg-surface-missing",
    ]);
  });

  it("ensures zero un-defined semantic token classes are used across frontend/src", () => {
    const files = collectSourceFiles(SRC_ROOT);
    expect(files.length).toBeGreaterThan(0);

    const allViolations: SemanticViolation[] = [];

    for (const filePath of files) {
      const relPath = path.relative(SRC_ROOT, filePath);
      const content = fs.readFileSync(filePath, "utf8");
      const violations = scanContentForSemanticOrphans(content, relPath, definedColors, regex);
      allViolations.push(...violations);
    }

    if (allViolations.length > 0) {
      const formatted = allViolations
        .map((v) => `  ${v.file}:${v.line} -> "${v.class}" (unknown color: "${v.unknownColor}")`)
        .join("\n");
      expect.fail(`Found ${allViolations.length} orphan semantic token class(es):\n${formatted}`);
    }

    expect(allViolations).toEqual([]);
  });
});
