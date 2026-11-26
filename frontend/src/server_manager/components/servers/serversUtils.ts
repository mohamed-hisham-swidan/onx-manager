import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useAuthStore } from "@/stores/authStore";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import { resolveServerMode } from "@/server_manager/utils/serverMode";
import type { ViewMode } from "@/components/ui/ViewModeToggle";
import type { ServerResponse } from "@/server_manager/types";
import type { CurrentUserResponse } from "@/types";

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

function decodeJwtPermissions(token: string | null): string[] {
  if (!token) return [];
  try {
    const parts = token.split(".");
    if (parts.length < 2) return [];
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const payload = JSON.parse(atob(padded)) as { permissions?: unknown };
    return Array.isArray(payload.permissions)
      ? payload.permissions.filter((p): p is string => typeof p === "string")
      : [];
  } catch {
    return [];
  }
}

export interface FleetPermissions {
  canCreate: boolean;
  canImport: boolean;
  canDelete: boolean;
  canManageVersioning?: boolean;
  canPower: (serverId: string) => boolean;
  canConsole: (serverId: string) => boolean;
  canWrite: (serverId: string) => boolean;
  canFiles: (serverId: string) => boolean;
  canManagePlugins: (serverId: string) => boolean;
  canViewExposure: (serverId: string) => boolean;
}

export function useFleetPermissions(): FleetPermissions {
  const api = useMemo(() => {
    try {
      return createAuthenticatedApi();
    } catch {
      return null;
    }
  }, []);
  const accessToken = useAuthStore((s) => s.accessToken);
  const canQueryMe = Boolean(api && typeof api.getMe === "function");

  const meQuery = useQuery<(CurrentUserResponse & { permissions?: string[] }) | null>({
    queryKey: queryKeys.auth.me,
    queryFn: async () => (api?.getMe ? api.getMe() : null),
    enabled: canQueryMe,
    staleTime: 30_000,
    retry: false,
  });

  const user = meQuery.data;
  const jwtPermissions = useMemo(() => decodeJwtPermissions(accessToken), [accessToken]);

  return useMemo(() => {
    if (!user && jwtPermissions.length === 0) {
      return {
        canCreate: false,
        canImport: false,
        canDelete: false,
        canManageVersioning: false,
        canPower: () => false,
        canConsole: () => false,
        canWrite: () => false,
        canFiles: () => false,
        canManagePlugins: () => false,
        canViewExposure: () => false,
      };
    }

    const roles = user?.roles ?? [];
    const perms = Array.from(new Set([...(user?.permissions ?? []), ...jwtPermissions]));
    const isGlobalAdmin =
      roles.includes("owner") ||
      roles.includes("admin") ||
      perms.includes("admin:full") ||
      perms.includes("global.*") ||
      perms.includes("global.servers.manage");

    if (isGlobalAdmin) {
      return {
        canCreate: true,
        canImport: true,
        canDelete: true,
        canManageVersioning: true,
        canPower: () => true,
        canConsole: () => true,
        canWrite: () => true,
        canFiles: () => true,
        canManagePlugins: () => true,
        canViewExposure: () => true,
      };
    }

    const hasExplicitPerms = perms.length > 0;
    const isViewerOnly = roles.length > 0 && roles.every((r) => r === "viewer");

    return {
      canCreate: hasExplicitPerms
        ? perms.includes("server:create")
        : !isViewerOnly,
      canImport: hasExplicitPerms
        ? perms.includes("server:write") || perms.includes("server:create")
        : !isViewerOnly,
      canDelete: hasExplicitPerms
        ? perms.includes("server:delete")
        : !isViewerOnly,
      canManageVersioning: hasExplicitPerms
        ? perms.includes("server.versioning.manage")
        : !isViewerOnly,
      canPower: (serverId: string) => {
        if (hasExplicitPerms) {
          return (
            perms.includes("server:write") ||
            perms.includes("server:start") ||
            perms.includes("server:power") ||
            perms.includes(`server.${serverId}.power`) ||
            perms.includes(`server.${serverId}.*`)
          );
        }
        return !isViewerOnly;
      },
      canConsole: (serverId: string) => {
        if (hasExplicitPerms) {
          return (
            perms.includes("server:write") ||
            perms.includes("server:console") ||
            perms.includes(`server.${serverId}.console`) ||
            perms.includes(`server.${serverId}.*`)
          );
        }
        return !isViewerOnly;
      },
      canWrite: (serverId: string) => {
        if (hasExplicitPerms) {
          return (
            perms.includes("server:write") ||
            perms.includes(`server.${serverId}.write`) ||
            perms.includes(`server.${serverId}.*`)
          );
        }
        return !isViewerOnly;
      },
      canFiles: (serverId: string) => {
        if (hasExplicitPerms) {
          return (
            perms.includes("server:write") ||
            perms.includes("server:files") ||
            perms.includes(`server.${serverId}.files`) ||
            perms.includes(`server.${serverId}.*`)
          );
        }
        return !isViewerOnly;
      },
      canManagePlugins: (serverId: string) => {
        if (hasExplicitPerms) {
          return (
            perms.includes("plugin:manage") ||
            perms.includes("server:write") ||
            perms.includes(`server.${serverId}.plugins`) ||
            perms.includes(`server.${serverId}.*`)
          );
        }
        return !isViewerOnly;
      },
      canViewExposure: (serverId: string) => {
        if (hasExplicitPerms) {
          return (
            perms.includes("server:write") ||
            perms.includes("exposure:read") ||
            perms.includes("exposure:write") ||
            perms.includes(`server.${serverId}.exposure`) ||
            perms.includes(`server.${serverId}.*`)
          );
        }
        return !isViewerOnly;
      },
    };
  }, [user, jwtPermissions]);
}
