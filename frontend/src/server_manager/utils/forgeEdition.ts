export type ForgeEdition = "modern" | "legacy";

const FORGE_INSTALLER_MIN_MAJOR = 1;
const FORGE_INSTALLER_MIN_MINOR = 17;
const NEOFORGE_INSTALLER_MIN_MAJOR = 1;
const NEOFORGE_INSTALLER_MIN_MINOR = 17;

/**
 * Whether a Minecraft version uses the modern Forge installer flow (>= 1.17).
 *
 * Mirrors the backend's `FORGE_INSTALLER_MIN_VERSION` / `forge_requires_installer`
 * decision in `backend/app/modules/server/application/services/jar_service.py`:
 * unparseable versions default to the installer (modern) flow, and comparisons are
 * numeric, never lexical.
 */
export function isModernForgeVersion(v: string): boolean {
  const trimmed = v.trim();
  const segments = trimmed.split(".").map((seg) => Number(seg));
  if (segments.length < 2 || segments.some((n) => Number.isNaN(n))) {
    return true;
  }
  const [major, minor] = segments;
  return major > FORGE_INSTALLER_MIN_MAJOR ||
    (major === FORGE_INSTALLER_MIN_MAJOR && minor >= FORGE_INSTALLER_MIN_MINOR);
}

/**
 * Whether a Minecraft version uses the modern NeoForge installer flow (>= 1.17).
 *
 * Mirrors the backend's `NEOFORGE_INSTALLER_MIN_VERSION` / `neoforge_requires_installer`
 * decision in `backend/app/modules/server/application/services/jar_service.py`.
 */
export function isModernNeoForgeVersion(v: string): boolean {
  const trimmed = v.trim();
  const segments = trimmed.split(".").map((seg) => Number(seg));
  if (segments.length < 2 || segments.some((n) => Number.isNaN(n))) {
    return true;
  }
  const [major, minor] = segments;
  return major > NEOFORGE_INSTALLER_MIN_MAJOR ||
    (major === NEOFORGE_INSTALLER_MIN_MAJOR && minor >= NEOFORGE_INSTALLER_MIN_MINOR);
}

export function forgeEditionForVersion(v: string): ForgeEdition {
  return isModernForgeVersion(v) ? "modern" : "legacy";
}

export function neoforgeEditionForVersion(v: string): ForgeEdition {
  return isModernNeoForgeVersion(v) ? "modern" : "legacy";
}

export const FORGE_EDITION_LABELS: Record<ForgeEdition, { label: string; description: string }> = {
  modern: {
    label: "Modern Forge (1.17+)",
    description: "Uses the Forge installer flow — auto-downloads forge-installer.jar and configures run.sh during setup.",
  },
  legacy: {
    label: "Legacy Forge (< 1.17)",
    description: "Downloads the forge-{version}-universal.jar directly — no installer step.",
  },
};

export const NEOFORGE_EDITION_LABELS: Record<ForgeEdition, { label: string; description: string }> = {
  modern: {
    label: "Modern NeoForge (1.17+)",
    description: "Uses the NeoForge installer flow — auto-downloads neoforge-installer.jar and configures run.sh during setup.",
  },
  legacy: {
    label: "Legacy NeoForge (< 1.17)",
    description: "Downloads the neoforge-{version}-universal.jar directly — no installer step.",
  },
};