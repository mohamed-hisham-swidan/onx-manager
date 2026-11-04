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
  startup_timeout_seconds?: number | null;
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
  startup_timeout_seconds?: number | null;
}

export interface ServerUpdateRequest {
  name?: string;
  properties?: Record<string, unknown>;
  min_memory_mb?: number | null;
  max_memory_mb?: number | null;
  cpu_cores?: number | null;
  cpu_affinity?: string | null;
  java_args?: string[] | null;
  startup_timeout_seconds?: number | null;
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
    color: "bg-status-online/15 text-status-online border border-status-online/30",
    dotColor: "bg-status-online",
    iconName: "check",
  },
  STARTING: {
    label: "Starting...",
    color: "bg-accent-primary/15 text-accent-primary border border-accent-primary/30",
    dotColor: "bg-accent-primary animate-pulse",
  },
  STOPPING: {
    label: "Stopping...",
    color: "bg-status-warn/15 text-status-warn border border-status-warn/30",
    dotColor: "bg-status-warn animate-pulse",
  },
  STOPPED: {
    label: "Stopped",
    color: "bg-surface-elevated text-text-muted border border-border-default",
    dotColor: "bg-text-muted",
  },
  DISABLED: {
    label: "Disabled",
    color: "bg-surface-elevated text-text-muted border border-border-default",
    dotColor: "bg-text-muted",
  },
  DEGRADED: {
    label: "Degraded",
    color: "bg-status-warn/15 text-status-warn border border-status-warn/30",
    dotColor: "bg-status-warn",
    iconName: "alert",
  },
  ERROR: {
    label: "Error",
    color: "bg-status-danger/15 text-status-danger border border-status-danger/30",
    dotColor: "bg-status-danger",
    iconName: "alert",
  },
  RECLAIM_REQUIRED: {
    label: "Token Revoked",
    color: "bg-status-danger/15 text-status-danger border border-status-danger/30",
    dotColor: "bg-status-danger",
    iconName: "alert",
  },
  CLAIM_REQUIRED: {
    label: "Claim Required",
    color: "bg-status-warn/15 text-status-warn border border-status-warn/30",
    dotColor: "bg-status-warn animate-pulse",
    iconName: "info",
  },
};

