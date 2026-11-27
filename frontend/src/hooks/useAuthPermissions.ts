import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useAuthStore } from "@/stores/authStore";
import type {
  CanonicalRole,
  CapabilityKey,
  CurrentUserResponse,
} from "@/types";

export const CAPABILITY_OPTIONS: ReadonlyArray<{
  key: CapabilityKey;
  label: string;
  viewerLabel: string;
  description: string;
  viewerDescription: string;
  viewerSupported: boolean;
}> = [
  {
    key: "power",
    label: "Power Control",
    viewerLabel: "Power Control",
    description: "Start, stop, and restart assigned servers",
    viewerDescription: "Viewers cannot start, stop, or restart servers",
    viewerSupported: false,
  },
  {
    key: "console",
    label: "Live Console",
    viewerLabel: "View Live Console",
    description: "Stream console logs and send server commands",
    viewerDescription: "Read live and historical console output (commands disabled)",
    viewerSupported: true,
  },
  {
    key: "files",
    label: "Files & Logs",
    viewerLabel: "View Crash & Log Files",
    description: "Browse, edit, upload files and read server logs",
    viewerDescription: "View server logs and crash reports (read-only)",
    viewerSupported: true,
  },
  {
    key: "plugins",
    label: "Plugins & Mods",
    viewerLabel: "View Plugins & Mods",
    description: "Install, upload, toggle, and remove server addons",
    viewerDescription: "View installed plugins and mods (read-only)",
    viewerSupported: true,
  },
  {
    key: "backups",
    label: "Backups & Schedules",
    viewerLabel: "View Backups",
    description: "Create, restore, verify, and schedule backups",
    viewerDescription: "View backup history and status (read-only)",
    viewerSupported: true,
  },
  {
    key: "settings",
    label: "Server Settings",
    viewerLabel: "Server Settings",
    description: "Modify server properties, memory, JVM flags, and alert rules",
    viewerDescription: "Viewers cannot view or modify server settings",
    viewerSupported: false,
  },
  {
    key: "exposure",
    label: "Network & Exposure",
    viewerLabel: "View Network & Ports",
    description: "Configure server tunnels, Playit endpoints, and public ports",
    viewerDescription: "View server connection address and ports (read-only)",
    viewerSupported: true,
  },
  {
    key: "versioning",
    label: "Versioning & Rollback",
    viewerLabel: "View Branches & History",
    description: "Manage Git branches, commits, sandboxes, and mode upgrades",
    viewerDescription: "View commit history and branches (read-only)",
    viewerSupported: true,
  },
];

export const ROLE_LABELS: Record<CanonicalRole, string> = {
  owner: "Owner",
  admin: "Administrator",
  server_admin: "Server Admin",
  viewer: "Viewer",
};

function decodeJwtPayload(token: string | null): {
  roles: string[];
  permissions: string[];
} {
  if (!token) return { roles: [], permissions: [] };
  try {
    const parts = token.split(".");
    if (parts.length < 2) return { roles: [], permissions: [] };
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const json = atob(padded);
    const payload = JSON.parse(json) as { roles?: unknown; permissions?: unknown };
    return {
      roles: Array.isArray(payload.roles)
        ? payload.roles.filter((r): r is string => typeof r === "string")
        : [],
      permissions: Array.isArray(payload.permissions)
        ? payload.permissions.filter((p): p is string => typeof p === "string")
        : [],
    };
  } catch {
    return { roles: [], permissions: [] };
  }
}

export function normalizeCanonicalRole(user?: CurrentUserResponse | null): CanonicalRole {
  const explicit = String(user?.global_role ?? "").trim().toLowerCase();
  if (explicit === "owner" || explicit === "admin" || explicit === "server_admin" || explicit === "viewer") {
    return explicit;
  }
  const roles = (user?.roles ?? []).map((r) => r.trim().toLowerCase());
  if (roles.includes("owner")) return "owner";
  if (roles.includes("admin")) return "admin";
  if (roles.includes("server_admin") || roles.includes("dev") || roles.includes("operator")) {
    return "server_admin";
  }
  const perms = user?.permissions ?? [];
  if (perms.includes("global:*") || perms.includes("global.*")) return "owner";
  if (perms.includes("admin:full")) return "admin";
  if (
    (user?.server_memberships ?? []).some((m) =>
      ["admin", "server_admin", "dev"].includes(String(m.role).toLowerCase()),
    )
  ) {
    return "server_admin";
  }
  return "viewer";
}

