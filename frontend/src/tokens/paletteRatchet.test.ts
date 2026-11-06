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
  // Legacy states and guards
  "components/CodeEditor.tsx": {
    maxHex: 0,
    maxPalette: 60,
    reason: "CodeEditor syntax highlighting token classes and gutter line numbers",
  },
  "components/ComingSoonState.tsx": {
    maxHex: 0,
    maxPalette: 20,
    reason: "Superseded legacy state component preserved for route compatibility",
  },
  "components/EmptyState.tsx": {
    maxHex: 0,
    maxPalette: 15,
    reason: "Superseded legacy empty state preserved for backwards compatibility",
  },
  "components/ErrorBoundary.tsx": {
    maxHex: 0,
    maxPalette: 10,
    reason: "Top-level error boundary fallback UI",
  },
  "components/ErrorState.tsx": {
    maxHex: 0,
    maxPalette: 10,
    reason: "Superseded legacy error state preserved for backwards compatibility",
  },
  "components/Skeleton.tsx": {
    maxHex: 0,
    maxPalette: 15,
    reason: "Superseded legacy skeleton loaders (CardSkeleton removed, ratcheted down from 25)",
  },
  "components/guards/SystemStatusGuard.tsx": {
    maxHex: 0,
    maxPalette: 25,
    reason: "System guard onboarding modal states",
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

  // Operations
  "operations/components/OperationDrawer.tsx": {
    maxHex: 0,
    maxPalette: 65,
    reason: "Operation status pill indicators and log viewer accents",
  },
  "operations/components/OperationFailure.tsx": {
    maxHex: 0,
    maxPalette: 20,
    reason: "Operation error card boundary",
  },
  "operations/components/OperationLogs.tsx": {
    maxHex: 0,
    maxPalette: 20,
    reason: "ANSI terminal log line styling",
  },
  "operations/components/OperationStepper.tsx": {
    maxHex: 0,
    maxPalette: 45,
    reason: "Multi-step saga progress stepper indicators",
  },

  // Auth & Onboarding
  "pages/InvitePage.tsx": {
    maxHex: 0,
    maxPalette: 100,
    reason: "Standalone invite acceptance flow",
  },
  "pages/RegisterPage.tsx": {
    maxHex: 0,
    maxPalette: 10,
    reason: "Amber invite-token advisory badge",
  },
  "pages/SetupPage.tsx": {
    maxHex: 0,
    maxPalette: 95,
    reason: "Initial deployment setup wizard",
  },

  // Server Manager Components & Modals
  "server_manager/components/AccessModeCard.tsx": {
    maxHex: 0,
    maxPalette: 110,
    reason: "Security access mode cards",
  },
  "server_manager/components/AccessSection.tsx": {
    maxHex: 0,
    maxPalette: 15,
    reason: "Access control tab user list",
  },
  "server_manager/components/AddCompanionTargetModal.tsx": {
    maxHex: 0,
    maxPalette: 80,
    reason: "Companion target modal",
  },
  "server_manager/components/BranchProtectionModal.tsx": {
    maxHex: 0,
    maxPalette: 100,
    reason: "Branch rule modal",
  },
  "server_manager/components/CommitDiffModal.tsx": {
    maxHex: 0,
    maxPalette: 165,
    reason: "Git commit diff viewer line coloring (ratcheted down from 190)",
  },
  "server_manager/components/CompatibilityCard.tsx": {
    maxHex: 0,
    maxPalette: 35,
    reason: "Java compatibility warning badges",
  },
  "server_manager/components/CrashReportViewerModal.tsx": {
    maxHex: 0,
    maxPalette: 90,
    reason: "Crash log stack trace viewer",
  },
  "server_manager/components/CreateBackupDialog.tsx": {
    maxHex: 0,
    maxPalette: 25,
    reason: "Create backup dialog modal",
  },
  "server_manager/components/CreateTagModal.tsx": {
    maxHex: 0,
    maxPalette: 50,
    reason: "Create version tag modal",
  },
  "server_manager/components/DashboardServerList.tsx": {
    maxHex: 0,
    maxPalette: 55,
    reason: "Dashboard server card status indicators",
  },
  "server_manager/components/EditPublicAddressModal.tsx": {
    maxHex: 0,
    maxPalette: 45,
    reason: "Address modal",
  },
  "server_manager/components/GlobalExposureActionsCard.tsx": {
    maxHex: 0,
    maxPalette: 90,
    reason: "Global network exposure card",
  },
  "server_manager/components/ImportReviewModal.tsx": {
    maxHex: 0,
    maxPalette: 125,
    reason: "Import archive review step",
  },
  "server_manager/components/InstallModal.tsx": {
    maxHex: 0,
    maxPalette: 100,
    reason: "Plugin/mod installation dialog",
  },
  "server_manager/components/InvitationsSection.tsx": {
    maxHex: 0,
    maxPalette: 150,
    reason: "User invitation management section",
  },
  "server_manager/components/ManageBranchesModal.tsx": {
    maxHex: 0,
    maxPalette: 95,
    reason: "Branch management modal (ratcheted down from 120)",
  },
  "server_manager/components/MaterializationBrowserModal.tsx": {
    maxHex: 0,
    maxPalette: 160,
    reason: "World materialization browser",
  },
  "server_manager/components/PanelExposureSection.tsx": {
    maxHex: 0,
    maxPalette: 250,
    reason: "Panel exposure tunnel controls",
  },
  "server_manager/components/PlayitClaimCard.tsx": {
    maxHex: 0,
    maxPalette: 85,
    reason: "Playit tunnel claim card",
  },
  "server_manager/components/ProjectCard.tsx": {
    maxHex: 0,
    maxPalette: 50,
    reason: "Marketplace project card",
  },
  "server_manager/components/ProjectVersionsList.tsx": {
    maxHex: 0,
    maxPalette: 40,
    reason: "Marketplace project version list",
  },
  "server_manager/components/ProvisioningProgress.tsx": {
    maxHex: 0,
    maxPalette: 25,
    reason: "Provisioning progress stepper",
  },
  "server_manager/components/RecentActivity.tsx": {
    maxHex: 0,
    maxPalette: 75,
    reason: "Recent audit activity timeline",
  },
  "server_manager/components/ServerConfigEditor.tsx": {
    maxHex: 0,
    maxPalette: 75,
    reason: "Server properties editor",
  },
  "server_manager/components/ServerConsole.tsx": {
    maxHex: 0,
    maxPalette: 95,
    reason: "Xterm console fallbacks and status tags",
  },
  "server_manager/components/ServerExposureMethodSelector.tsx": {
    maxHex: 0,
    maxPalette: 190,
    reason: "Exposure tunnel selector tabs",
  },
  "server_manager/components/ServerMetricsCharts.tsx": {
    maxHex: 5,
    maxPalette: 20,
    reason: "SVG metric stroke colors (CPU/RAM chart lines)",
  },
  "server_manager/components/ServerSettingsSection.tsx": {
    maxHex: 0,
    maxPalette: 275,
    reason: "Server configuration cards and property forms",
  },
  "server_manager/components/Sparkline.tsx": {
    maxHex: 2,
    maxPalette: 0,
    reason: "Sparkline SVG stroke color fallback",
  },
  "server_manager/components/StartingMonitorBanner.tsx": {
    maxHex: 0,
    maxPalette: 55,
    reason: "Slow startup warning banner status indicators (amber/sky variants)",
  },
  "server_manager/components/TargetCard.tsx": {
    maxHex: 0,
    maxPalette: 110,
    reason: "Deployment target card",
  },
  "server_manager/components/TargetListSection.tsx": {
    maxHex: 0,
    maxPalette: 25,
    reason: "Deployment targets list",
  },
  "server_manager/components/TestDefinitionsModal.tsx": {
    maxHex: 0,
    maxPalette: 105,
    reason: "Test definition configuration modal (ratcheted down from 130)",
  },
  "server_manager/components/TestEvidenceModal.tsx": {
    maxHex: 0,
    maxPalette: 75,
    reason: "Test evidence report modal",
  },
  "server_manager/components/TestRunModal.tsx": {
    maxHex: 0,
    maxPalette: 120,
    reason: "Test run progress modal",
  },
  "server_manager/components/VersionList.tsx": {
    maxHex: 0,
    maxPalette: 40,
    reason: "Platform version selector list",
  },
  "server_manager/components/versioning/CommitTimeline.tsx": {
    maxHex: 0,
    maxPalette: 5,
    reason: "Preserved dark:bg-gray-800 for ServerVersioningPage.test.tsx assertions",
  },
  "server_manager/components/versioning/TestRunList.tsx": {
    maxHex: 0,
    maxPalette: 5,
    reason: "Preserved dark:bg-gray-800 for ServerVersioningPage.test.tsx assertions",
  },
  "server_manager/data/platforms.ts": {
    maxHex: 20,
    maxPalette: 0,
    reason: "Server platform official branding colors (Paper, Purpur, Forge, Fabric, etc.)",
  },
  "server_manager/pages/ApiKeysPage.tsx": {
    maxHex: 0,
    maxPalette: 85,
    reason: "API key management page",
  },
  "server_manager/pages/BackupListPage.tsx": {
    maxHex: 0,
    maxPalette: 95,
    reason: "Server backups management page",
  },
  "server_manager/pages/ImportServerPage.tsx": {
    maxHex: 0,
    maxPalette: 190,
    reason: "Zip / folder server import wizard",
  },
  "server_manager/pages/PluginDetailPage.tsx": {
    maxHex: 0,
    maxPalette: 155,
    reason: "Plugin markdown details view",
  },
  "server_manager/pages/PluginMarketplacePage.tsx": {
    maxHex: 0,
    maxPalette: 45,
    reason: "Marketplace search grid (ratcheted down from 70)",
  },
  "server_manager/pages/ServerActivityPage.tsx": {
    maxHex: 0,
    maxPalette: 175,
    reason: "Server activity audit logs page",
  },
  "server_manager/pages/ServerDetailPage.tsx": {
    maxHex: 6,
    maxPalette: 145,
    reason: "Server detail quick action cards and sparklines (ratcheted down from 175)",
  },
  "server_manager/pages/ServerExposurePage.tsx": {
    maxHex: 0,
    maxPalette: 60,
    reason: "Server network exposure page",
  },
  "server_manager/pages/ServerModsPage.tsx": {
    maxHex: 0,
    maxPalette: 25,
    reason: "Server mods page loader and status chips (orange/sky variants)",
  },
  "server_manager/pages/SettingsPage.tsx": {
    maxHex: 0,
    maxPalette: 30,
    reason: "Settings page restart and status notice chips",
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
