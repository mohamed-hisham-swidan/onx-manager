import type { PluginVersionResponse } from "@/types";

export const LOADER_COMPATIBILITY: Record<string, string[]> = {
  purpur: ["purpur", "paper", "spigot", "bukkit"],
  paper: ["paper", "spigot", "bukkit"],
  spigot: ["spigot", "bukkit"],
  bukkit: ["bukkit"],
  folia: ["folia"],
  waterfall: ["waterfall", "bungeecord"],
  bungeecord: ["bungeecord"],
  velocity: ["velocity"],
  minestom: ["minestom"],
  quilt: ["quilt", "fabric"],
  fabric: ["fabric"],
  forge: ["forge"],
  neoforge: ["neoforge"],
};

const LOADER_TIERS: Record<string, string[][]> = {
  purpur: [["purpur", "paper"], ["spigot"], ["bukkit"]],
  paper: [["paper"], ["spigot"], ["bukkit"]],
  spigot: [["spigot"], ["bukkit"]],
  bukkit: [["bukkit"]],
  folia: [["folia"]],
  waterfall: [["waterfall"], ["bungeecord"]],
  bungeecord: [["bungeecord"]],
  velocity: [["velocity"]],
  minestom: [["minestom"]],
  quilt: [["quilt", "fabric"]],
  fabric: [["fabric"]],
  forge: [["forge"]],
  neoforge: [["neoforge"]],
};

const VERSION_TYPE_RANK: Record<string, number> = {
  release: 2,
  beta: 1,
  alpha: 0,
};

const LOADER_PREFIX_RE =
  /^(?:(?:purpur|paper|spigot|bukkit|folia|fabric|quilt|forge|neoforge|velocity|bungeecord|bungee|waterfall|minestom)[-_+ ]+)+/i;
const PRERELEASE_RE = /(?:^|[-._+])(alpha|beta|rc|dev|snapshot|pre|canary)(?:[-._+\d]|$)/i;

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
  const stripped = v.trim().replace(LOADER_PREFIX_RE, "").replace(/^v(?=\d)/i, "");
  const core = stripped.split("+")[0] ?? stripped;
  const parts = core.split(/([.\-_])/).filter((p) => p && !/^[.\-_]$/.test(p));
  return parts.map((p) => (/^\d+$/.test(p) ? parseInt(p, 10) : p.toLowerCase()));
}

export function compareVersionNumbers(v1: string, v2: string): number {
  const t1 = parseVersionTokens(v1 || "");
  const t2 = parseVersionTokens(v2 || "");
  const maxLen = Math.max(t1.length, t2.length);

  for (let i = 0; i < maxLen; i++) {
    const a = t1[i];
    const b = t2[i];

    if (a === undefined) {
      // Final release ("1.0.0") strictly beats prerelease ("1.0.0-alpha")
      return typeof b === "string" ? 1 : -1;
    }
    if (b === undefined) {
      return typeof a === "string" ? -1 : 1;
    }

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

function effectiveVersionTypeRank(v: PluginVersionResponse): number {
  const raw = (v.version_type || "").trim().toLowerCase();
  if (raw in VERSION_TYPE_RANK) {
    const base = VERSION_TYPE_RANK[raw];
    if (base === 2 && PRERELEASE_RE.test(v.version_number || "")) {
      return 1;
    }
    return base;
  }
  return PRERELEASE_RE.test(v.version_number || "") ? 1 : 2;
}

export function compareVersions(
  a: PluginVersionResponse,
  b: PluginVersionResponse,
  serverType = "",
): number {
  const vtDiff = effectiveVersionTypeRank(a) - effectiveVersionTypeRank(b);
  if (vtDiff !== 0) return vtDiff;
  const vCmp = compareVersionNumbers(a.version_number || "", b.version_number || "");
  if (vCmp !== 0) return vCmp;
  const d1 = a.date_published || "";
  const d2 = b.date_published || "";
  if (d1 !== d2) return d1.localeCompare(d2);
  if (serverType) {
    const st = serverType.trim().toLowerCase();
    const aExact = a.loaders.map((l) => l.trim().toLowerCase()).includes(st) ? 1 : 0;
    const bExact = b.loaders.map((l) => l.trim().toLowerCase()).includes(st) ? 1 : 0;
    return aExact - bExact;
  }
  return 0;
}

export function selectRecommendedVersion(
  serverType: string,
  minecraftVersion: string,
  versions: PluginVersionResponse[],
): PluginVersionResponse | null {
  if (!versions || versions.length === 0) return null;

  const st = (serverType || "").trim().toLowerCase();
  const tiers = LOADER_TIERS[st] ?? (st ? [[st]] : []);
  const sv = (minecraftVersion || "").trim();

  function loaderMatches(v: PluginVersionResponse, loader: string): boolean {
    return v.loaders.map((l) => l.trim().toLowerCase()).includes(loader);
  }

  // 1. Candidates: versions matching game_versions
  const candidates = versions.filter((v) =>
    v.game_versions.some((gv) => gameVersionMatches(sv, gv)),
  );

  if (candidates.length > 0) {
    for (const tierLoaders of tiers) {
      const group = candidates.filter((v) => tierLoaders.some((ldr) => loaderMatches(v, ldr)));
      if (group.length > 0) {
        return group.reduce((best, cur) => (compareVersions(cur, best, st) > 0 ? cur : best));
      }
    }
  }

  return null;
}
