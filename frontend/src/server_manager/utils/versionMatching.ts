import type { PluginVersionResponse } from "@/types";

export const LOADER_COMPATIBILITY: Record<string, string[]> = {
  purpur: ["purpur", "paper", "spigot", "bukkit"],
  paper: ["paper", "spigot", "bukkit"],
  spigot: ["spigot", "bukkit"],
  bukkit: ["bukkit"],
  folia: ["folia", "paper", "spigot", "bukkit"],
};

export function parseMc(version: string): [number, number, number] {
  const parts = version.trim().split(".");
  const nums: number[] = [];
  for (const p of parts) {
    const n = parseInt(p, 10);
    if (isNaN(n) || !/^\d+$/.test(p)) {
      break;
    }
    nums.push(n);
  }
  while (nums.length < 3) {
    nums.push(0);
  }
  return [nums[0], nums[1], nums[2]];
}

export function isSafeNumericVersion(segments: string[]): boolean {
  return (
    (segments.length === 2 || segments.length === 3) &&
    segments.every((seg) => /^\d+$/.test(seg))
  );
}

/**
 * Port of v1.3 _game_version_matches.
 * Two-part gate: numeric purity AND segment-count in {2, 3}.
 */
export function gameVersionMatches(serverVersion: string, listedVersion: string): boolean {
  const sTrim = serverVersion.trim();
  const lTrim = listedVersion.trim();
  const serverRawSegments = sTrim.split(".");
  const listedRawSegments = lTrim.split(".");

  if (
    !isSafeNumericVersion(serverRawSegments) ||
    !isSafeNumericVersion(listedRawSegments)
  ) {
    return sTrim === lTrim;
  }

  const serverParts = parseMc(serverVersion);
  const listedParts = parseMc(listedVersion);

  if (listedRawSegments.length === 2) {
    return serverParts[0] === listedParts[0] && serverParts[1] === listedParts[1];
  }

  return (
    serverParts[0] === listedParts[0] &&
    serverParts[1] === listedParts[1] &&
    serverParts[2] === listedParts[2]
  );
}

function parseVersionTokens(v: string): Array<number | string> {
  const cleaned = v.trim().replace(/^v/i, "");
  const parts = cleaned.split(/([.\-+_])/).filter((p) => p && !/^[.\-+_]$/.test(p));
  return parts.map((p) => (/^\d+$/.test(p) ? parseInt(p, 10) : p.toLowerCase()));
}

export function compareVersionNumbers(v1: string, v2: string): number {
  const t1 = parseVersionTokens(v1 || "");
  const t2 = parseVersionTokens(v2 || "");
  const maxLen = Math.max(t1.length, t2.length);

  for (let i = 0; i < maxLen; i++) {
    const a = t1[i];
    const b = t2[i];

    if (a === undefined) return -1;
    if (b === undefined) return 1;

    if (typeof a === "number" && typeof b === "number") {
      if (a !== b) return a - b;
    } else if (typeof a === "number" && typeof b === "string") {
      return 1;
    } else if (typeof a === "string" && typeof b === "number") {
      return -1;
    } else {
      const cmp = String(a).localeCompare(String(b));
      if (cmp !== 0) return cmp;
    }
  }
  return 0;
}

export function compareVersions(a: PluginVersionResponse, b: PluginVersionResponse): number {
  const vCmp = compareVersionNumbers(a.version_number || "", b.version_number || "");
  if (vCmp !== 0) return vCmp;
  const d1 = a.date_published || "";
  const d2 = b.date_published || "";
  return d1.localeCompare(d2);
}

export function selectRecommendedVersion(
  serverType: string,
  minecraftVersion: string,
  versions: PluginVersionResponse[],
): PluginVersionResponse | null {
  if (!versions || versions.length === 0) return null;

  const st = (serverType || "").trim().toLowerCase();
  const chain = LOADER_COMPATIBILITY[st] ?? (st ? [st] : []);
  const sv = (minecraftVersion || "").trim();

  function loaderMatches(v: PluginVersionResponse, loader: string): boolean {
    return v.loaders.map((l) => l.trim().toLowerCase()).includes(loader);
  }

  // 1. Candidates: versions matching game_versions
  const candidates = versions.filter((v) =>
    v.game_versions.some((gv) => gameVersionMatches(sv, gv)),
  );

  if (candidates.length > 0) {
    for (const loader of chain) {
      const group = candidates.filter((v) => loaderMatches(v, loader));
      if (group.length > 0) {
        return group.reduce((best, cur) => (compareVersions(cur, best) > 0 ? cur : best));
      }
    }
  }

  return null;
}
