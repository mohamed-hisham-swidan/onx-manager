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
 * Strict allowlist of files permitted to contain `fixed inset-0` overlays.
 * Any other `.tsx` file in frontend/src containing `fixed inset-0` will fail this test,
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

describe("Overlay Ratchet Test (ADR-0021 & F5d-3)", () => {
  const allFiles = collectTsxFiles(SRC_ROOT);
  const foundOverlayFiles: { relPath: string; lineNumbers: number[] }[] = [];

  for (const file of allFiles) {
    const content = fs.readFileSync(file, "utf8");
    if (content.includes("fixed inset-0")) {
      const relPath = path.relative(SRC_ROOT, file).replace(/\\/g, "/");
      const lines = content.split("\n");
      const lineNumbers: number[] = [];
      lines.forEach((line, idx) => {
        if (line.includes("fixed inset-0")) {
          lineNumbers.push(idx + 1);
        }
      });
      foundOverlayFiles.push({ relPath, lineNumbers });
    }
  }

  it("detects all files using fixed inset-0 and asserts none exceed the allowed list", () => {
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
        `Allowlist entry ${allowedFile} no longer contains 'fixed inset-0'. Remove it from ALLOWED_OVERLAY_FILES to ratchet down!`,
      ).toBe(true);
    }
  });

  it("asserts exact count of allowlisted overlay files equals 4", () => {
    expect(foundOverlayFiles.length).toBe(4);
    expect(Object.keys(ALLOWED_OVERLAY_FILES).length).toBe(4);
  });
});
