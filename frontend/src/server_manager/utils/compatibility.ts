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
 * Groups Modrinth game versions into compact, Modrinth-style pills:
 * - a single version in a major.minor line → exact string ("26.2", "1.17.1")
 * - the line includes the bare base release ("1.18", "26.1") → "major.minor.x"
 * - a gap-free contiguous patch run → "1.16.3–1.16.5" range
 * - anything else (gaps, no base) → "major.minor.x"
 * Consecutive base-covered lines of the same major merge into a line range:
 * "1.17.x", "1.18.x", "1.19.x" → "1.17–1.19" (a partially-covered line such
 * as "1.20.x" from gaps is NOT merged, so ranges never overstate coverage).
 * Non-numeric versions (snapshots, pre-releases like "24w14potato",
 * "26.2-rc-1") are kept raw. Order: numeric lines newest-first, then
 * non-numeric strings descending.
 */
export function groupGameVersions(versions: string[]): string[] {
  const groups = new Map<string, Map<number, string>>();
  const nonNumeric: string[] = [];

  for (const v of versions) {
    const parsed = parseGameVersion(v);
    if (!parsed) {
      nonNumeric.push(v.trim());
      continue;
    }
    const key = `${parsed.major}.${parsed.minor}`;
    let group = groups.get(key);
    if (!group) {
      group = new Map();
      groups.set(key, group);
    }
    const existing = group.get(parsed.patch);
    if (existing === undefined || parsed.raw < existing) group.set(parsed.patch, parsed.raw);
  }

  interface GameLine {
    major: number;
    minor: number;
    kind: "exact" | "range" | "xb" | "xg";
    display: string;
  }

  const lines: GameLine[] = [];
  for (const [key, group] of groups) {
    const patches = [...group.keys()];
    const [major, minor] = key.split(".").map(Number);
    if (patches.length === 1) {
      lines.push({ major, minor, kind: "exact", display: group.get(patches[0])! });
    } else if (group.has(0)) {
      lines.push({ major, minor, kind: "xb", display: `${major}.${minor}.x` });
    } else {
      const min = Math.min(...patches);
      const max = Math.max(...patches);
      const contiguous = max - min + 1 === patches.length;
      lines.push(
        contiguous
          ? { major, minor, kind: "range", display: `${major}.${minor}.${min}${EN_DASH}${major}.${minor}.${max}` }
          : { major, minor, kind: "xg", display: `${major}.${minor}.x` },
      );
    }
  }

  lines.sort((a, b) => a.major - b.major || a.minor - b.minor);

  const pills: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const cur = lines[i];
    if (cur.kind !== "xb") {
      pills.push(cur.display);
      i += 1;
      continue;
    }
    let end = i;
    while (
      end + 1 < lines.length &&
      lines[end + 1].kind === "xb" &&
      lines[end + 1].major === cur.major &&
      lines[end + 1].minor === lines[end].minor + 1
    ) {
      end += 1;
    }
    if (end === i) {
      pills.push(cur.display);
    } else {
      pills.push(
        `${cur.major}.${cur.minor}${EN_DASH}${lines[end].major}.${lines[end].minor}`,
      );
    }
    i = end + 1;
  }

  pills.sort((a, b) => {
    const pa = parseGameVersion(a) ?? parseGameVersion(a.split(EN_DASH)[0]);
    const pb = parseGameVersion(b) ?? parseGameVersion(b.split(EN_DASH)[0]);
    if (pa && pb) {
      if (pa.major !== pb.major) return pb.major - pa.major;
      if (pa.minor !== pb.minor) return pb.minor - pa.minor;
      return pb.patch - pa.patch;
    }
    return b < a ? -1 : b > a ? 1 : 0;
  });

  const sortedNonNumeric = nonNumeric.sort().reverse();
  return [...pills, ...sortedNonNumeric];
}

export function environmentLabels(clientSide?: string | null, serverSide?: string | null): string[] {
  const labels: string[] = [];
  if (clientSide === "required" || clientSide === "optional") labels.push("Client-side");
  if (serverSide === "required" || serverSide === "optional") labels.push("Server-side");
  if (labels.length === 2) return ["Client and server"];
  return labels.length ? labels : [];
}
