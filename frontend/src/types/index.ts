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
}

export interface CreateBackupRequest {
  server_id: string;
  backup_type?: string;
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
  wiki_url: string;
  source_url: string;
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
}

export interface InstallModrinthPluginRequest {
  project_id: string;
  version_id?: string | null;
  minecraft_version?: string | null;
}

export interface InstallModrinthPluginResponse {
  plugin_id: string;
  version: string;
  filename: string;
  source: string;
  notice: string;
  notice_kind: string;
}

export interface LoginRequest {
  email: string;
  password: string;
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
  email: string;
  display_name: string;
  is_active: boolean;
  roles: string[];
  created_at: string;
  last_login_at: string | null;
}

export interface CreateUserRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface UpdateUserRequest {
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
  requires_restart?: string[];
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
}

export interface SettingsUpdateResponse {
  success: boolean;
  message: string;
  requires_restart: string[];
  settings: SettingsResponse;
}

export interface SystemStatusResponse {
  initialized: boolean;
  access_mode: "LOCAL" | "GLOBAL";
  user_count: number;
  version: string;
}

export interface BootstrapRequest {
  email: string;
  password: string;
  display_name: string;
  access_mode: "LOCAL" | "GLOBAL";
}

export interface BootstrapResponse {
  success: boolean;
  message: string;
  user_id: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CurrentUserResponse {
  user_id: string;
  email: string;
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
  email: string;
  password: string;
  display_name: string;
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