export interface AuthPermissionsState {
  isLoading: boolean;
  user: CurrentUserResponse | null | undefined;
  globalRole: CanonicalRole;
  isOwner: boolean;
  isAdmin: boolean;
  isServerAdmin: boolean;
  isViewer: boolean;
  allServersAccess: boolean;
  assignedServerIds: string[];
  deniedPermissions: string[];
  canAccessHostExposure: boolean;
  canAccessModeAndCreds: boolean;
  canAccessGlobalSettings: boolean;
  canManageUsers: boolean;
  canManageApiKeys: boolean;
  canCreateServer: boolean;
  canDeleteServer: boolean;
  canImportServer: boolean;
  canViewServer: (serverId?: string) => boolean;
  canUseCapability: (serverId: string | undefined, cap: CapabilityKey) => boolean;
  canViewCapability: (serverId: string | undefined, cap: CapabilityKey) => boolean;
  canPower: (serverId?: string) => boolean;
  canConsole: (serverId?: string) => boolean;
  canConsoleView: (serverId?: string) => boolean;
  canFiles: (serverId?: string) => boolean;
  canViewLogs: (serverId?: string) => boolean;
  canManagePlugins: (serverId?: string) => boolean;
  canViewPlugins: (serverId?: string) => boolean;
  canBackups: (serverId?: string) => boolean;
  canViewBackups: (serverId?: string) => boolean;
  canSettings: (serverId?: string) => boolean;
  canManageExposure: (serverId?: string) => boolean;
  canViewExposure: (serverId?: string) => boolean;
  canVersioning: (serverId?: string) => boolean;
  canViewVersioning: (serverId?: string) => boolean;
}

