import type { IconName } from "@/components/ui/Icon";

/**
 * Single source of truth for every platform/loader the app can display.
 *
 * Each entry drives:
 *  - the platform pills on the detail page, the marketplace cards, and the
 *    `?loader=` filter tag (via `getPlatformDisplay`)
 *  - the "Choose Server Software" picker (via `getPlatformSoftwareInfo`)
 *  - the marketplace project-type mapping (via `platformProjectType`)
 *
 * The `key` matches Modrinth's category/loader slug so the same key is used
 * both for display and for the `?loader=` search facet.
 */
export interface PlatformInfo {
  /** Display name, e.g. "Paper", "BungeeCord" */
  label: string;
  /** Brand icon rendered in pills and the software picker */
  icon: IconName;
  /** Approximate brand color, used as the picker swatch tint */
  color: string;
  /** Marketplace project type this platform hosts, if any */
  projectType: "plugin" | "mod" | null;
  /** Human description shown in the "Choose Server Software" picker */
  description?: string;
  /** Short platform family tag shown in the picker */
  kind?: string;
}

const PLATFORMS: Record<string, PlatformInfo> = {
  paper: {
    label: "Paper",
    icon: "paper",
    color: "#c81212",
    projectType: "plugin",
    description: "High-performance fork of Spigot with extensive optimizations and API.",
    kind: "Plugin",
  },
  purpur: {
    label: "Purpur",
    icon: "purpur",
    color: "#8e44ad",
    projectType: "plugin",
    description: "Fork of Paper with more configuration options and features.",
    kind: "Plugin",
  },
  spigot: {
    label: "Spigot",
    icon: "spigot",
    color: "#e67e22",
    projectType: "plugin",
    description: "Most widely-used Minecraft server software with plugin support.",
    kind: "Plugin",
  },
  bukkit: {
    label: "Bukkit",
    icon: "bukkit",
    color: "#2ecc71",
    projectType: "plugin",
    description: "Original plugin API for Minecraft servers.",
    kind: "Plugin",
  },
  folia: {
    label: "Folia",
    icon: "folia",
    color: "#16a34a",
    projectType: "plugin",
    description: "Parallel-threaded Paper fork for high-player-count servers.",
    kind: "Plugin",
  },
  velocity: {
    label: "Velocity",
    icon: "velocity",
    color: "#3b82f6",
    projectType: "plugin",
    description: "Modern, high-performance Minecraft proxy server.",
    kind: "Proxy",
  },
  bungeecord: {
    label: "BungeeCord",
    icon: "bungeecord",
    color: "#dc2626",
    projectType: "plugin",
    description: "Original Minecraft proxy to link multiple servers together.",
    kind: "Proxy",
  },
  waterfall: {
    label: "Waterfall",
    icon: "waterfall",
    color: "#06b6d4",
    projectType: "plugin",
    description: "BungeeCord fork focused on stability and performance.",
    kind: "Proxy",
  },
  minestom: {
    label: "Minestom",
    icon: "download",
    color: "#64748b",
    projectType: "plugin",
    description: "Lightweight server software built without vanilla features.",
    kind: "Plugin",
  },
  geyser: {
    label: "Geyser Extension",
    icon: "globe",
    color: "#0ea5e9",
    projectType: "plugin",
    description: "Extension for GeyserMC Bedrock-to-Java bridge.",
    kind: "Extension",
  },
  fabric: {
    label: "Fabric",
    icon: "fabric",
    color: "#b45309",
    projectType: "mod",
    description: "Lightweight modding toolchain for Minecraft.",
    kind: "Mod",
  },
  forge: {
    label: "Forge",
    icon: "forge",
    color: "#d0a94b",
    projectType: "mod",
    description: "The original Minecraft modding API. Requires manual JAR installation.",
    kind: "Mod",
  },
  neoforge: {
    label: "NeoForge",
    icon: "neoforge",
    color: "#2563eb",
    projectType: "mod",
    description: "Community-driven fork of Forge for modern Minecraft versions.",
    kind: "Mod",
  },
  quilt: {
    label: "Quilt",
    icon: "quilt",
    color: "#0d9488",
    projectType: "mod",
    description: "Modding toolchain for Minecraft built on the Fabric ecosystem.",
    kind: "Mod",
  },
  datapack: {
    label: "Datapack",
    icon: "datapack",
    color: "#f59e0b",
    projectType: null,
    description: "Vanilla-compatible data packs — no loader required.",
    kind: "Data",
  },
  vanilla: {
    label: "Vanilla",
    icon: "vanilla",
    color: "#65a30d",
    projectType: null,
    description: "The official Minecraft server from Mojang.",
    kind: "Vanilla",
  },
};

const DEFAULT_INFO: PlatformInfo = {
  label: "",
  icon: "download",
  color: "#6b7280",
  projectType: null,
};

export function getPlatformInfo(key: string): PlatformInfo {
  return PLATFORMS[key.toLowerCase()] ?? { ...DEFAULT_INFO, label: key };
}

export function getPlatformLabel(key: string): string {
  return getPlatformInfo(key).label || key;
}

export function getPlatformIcon(key: string): IconName {
  return getPlatformInfo(key).icon;
}

/** True when the key is a known platform/loader. */
export function isKnownPlatform(key: string): boolean {
  return key.toLowerCase() in PLATFORMS;
}

/** Marketplace project type ("plugin" | "mod") for a platform, falling back to `fallback`. */
export function platformProjectType(
  key: string,
  fallback: "plugin" | "mod",
): "plugin" | "mod" {
  return getPlatformInfo(key).projectType ?? fallback;
}

/** The server software entries used by the "Choose Server Software" picker. */
export function getPlatformSoftwareInfo(key: string): PlatformInfo | undefined {
  const info = PLATFORMS[key.toLowerCase()];
  if (!info?.description) return undefined;
  return info;
}

/**
 * Resolves the effective marketplace types ("plugin" and/or "mod") for a project
 * by inspecting both its declared `project_types` and its published `loaders`.
 * Ensures dual-platform projects (e.g. Fabric + Paper) display both Plugin and Mod.
 */
export function inferProjectTypes(
  projectTypes?: string[] | null,
  loaders?: string[] | null,
): Array<"plugin" | "mod"> {
  const normalizedTypes = (projectTypes ?? []).map((t) => t.trim().toLowerCase());
  const hasPluginType = normalizedTypes.includes("plugin");
  const hasModType = normalizedTypes.includes("mod");
  const hasPluginLoader = (loaders ?? []).some(
    (l) => getPlatformInfo(l).projectType === "plugin",
  );
  const hasModLoader = (loaders ?? []).some(
    (l) => getPlatformInfo(l).projectType === "mod",
  );

  const result: Array<"plugin" | "mod"> = [];
  if (hasPluginType || hasPluginLoader) result.push("plugin");
  if (hasModType || hasModLoader) result.push("mod");
  return result.length > 0 ? result : ["plugin"];
}
