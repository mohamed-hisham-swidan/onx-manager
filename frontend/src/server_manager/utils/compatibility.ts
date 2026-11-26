import type { IconName } from "@/components/ui/Icon";
import { getPlatformInfo } from "@/server_manager/data/platforms";

export function getLoaderDisplay(loader: string): { label: string; icon: IconName } {
  const info = getPlatformInfo(loader);
  return { label: info.label || loader, icon: info.icon };
}

export interface ParsedVersion {
  major: number;
  minor: number;
  patch: number;
  raw: string;
}

const EN_DASH = "\u2013";

export function parseGameVersion(version: string): ParsedVersion | null {
  const segments = version.trim().split(".");
  if (segments.length !== 2 && segments.length !== 3) return null;
  if (!segments.every((seg) => /^\d+$/.test(seg))) return null;
  const [major, minor, patchRaw] = segments;
  return {
    major: Number(major),
    minor: Number(minor),
    patch: patchRaw === undefined ? 0 : Number(patchRaw),
    raw: version.trim(),
  };
}

/**
 * Groups Modrinth game versions into accurate, contiguous pills:
 * - Only groups **actually contiguous** Minecraft release versions within the
 *   same `major.minor` line into ranges (e.g. `1.21.7–1.21.11`, `1.21.4–1.21.5`,
 *   `1.21–1.21.1`) so gaps are never falsely collapsed into `1.21.x` or `1.17–1.20`.
 * - Single isolated versions stay exact (e.g. `1.21.1`, `1.20.4`, `26.2`).
 * - Non-numeric versions (snapshots, pre-releases like `24w14potato`, `26.2-rc-1`)
 *   are kept raw after numeric pills, sorted descending.
 * - Order: numeric pills newest-first by highest covered version, then non-numeric descending.
 */
export function groupGameVersions(versions: string[]): string[] {
  const groups = new Map<string, Map<number, string>>();
  const nonNumericSet = new Set<string>();

  for (const v of versions) {
    const trimmed = v.trim();
    if (!trimmed) continue;
    const parsed = parseGameVersion(trimmed);
    if (!parsed) {
      nonNumericSet.add(trimmed);
      continue;
    }
    const key = `${parsed.major}.${parsed.minor}`;
    let group = groups.get(key);
    if (!group) {
      group = new Map();
      groups.set(key, group);
    }
    const existing = group.get(parsed.patch);
    // Prefer bare "1.21" over "1.21.0" if both appear
    if (existing === undefined || parsed.raw.length < existing.length) {
      group.set(parsed.patch, parsed.raw);
    }
  }

  interface VersionRun {
    major: number;
    minor: number;
    endPatch: number;
    display: string;
  }

  const runs: VersionRun[] = [];
  for (const [key, group] of groups) {
    const [major, minor] = key.split(".").map(Number);
    const patches = [...group.keys()].sort((a, b) => a - b);
    let startIdx = 0;
    while (startIdx < patches.length) {
      let endIdx = startIdx;
      while (
        endIdx + 1 < patches.length &&
        patches[endIdx + 1] === patches[endIdx] + 1
      ) {
        endIdx += 1;
      }
      const startPatch = patches[startIdx];
      const endPatch = patches[endIdx];
      const startLabel = group.get(startPatch)!;
      const endLabel = group.get(endPatch)!;
      runs.push({
        major,
        minor,
        endPatch,
        display: startIdx === endIdx ? startLabel : `${startLabel}${EN_DASH}${endLabel}`,
      });
      startIdx = endIdx + 1;
    }
  }

  runs.sort((a, b) => {
    if (a.major !== b.major) return b.major - a.major;
    if (a.minor !== b.minor) return b.minor - a.minor;
    return b.endPatch - a.endPatch;
  });

  const sortedNonNumeric = [...nonNumericSet].sort().reverse();
  return [...runs.map((r) => r.display), ...sortedNonNumeric];
}

/**
 * Returns unique official Minecraft release versions (strictly excluding snapshots,
 * pre-releases, release candidates, and week builds), sorted newest-first.
 */
export function sortReleaseVersionsDesc(versions: string[]): string[] {
  const seen = new Map<string, ParsedVersion>();
  for (const v of versions) {
    const parsed = parseGameVersion(v);
    if (!parsed) continue;
    const key = `${parsed.major}.${parsed.minor}.${parsed.patch}`;
    const existing = seen.get(key);
    if (!existing || parsed.raw.length < existing.raw.length) {
      seen.set(key, parsed);
    }
  }
  return [...seen.values()]
    .sort((a, b) => {
      if (a.major !== b.major) return b.major - a.major;
      if (a.minor !== b.minor) return b.minor - a.minor;
      return b.patch - a.patch;
    })
    .map((p) => p.raw);
}

export function isSnapshotOrPreRelease(version: string): boolean {
  return parseGameVersion(version) === null;
}

export function splitReleaseAndSnapshotVersions(versions: string[]): {
  releases: string[];
  snapshots: string[];
} {
  const releases: string[] = [];
  const snapshots: string[] = [];
  for (const v of versions) {
    const trimmed = v.trim();
    if (!trimmed) continue;
    if (isSnapshotOrPreRelease(trimmed)) {
      snapshots.push(trimmed);
    } else {
      releases.push(trimmed);
    }
  }
  return { releases, snapshots };
}

export function groupReleaseVersions(versions: string[]): {
  releasePills: string[];
  snapshots: string[];
} {
  const { releases, snapshots } = splitReleaseAndSnapshotVersions(versions);
  const releasePills = groupGameVersions(releases);
  const uniqueSnapshots = [...new Set(snapshots)].sort().reverse();
  return { releasePills, snapshots: uniqueSnapshots };
}

const POPULAR_MC_VERSIONS = new Set([
  "1.21.4",
  "1.21.1",
  "1.20.4",
  "1.20.1",
  "1.19.4",
  "1.19.2",
  "1.18.2",
  "1.17.1",
  "1.16.5",
  "1.12.2",
  "1.8.9",
]);

export function categorizeServerVersions(
  versions: string[],
  selected?: string,
): {
  mainVersions: string[];
  snapshotAndDropVersions: string[];
  allVersions: string[];
} {
  const latestByMinor = new Map<number, ParsedVersion>();

  for (const v of versions) {
    const parsed = parseGameVersion(v);
    if (!parsed || parsed.major !== 1) continue;
    const prev = latestByMinor.get(parsed.minor);
    if (!prev || parsed.patch > prev.patch) {
      latestByMinor.set(parsed.minor, parsed);
    }
  }

  const mainVersions: string[] = [];
  const snapshotAndDropVersions: string[] = [];

  for (const v of versions) {
    const parsed = parseGameVersion(v);
    if (!parsed || parsed.major >= 26) {
      snapshotAndDropVersions.push(v);
      continue;
    }
    if (parsed.major === 1) {
      const latestForMinor = latestByMinor.get(parsed.minor);
      const isLatest = latestForMinor?.raw === parsed.raw;
      if (isLatest || POPULAR_MC_VERSIONS.has(parsed.raw) || (selected && v === selected)) {
        mainVersions.push(v);
      }
    }
  }

  return {
    mainVersions,
    snapshotAndDropVersions,
    allVersions: versions,
  };
}

export function environmentLabels(clientSide?: string | null, serverSide?: string | null): string[] {
  const labels: string[] = [];
  if (clientSide === "required" || clientSide === "optional") labels.push("Client-side");
  if (serverSide === "required" || serverSide === "optional") labels.push("Server-side");
  if (labels.length === 2) return ["Client and server"];
  return labels.length ? labels : [];
}