export function useAuthPermissions(): AuthPermissionsState {
  const queryClient = useQueryClient();
  const api = useMemo(() => {
    try {
      return createAuthenticatedApi();
    } catch {
      return null;
    }
  }, []);
  const accessToken = useAuthStore((s) => s.accessToken);
  const canQueryMe = Boolean(api && typeof api.getMe === "function");

  const cachedAuthMe = queryClient.getQueryData<CurrentUserResponse | null>(queryKeys.auth.me);
  const cachedCurrentUser = queryClient.getQueryData<CurrentUserResponse | null>(["currentUser"]);

  const meQuery = useQuery<CurrentUserResponse | null>({
    queryKey: ["currentUser"],
    queryFn: async () => (api?.getMe ? api.getMe() : null),
    enabled: canQueryMe,
    staleTime: 15_000,
    retry: false,
  });

  return useMemo(() => {
    const user = meQuery.data ?? cachedCurrentUser ?? cachedAuthMe;
    const isLoading = Boolean(canQueryMe && meQuery.isLoading);
    const jwt = decodeJwtPayload(accessToken);

    if (!user && !accessToken) {
      return {
        isLoading,
        user: null,
        globalRole: "viewer",
        isOwner: false,
        isAdmin: false,
        isServerAdmin: false,
        isViewer: true,
        allServersAccess: false,
        assignedServerIds: [],
        deniedPermissions: [],
        canAccessHostExposure: false,
        canAccessModeAndCreds: false,
        canAccessGlobalSettings: false,
        canManageUsers: false,
        canManageApiKeys: false,
        canCreateServer: false,
        canDeleteServer: false,
        canImportServer: false,
        canViewServer: () => false,
        canUseCapability: () => false,
        canViewCapability: () => false,
        canPower: () => false,
        canConsole: () => false,
        canConsoleView: () => false,
        canFiles: () => false,
        canViewLogs: () => false,
        canManagePlugins: () => false,
        canViewPlugins: () => false,
        canBackups: () => false,
        canViewBackups: () => false,
        canSettings: () => false,
        canManageExposure: () => false,
        canViewExposure: () => false,
        canVersioning: () => false,
        canViewVersioning: () => false,
      };
    }

    const synthesizedUser: CurrentUserResponse | null =
      user ??
      (accessToken
        ? {
            user_id: "",
            email: null,
            display_name: "",
            is_active: true,
            roles: jwt.roles,
            permissions: jwt.permissions,
            created_at: "",
            last_login_at: null,
          }
        : null);

    const globalRole = normalizeCanonicalRole(synthesizedUser);
    const isOwner = globalRole === "owner";
    const isAdmin = globalRole === "owner" || globalRole === "admin";
    const isServerAdmin = globalRole === "server_admin";
    const isViewer = globalRole === "viewer";

    const denied = new Set(
      (synthesizedUser?.denied_permissions ?? []).map((p) => String(p).toLowerCase()),
    );

    const assignedSet = new Set<string>([
      ...(synthesizedUser?.assigned_server_ids ?? []),
      ...(synthesizedUser?.owned_server_ids ?? []),
      ...(synthesizedUser?.server_memberships ?? []).map((m) => m.server_id),
    ]);
    const hasExplicitScopeFields = Boolean(
      synthesizedUser &&
        (synthesizedUser.all_servers_access !== undefined ||
          synthesizedUser.assigned_server_ids !== undefined ||
          synthesizedUser.server_memberships !== undefined),
    );
    const allServersAccess = isAdmin || Boolean(synthesizedUser?.all_servers_access);
    const assignedServerIds = Array.from(assignedSet);

    const membershipMap = new Map<string, string>(
      (synthesizedUser?.server_memberships ?? []).map((m) => [
        m.server_id,
        String(m.role).toLowerCase(),
      ]),
    );

    const hasServerAccess = (serverId?: string): boolean => {
      if (isAdmin) return true;
      if (!hasExplicitScopeFields && !serverId) return true;
      if (!serverId) return allServersAccess || assignedSet.size > 0;
      if (allServersAccess) return true;
      if (!hasExplicitScopeFields) return false;
      return assignedSet.has(serverId);
    };

    const isServerWritable = (serverId?: string): boolean => {
      if (isAdmin) return true;
      if (isViewer) return false;
      if (!hasServerAccess(serverId)) return false;
      if (serverId && membershipMap.get(serverId) === "viewer") {
        return (synthesizedUser?.owned_server_ids ?? []).includes(serverId);
      }
      return isServerAdmin;
    };

    const canViewServer = (serverId?: string): boolean => hasServerAccess(serverId);

    const canUseCapability = (
      serverId: string | undefined,
      cap: CapabilityKey,
    ): boolean => {
      if (isAdmin) return true;
      if (!isServerWritable(serverId)) return false;
      return !denied.has(cap);
    };

    const canViewCapability = (
      serverId: string | undefined,
      cap: CapabilityKey,
    ): boolean => {
      if (isAdmin) return true;
      if (!hasServerAccess(serverId)) return false;
      return !denied.has(cap);
    };

    return {
      isLoading,
      user: synthesizedUser,
      globalRole,
      isOwner,
      isAdmin,
      isServerAdmin,
      isViewer,
      allServersAccess,
      assignedServerIds,
      deniedPermissions: Array.from(denied),
      canAccessHostExposure: isOwner,
      canAccessModeAndCreds: isOwner,
      canAccessGlobalSettings: isAdmin,
      canManageUsers: isAdmin,
      canManageApiKeys: isAdmin,
      canCreateServer: isAdmin,
      canDeleteServer: isAdmin,
      canImportServer: isAdmin,
      canViewServer,
      canUseCapability,
      canViewCapability,
      canPower: (serverId?: string) => canUseCapability(serverId, "power"),
      canConsole: (serverId?: string) => canUseCapability(serverId, "console"),
      canConsoleView: (serverId?: string) => canViewCapability(serverId, "console"),
      canFiles: (serverId?: string) => canUseCapability(serverId, "files"),
      canViewLogs: (serverId?: string) => canViewCapability(serverId, "files"),
      canManagePlugins: (serverId?: string) => canUseCapability(serverId, "plugins"),
      canViewPlugins: (serverId?: string) => canViewCapability(serverId, "plugins"),
      canBackups: (serverId?: string) => canUseCapability(serverId, "backups"),
      canViewBackups: (serverId?: string) => canViewCapability(serverId, "backups"),
      canSettings: (serverId?: string) => canUseCapability(serverId, "settings"),
      canManageExposure: (serverId?: string) => canUseCapability(serverId, "exposure"),
      canViewExposure: (serverId?: string) => canViewCapability(serverId, "exposure"),
      canVersioning: (serverId?: string) => canUseCapability(serverId, "versioning"),
      canViewVersioning: (serverId?: string) => canViewCapability(serverId, "versioning"),
    };
  }, [accessToken, cachedAuthMe, cachedCurrentUser, canQueryMe, meQuery.data, meQuery.isLoading]);
}
