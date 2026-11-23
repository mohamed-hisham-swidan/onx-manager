export interface BackupResponse {
  backup_id: string;
  server_id: string;
  backup_type: string;
  status: string;
  size_bytes: number;
  checksum: string;
  error_message: string;
  created_at: string;
  completed_at: string | null;
  tier: "tier_1" | "tier_2" | string;
  pinned: boolean;
}

export interface CreateBackupRequest {
  server_id: string;
  backup_type?: string;
  tier?: "tier_1" | "tier_2";
  archive_format?: "tar.zst" | "tar.gz";
  include_cas_jars?: boolean;
}

export interface ConvertToAdvancedResponse {
  server_id: string;
  mode: "advanced";
  main_commit_sha: string;
  backup_id: string;
  cas_ingested: number;
}

export interface ConvertToSimpleRequest {
  name: string;
  port?: number;
}

export interface ConvertToSimpleResponse {
  new_server_id: string;
  name: string;
}

export interface VerifyBackupResponse {
  backup_id: string;
  valid: boolean;
  checksum_valid: boolean;
  size_valid: boolean;
}

export type PluginSource = "manual" | "modrinth" | "detected";

export interface PluginResponse {
  plugin_id: string;
  server_id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  status: string;
  dependencies: string[];
  installed_at: string;
  updated_at: string;
  source?: PluginSource;
  filename?: string | null;
  pending_deletion?: boolean;
  pending_deletion_requested_at?: string | null;
  external_project_id?: string | null;
  external_version_id?: string | null;
  external_url?: string | null;
  checksum?: string | null;
  icon_url?: string | null;
  loader?: string | null;
  mod_id?: string | null;
  is_disabled_on_disk?: boolean;
  warning?: string | null;
  branch_name?: string | null;
  is_committed?: boolean;
}

export interface ToggleModStateRequest {
  mod_id?: string | null;
  plugin_id?: string | null;
  enabled: boolean;
}

export interface PluginSearchResultResponse {
  project_id: string;
  slug: string;
  title: string;
  description: string;
  author: string;
  project_types: string[];
  downloads: number;
  follows: number;
  icon_url: string | null;
  latest_version_id: string;
  categories: string[];
  loaders: string[];
  client_side: string | null;
  server_side: string | null;
  date_modified: string;
  color: number | null;
}

export interface PluginSearchResultsResponse {
  items: PluginSearchResultResponse[];
  total_hits: number;
  offset: number;
  limit: number;
}

export interface PluginProjectResponse {
  project_id: string;
  slug: string;
  title: string;
  description: string;
  body: string;
  author: string;
  project_types: string[];
  loaders: string[];
  game_versions: string[];
  downloads: number;
  follows: number;
  icon_url: string | null;
  wiki_url: string | null;
  source_url: string | null;
  client_side?: string | null;
  server_side?: string | null;
}

export interface PluginFileResponse {
  url: string;
  filename: string;
  size_bytes: number;
  sha1: string;
  sha512: string;
  primary: boolean;
}

export interface PluginVersionResponse {
  version_id: string;
  project_id: string;
  name: string;
  version_number: string;
  game_versions: string[];
  loaders: string[];
  files: PluginFileResponse[];
  dependencies: string[];
  date_published: string;
}

export interface PluginVersionsResponse {
  project_id: string;
  versions: PluginVersionResponse[];
  selected: PluginVersionResponse | null;
  notice: string;
  notice_kind: string;
  total: number;
}

export interface InstallModrinthPluginRequest {
  project_id: string;
  version_id?: string | null;
  minecraft_version?: string | null;
  branch?: string | null;
}

export interface InstallModrinthPluginResponse {
  plugin_id: string;
  version: string;
  filename: string;
  source: string;
  notice: string;
  notice_kind: string;
  branch_name?: string | null;
  is_committed?: boolean;
}

