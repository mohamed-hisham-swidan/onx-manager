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
  SystemStatusResponse,
  BootstrapRequest,
  BootstrapResponse,
  CreateInviteRequest,
  CreateInviteResponse,
  VerifyInviteResponse,
  AcceptInviteRequest,
  AcceptInviteResponse,
  InvitationItem,
  CurrentUserResponse,
  PanelExposureResponse,
  PanelExposureUpdateRequest,
  AgentStatusResponse,
  ClaimResponse,
  ServerExposureResponse,
  ServerExposureUpdateRequest,
  ServerExposureStateUpdateRequest,
  TargetResponse,
  TargetCreateRequest,
  TargetUpdateRequest,
  RegisteredPortResponse,
  RegisteredPortCreateRequest,
  StopAllResponse,
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
  responseType?: "json" | "blob" | "text";
  headers?: Record<string, string>;
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
    let token = getToken();

    // Proactively refresh expired token before making authenticated request
    if (
      !token &&
      onRefresh &&
      path !== "/api/v1/auth/refresh" &&
      path !== "/api/v1/auth/login" &&
      !path.startsWith("/api/v1/invites/verify")
    ) {
      const refreshed = await refreshAuth();
      if (refreshed) {
        token = getToken();
      }
    }

    const headers: Record<string, string> = {
      ...config.headers,
    };
    if (!headers["Content-Type"] && !(config.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const url = buildUrl(baseUrl, path, config.params);

    let response: Response;
    try {
      response = await fetch(url, {
        method: config.method ?? "GET",
        headers,
        body: config.body instanceof FormData ? config.body : (typeof config.body === "string" ? config.body : (config.body ? JSON.stringify(config.body) : undefined)),
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
              body: config.body instanceof FormData ? config.body : (typeof config.body === "string" ? config.body : (config.body ? JSON.stringify(config.body) : undefined)),
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
      if (config.responseType === "blob") {
        data = await response.blob();
      } else if (config.responseType === "text") {
        data = await response.text();
      } else {
        data = await response.json();
      }
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
      request<CurrentUserResponse>("/api/v1/auth/me"),
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
    getServerRuntime: (serverId: string) =>
      request<import("@/server_manager/types").RuntimeDiagnosticsResponse>(`/api/v1/servers/${serverId}/runtime`),
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
    createAlertRule: (serverId: string, body: CreateAlertRuleRequest) =>
      request<Record<string, unknown>>(`/api/v1/monitoring/alerts/${serverId}`, { method: "POST", body }),
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

    // Files
    listServerFiles: (serverId: string, path?: string) =>
      request<import("@/server_manager/types").FileItem[]>(`/api/v1/servers/${serverId}/files/`, { params: { path } }),
    readServerFileContent: (serverId: string, path: string) =>
      request<string>(`/api/v1/servers/${serverId}/files/content`, { params: { path }, responseType: "text" }),
    writeServerFileContent: (serverId: string, path: string, content: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/files/content`, { method: "POST", params: { path }, body: { content } }),
    deleteServerFile: (serverId: string, path: string) =>
      request<void>(`/api/v1/servers/${serverId}/files/`, { method: "DELETE", params: { path } }),
    uploadServerFile: (serverId: string, path: string, file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return request<Record<string, unknown>>(`/api/v1/servers/${serverId}/files/upload`, { method: "POST", params: { path }, body: formData });
    },
    downloadServerFile: (serverId: string, path: string) =>
      request<Blob>(`/api/v1/servers/${serverId}/files/download`, { params: { path }, responseType: "blob" }),
    mkdirServerDirectory: (serverId: string, path: string, folderName: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/files/mkdir`, { method: "POST", params: { path }, body: { folder_name: folderName } }),

    // Setup & Invites
    getSetupStatus: () =>
      request<SystemStatusResponse>("/api/v1/setup/status"),
    bootstrapInstance: (body: BootstrapRequest) =>
      request<BootstrapResponse>("/api/v1/setup/bootstrap", { method: "POST", body }),
    updateAccessMode: (body: { access_mode: string }) =>
      request<SystemStatusResponse>("/api/v1/setup/access-mode", { method: "PUT", body }),
    listInvites: () =>
      request<InvitationItem[]>("/api/v1/invites"),
    createInvite: (body: CreateInviteRequest) =>
      request<CreateInviteResponse>("/api/v1/invites", { method: "POST", body }),
    revokeInvite: (inviteId: string) =>
      request<void>(`/api/v1/invites/${inviteId}`, { method: "DELETE" }),
    verifyInvite: (token: string) =>
      request<VerifyInviteResponse>(`/api/v1/invites/verify/${token}`),
    acceptInvite: (body: AcceptInviteRequest) =>
      request<AcceptInviteResponse>("/api/v1/invites/accept", { method: "POST", body }),

    // Exposure - Panel & Agent
    getPanelExposure: () =>
      request<PanelExposureResponse>("/api/v1/exposure/panel"),
    setPanelExposure: (body: PanelExposureUpdateRequest) =>
      request<PanelExposureResponse>("/api/v1/exposure/panel", {
        method: "PUT",
        body,
      }),
    getAgentStatus: () =>
      request<AgentStatusResponse>("/api/v1/exposure/agent"),
    generateClaim: () =>
      request<ClaimResponse>("/api/v1/exposure/agent/claim", {
        method: "POST",
      }),
    resetAgent: () =>
      request<AgentStatusResponse>("/api/v1/exposure/agent/reset", {
        method: "POST",
      }),

    // Server Exposure & Targets (Phase 7.5)
    getServerExposure: (serverId: string) =>
      request<ServerExposureResponse>(`/api/v1/servers/${serverId}/exposure`),
    setServerExposure: (serverId: string, body: ServerExposureUpdateRequest) =>
      request<ServerExposureResponse>(`/api/v1/servers/${serverId}/exposure`, {
        method: "PUT",
        body,
      }),
    setServerExposureState: (serverId: string, body: ServerExposureStateUpdateRequest) =>
      request<ServerExposureResponse>(`/api/v1/servers/${serverId}/exposure`, {
        method: "PATCH",
        body,
      }),
    removeServerExposure: (serverId: string) =>
      request<void>(`/api/v1/servers/${serverId}/exposure`, {
        method: "DELETE",
      }),
    listExposureTargets: (serverId: string) =>
      request<TargetResponse[]>(`/api/v1/servers/${serverId}/exposure/targets`),
    createExposureTarget: (serverId: string, body: TargetCreateRequest) =>
      request<TargetResponse>(`/api/v1/servers/${serverId}/exposure/targets`, {
        method: "POST",
        body,
      }),
    updateExposureTarget: (serverId: string, targetId: string, body: TargetUpdateRequest) =>
      request<TargetResponse>(`/api/v1/servers/${serverId}/exposure/targets/${targetId}`, {
        method: "PUT",
        body,
      }),
    deleteExposureTarget: (serverId: string, targetId: string) =>
      request<void>(`/api/v1/servers/${serverId}/exposure/targets/${targetId}`, {
        method: "DELETE",
      }),
    listServerPorts: (serverId: string) =>
      request<RegisteredPortResponse[]>(`/api/v1/servers/${serverId}/ports`),
    registerServerPort: (serverId: string, body: RegisteredPortCreateRequest) =>
      request<RegisteredPortResponse>(`/api/v1/servers/${serverId}/ports`, {
        method: "POST",
        body,
      }),
    deleteServerPort: (serverId: string, portId: string) =>
      request<void>(`/api/v1/servers/${serverId}/ports/${portId}`, {
        method: "DELETE",
      }),

    // Global Exposure Actions (Owner-Only)
    stopAllExposures: () =>
      request<StopAllResponse>("/api/v1/exposure/stop-all", {
        method: "POST",
      }),
    removeCredentials: () =>
      request<{ status: string }>("/api/v1/exposure/credentials/remove", {
        method: "POST",
      }),
  };
}

export interface MetricsSnapshot {
  tps: number | null;
  players: number;
  ram_used_mb: number;
  cpu_percent: number;
  timestamp: string;
}


