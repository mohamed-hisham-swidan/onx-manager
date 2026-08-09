import type {
  ApiKeyCreateRequest,
  ApiKeyResponse,
  BackupResponse,
  CreateAlertRuleRequest,
  CreateBackupRequest,
  CreateUserRequest,
  HealthResponse,
  InstallModrinthPluginRequest,
  InstallModrinthPluginResponse,
  LoginRequest,
  LoginResponse,
  PluginResponse,
  PluginProjectResponse,
  PluginSearchResultResponse,
  PluginVersionsResponse,
  RefreshTokenRequest,
  SettingsResponse,
  SettingsUpdateRequest,
  SettingsUpdateResponse,

  UpdateUserRequest,
  UserResponse,
  VerifyBackupResponse,
} from "@/types";
import { useAuthStore } from "@/stores/authStore";
import type {
  CommandRequest,
  ConsoleResponse,
  ScanResult,
  ServerCreateRequest,
  ServerDetailResponse,
  ServerResponse,
  ServerUpdateRequest,
  SoftwareInfo,
} from "@/server_manager/types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public detail: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function createAuthenticatedApi() {
  const state = useAuthStore.getState();
  return createApiClient(
    window.location.origin,
    state.getAccessToken,
    async () => {
      const s = useAuthStore.getState();
      if (!s.refreshToken) return null;
      const api = createApiClient(window.location.origin, () => null);
      try {
        const result = await api.refreshToken({ refresh_token: s.refreshToken });
        s.setTokens(result.access_token, result.refresh_token, result.expires_in);
        return { accessToken: result.access_token, refreshToken: result.refresh_token, expiresIn: result.expires_in };
      } catch {
        s.logout();
        return null;
      }
    },
  );
}


interface RequestConfig {
  method?: string;
  body?: unknown;
  params?: Record<string, string | undefined>;
  cache?: RequestCache;
}

function buildUrl(base: string, path: string, params?: Record<string, string | undefined>): string {
  const url = new URL(path, base);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) url.searchParams.set(key, value);
    }
  }
  return url.toString();
}

