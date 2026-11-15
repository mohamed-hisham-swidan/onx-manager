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
  PluginSearchResultsResponse,
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
  ActivityLogListResponse,
  AutoCommitLiveChangesRequest,
  AutoCommitLiveChangesResponse,
  BotSettings,
  BotSettingsRequest,
  BranchProtectionResponse,
  CommandRequest,
  ConsoleResponse,
  CrashReportSummary,
  CreateBranchRequest,
  CreateCommitRequest,
  CreateMaterializationRequest,
  CreateTagRequest,
  CreateTestDefinitionRequest,
  DiffResponse,
  EvidenceBundle,
  GetActivityParams,
  ImportReviewActionResponse,
  MaterializationCreateResponse,
  MaterializationFileResponse,
  MaterializationListItemResponse,
  MaterializationTreeResponse,
  PreflightStatus,
  PromoteCommitRequest,
  RunIsolatedTestRequest,
  ScanLiveChangesResponse,
  ScanResult,
  ServerBranch,
  ServerCommit,
  ServerCreateRequest,
  ServerDetailResponse,
  ServerImportRequest,
  ServerResponse,
  ServerTag,
  ServerTestRun,
  ServerUpdateRequest,
  SetBranchProtectionRequest,
  SetEditModeResponse,
  SoftwareInfo,
  TestDefinition,
} from "@/server_manager/types";
import type {
  CreateOperationRequest,
  OperationDetail,
  OperationSummary,
} from "@/operations/types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public detail: Record<string, unknown> | unknown[] | string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function isTokenExpiredOrNearExpiry(token: string | null, thresholdSeconds = 30): boolean {
  if (!token) return true;
  try {
    const parts = token.split(".");
    if (parts.length === 3) {
      const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
      if (typeof payload.exp === "number") {
        return Date.now() >= (payload.exp - thresholdSeconds) * 1000;
      }
    }
  } catch {
    // Non-JWT token
  }
  return false;
}

let sharedAuthenticatedApi: ReturnType<typeof createApiClient> | null = null;

export function resetAuthenticatedApi(): void {
  sharedAuthenticatedApi = null;
}

