import { useAuthPermissions } from "@/hooks/useAuthPermissions";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import { resolveServerMode } from "@/server_manager/utils/serverMode";
import type { ViewMode } from "@/components/ui/ViewModeToggle";
import type { ServerResponse } from "@/server_manager/types";

export const SERVERS_VIEW_MODE_STORAGE_KEY = "onx_servers_view_mode";

export const STATUS_FILTERS = [
  "all",
  "attention",
  "running",
  "stopped",
  "starting",
  "provisioning",
  "provisioning_failed",
  "stopping",
  "crashed",
  "broken",
  "created",
  "restoring",
] as const;

export type SortKey = "name" | "status" | "players" | "memory" | "version" | "created";

export interface ServerLiveTelemetry {
  players: number | null;
  tps: number | null;
  ramUsedMb: number | null;
  ramLimitMb: number | null;
  cpuPercent: number | null;
  hasLiveMetrics: boolean;
}

export function readInitialViewMode(storageKey = SERVERS_VIEW_MODE_STORAGE_KEY): ViewMode {
  if (typeof window === "undefined") return "grid";
  try {
    const saved = window.localStorage.getItem(storageKey);
    if (saved === "list" || saved === "grid") {
      return saved;
    }
  } catch {
    // Ignore localStorage access errors
  }
  return "grid";
}

const DOCKER_BRIDGE_IPV4_RE = /^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/;

function isUnplayableBindHost(host?: string): boolean {
  if (!host) return true;
  if (host === "0.0.0.0" || host === "::" || host === "[::]" || host === "*") {
    return true;
  }
  return DOCKER_BRIDGE_IPV4_RE.test(host);
}

function resolveBrowserFallbackHost(): string {
  if (typeof window !== "undefined") {
    const hostname = window.location?.hostname?.trim();
    if (
      hostname &&
      hostname !== "localhost" &&
      hostname !== "127.0.0.1" &&
      hostname !== "::1" &&
      hostname !== "[::1]"
    ) {
      return hostname;
    }
  }
  return "localhost";
}

export function resolveJoinAddress(server: ServerResponse): {
  address: string;
  isPublic: boolean;
} {
  const pub = server.public_address?.trim();
  if (pub) {
    return { address: pub, isPublic: true };
  }
  const rawHost = server.deployment_host?.trim();
  const host = isUnplayableBindHost(rawHost) ? resolveBrowserFallbackHost() : rawHost;
  return { address: `${host}:${server.port}`, isPublic: false };
}

export function formatMemoryMb(mb: number | null | undefined): string {
  if (mb == null || !Number.isFinite(mb) || mb < 0) return "—";
  if (mb >= 1024) {
    const gb = mb / 1024;
    return `${gb % 1 === 0 ? gb.toFixed(0) : gb.toFixed(1)} GB`;
  }
  return `${Math.round(mb)} MB`;
}

export function formatUptime(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const mins = Math.floor((total % 3600) / 60);
  if (days > 0) return `Up ${days}d ${hours}h`;
  if (hours > 0) return `Up ${hours}h ${mins}m`;
  if (mins > 0) return `Up ${mins}m`;
  return `Up ${total}s`;
}

export function isRetryableProvisioningFailure(server: ServerResponse): boolean {
  return server.status === "provisioning_failed" && server.provisioning_retryable !== false;
}

const STATUS_SORT_RANK: Record<string, number> = {
  running: 0,
  starting: 1,
  provisioning: 2,
  restoring: 3,
  stopping: 4,
  crashed: 5,
  broken: 6,
  provisioning_failed: 7,
  stopped: 8,
  created: 9,
};