export interface LoginRequest {
  username: string;
  password: string;
  email?: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface RefreshTokenRequest {
  refresh_token: string;
}

export interface ApiKeyCreateRequest {
  name: string;
  permissions?: string[];
}

export interface ApiKeyResponse {
  api_key_id: string;
  name: string;
  prefix: string;
  key: string | null;
  permissions: string[];
  expires_at: string | null;
  is_revoked: boolean;
  created_at: string;
}

export interface UserResponse {
  user_id: string;
  username?: string;
  email: string | null;
  display_name: string;
  is_active: boolean;
  roles: string[];
  created_at: string;
  last_login_at: string | null;
}

export interface CreateUserRequest {
  username: string;
  password: string;
  display_name?: string;
  email?: string | null;
}

export interface UpdateUserRequest {
  username?: string | null;
  email?: string | null;
  display_name?: string | null;
  is_active?: boolean | null;
}

export interface ErrorResponse {
  error: string;
  error_code: string;
  detail: Record<string, unknown> | null;
  timestamp: string | null;
}

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  uptime_seconds: number | null;
  docker?: boolean;
}

export interface CreateAlertRuleRequest {
  metric_name: string;
  condition?: string;
  threshold: number;
  severity?: string;
  cooldown_minutes?: number;
}

export interface SettingsResponse {
  app_name: string;
  version: string;
  debug: boolean;
  log_level: string;
  rate_limit_per_minute: number;
  idempotency_ttl_hours: number;
  circuit_breaker_max_failures: number;
  circuit_breaker_timeout_seconds: number;
  event_bus_retry_attempts: number;
  saga_timeout_seconds: number;
  metrics_interval_seconds?: number;
  server_startup_timeout_seconds?: number;
  test_boot_timeout_seconds?: number;
  host_ram_reserve_mb?: number;
  host_cpu_reserve?: number;
  requires_restart?: string[];
}

export interface HostResourceAllocation {
  id: string;
  name: string;
  kind: "server" | "branch_runtime" | "test_run";
  status: string;
  ram_mb: number;
  cpu_cores: number;
}

export interface HostResourceBudget {
  total_ram_mb: number;
  os_reserve_ram_mb: number;
  allocatable_ram_mb: number;
  allocated_ram_mb: number;
  available_ram_mb: number;
  total_cpus: number;
  reserved_cpus: number;
  allocatable_cpus: number;
  allocated_cpus: number;
  available_cpus: number;
  profile: "local" | "vps" | string;
  ram_reserve_override_mb: number;
  cpu_reserve_override: number;
  allocations: HostResourceAllocation[];
}

export interface SettingsUpdateRequest {
  app_name?: string;
  debug?: boolean;
  log_level?: string;
  rate_limit_per_minute?: number;
  idempotency_ttl_hours?: number;
  circuit_breaker_max_failures?: number;
  circuit_breaker_timeout_seconds?: number;
  event_bus_retry_attempts?: number;
  saga_timeout_seconds?: number;
  metrics_interval_seconds?: number;
  server_startup_timeout_seconds?: number;
  test_boot_timeout_seconds?: number;
  host_ram_reserve_mb?: number;
  host_cpu_reserve?: number;
}

export interface SettingsUpdateResponse {
  success: boolean;
  message: string;
  requires_restart: string[];
  settings: SettingsResponse;
}

export type DeploymentProfile = "local" | "vps";
export type AuthMode = "local_zero_login" | "jwt";

export interface SystemStatusResponse {
  initialized: boolean;
  access_mode: "LOCAL" | "GLOBAL";
  user_count: number;
  version: string;
  advanced_mode_enabled?: boolean;
  deployment_profile?: DeploymentProfile;
  password_configured?: boolean;
  auth_mode?: AuthMode;
}

export interface BootstrapRequest {
  username: string;
  password: string;
  display_name?: string;
  email?: string | null;
  access_mode: "LOCAL" | "GLOBAL";
}

export interface ConfigureCredentialsRequest {
  username: string;
  password: string;
  display_name?: string;
  email?: string | null;
}

