export interface SoftwareInfo {
  type: string;
  name: string;
  description: string;
  url: string;
  supports_versions: boolean;
}

export interface ServerResponse {
  server_id: string;
  name: string;
  server_type: string;
  minecraft_version: string;
  status: string;
  group_id: string;
  port: number;
  motd: string;
  max_players: number;
  gamemode: string;
  difficulty: string;
  created_at: string;
  updated_at: string;
  provisioning_error?: string | null;
  provisioning_retryable?: boolean;
}

export interface ServerDetailResponse extends ServerResponse {
  min_memory_mb: number;
  max_memory_mb: number;
  java_args: string;
  cpu_cores?: number;
  cpu_affinity?: string;
  raw_properties?: Record<string, string>;
  spawn_protection: number;
  pvp: boolean;
  enable_command_block: boolean;
  online_mode: boolean;
  whitelist: boolean;
  view_distance: number;
  simulation_distance: number;
  provider: string | null;
  deployment_host: string | null;
  deployment_port: number | null;
  deployment_pid: number | null;
  location_type: string | null;
  location_uri: string | null;
  root_path: string | null;
  working_directory: string | null;
  startup_jar: string | null;
  startup_command: string | null;
  primary_world: string | null;
}

export interface PluginInfo {
  filename: string;
  size_bytes: number;
  name: string;
  version: string;
  main: string;
  api_version: string;
}

export interface ModInfo {
  filename: string;
  size_bytes: number;
  name: string;
  version: string;
}

export interface WorldInfo {
  name: string;
  path: string;
  size_bytes: number;
}

export interface ServerPropertiesInfo {
  port: number;
  motd: string;
  max_players: number;
  gamemode: string;
  difficulty: string;
  spawn_protection: number;
  pvp: boolean;
  enable_command_block: boolean;
  online_mode: boolean;
  whitelist: boolean;
  view_distance: number;
  simulation_distance: number;
}

export interface ScanResult {
  path: string;
  name: string;
  server_name_declared?: boolean;
  server_type: string;
  minecraft_version: string;
  eula_accepted: boolean;
  server_jar: string | null;
  jar_size_bytes: number;
  properties: ServerPropertiesInfo;
  plugins: PluginInfo[];
  mods: ModInfo[];
  worlds: WorldInfo[];
  icon: string | null;
  ops: string[];
  banned_players: string[];
  whitelisted_players: string[];
}

export interface ServerCreateRequest {
  name: string;
  server_type?: string;
  minecraft_version?: string;
  min_memory_mb?: number;
  max_memory_mb?: number;
  port?: number;
  motd?: string;
  max_players?: number;
  gamemode?: string;
  difficulty?: string;
  spawn_protection?: number;
  pvp?: boolean;
  enable_command_block?: boolean;
  online_mode?: boolean;
  whitelist?: boolean;
  view_distance?: number;
  simulation_distance?: number;
  java_args?: string[] | null;
  group_id?: string;
  provider?: string;
}

export interface ServerUpdateRequest {
  name?: string;
  properties?: Record<string, unknown>;
  min_memory_mb?: number | null;
  max_memory_mb?: number | null;
  cpu_cores?: number | null;
  cpu_affinity?: string | null;
  java_args?: string[] | null;
}

export interface ConsoleResponse {
  server_id: string;
  lines: string[];
}

export interface CommandRequest {
  command: string;
}

export interface ServerActionRequest {
  reason?: string;
}

export type StatusBadge = { label: string; color: string };

export interface ExposureStatusBadgeConfig {
  label: string;
  color: string;
  dotColor: string;
  iconName?: "check" | "alert" | "info" | "restart";
}

export const EXPOSURE_STATUS_MAP: Record<import("@/types").ExposureStatusType, ExposureStatusBadgeConfig> = {
  ACTIVE: {
    label: "Active",
    color: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300 border border-green-200 dark:border-green-800",
    dotColor: "bg-green-500",
    iconName: "check",
  },
  STARTING: {
    label: "Starting...",
    color: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 border border-blue-200 dark:border-blue-800",
    dotColor: "bg-blue-500 animate-pulse",
  },
  STOPPING: {
    label: "Stopping...",
    color: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300 border border-orange-200 dark:border-orange-800",
    dotColor: "bg-orange-500 animate-pulse",
  },
  STOPPED: {
    label: "Stopped",
    color: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border border-gray-200 dark:border-gray-700",
    dotColor: "bg-gray-400",
  },
  DISABLED: {
    label: "Disabled",
    color: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 border border-gray-200 dark:border-gray-700",
    dotColor: "bg-gray-400",
  },
  DEGRADED: {
    label: "Degraded",
    color: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 border border-amber-200 dark:border-amber-800",
    dotColor: "bg-amber-500",
    iconName: "alert",
  },
  ERROR: {
    label: "Error",
    color: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border border-red-200 dark:border-red-800",
    dotColor: "bg-red-500",
    iconName: "alert",
  },
  RECLAIM_REQUIRED: {
    label: "Token Revoked",
    color: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300 border border-red-200 dark:border-red-800",
    dotColor: "bg-red-500",
    iconName: "alert",
  },
  CLAIM_REQUIRED: {
    label: "Claim Required",
    color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300 border border-yellow-200 dark:border-yellow-800",
    dotColor: "bg-yellow-500 animate-pulse",
    iconName: "info",
  },
};

