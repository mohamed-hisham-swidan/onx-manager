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