export function createAuthenticatedApi() {
  if (!sharedAuthenticatedApi) {
    const origin =
      typeof window !== "undefined" && window.location && window.location.origin
        ? window.location.origin
        : "http://localhost:8000";
    sharedAuthenticatedApi = createApiClient(
      origin,
      () => useAuthStore.getState().getAccessToken(),
      async () => {
        const s = useAuthStore.getState();
        if (!s.refreshToken) return null;
        const api = createApiClient(origin, () => null);
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
  return sharedAuthenticatedApi;
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
  isTokenExpiring?: (token: string | null) => boolean,
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
    const shouldProactivelyRefresh = isTokenExpiring
      ? isTokenExpiring(token)
      : (!token || isTokenExpiredOrNearExpiry(token, 30) || (useAuthStore.getState().isTokenExpiringSoon ? useAuthStore.getState().isTokenExpiringSoon(30) : false));

    if (
      shouldProactivelyRefresh &&
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
      let detailMsg: string | null = null;
      if (typeof body?.detail === "string") {
        detailMsg = body.detail;
      } else if (Array.isArray(body?.detail)) {
        detailMsg = body.detail
          .map((item) => {
            if (typeof item === "string") return item;
            if (item && typeof item === "object") {
              const obj = item as Record<string, unknown>;
              const msg = typeof obj.msg === "string" ? obj.msg : JSON.stringify(obj);
              const loc = Array.isArray(obj.loc) ? obj.loc.filter((l) => l !== "body").join(".") : "";
              return loc ? `${loc}: ${msg}` : msg;
            }
            return String(item);
          })
          .join("; ");
      } else if (body?.detail && typeof body.detail === "object") {
        detailMsg = ((body.detail as Record<string, unknown>).error as string) ?? null;
      }

      const errMsg =
        (body?.error as string) ??
        detailMsg ??
        "Request failed";
      const errCode =
        (body?.error_code as string) ??
        ((body?.detail as Record<string, unknown>)?.error_code as string) ??
        (response.status === 422 ? "VALIDATION_ERROR" : "UNKNOWN");
      const errDetail = (body?.detail as Record<string, unknown> | unknown[] | string | null) ?? null;
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
    retryProvisioning: (serverId: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/retry-provisioning`, { method: "POST" }),
    getServerConsole: (serverId: string, tail?: number) =>
      request<ConsoleResponse>(`/api/v1/servers/${serverId}/console`, { params: { tail: tail?.toString() } }),
    getServerCrashReports: (serverId: string, limit?: number) =>
      request<CrashReportSummary[]>(`/api/v1/servers/${serverId}/crash-reports`, {
        params: { limit: limit?.toString() },
      }),
    getServerActivity: (serverId: string, params?: GetActivityParams) =>
      request<ActivityLogListResponse>(`/api/v1/servers/${serverId}/activity`, {
        params: {
          limit: params?.limit?.toString(),
          offset: params?.offset?.toString(),
          event_type: params?.event_type,
          from_date: params?.from_date?.toString(),
          to_date: params?.to_date?.toString(),
        },
      }),

    // Versioning & Isolated Testing Subsystem
    getServerBranches: (serverId: string) =>
      request<ServerBranch[]>(`/api/v1/servers/${serverId}/versioning/branches`),
    createServerBranch: (serverId: string, body: CreateBranchRequest) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/branches`, {
        method: "POST",
        body,
      }),
    getServerCommits: (serverId: string, branchId?: string, limit?: number) =>
      request<ServerCommit[]>(`/api/v1/servers/${serverId}/versioning/commits`, {
        params: {
          branch_id: branchId,
          limit: limit?.toString(),
        },
      }),
    createServerCommit: (serverId: string, body: CreateCommitRequest) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/commits`, {
        method: "POST",
        body,
      }),
    runIsolatedTest: (serverId: string, body: RunIsolatedTestRequest) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/tests`, {
        method: "POST",
        body,
      }),
    getServerTestRuns: (serverId: string, limit?: number) =>
      request<ServerTestRun[]>(`/api/v1/servers/${serverId}/versioning/tests`, {
        params: { limit: limit?.toString() },
      }),
    getTestStatus: (serverId: string, testId: string) =>
      request<ServerTestRun>(`/api/v1/servers/${serverId}/versioning/tests/${testId}`),
    promoteTestCommit: (serverId: string, testId: string, body: PromoteCommitRequest) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/tests/${testId}/promote`, {
        method: "POST",
        body,
      }),
    discardTest: (serverId: string, testId: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/tests/${testId}/discard`, {
        method: "POST",
      }),
    getBotSettings: (serverId: string) =>
      request<BotSettings>(`/api/v1/servers/${serverId}/versioning/settings`),
    updateBotSettings: (serverId: string, body: BotSettingsRequest) =>
      request<BotSettings>(`/api/v1/servers/${serverId}/versioning/settings`, {
        method: "PUT",
        body,
      }),
    getPreflightStatus: (serverId: string, botCount?: number) =>
      request<PreflightStatus>(`/api/v1/servers/${serverId}/versioning/preflight`, {
        params: { bot_count: botCount?.toString() },
      }),

    // Branch Protection (Stage G)
    getBranchProtection: (serverId: string, branchName: string) =>
      request<BranchProtectionResponse>(
        `/api/v1/servers/${serverId}/versioning/branches/${encodeURIComponent(branchName)}/protection`,
      ),
    setBranchProtection: (serverId: string, branchName: string, body: SetBranchProtectionRequest) =>
      request<Record<string, unknown>>(
        `/api/v1/servers/${serverId}/versioning/branches/${encodeURIComponent(branchName)}/protection`,
        {
          method: "PUT",
          body,
        },
      ),
    removeBranchProtection: (serverId: string, branchName: string) =>
      request<Record<string, unknown>>(
        `/api/v1/servers/${serverId}/versioning/branches/${encodeURIComponent(branchName)}/protection`,
        {
          method: "DELETE",
        },
      ),

    // Test Definitions & Evidence (Stage F)
    getTestDefinitions: (serverId: string) =>
      request<TestDefinition[]>(`/api/v1/servers/${serverId}/versioning/test-definitions`),
    createTestDefinition: (serverId: string, body: CreateTestDefinitionRequest) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/test-definitions`, {
        method: "POST",
        body,
      }),
    updateTestDefinition: (
      serverId: string,
      definitionId: string,
      body: Partial<CreateTestDefinitionRequest>,
    ) =>
      request<Record<string, unknown>>(
        `/api/v1/servers/${serverId}/versioning/test-definitions/${definitionId}`,
        {
          method: "PUT",
          body,
        },
      ),
    deleteTestDefinition: (serverId: string, definitionId: string) =>
      request<Record<string, unknown>>(
        `/api/v1/servers/${serverId}/versioning/test-definitions/${definitionId}`,
        {
          method: "DELETE",
        },
      ),
    getTestEvidence: (serverId: string, testId: string) =>
      request<EvidenceBundle>(`/api/v1/servers/${serverId}/versioning/tests/${testId}/evidence`),

    // Materializations & Import Reviews (Stage C)
    getMaterializations: (serverId: string) =>
      request<MaterializationListItemResponse[]>(
        `/api/v1/servers/${serverId}/versioning/materializations`,
      ),
    createMaterialization: (serverId: string, body: CreateMaterializationRequest) =>
      request<MaterializationCreateResponse>(
        `/api/v1/servers/${serverId}/versioning/materializations`,
        {
          method: "POST",
          body,
        },
      ),
    deleteMaterialization: (serverId: string, matId: string) =>
      request<Record<string, unknown>>(
        `/api/v1/servers/${serverId}/versioning/materializations/${matId}`,
        {
          method: "DELETE",
        },
      ),
    setMaterializationMode: (serverId: string, matId: string, enabled: boolean) =>
      request<SetEditModeResponse>(
        `/api/v1/servers/${serverId}/versioning/materializations/${matId}/edit-mode`,
        {
          method: "POST",
          body: { enabled },
        },
      ),
    getMaterializationTree: (serverId: string, matId: string) =>
      request<MaterializationTreeResponse>(
        `/api/v1/servers/${serverId}/versioning/materializations/${matId}/tree`,
      ),
    getMaterializationFile: (serverId: string, matId: string, path: string) =>
      request<MaterializationFileResponse>(
        `/api/v1/servers/${serverId}/versioning/materializations/${matId}/files`,
        {
          params: { path },
        },
      ),
    writeMaterializationFile: (
      serverId: string,
      matId: string,
      path: string,
      content: string,
    ) =>
      request<Record<string, unknown>>(
        `/api/v1/servers/${serverId}/versioning/materializations/${matId}/files`,
        {
          method: "PUT",
          body: { path, content },
        },
      ),
    getLiveChanges: (serverId: string, source: string = "main") =>
      request<ScanLiveChangesResponse>(
        `/api/v1/servers/${serverId}/versioning/import-review/scan`,
        {
          method: "POST",
          body: { source },
        },
      ),
    autoCommitLiveChanges: (serverId: string, body?: AutoCommitLiveChangesRequest) =>
      request<AutoCommitLiveChangesResponse>(
        `/api/v1/servers/${serverId}/versioning/import-review/auto-commit`,
        {
          method: "POST",
          body: body || { branch: "main" },
        },
      ),
    confirmImportReview: (serverId: string, reviewId: string) =>
      request<ImportReviewActionResponse>(
        `/api/v1/servers/${serverId}/versioning/import-review/${encodeURIComponent(reviewId)}/confirm`,
        {
          method: "POST",
        },
      ),
    dismissImportReview: (serverId: string, reviewId: string) =>
      request<ImportReviewActionResponse>(
        `/api/v1/servers/${serverId}/versioning/import-review/${encodeURIComponent(reviewId)}/dismiss`,
        {
          method: "POST",
        },
      ),
    revertImportReview: (serverId: string, reviewId: string) =>
      request<ImportReviewActionResponse>(
        `/api/v1/servers/${serverId}/versioning/import-review/${encodeURIComponent(reviewId)}/revert`,
        {
          method: "POST",
        },
      ),

    // Branch Management, Tags & Diffing (Stage B)
    archiveBranch: (serverId: string, branchName: string) =>
      request<Record<string, unknown>>(
        `/api/v1/servers/${serverId}/versioning/branches/${encodeURIComponent(branchName)}/archive`,
        {
          method: "POST",
        },
      ),
    getServerTags: (serverId: string) =>
      request<ServerTag[]>(`/api/v1/servers/${serverId}/versioning/tags`),
    createTag: (serverId: string, body: CreateTagRequest) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/versioning/tags`, {
        method: "POST",
        body,
      }),
    diffCommits: (serverId: string, fromCommitId: string, toCommitId: string) =>
      request<DiffResponse>(`/api/v1/servers/${serverId}/versioning/commits/diff`, {
        params: { from: fromCommitId, to: toCommitId },
      }),

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
    uploadPluginOrMod: (serverId: string, file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return request<Record<string, unknown>>(`/api/v1/servers/${serverId}/plugins/upload`, {
        method: "POST",
        body: formData,
      });
    },
    toggleModState: (serverId: string, body: { mod_id?: string | null; plugin_id?: string | null; enabled: boolean }) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/plugins/toggle`, {
        method: "POST",
        body,
      }),

    // Plugin marketplace
    searchMarketplace: (serverId: string, query: string, projectType?: string, limit?: number, offset?: number, loader?: string) =>
      request<PluginSearchResultsResponse>(`/api/v1/servers/${serverId}/plugins/marketplace/search`, {
        params: { query, project_type: projectType, limit: limit?.toString(), offset: offset?.toString(), loader },
      }),
    // Global variant: server-independent marketplace search (no server_id in the path).
    searchMarketplaceGlobal: (query: string, projectType?: string, limit?: number, offset?: number, loader?: string) =>
      request<PluginSearchResultsResponse>(`/api/v1/marketplace/search`, {
        params: { query, project_type: projectType, limit: limit?.toString(), offset: offset?.toString(), loader },
      }),
    getMarketplaceProject: (projectId: string) =>
      request<PluginProjectResponse>(`/api/v1/marketplace/projects/${projectId}`),
    getMarketplaceProjectVersions: (projectId: string, limit?: number, offset?: number) =>
      request<PluginVersionsResponse>(`/api/v1/marketplace/projects/${projectId}/versions`, {
        params: { limit: limit?.toString(), offset: offset?.toString() },
      }),
    getProjectVersions: (serverId: string, projectId: string, limit?: number, offset?: number) =>
      request<PluginVersionsResponse>(`/api/v1/servers/${serverId}/plugins/marketplace/projects/${projectId}/versions`, {
        params: { limit: limit?.toString(), offset: offset?.toString() },
      }),
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
    scanDirectory: (import_id: string) =>
      request<ScanResult>("/api/v1/servers/scan", { method: "POST", body: { import_id } }),
    uploadImportZip: async (file: File, onProgress?: (percent: number) => void): Promise<ScanResult> => {
      const formData = new FormData();
      formData.append("file", file);

      let token = getToken();
      const shouldProactivelyRefresh = isTokenExpiring
        ? isTokenExpiring(token)
        : (!token || isTokenExpiredOrNearExpiry(token, 30) || (useAuthStore.getState().isTokenExpiringSoon ? useAuthStore.getState().isTokenExpiringSoon(30) : false));

      if (shouldProactivelyRefresh && onRefresh) {
        const refreshed = await refreshAuth();
        if (refreshed) {
          token = getToken();
        }
      }

      if (typeof XMLHttpRequest !== "undefined") {
        return new Promise<ScanResult>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          const url = buildUrl(baseUrl, "/api/v1/servers/import/upload");
          xhr.open("POST", url);

          if (token) {
            xhr.setRequestHeader("Authorization", `Bearer ${token}`);
          }

          if (xhr.upload && onProgress) {
            xhr.upload.onprogress = (event) => {
              if (event.lengthComputable) {
                const percent = Math.round((event.loaded / event.total) * 100);
                onProgress(percent);
              }
            };
          }

          xhr.onload = () => {
            let json: Record<string, unknown>;
            try {
              json = JSON.parse(xhr.responseText);
            } catch {
              if (xhr.status >= 200 && xhr.status < 300) {
                return reject(new ApiError(0, "PARSE_ERROR", "Invalid response from server"));
              }
              return reject(new ApiError(xhr.status, "UNKNOWN", `Request failed with status ${xhr.status}`));
            }

            if (xhr.status >= 200 && xhr.status < 300) {
              resolve(json as unknown as ScanResult);
            } else {
              const errMsg =
                typeof json?.detail === "string"
                  ? json.detail
                  : ((json?.error as string) || `Upload failed with status ${xhr.status}`);
              const errDetail = (json?.detail as Record<string, unknown> | unknown[] | string | null) ?? null;
              reject(new ApiError(xhr.status, "UPLOAD_FAILED", errMsg, errDetail));
            }
          };

          xhr.onerror = () => {
            reject(new ApiError(0, "NETWORK_ERROR", "Unable to reach server. Check your connection."));
          };

          xhr.send(formData);
        });
      }

      return request<ScanResult>("/api/v1/servers/import/upload", {
        method: "POST",
        body: formData,
      });
    },
    importServer: (body: ServerImportRequest) =>
      request<Record<string, unknown>>("/api/v1/servers/import", { method: "POST", body }),

    // Settings
    getSettings: () =>
      request<SettingsResponse>("/api/v1/settings"),
    updateSettings: (body: SettingsUpdateRequest) =>
      request<SettingsUpdateResponse>("/api/v1/settings", { method: "PATCH", body }),

    // Files
    listServerFiles: (serverId: string, path?: string, branch?: string) =>
      request<import("@/server_manager/types").FileItem[]>(`/api/v1/servers/${serverId}/files`, { params: { path, branch } }),
    readServerFileContent: (serverId: string, path: string, branch?: string) =>
      request<import("@/server_manager/types").FileContentResponse>(`/api/v1/servers/${serverId}/files/content`, { params: { path, branch } }),
    writeServerFileContent: (serverId: string, path: string, content: string, branch?: string) =>
      request<Record<string, unknown>>(`/api/v1/servers/${serverId}/files/content`, { method: "PUT", params: { path, branch }, body: { content } }),
    deleteServerFile: (serverId: string, path: string, branch?: string) =>
      request<void>(`/api/v1/servers/${serverId}/files`, { method: "DELETE", params: { path, branch } }),
    uploadServerFile: (serverId: string, path: string, file: File, branch?: string) => {
      const formData = new FormData();
      formData.append("file", file);
      return request<Record<string, unknown>>(`/api/v1/servers/${serverId}/files/upload`, { method: "POST", params: { path, branch }, body: formData });
    },
    downloadServerFile: (serverId: string, path: string, branch?: string) =>
      request<Blob>(`/api/v1/servers/${serverId}/files/download`, { params: { path, branch }, responseType: "blob" }),
    mkdirServerDirectory: (serverId: string, path: string, folderName?: string, branch?: string) => {
      const fullPath = folderName
        ? (path ? `${path.replace(/\/+$/, "")}/${folderName.replace(/^\/+/, "")}` : folderName)
        : path;
      return request<Record<string, unknown>>(`/api/v1/servers/${serverId}/files/mkdir`, {
        method: "POST",
        params: { path: fullPath, branch },
      });
    },

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
      request<VerifyInviteResponse>("/api/v1/invites/verify", {
        method: "POST",
        body: { token },
      }),
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

    // Operations (Phase 5.5 Stage A)
    createOperation: (body: CreateOperationRequest, idempotencyKey?: string) =>
      request<OperationDetail>("/api/v1/operations", {
        method: "POST",
        body,
        headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
      }),
    getOperation: (operationId: string) =>
      request<OperationDetail>(`/api/v1/operations/${operationId}`),
    listOperations: (params?: { target_type?: string; target_id?: string; status?: string; limit?: number }) =>
      request<OperationSummary[]>("/api/v1/operations", {
        params: params
          ? {
              target_type: params.target_type,
              target_id: params.target_id,
              status: params.status,
              limit: params.limit !== undefined ? String(params.limit) : undefined,
            }
          : undefined,
      }),
    cancelOperation: (operationId: string, idempotencyKey?: string) =>
      request<OperationDetail>(`/api/v1/operations/${operationId}/cancel`, {
        method: "POST",
        headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
      }),
    retryOperation: (operationId: string, idempotencyKey?: string) =>
      request<OperationDetail>(`/api/v1/operations/${operationId}/retry`, {
        method: "POST",
        headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
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