export const STATUS_MAP: Record<string, StatusBadge> = {
  running: { label: "Online", color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" },
  stopped: { label: "Offline", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400" },
  created: { label: "Not Started", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400" },
  provisioning: { label: "Installing", color: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400" },
  provisioning_failed: { label: "Install Failed", color: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" },
  starting: { label: "Starting", color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400" },
  stopping: { label: "Stopping", color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400" },
  crashed: { label: "Crashed", color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" },
  broken: { label: "Broken", color: "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400" },
  restoring: { label: "Restoring", color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400" },
  ...Object.fromEntries(
    Object.entries(EXPOSURE_STATUS_MAP).map(([k, v]) => [k, { label: v.label, color: v.color }])
  ),
};

export interface RuntimeDiagnosticsResponse {
  server_id: string;
  server_name: string;
  status: string;
  alive: boolean;
  pid: number | null;
  provider: string | null;
  uptime_seconds: number;
  heartbeat_age_seconds: number | null;
  startup_duration_seconds: number | null;
  restart_count: number;
  failure_code: string | null;
  failure_reason: string | null;
  last_logs: string[] | null;
  last_exception: string | null;
  last_verification_timestamp: number | null;
  supervised: boolean;
  runtime_handle: string | null;
  provider_status: string | null;
  last_crash_time: number | null;
  port: number | null;
  port_owner: string | null;
  tmux_session: string | null;
  jvm_command: string | null;
  owner_conflicts: Record<string, unknown>[];
  validation_chain: string[];
}

export interface FileItem {
  name: string;
  is_dir: boolean;
  size: number;
  path: string;
}

export interface FileContentResponse {
  path: string;
  content: string;
  is_binary?: boolean;
}

export interface CrashReportSummary {
  filename: string;
  timestamp: string;
  failure_code: string;
  blamed_mod: string | null;
  stack_trace_snippet: string;
  suggested_remediation: string;
  raw_content: string;
}

export interface ServerBranch {
  id: string;
  server_id: string;
  name: string;
  head_commit_id: string | null;
  created_at: string;
}

export interface CreateBranchRequest {
  name: string;
  head_commit_id?: string | null;
}

export interface CommitManifest {
  server_type: string;
  minecraft_version: string;
  configs: Record<string, string>;
  mods: Array<{
    filename: string;
    sha256: string;
    source: string;
  }>;
  env_vars: Record<string, string>;
  java_args: string;
}

export interface ServerCommit {
  id: string;
  server_id: string;
  branch_id: string | null;
  parent_commit_id: string | null;
  author_id: string | null;
  message: string;
  manifest: CommitManifest;
  world_snapshot_id: string | null;
  created_at: string;
}

export interface CreateCommitRequest {
  message: string;
  branch_name?: string;
  author_id?: string | null;
}

export type TestRunStatus = "PENDING" | "RUNNING" | "PASSED" | "FAILED" | "CANCELLED";

export interface ServerTestRun {
  id: string;
  server_id: string;
  commit_id: string;
  node_id: string;
  status: TestRunStatus;
  ephemeral_port: number | null;
  log_output: string | null;
  failure_reason: string | null;
  created_at: string;
  expires_at: string | null;
  bot_count: number;
  duration_minutes: number;
  placement_mode: string;
  bot_tech: string;
}

export interface RunIsolatedTestRequest {
  commit_id?: string | null;
  bot_count?: number | null;
  duration_minutes?: number | null;
  placement_mode?: string | null;
  bot_tech?: string | null;
}

export interface PromoteCommitRequest {
  keep_world_changes?: boolean;
}

export interface BotSettings {
  server_id: string;
  bot_count: number | null;
  duration_minutes: number | null;
  bot_tech: string | null;
  placement_mode: string | null;
  effective_bot_count: number;
  effective_duration_minutes: number;
  effective_bot_tech: string;
  effective_placement_mode: string;
}

export interface BotSettingsRequest {
  bot_count?: number | null;
  duration_minutes?: number | null;
  bot_tech?: string | null;
  placement_mode?: string | null;
}

export interface PreflightStatus {
  reflink_supported: boolean;
  available_ram_mb: number;
  available_cores: number;
  min_required_ram_mb: number;
  min_required_cores: number;
  passed: boolean;
  error: string | null;
}

export interface ServerActivityLog {
  id: string;
  server_id: string;
  timestamp: number;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  summary: string;
  details: Record<string, unknown>;
}

export interface ActivityLogListResponse {
  items: ServerActivityLog[];
  total: number;
  limit: number;
  offset: number;
}

export interface GetActivityParams {
  limit?: number;
  offset?: number;
  event_type?: string;
  from_date?: number;
  to_date?: number;
}