export function filterAndSortServers(
  servers: ServerResponse[],
  options: {
    search: string;
    statusFilter: string;
    loaderFilter: string;
    modeFilter: string;
    sortKey: SortKey;
    metricsByServerId?: Record<string, ServerLiveTelemetry>;
  },
): ServerResponse[] {
  const { search, statusFilter, loaderFilter, modeFilter, sortKey, metricsByServerId } = options;
  const query = search.trim().toLowerCase();

  const list = servers.filter((s) => {
    if (statusFilter === "attention") {
      if (
        s.status !== "crashed" &&
        s.status !== "broken" &&
        s.status !== "provisioning_failed"
      ) {
        return false;
      }
    } else if (statusFilter !== "all" && s.status !== statusFilter) {
      return false;
    }
    if (loaderFilter !== "all" && (s.server_type ?? "").toLowerCase() !== loaderFilter.toLowerCase()) {
      return false;
    }
    if (modeFilter !== "all" && resolveServerMode(s.mode) !== modeFilter) {
      return false;
    }
    if (query) {
      const cleanMotd = s.motd ? stripMinecraftFormatting(s.motd).toLowerCase() : "";
      const matches =
        s.name.toLowerCase().includes(query) ||
        (s.server_type ?? "").toLowerCase().includes(query) ||
        (s.minecraft_version ?? "").toLowerCase().includes(query) ||
        String(s.port).includes(query) ||
        cleanMotd.includes(query);
      if (!matches) return false;
    }
    return true;
  });

  return [...list].sort((a, b) => {
    if (sortKey === "status") {
      const rankDiff =
        (STATUS_SORT_RANK[a.status] ?? 99) - (STATUS_SORT_RANK[b.status] ?? 99);
      if (rankDiff !== 0) return rankDiff;
      return a.name.localeCompare(b.name);
    }
    if (sortKey === "players") {
      const pa = metricsByServerId?.[a.server_id]?.players ?? -1;
      const pb = metricsByServerId?.[b.server_id]?.players ?? -1;
      if (pb !== pa) return pb - pa;
      return a.name.localeCompare(b.name);
    }
    if (sortKey === "memory") {
      const ma = metricsByServerId?.[a.server_id]?.ramLimitMb ?? a.max_memory_mb ?? 0;
      const mb = metricsByServerId?.[b.server_id]?.ramLimitMb ?? b.max_memory_mb ?? 0;
      if (mb !== ma) return mb - ma;
      return a.name.localeCompare(b.name);
    }
    if (sortKey === "version") {
      const cmp = (b.minecraft_version ?? "").localeCompare(
        a.minecraft_version ?? "",
        undefined,
        { numeric: true },
      );
      if (cmp !== 0) return cmp;
      return a.name.localeCompare(b.name);
    }
    if (sortKey === "created") {
      const cmp = (b.created_at ?? "").localeCompare(a.created_at ?? "");
      if (cmp !== 0) return cmp;
      return a.name.localeCompare(b.name);
    }
    return a.name.localeCompare(b.name);
  });
}

export interface FleetPermissions {
  canCreate: boolean;
  canImport: boolean;
  canDelete: boolean;
  canManageVersioning?: boolean;
  isOwner?: boolean;
  isAdmin?: boolean;
  isViewer?: boolean;
  canPower: (serverId: string) => boolean;
  canConsole: (serverId: string) => boolean;
  canConsoleView?: (serverId: string) => boolean;
  canWrite: (serverId: string) => boolean;
  canFiles: (serverId: string) => boolean;
  canViewLogs?: (serverId: string) => boolean;
  canManagePlugins: (serverId: string) => boolean;
  canViewPlugins?: (serverId: string) => boolean;
  canViewExposure: (serverId: string) => boolean;
  canManageExposure?: (serverId: string) => boolean;
  canBackups?: (serverId: string) => boolean;
  canViewBackups?: (serverId: string) => boolean;
  canSettings?: (serverId: string) => boolean;
  canVersioning?: (serverId: string) => boolean;
  canViewVersioning?: (serverId: string) => boolean;
}

export function useFleetPermissions(): FleetPermissions {
  const auth = useAuthPermissions();

  return {
    canCreate: auth.canCreateServer,
    canImport: auth.canImportServer,
    canDelete: auth.canDeleteServer,
    canManageVersioning: auth.isAdmin || auth.canVersioning(),
    isOwner: auth.isOwner,
    isAdmin: auth.isAdmin,
    isViewer: auth.isViewer,
    canPower: (serverId: string) => auth.canPower(serverId),
    canConsole: (serverId: string) => auth.canConsole(serverId),
    canConsoleView: (serverId: string) => auth.canConsoleView(serverId),
    canWrite: (serverId: string) => auth.canSettings(serverId),
    canFiles: (serverId: string) => auth.canFiles(serverId),
    canViewLogs: (serverId: string) => auth.canViewLogs(serverId),
    canManagePlugins: (serverId: string) => auth.canManagePlugins(serverId),
    canViewPlugins: (serverId: string) => auth.canViewPlugins(serverId),
    canViewExposure: (serverId: string) => auth.canViewExposure(serverId),
    canManageExposure: (serverId: string) => auth.canManageExposure(serverId),
    canBackups: (serverId: string) => auth.canBackups(serverId),
    canViewBackups: (serverId: string) => auth.canViewBackups(serverId),
    canSettings: (serverId: string) => auth.canSettings(serverId),
    canVersioning: (serverId: string) => auth.canVersioning(serverId),
    canViewVersioning: (serverId: string) => auth.canViewVersioning(serverId),
  };
}
