import type { PluginResponse } from "@/types";

export interface AddonTargetIdentity {
  project_id: string;
  slug?: string;
  title?: string;
}

/**
 * Locate an already-installed plugin/mod matching a Marketplace project.
 * Excludes items pending deletion so users can reinstall cleanly after removal.
 */
export function findInstalledAddon(
  plugins: PluginResponse[] | undefined,
  target: AddonTargetIdentity,
): PluginResponse | null {
  if (!plugins || plugins.length === 0) return null;

  const targetId = target.project_id.trim();
  const targetSlug = target.slug?.trim().toLowerCase() ?? "";
  const targetTitle = target.title?.trim().toLowerCase() ?? "";

  for (const plugin of plugins) {
    if (plugin.pending_deletion) continue;
    if (plugin.external_project_id && plugin.external_project_id === targetId) {
      return plugin;
    }
    if (targetSlug) {
      const extLower = plugin.external_project_id?.trim().toLowerCase() ?? "";
      const modIdLower = plugin.mod_id?.trim().toLowerCase() ?? "";
      if (extLower === targetSlug || modIdLower === targetSlug) {
        return plugin;
      }
    }
    if (targetTitle && plugin.name.trim().toLowerCase() === targetTitle) {
      return plugin;
    }
  }

  return null;
}
