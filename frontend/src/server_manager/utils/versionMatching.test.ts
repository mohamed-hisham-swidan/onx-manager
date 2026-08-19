import { describe, it, expect } from "vitest";
import {
  gameVersionMatches,
  compareVersionNumbers,
  selectRecommendedVersion,
} from "./versionMatching";
import type { PluginVersionResponse } from "@/types";

function makeVer(
  versionNumber: string,
  opts?: {
    gameVersions?: string[];
    loaders?: string[];
    datePublished?: string;
  },
): PluginVersionResponse {
  return {
    version_id: `v-${versionNumber}`,
    project_id: "p-1",
    name: versionNumber,
    version_number: versionNumber,
    game_versions: opts?.gameVersions ?? ["1.21"],
    loaders: opts?.loaders ?? ["paper"],
    files: [],
    dependencies: [],
    date_published: opts?.datePublished ?? "2024-01-01T00:00:00Z",
  };
}

describe("versionMatching - gameVersionMatches", () => {
  // 13 test cases matching backend v1.3 two-part gate exactly
  it("handles prefix collision prevention", () => {
    expect(gameVersionMatches("1.21.11", "1.21.1")).toBe(false);
    expect(gameVersionMatches("1.21.4", "1.21.40")).toBe(false);
    expect(gameVersionMatches("1.21.11", "1.21")).toBe(true);
    expect(gameVersionMatches("1.21.11", "1.21.11")).toBe(true);
    expect(gameVersionMatches("1.21.1", "1.21.11")).toBe(false);
  });

  it("handles suffixed and snapshot versions", () => {
    expect(gameVersionMatches("1.21.11", "1.21.11-rc3")).toBe(false);
    expect(gameVersionMatches("1.21.11-rc3", "1.21.11-rc3")).toBe(true);
    expect(gameVersionMatches("26.3", "26.3-snapshot-9")).toBe(false);
    expect(gameVersionMatches("18w50a", "18w50a")).toBe(true);
  });

  it("handles segment count overflow and edge cases", () => {
    expect(gameVersionMatches("1.21.11.2", "1.21.11.9")).toBe(false);
    expect(gameVersionMatches("1.21.11.2", "1.21.11.2")).toBe(true);
    expect(gameVersionMatches("1..21", "1.21")).toBe(false);
    expect(gameVersionMatches("", "")).toBe(true);
  });
});

describe("versionMatching - compareVersionNumbers", () => {
  it("correctly compares semver numbers", () => {
    expect(compareVersionNumbers("1.10", "1.9")).toBeGreaterThan(0);
    expect(compareVersionNumbers("1.9", "1.10")).toBeLessThan(0);
    expect(compareVersionNumbers("2.0.0", "1.9.9")).toBeGreaterThan(0);
    expect(compareVersionNumbers("1.2.3", "1.2.3")).toBe(0);
  });
});

describe("versionMatching - selectRecommendedVersion", () => {
  it("selects exact match on exact loader", () => {
    const versions = [
      makeVer("1.0.0", { gameVersions: ["1.20"], loaders: ["paper"] }),
      makeVer("2.0.0", { gameVersions: ["1.21"], loaders: ["paper"] }),
    ];
    const rec = selectRecommendedVersion("paper", "1.21", versions);
    expect(rec?.version_number).toBe("2.0.0");
  });

  it("falls back to parent loader in chain (purpur -> paper)", () => {
    const versions = [
      makeVer("2.0.0", { gameVersions: ["1.21"], loaders: ["paper"] }),
    ];
    const rec = selectRecommendedVersion("purpur", "1.21", versions);
    expect(rec?.version_number).toBe("2.0.0");
  });

  it("returns null when no loader matches", () => {
    const versions = [
      makeVer("1.0.0", { gameVersions: ["1.21"], loaders: ["fabric"] }),
    ];
    const rec = selectRecommendedVersion("paper", "1.21", versions);
    expect(rec).toBeNull();
  });

  it("returns null when game version mismatches even on compatible loader", () => {
    const versions = [
      makeVer("1.0.0", { gameVersions: ["1.19"], loaders: ["paper"] }),
    ];
    const rec = selectRecommendedVersion("paper", "1.21", versions);
    expect(rec).toBeNull();
  });

  it("returns null when no game version matches despite closest-published fallback candidate", () => {
    const versions = [
      makeVer("1.0.0", { gameVersions: ["1.20.2"], loaders: ["paper"] }),
      makeVer("1.1.0", { gameVersions: ["1.20"], loaders: ["paper"] }),
    ];
    const rec = selectRecommendedVersion("paper", "1.21", versions);
    expect(rec).toBeNull();
  });

  it("breaks tie with semver version number first, then date published", () => {
    const versions = [
      makeVer("1.2", { gameVersions: ["1.21"], loaders: ["paper"], datePublished: "2024-06-01T00:00:00Z" }),
      makeVer("1.9", { gameVersions: ["1.21"], loaders: ["paper"], datePublished: "2024-01-01T00:00:00Z" }),
      makeVer("1.10", { gameVersions: ["1.21"], loaders: ["paper"], datePublished: "2020-01-01T00:00:00Z" }),
    ];
    const rec = selectRecommendedVersion("paper", "1.21", versions);
    expect(rec?.version_number).toBe("1.10");
  });
});