export interface BootstrapResponse {
  success: boolean;
  message: string;
  user_id: string;
  username?: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CurrentUserResponse {
  user_id: string;
  username?: string;
  email: string | null;
  display_name: string;
  is_active: boolean;
  roles: string[];
  created_at: string;
  last_login_at: string | null;
}


export interface CreateInviteRequest {
  email?: string | null;
  global_role?: string;
  server_id?: string | null;
  server_role?: string | null;
  max_uses?: number;
  expires_in_hours?: number | null;
}

export interface CreateInviteResponse {
  invite_id: string;
  token: string;
  token_prefix: string;
  email: string | null;
  global_role: string;
  server_id: string | null;
  server_role: string | null;
  status: string;
  max_uses: number;
  expires_at: string | null;
}

export interface VerifyInviteResponse {
  valid: boolean;
  email: string | null;
  expires_at: string | null;
}

export interface AcceptInviteRequest {
  token: string;
  username: string;
  password: string;
  display_name?: string;
  email?: string | null;
}

export interface AcceptInviteResponse {
  user_id: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface InvitationItem {
  invite_id: string;
  token_prefix: string;
  email: string | null;
  global_role: string;
  server_id: string | null;
  server_role: string | null;
  creator_id: string;
  status: string;
  max_uses: number;
  use_count: number;
  expires_at: string | null;
  created_at: string;
}

export type PanelExposureMethodType = "none" | "cloudflare_tunnel" | "playit_http" | "port_forward";

export type CloudflareModeType = "token" | "quick";

export type DesiredStateType = "ENABLED" | "DISABLED";

export type ExposureStatusType =
  | "DISABLED"
  | "STARTING"
  | "ACTIVE"
  | "STOPPING"
  | "STOPPED"
  | "DEGRADED"
  | "ERROR"
  | "RECLAIM_REQUIRED"
  | "CLAIM_REQUIRED";

export interface PanelExposureResponse {
  method: PanelExposureMethodType;
  desired_state: DesiredStateType;
  status: ExposureStatusType;
  public_address: string | null;
  tls: boolean;
  protocol: "http" | "https";
  external_port: number | null;
  cloudflare_tunnel_id: string | null;
  cloudflare_mode?: CloudflareModeType | null;
  token_configured?: boolean;
  ephemeral?: boolean;
  playit_tunnel_id: string | null;
  upnp_last_result: string | null;
  error_code: string | null;
  error_message: string | null;
  fix_hint: string | null;
  auto_fixed: boolean;
  security_advisory: string | null;
}

export interface PanelExposureUpdateRequest {
  method: PanelExposureMethodType;
  desired_state: DesiredStateType;
  cloudflare_mode?: CloudflareModeType;
  cloudflare_token?: string;
  hostname?: string;
  external_port?: number | null;
}

export interface AgentStatusResponse {
  claimed: boolean;
  process_status: string;
  desired_agent_running: boolean;
  last_health_at: string | null;
  claim_active: boolean;
  claim_expires_at: string | null;
}

export interface ClaimResponse {
  claim_code: string;
  claim_url: string;
  expires_at: string;
}

// Server Network Exposure & Targets (Phase 7.5)
export type ExposureMethodType = "none" | "host_port" | "playit" | "port_forward" | "cloudflare_tcp";

export type TargetProtocolType = "tcp" | "udp";

export type ServiceType = "java" | "bedrock" | "voice" | "bluemap";

export interface TargetResponse {
  id: string;
  exposure_id: string;
  protocol: TargetProtocolType;
  service_type: ServiceType;
  local_port: number;
  public_address: string | null;
  status: ExposureStatusType;
  error_code: string | null;
  error_message: string | null;
  dashboard_url: string | null;
  setup_instructions: string | null;
}

export interface ServerExposureResponse {
  server_id: string;
  branch_name?: string;
  branch_runtime_status?: string | null;
  allocated_game_port?: number | null;
  allocated_port_set?: {
    game_port: number;
    rcon_port: number;
    query_port?: number | null;
    plugin_ports?: Record<string, number>;
  } | null;
  method: ExposureMethodType;
  desired_state: DesiredStateType;
  aggregate_status: ExposureStatusType;
  error_code: string | null;
  error_message: string | null;
  cloudflare_tunnel_id: string | null;
  has_cloudflare_credentials: boolean;
  cloudflare_mode?: "quick" | "subdomain" | "tcp" | null;
  subdomain_prefix?: string | null;
  base_domain?: string | null;
  srv_record_enabled?: boolean;
  srv_record_hint?: string | null;
  ephemeral?: boolean;
  upnp_status?: string | null;
  detected_wan_ip?: string | null;
  targets: TargetResponse[];
}

export interface ServerExposureUpdateRequest {
  method: ExposureMethodType;
  desired_state: DesiredStateType;
  cloudflare_mode?: "quick" | "subdomain" | "tcp" | null;
  cloudflare_token?: string;
  hostname?: string;
  subdomain_prefix?: string | null;
  base_domain?: string | null;
  srv_record_enabled?: boolean;
  external_port?: number | null;
  acknowledged_warning?: boolean;
}

export interface ServerExposureStateUpdateRequest {
  desired_state: DesiredStateType;
  cloudflare_token?: string;
  hostname?: string;
  acknowledged_warning?: boolean;
}

export interface TargetCreateRequest {
  service_type: ServiceType;
  protocol?: TargetProtocolType;
  local_port?: number;
  public_address?: string;
}

export interface TargetUpdateRequest {
  public_address: string;
}

export interface RegisteredPortResponse {
  id: string;
  server_id: string;
  service_type: ServiceType;
  protocol: TargetProtocolType;
  port: number;
  name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RegisteredPortCreateRequest {
  service_type: Exclude<ServiceType, "java">;
  protocol: TargetProtocolType;
  port: number;
  name?: string;
}

export interface StopAllResponse {
  disabled_count: number;
}

export const SERVICE_METADATA: Record<ServiceType, {
  label: string;
  defaultProtocol: TargetProtocolType;
  defaultPort: number;
  description: string;
  isPrimary: boolean;
}> = {
  java: {
    label: "Java Edition",
    defaultProtocol: "tcp",
    defaultPort: 25565,
    description: "Standard Minecraft Java game protocol (TCP). Port bound to Server Configuration.",
    isPrimary: true,
  },
  bedrock: {
    label: "Bedrock Edition (Geyser)",
    defaultProtocol: "udp",
    defaultPort: 19132,
    description: "Minecraft Bedrock RakNet protocol (UDP) for cross-play.",
    isPrimary: false,
  },
  voice: {
    label: "Simple Voice Chat",
    defaultProtocol: "udp",
    defaultPort: 24454,
    description: "In-game proximity voice chat protocol (UDP).",
    isPrimary: false,
  },
  bluemap: {
    label: "BlueMap Web Map",
    defaultProtocol: "tcp",
    defaultPort: 8100,
    description: "3D browser map viewer (HTTP/TCP).",
    isPrimary: false,
  },
};

export const DENY_LIST_PORTS: ReadonlySet<number> = new Set([
  25575, // RCON default
  3306,  // MySQL
  5432,  // PostgreSQL
  6379,  // Redis
  27017, // MongoDB
  9090,  // Prometheus metrics
  9100,  // Node exporter
]);

export function validateLocalPort(port: number, serverGamePort: number): { valid: boolean; error?: string } {
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return { valid: false, error: "Port must be a valid number between 1 and 65535." };
  }
  if (DENY_LIST_PORTS.has(port)) {
    return { valid: false, error: `Port ${port} is reserved for internal management/database services and cannot be exposed.` };
  }
  if (port === serverGamePort) {
    return { valid: false, error: `Port ${port} is already assigned to the primary Java game server.` };
  }
  return { valid: true };
}



// P5.5 shared re-exports (single source of truth lives in server_manager/types)
export type {
  ApplyUpgradeRequest,
  CompatibilityMatrixPayload,
  CurseForgeIntegrationKeySetRequest,
  CurseForgeIntegrationStatusResponse,
  InstallPlanFileItem,
  InstallPlanOverrideItem,
  InstallPlanPayload,
  LecEntryResponse,
  LecGcRequest,
  LecGcResponse,
  LecPrewarmRequest,
  LecPrewarmResponse,
  ManualDownloadBlockerItem,
  MatrixEntryItem,
  MatrixStatusType,
  ModpackInspectResponse,
  ModpackInstallRequest,
  ModpackInstallResponse,
  P55LoaderId,
  PlanUpgradeRequest,
  PrepareUpgradeTestRequest,
  PrepareUpgradeTestResponse,
  RollbackUpgradeRequest,
  ServerP55SettingsResponse,
  ServerP55SettingsUpdateRequest,
  ServerUpgradeListResponse,
  ServerUpgradeResponse,
} from "@/server_manager/types";
