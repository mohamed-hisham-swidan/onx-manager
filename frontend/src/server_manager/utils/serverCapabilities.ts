export interface ServerCapabilities {
  supportsMods: boolean;
  supportsPlugins: boolean;
}

const MOD_SERVER_TYPES = new Set([
  "fabric",
  "forge",
  "neoforge",
  "quilt",
]);

const PLUGIN_SERVER_TYPES = new Set([
  "paper",
  "purpur",
  "spigot",
  "bukkit",
  "folia",
  "velocity",
  "bungeecord",
  "waterfall",
  "minestom",
]);

const KNOWN_SERVER_TYPES = new Set([
  "vanilla",
  ...MOD_SERVER_TYPES,
  ...PLUGIN_SERVER_TYPES,
]);

export function getServerCapabilities(serverType?: string | null): ServerCapabilities {
  if (!serverType) {
    return { supportsMods: false, supportsPlugins: false };
  }

  const st = serverType.trim().toLowerCase();

  if (!st || !KNOWN_SERVER_TYPES.has(st)) {
    // Unrecognized / unknown server type defaults to permissive (both)
    return { supportsMods: true, supportsPlugins: true };
  }

  if (st === "vanilla") {
    return { supportsMods: false, supportsPlugins: false };
  }

  return {
    supportsMods: MOD_SERVER_TYPES.has(st),
    supportsPlugins: PLUGIN_SERVER_TYPES.has(st),
  };
}
