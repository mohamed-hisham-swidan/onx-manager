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

const SRC_ROOT = path.resolve(process.cwd().endsWith("frontend") ? "src" : "frontend/src");

/**
 * Strict allowlist of files permitted to contain full-screen overlay positioning classes.
 * Any other `.tsx` file in frontend/src containing overlay classes will fail this test,
 * ensuring zero unmanaged/bypassing modal dialogs or raw backdrop overlays.
 */
export const ALLOWED_OVERLAY_FILES: Record<string, { reason: string }> = {
  "components/ui/Modal.tsx": {
    reason: "Canonical modal dialog primitive with focus trap, Escape handler, and scroll locking",
  },
  "components/ui/ConfirmDialog.tsx": {
    reason: "Canonical confirmation dialog primitive with focus trap and action styling",
  },
  "components/layout/Sidebar.tsx": {
    reason: "Mobile navigation drawer backdrop overlay",
  },
  "components/brand/SplashScreen.tsx": {
    reason: "Full-page application boot splash overlay",
  },
};

/**
 * Detects whether a class-list string contains full-screen overlay positioning tokens.
 *
 * Order-independent: flags if `fixed` is present along with either `inset-0`,
 * both `inset-x-0` and `inset-y-0`, or all four edge utilities (`top-0`, `bottom-0`, `left-0`, `right-0`).
 * Does NOT flag `absolute inset-0` or unpositioned utilities.
 *
 * Limitation: Classes split across separate `clsx` arguments or dynamic expressions
 * (e.g., `clsx("fixed", "inset-0")`) are not detected.
 */
export function isOverlayClassList(classList: string): boolean {
  const tokens = new Set(classList.trim().split(/\s+/));
  if (!tokens.has("fixed")) {
    return false;
  }
  const hasFullInset = tokens.has("inset-0");
  const hasAxisInsets = tokens.has("inset-x-0") && tokens.has("inset-y-0");
  const hasFourEdges =
    tokens.has("top-0") &&
    tokens.has("bottom-0") &&
    tokens.has("left-0") &&
    tokens.has("right-0");
  return hasFullInset || hasAxisInsets || hasFourEdges;
}

/**
 * Scans file content for any string literals, template literals, or attribute values
 * that match full-screen overlay class patterns.
 */
export function findOverlayViolations(content: string): number[] {
  const lineNumbers = new Set<number>();
  const stringRegex = /(["'`])((?:\\.|(?!\1)[^\\])*)\1/g;
  let match: RegExpExecArray | null;

  while ((match = stringRegex.exec(content)) !== null) {
    const rawString = match[2];
    if (isOverlayClassList(rawString)) {
      const offset = match.index;
      const lineNumber = content.substring(0, offset).split("\n").length;
      lineNumbers.add(lineNumber);
    }
  }

  return Array.from(lineNumbers).sort((a, b) => a - b);
}

function collectTsxFiles(dir: string): string[] {
  const results: string[] = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectTsxFiles(fullPath));
    } else if (
      entry.name.endsWith(".tsx") &&
      !entry.name.endsWith(".test.tsx")
    ) {
      results.push(fullPath);
    }
  }

  return results;
}

describe("isOverlayClassList detector", () => {
  it("flags positive overlay class combinations", () => {
    expect(isOverlayClassList("fixed inset-0")).toBe(true);
    expect(isOverlayClassList("inset-0 fixed")).toBe(true);
    expect(isOverlayClassList("fixed inset-x-0 inset-y-0")).toBe(true);
    expect(isOverlayClassList("fixed top-0 left-0 right-0 bottom-0")).toBe(true);
    expect(isOverlayClassList("p-4 fixed bg-black inset-0 z-50")).toBe(true);
  });

  it("does not flag negative or non-overlay class combinations", () => {
    expect(isOverlayClassList("absolute inset-0")).toBe(false);
    expect(isOverlayClassList("fixed top-0")).toBe(false);
    expect(isOverlayClassList("relative inset-0")).toBe(false);
    expect(isOverlayClassList("inset-0")).toBe(false);
  });
});

describe("Overlay Ratchet Test (ADR-0021 & F5d-3)", () => {
  const allFiles = collectTsxFiles(SRC_ROOT);
  const foundOverlayFiles: { relPath: string; lineNumbers: number[] }[] = [];

  for (const file of allFiles) {
    const content = fs.readFileSync(file, "utf8");
    const lineNumbers = findOverlayViolations(content);
    if (lineNumbers.length > 0) {
      const relPath = path.relative(SRC_ROOT, file).replace(/\\/g, "/");
      foundOverlayFiles.push({ relPath, lineNumbers });
    }
  }

  it("detects all files using overlay classes and asserts none exceed the allowed list", () => {
    const violations = foundOverlayFiles.filter(
      (item) => !(item.relPath in ALLOWED_OVERLAY_FILES),
    );

    expect(
      violations,
      `Bypassing raw overlay markup found in non-allowlisted files: ${violations
        .map((v) => `${v.relPath} (lines: ${v.lineNumbers.join(", ")})`)
        .join("; ")}. Migrate all dialogs/overlays to Modal or ConfirmDialog.`,
    ).toEqual([]);
  });

  it("asserts no stale entries exist in the allowlist", () => {
    const foundSet = new Set(foundOverlayFiles.map((f) => f.relPath));

    for (const allowedFile of Object.keys(ALLOWED_OVERLAY_FILES)) {
      const fullPath = path.join(SRC_ROOT, allowedFile);
      expect(
        fs.existsSync(fullPath),
        `Allowlisted file ${allowedFile} does not exist in src/`,
      ).toBe(true);

      expect(
        foundSet.has(allowedFile),
        `Allowlist entry ${allowedFile} no longer contains overlay classes. Remove it from ALLOWED_OVERLAY_FILES to ratchet down!`,
      ).toBe(true);
    }
  });

  it("asserts exact count of allowlisted overlay files equals 4", () => {
    expect(foundOverlayFiles.length).toBe(4);
    expect(Object.keys(ALLOWED_OVERLAY_FILES).length).toBe(4);
  });
});
