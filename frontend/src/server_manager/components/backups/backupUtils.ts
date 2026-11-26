import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { formatDateTime } from "@/server_manager/utils/format";
import type { BackupResponse, ScheduleResponse, UserResponse } from "@/types";

export interface TierMeta {
  label: string;
  subtitle: string;
  shortDesc: string;
}

export const TIER_META: Record<"tier_1" | "tier_2", TierMeta> = {
  tier_1: {
    label: "Quick Snapshot",
    subtitle: "Fast local copy · Keeps last 5",
    shortDesc: "Fast local copy for instant rollbacks. Keeps last 5.",
  },
  tier_2: {
    label: "Encrypted Archive",
    subtitle: "Compressed AES-256 archive · 7 daily + 4 weekly",
    shortDesc: "Compressed AES-256-GCM archive. Keeps 7 daily + 4 weekly.",
  },
};

export function getTierMeta(tier: string): TierMeta {
  return tier === "tier_2" ? TIER_META.tier_2 : TIER_META.tier_1;
}

export interface ScopeMeta {
  value: string;
  label: string;
  shortLabel: string;
}

export const BACKUP_SCOPES: ScopeMeta[] = [
  { value: "full", label: "Full Server", shortLabel: "Full" },
  { value: "worlds", label: "All Worlds", shortLabel: "Worlds" },
  { value: "world", label: "Overworld Only", shortLabel: "Overworld" },
  { value: "nether", label: "Nether Only", shortLabel: "Nether" },
  { value: "end", label: "The End Only", shortLabel: "The End" },
  { value: "plugins", label: "Plugins / Mods", shortLabel: "Plugins" },
  { value: "config", label: "Configuration Only", shortLabel: "Config" },
];

const SCOPE_MAP = new Map(BACKUP_SCOPES.map((s) => [s.value, s]));

export function getScopeMeta(scope: string): ScopeMeta {
  return (
    SCOPE_MAP.get(scope) ?? {
      value: scope,
      label: scope.charAt(0).toUpperCase() + scope.slice(1),
      shortLabel: scope.charAt(0).toUpperCase() + scope.slice(1),
    }
  );
}

export interface StatusMeta {
  label: string;
  badgeClass: string;
  pulse: boolean;
}

export const STATUS_META: Record<string, StatusMeta> = {
  completed: {
    label: "Completed",
    badgeClass: "bg-status-success-bg text-status-success border border-status-success-border",
    pulse: false,
  },
  in_progress: {
    label: "In Progress",
    badgeClass: "bg-status-info-bg text-status-info border border-status-info-border",
    pulse: true,
  },
  pending: {
    label: "Pending",
    badgeClass: "bg-status-warning-bg text-status-warning border border-status-warning-border",
    pulse: false,
  },
  failed: {
    label: "Failed",
    badgeClass: "bg-status-danger-bg text-status-danger border border-status-danger-border",
    pulse: false,
  },
  failed_timeout: {
    label: "Timed Out",
    badgeClass: "bg-status-warning-bg text-status-warning border border-status-warning-border",
    pulse: false,
  },
};

export function getStatusMeta(status: string): StatusMeta {
  if (STATUS_META[status]) {
    return STATUS_META[status];
  }
  const normalized = status === "running" ? "in_progress" : status;
  if (STATUS_META[normalized]) {
    return STATUS_META[normalized];
  }
  return {
    label: status.charAt(0).toUpperCase() + status.slice(1).replace(/_/g, " "),
    badgeClass: "bg-surface-elevated text-text-secondary border border-border-subtle",
    pulse: false,
  };
}

export function resolveBackupServer(
  backup: BackupResponse,
  serverMap: Map<string, string>,
  serversResolved: boolean,
): { name: string; deleted: boolean } {
  const fromList = serverMap.get(backup.server_id);
  if (fromList) {
    return { name: fromList, deleted: false };
  }
  if (backup.server_name) {
    return { name: backup.server_name, deleted: Boolean(backup.server_deleted) };
  }
  if (backup.server_deleted || serversResolved) {
    return { name: "Deleted Server", deleted: true };
  }
  return { name: "Loading server…", deleted: false };
}

export function formatShortDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return formatDateTime(dateStr);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(d);
}

export interface SchedulePreset {
  id: string;
  label: string;
  cron: string;
}

export const SCHEDULE_PRESETS: SchedulePreset[] = [
  { id: "6h", label: "Every 6 hours", cron: "0 */6 * * *" },
  { id: "daily_3am", label: "Daily at 3:00 AM", cron: "0 3 * * *" },
  { id: "daily_midnight", label: "Daily at Midnight", cron: "0 0 * * *" },
  { id: "weekly_sun", label: "Weekly (Sunday 3:00 AM)", cron: "0 3 * * 0" },
  { id: "custom", label: "Custom Cron...", cron: "" },
];

export function describeCronExpression(expr: string): string {
  const trimmed = expr.trim();
  const preset = SCHEDULE_PRESETS.find((p) => p.cron && p.cron === trimmed);
  if (preset) return preset.label;
  if (trimmed === "0 * * * *") return "Hourly";
  const parts = trimmed.split(/\s+/);
  if (parts.length === 5) {
    const [min, hour, dom, mon, dow] = parts;
    if (dom === "*" && mon === "*" && dow === "*" && /^\d+$/.test(min) && /^\d+$/.test(hour)) {
      return `Daily at ${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;
    }
    if (min === "0" && hour.startsWith("*/") && dom === "*" && mon === "*" && dow === "*") {
      return `Every ${hour.slice(2)} hours`;
    }
  }
  return `Cron (${trimmed})`;
}

export function isBackupSchedule(schedule: ScheduleResponse): boolean {
  return schedule.task_name === "run_backup_task" || schedule.task_name === "backup";
}

function hasAnyPermission(
  user: (UserResponse & { permissions?: string[] }) | null | undefined,
  required: string[],
): boolean {
  if (!user) return true;
  const roles = user.roles ?? [];
  if (roles.includes("owner") || roles.includes("admin")) return true;
  const perms = user.permissions ?? [];
  if (perms.includes("admin:full") || perms.includes("global.*")) return true;
  return required.some((p) => perms.includes(p));
}

export function useBackupPermissions() {
  const api = useMemo(() => {
    try {
      return createAuthenticatedApi();
    } catch {
      return null;
    }
  }, []);

  const canQueryMe = Boolean(api && typeof api.getMe === "function");
  const meQuery = useQuery<UserResponse | null>({
    queryKey: ["currentUser"],
    queryFn: async () => (api?.getMe ? api.getMe() : null),
    enabled: canQueryMe,
    staleTime: 30_000,
    retry: false,
  });

  const user = meQuery.data;
  return {
    canCreate: hasAnyPermission(user, ["backup:create"]),
    canRestore: hasAnyPermission(user, ["backup:restore"]),
    canDelete: hasAnyPermission(user, ["backup:delete"]),
    canManageSchedules: hasAnyPermission(user, ["global.settings"]),
  };
}
