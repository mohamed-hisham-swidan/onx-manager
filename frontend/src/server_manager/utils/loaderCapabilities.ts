/** Server types that support mod loaders and .mrpack / CurseForge modpacks. */
export const MODPACK_SUPPORTED_LOADERS = new Set([
  "fabric",
  "forge",
  "neoforge",
  "quilt",
]);

/** Server types that run Bukkit/Spigot/Paper/Proxy plugins rather than mods. */
export const PLUGIN_LOADERS = new Set([
  "paper",
  "spigot",
  "purpur",
  "folia",
  "bukkit",
  "velocity",
  "bungeecord",
  "waterfall",
]);

/** Server types eligible for Paper experimental Fill v3 fallback builds. */
export const PAPER_FAMILY_LOADERS = new Set(["paper", "purpur"]);

export function normalizeLoader(loader: string | null | undefined): string {
  return (loader ?? "").trim().toLowerCase();
}

export function isModpackSupportedLoader(loader: string | null | undefined): boolean {
  return MODPACK_SUPPORTED_LOADERS.has(normalizeLoader(loader));
}

export function isPluginLoader(loader: string | null | undefined): boolean {
  return PLUGIN_LOADERS.has(normalizeLoader(loader));
}

export function isPaperFamilyLoader(loader: string | null | undefined): boolean {
  return PAPER_FAMILY_LOADERS.has(normalizeLoader(loader));
}