export function createApiClient(
  baseUrl: string,
  getToken: () => string | null,
  onRefresh?: () => Promise<{ accessToken: string; refreshToken: string; expiresIn: number } | null>,
) {
  let refreshing: Promise<boolean> | null = null;

  async function refreshAuth(): Promise<boolean> {
    if (!onRefresh) return false;
    if (refreshing) return refreshing;
    refreshing = (async () => {
      try {
        const result = await onRefresh();
        return result !== null;
      } catch {
        return false;
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  async function request<T>(path: string, config: RequestConfig = {}): Promise<T> {
    const token = getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const url = buildUrl(baseUrl, path, config.params);

    let response: Response;
    try {
      response = await fetch(url, {
        method: config.method ?? "GET",
        headers,
        body: config.body ? JSON.stringify(config.body) : undefined,
        cache: config.cache ?? "no-store",
      });
    } catch {
      throw new ApiError(0, "NETWORK_ERROR", "Unable to reach server. Check your connection.");
    }

    if (response.status === 401 && onRefresh && path !== "/api/v1/auth/refresh") {
      const refreshed = await refreshAuth();
      if (refreshed) {
        const newToken = getToken();
        if (newToken) {
          headers["Authorization"] = `Bearer ${newToken}`;
          try {
            response = await fetch(url, {
              method: config.method ?? "GET",
              headers,
              body: config.body ? JSON.stringify(config.body) : undefined,
              cache: config.cache ?? "no-store",
            });
          } catch {
            throw new ApiError(0, "NETWORK_ERROR", "Unable to reach server. Check your connection.");
          }
        }
      }
    }

    console.debug(`%c${config.method ?? "GET"} %c${path} %c${response.status}`, "color:#64b5f6", "color:#e0e0e0", `color:${response.status < 400 ? "#81c784" : "#e57373"}`);

    if (response.status === 204) return undefined as T;

    let data: unknown;
    try {
      data = await response.json();
    } catch {
      if (!response.ok) {
        throw new ApiError(response.status, "UNKNOWN", `Request failed with status ${response.status}`);
      }
      throw new ApiError(0, "PARSE_ERROR", "Invalid response from server");
    }

    if (!response.ok) {
      const body = data as Record<string, unknown>;
      const errMsg =
        (body.error as string) ??
        ((body.detail as Record<string, unknown>)?.error as string) ??
        (typeof body.detail === "string" ? body.detail : null) ??
        "Request failed";
      const errCode =
        (body.error_code as string) ??
        ((body.detail as Record<string, unknown>)?.error_code as string) ??
        "UNKNOWN";
      const errDetail = (body.detail as Record<string, unknown>) ?? null;
      throw new ApiError(response.status, errCode, errMsg, errDetail);
    }

    return data as T;
  }

  return {
    // Health
    health: () => request<HealthResponse>("/health"),

    // Auth
    login: (body: LoginRequest) =>
      request<LoginResponse>("/api/v1/auth/login", { method: "POST", body }),
    refreshToken: (body: RefreshTokenRequest) =>
      request<LoginResponse>("/api/v1/auth/refresh", { method: "POST", body }),
    logout: (body: { refresh_token: string }) =>
      request<Record<string, unknown>>("/api/v1/auth/logout", { method: "POST", body }),
    getMe: () =>
      request<Record<string, unknown>>("/api/v1/auth/me"),
    listApiKeys: () =>
      request<ApiKeyResponse[]>("/api/v1/auth/api-keys"),
    createApiKey: (body: ApiKeyCreateRequest) =>
      request<ApiKeyResponse>("/api/v1/auth/api-keys", { method: "POST", body }),
    revokeApiKey: (apiKeyId: string) =>
      request<void>(`/api/v1/auth/api-keys/${apiKeyId}`, { method: "DELETE" }),

    // Users
    listUsers: () =>
      request<UserResponse[]>("/api/v1/users"),
    createUser: (body: CreateUserRequest) =>
      request<UserResponse>("/api/v1/users", { method: "POST", body }),
    getUser: (userId: string) =>
      request<UserResponse>(`/api/v1/users/${userId}`),
    updateUser: (userId: string, body: UpdateUserRequest) =>
      request<UserResponse>(`/api/v1/users/${userId}`, { method: "PATCH", body }),
    deleteUser: (userId: string) =>
      request<void>(`/api/v1/users/${userId}`, { method: "DELETE" }),

    // Servers
    listServers: (params?: { status?: string; group_id?: string; name_search?: string; minecraft_version?: string }) =>
      request<ServerResponse[]>("/api/v1/servers", { params }),
    createServer: (body: ServerCreateRequest) =>
      request<Record<string, unknown>>("/api/v1/servers", { method: "POST", body }),
    getServer: (serverId: string) =>
      request<ServerDetailResponse>(`/api/v1/servers/${serverId}`),
    updateServer: (serverId: string, body: ServerUpdateRequest) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}`, { method: "PATCH", body }),
    deleteServer: (serverId: string) =>
      request<void>(`/api/v1/servers/${serverId}`, { method: "DELETE" }),
    startServer: (serverId: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/start`, { method: "POST" }),
    stopServer: (serverId: string, reason?: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/stop`, { method: "POST", body: { reason: reason ?? "" } }),
    restartServer: (serverId: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/restart`, { method: "POST" }),
    getServerConsole: (serverId: string, tail?: number) =>
      request<ConsoleResponse>(`/api/v1/servers/${serverId}/console`, { params: { tail: tail?.toString() } }),
    sendServerCommand: (serverId: string, body: CommandRequest) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/command`, { method: "POST", body }),

    // Backups
    listBackups: (serverId?: string) =>
      request<BackupResponse[]>("/api/v1/backups", { params: { server_id: serverId } }),
    createBackup: (body: CreateBackupRequest) =>
      request<Record<string, unknown>>("/api/v1/backups", { method: "POST", body }),
    getBackup: (backupId: string) =>
      request<BackupResponse>(`/api/v1/backups/${backupId}`),
    deleteBackup: (backupId: string) =>
      request<void>(`/api/v1/backups/${backupId}`, { method: "DELETE" }),
    restoreBackup: (backupId: string) =>
      request<Record<string, unknown>>(`/api/v1/backups/${backupId}/restore`, { method: "POST" }),
    verifyBackup: (backupId: string) =>
      request<VerifyBackupResponse>(`/api/v1/backups/${backupId}/verify`, { method: "POST" }),

    // Plugins
    listPlugins: (serverId: string) =>
      request<PluginResponse[]>(`/api/v1/servers/${serverId}/plugins`),
    getPlugin: (serverId: string, pluginId: string) =>
      request<PluginResponse>(`/api/v1/servers/${serverId}/plugins/${pluginId}`),
    uninstallPlugin: (serverId: string, pluginId: string) =>
      request<void>(`/api/v1/servers/${serverId}/plugins/${pluginId}`, { method: "DELETE" }),
    enablePlugin: (serverId: string, pluginId: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/plugins/${pluginId}/enable`, { method: "POST" }),
    disablePlugin: (serverId: string, pluginId: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/plugins/${pluginId}/disable`, { method: "POST" }),

    // Plugin marketplace
    searchMarketplace: (serverId: string, query: string, projectType?: string, limit?: number, offset?: number) =>
      request<PluginSearchResultResponse[]>(`/api/v1/servers/${serverId}/plugins/marketplace/search`, {
        params: { query, project_type: projectType, limit: limit?.toString(), offset: offset?.toString() },
      }),
    // Global variant: server-independent marketplace search (no server_id in the path).
    searchMarketplaceGlobal: (query: string, projectType?: string, limit?: number, offset?: number) =>
      request<PluginSearchResultResponse[]>(`/api/v1/marketplace/search`, {
        params: { query, project_type: projectType, limit: limit?.toString(), offset: offset?.toString() },
      }),
    getMarketplaceProject: (projectId: string) =>
      request<PluginProjectResponse>(`/api/v1/marketplace/projects/${projectId}`),
    getProjectVersions: (serverId: string, projectId: string) =>
      request<PluginVersionsResponse>(`/api/v1/servers/${serverId}/plugins/marketplace/projects/${projectId}/versions`),
    installFromMarketplace: (serverId: string, body: InstallModrinthPluginRequest) =>
      request<InstallModrinthPluginResponse>(`/api/v1/servers/${serverId}/plugins/marketplace/install`, {
        method: "POST",
        body,
      }),

    // Monitoring
    getMetrics: (serverId: string, limit?: number) =>
      request<MetricsSnapshot[]>("/api/v1/monitoring/metrics", { params: { server_id: serverId, limit: limit?.toString() } }),
    listAlerts: () =>
      request<Record<string, unknown>[]>("/api/v1/monitoring/alerts"),
    createAlertRule: (body: CreateAlertRuleRequest) =>
      request<Record<string, unknown>>("/api/v1/monitoring/alerts", { method: "POST", body }),
    deleteAlertRule: (alertRuleId: string) =>
      request<void>(`/api/v1/monitoring/alerts/${alertRuleId}`, { method: "DELETE" }),

    // Schedules
    listSchedules: () =>
      request<Record<string, unknown>[]>("/api/v1/schedules"),
    createSchedule: (body: Record<string, unknown>) =>
      request<Record<string, unknown>>("/api/v1/schedules", { method: "POST", body }),
    deleteSchedule: (scheduleId: string) =>
      request<void>(`/api/v1/schedules/${scheduleId}`, { method: "DELETE" }),

    // Software catalog
    listSoftware: () =>
      request<SoftwareInfo[]>("/api/v1/software"),
    listSoftwareVersions: (softwareType: string) =>
      request<string[]>(`/api/v1/software/${softwareType}/versions`),

    // Servers
    getAvailablePort: () =>
      request<{ port: number }>("/api/v1/servers/available-port"),

    // Import
    scanDirectory: (path: string) =>
      request<ScanResult>("/api/v1/servers/scan", { method: "POST", body: { path } }),
    importServer: (body: Record<string, unknown>) =>
      request<Record<string, unknown>>("/api/v1/servers/import", { method: "POST", body }),

    // Settings
    getSettings: () =>
      request<SettingsResponse>("/api/v1/settings"),
    updateSettings: (body: SettingsUpdateRequest) =>
      request<SettingsUpdateResponse>("/api/v1/settings", { method: "PATCH", body }),
  };
}

export interface MetricsSnapshot {
  tps: number;
  players: number;
  ram_used_mb: number;
  cpu_percent: number;
  timestamp: string;
}


