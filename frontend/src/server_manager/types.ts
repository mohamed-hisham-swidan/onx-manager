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
}

export interface ServerDetailResponse extends ServerResponse {
  min_memory_mb: number;
  max_memory_mb: number;
  java_args: string;
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
}

export interface ServerUpdateRequest {
  properties?: Record<string, unknown>;
  min_memory_mb?: number | null;
  max_memory_mb?: number | null;
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

export const STATUS_MAP: Record<string, StatusBadge> = {
  running: { label: "Online", color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" },
  stopped: { label: "Offline", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400" },
  created: { label: "Not Started", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400" },
  starting: { label: "Starting", color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400" },
  stopping: { label: "Stopping", color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400" },
  crashed: { label: "Crashed", color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" },
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