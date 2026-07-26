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
}

export interface InstallPluginRequest {
  server_id: string;
  name: string;
  version: string;
  description?: string;
  author?: string;
  website?: string;
  dependencies?: string[];
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
  server_id: string;
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
}