export const STATUS_MAP: Record<string, StatusBadge> = {
  running: { label: "Online", color: "bg-status-online/15 text-status-online" },
  stopped: { label: "Offline", color: "bg-surface-elevated text-text-muted" },
  created: { label: "Not Started", color: "bg-surface-elevated text-text-muted" },
  provisioning: { label: "Installing", color: "bg-accent-primary/15 text-accent-primary" },
  provisioning_failed: { label: "Install Failed", color: "bg-status-danger/15 text-status-danger" },
  starting: { label: "Starting", color: "bg-status-warn/15 text-status-warn" },
  stopping: { label: "Stopping", color: "bg-status-warn/15 text-status-warn" },
  crashed: { label: "Crashed", color: "bg-status-danger/15 text-status-danger" },
  broken: { label: "Broken", color: "bg-status-danger/15 text-status-danger" },
  restoring: { label: "Restoring", color: "bg-accent-primary/15 text-accent-primary" },
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

export interface BranchProtectionPolicy {
  require_test_pass: boolean;
  allow_direct_commit: boolean;
  allow_force_bypass: boolean;
  prevent_deletion: boolean;
}

export interface BranchProtectionResponse {
  server_id: string;
  branch_name: string;
  is_protected: boolean;
  policy: BranchProtectionPolicy | null;
}

export interface ServerBranch {
  id: string;
  server_id: string;
  name: string;
  head_commit_id: string | null;
  created_at: string;
  status?: string;
  is_protected?: boolean;
  protection_policy?: BranchProtectionPolicy | null;
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

export interface SetBranchProtectionRequest {
  policy?: Partial<BranchProtectionPolicy> | null;
}

export interface ServerCommit {
  id: string;
  server_id: string;
  branch_id: string | null;
  parent_id?: string | null;
  parent_commit_id: string | null;
  parent_commit_ids?: string[];
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
  force?: boolean;
  force_reason?: string | null;
}

export type RevisionType = "commit" | "branch" | "tag";
export type MaterializationMode = "readonly" | "editable";

export interface CreateMaterializationRequest {
  revision_type: RevisionType;
  ref: string;
  mode?: MaterializationMode;
}

export interface MaterializationCreateResponse {
  materialization_id: string;
  id?: string;
  revision: string;
  mode: MaterializationMode;
  status: string;
  root: string;
}

export interface MaterializationListItemResponse {
  id: string;
  revision: string;
  mode: MaterializationMode;
  status: string;
  stale: boolean;
  created_at: string;
}

export interface MaterializationTreeEntry {
  path: string;
  classification: string;
  is_dir?: boolean;
  size_bytes: number;
  origin?: string;
}

export interface MaterializationTreeResponse {
  entries: MaterializationTreeEntry[];
}

export interface MaterializationFileResponse {
  content: string;
  encoding: string;
  path: string;
  size_bytes: number;
}

export interface SetEditModeRequest {
  enabled: boolean;
}

export interface SetEditModeResponse {
  mode: string;
}

export interface LiveChangeEntry {
  path: string;
  classification?: string;
  change?: string;
  change_type?: string;
  size_bytes?: number;
}

export interface ScanLiveChangesResponse {
  changes: LiveChangeEntry[];
  has_changes?: boolean;
  auto_commit?: string | null;
  review_id?: string | null;
  base_commit_id?: string | null;
  detected_at?: string;
}

export interface AutoCommitLiveChangesRequest {
  branch?: string;
  message?: string;
}

export interface AutoCommitLiveChangesResponse {
  commit_id?: string | null;
  review_id?: string | null;
  changes?: LiveChangeEntry[];
}

export interface ImportReviewActionResponse {
  status: string;
  success?: boolean;
  action?: string;
  review_id?: string;
  commit_id?: string | null;
  revert_commit_id?: string | null;
  message?: string;
}

export interface ServerTag {
  id: string;
  server_id: string;
  name: string;
  commit_id: string;
  created_at: string;
}

export interface CreateTagRequest {
  name: string;
  commit_id: string;
}

export interface DictDiff {
  added?: Record<string, string>;
  removed?: Record<string, string>;
  modified?: Record<string, { from?: string; to?: string } | Record<string, string>>;
}

export interface ModDiffEntry {
  filename: string;
  sha256?: string;
}

export interface ModDiff {
  added?: (string | ModDiffEntry)[];
  removed?: (string | ModDiffEntry)[];
  modified?: (string | ModDiffEntry)[];
}

export interface DiffResponse {
  from_commit_id: string;
  to_commit_id: string;
  has_changes: boolean;
  server_type: Record<string, string> | null;
  minecraft_version: Record<string, string> | null;
  java_args: Record<string, string> | null;
  configs: DictDiff;
  env_vars: DictDiff;
  mods: ModDiff;
}

export type TestRunStatus = "PENDING" | "BOOTING" | "RUNNING" | "PASSED" | "FAILED" | "CANCELLED";
export type RuntimeStatus = "STARTING" | "RUNNING" | "TERMINATED" | "CRASHED";

export interface RuntimeInfo {
  id: string;
  server_id?: string | null;
  commit_id: string;
  materialization_id?: string | null;
  provider_type: string;
  container_id?: string | null;
  pid?: number | null;
  port?: number | null;
  status: RuntimeStatus;
  exit_code?: number | null;
  oom_killed: boolean;
  started_at?: string | null;
  stopped_at?: string | null;
  created_at: string;
}

export interface EvidenceBundle {
  test_id: string;
  server_id: string;
  commit_id: string;
  runtime: Record<string, unknown>;
  assertions: Record<string, unknown>;
  crash_analysis: Record<string, unknown>;
  log_tail: string[];
}

export interface TestDefinition {
  id: string;
  server_id: string;
  name: string;
  description: string;
  server_type: string;
  bot_technology: string;
  bot_count: number;
  duration_seconds: number;
  join_stagger_seconds: number;
  connect_grace_seconds: number;
  placement_mode: string;
  assertion_rules: Record<string, unknown>;
  timeout_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface CreateTestDefinitionRequest {
  name: string;
  description?: string;
  server_type?: string;
  bot_technology?: string;
  bot_count?: number;
  duration_seconds?: number;
  join_stagger_seconds?: number;
  connect_grace_seconds?: number;
  placement_mode?: string;
  assertion_rules?: Record<string, unknown>;
  timeout_seconds?: number;
}

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
  runtime_id?: string | null;
  test_definition_id?: string | null;
  artifacts_purged?: boolean;
  reserved_ram_mb?: number | null;
  reserved_cores?: number | null;
  operation_id?: string | null;
  evidence_bundle?: EvidenceBundle | null;
}

export interface RunIsolatedTestRequest {
  commit_id?: string | null;
  bot_count?: number | null;
  duration_minutes?: number | null;
  placement_mode?: string | null;
  bot_tech?: string | null;
  test_definition_id?: string | null;
}

export interface PromoteCommitRequest {
  keep_world_changes?: boolean;
  force?: boolean;
  force_reason?: string;
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