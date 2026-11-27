const SERVER_TYPE_LABELS: Record<string, string> = {
  vanilla: "Vanilla",
  paper: "Paper",
  purpur: "Purpur",
  fabric: "Fabric",
  forge: "Forge",
  neoforge: "NeoForge",
  quilt: "Quilt",
  spigot: "Spigot",
  folia: "Folia",
  bukkit: "Bukkit",
  velocity: "Velocity",
  bungeecord: "BungeeCord",
  waterfall: "Waterfall",
};

const UUID_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const SAFE_BRANCH_SEGMENT_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$/;

/** Normalize persisted 'ServerType.PURPUR' or raw loader slugs to clean display labels. */
export function formatServerTypeLabel(value: string | null | undefined): string {
  if (!value) return "";
  let clean = value.trim();
  if (clean.startsWith("ServerType.")) {
    clean = clean.slice("ServerType.".length);
  }
  const lower = clean.toLowerCase();
  if (!lower) return "";
  return (
    SERVER_TYPE_LABELS[lower] ??
    lower.charAt(0).toUpperCase() + lower.slice(1)
  );
}

/** Return true when an author string is a raw internal UUID rather than a human name. */
export function isRawUuid(value: string | null | undefined): boolean {
  if (!value) return false;
  return UUID_REGEX.test(value.trim());
}

/** Format commit author cleanly without leaking raw internal UUID strings. */
export function formatCommitAuthor(authorId: string | null | undefined): string | null {
  if (!authorId) return null;
  const trimmed = authorId.trim();
  if (!trimmed) return null;
  if (isRawUuid(trimmed)) return null;
  return trimmed;
}

/** Validate a new Git branch name against backend naming rules. */
export function validateBranchName(raw: string): string | null {
  const name = raw.trim();
  if (!name) return "Branch name is required.";
  if (name === "main" || name === "HEAD") {
    return `'${name}' is a reserved branch name.`;
  }
  if (name.includes("..")) {
    return "Branch name cannot contain '..'.";
  }
  if (!SAFE_BRANCH_SEGMENT_RE.test(name)) {
    return "Use 1–63 characters: letters, numbers, '.', '_', or '-' (must start with a letter or number).";
  }
  return null;
}

export interface RetentionOption {
  value: string;
  label: string;
  description: string;
}

export const RETENTION_POLICY_OPTIONS: readonly RetentionOption[] = [
  {
    value: "until_confirm",
    label: "Keep until manually confirmed (Recommended)",
    description:
      "Preserves your previous server files so you can undo anytime until you explicitly free disk space.",
  },
  {
    value: "24h",
    label: "Keep for 24 hours",
    description:
      "Automatically frees previous server files 24 hours after deployment.",
  },
  {
    value: "72h",
    label: "Keep for 72 hours",
    description:
      "Automatically frees previous server files 72 hours after deployment.",
  },
  {
    value: "until_health_gate",
    label: "Delete immediately after health checks pass",
    description:
      "Minimizes disk usage; undo is only available if startup health checks fail.",
  },
];
