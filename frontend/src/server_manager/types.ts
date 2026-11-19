export interface SoftwareInfo {
  type: string;
  name: string;
  description: string;
  url: string;
  supports_versions: boolean;
}

export type ServerMode = "simple" | "advanced";

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
  mode?: ServerMode;
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
  import_id?: string;
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
  mode?: ServerMode;
}

export interface ServerImportRequest {
  import_id: string;
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
  mode?: ServerMode;
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
    color: "bg-status-success/15 text-status-success border border-status-success/30",
    dotColor: "bg-status-success",
    iconName: "check",
  },
  STARTING: {
    label: "Starting...",
    color: "bg-accent-primary/15 text-accent-primary border border-accent-primary/30",
    dotColor: "bg-accent-primary animate-pulse",
  },
  STOPPING: {
    label: "Stopping...",
    color: "bg-status-warning/15 text-status-warning border border-status-warning/30",
    dotColor: "bg-status-warning animate-pulse",
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
    color: "bg-status-warning/15 text-status-warning border border-status-warning/30",
    dotColor: "bg-status-warning",
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
    color: "bg-status-warning/15 text-status-warning border border-status-warning/30",
    dotColor: "bg-status-warning animate-pulse",
    iconName: "info",
  },
};

export const STATUS_MAP: Record<string, StatusBadge> = {
  running: { label: "Online", color: "bg-status-success/15 text-status-success" },
  stopped: { label: "Offline", color: "bg-surface-elevated text-text-muted" },
  created: { label: "Not Started", color: "bg-surface-elevated text-text-muted" },
  provisioning: { label: "Installing", color: "bg-accent-primary/15 text-accent-primary" },
  provisioning_failed: { label: "Install Failed", color: "bg-status-danger/15 text-status-danger" },
  starting: { label: "Starting", color: "bg-status-warning/15 text-status-warning" },
  stopping: { label: "Stopping", color: "bg-status-warning/15 text-status-warning" },
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
  worktree_path?: string | null;
  worktree_locked?: boolean;
  worktree_lock_reason?: string | null;
  runtime_status?: string;
  port_set?: PortSet | null;
  active_runtime_id?: string | null;
  active_commit_sha?: string | null;
  active_data_template_id?: string | null;
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
  snapshot_hash?: string | null;
  changes_summary?: Record<string, unknown> | null;
  warnings?: unknown[];
  noop?: boolean;
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
  previous_tree_retention?: string;
}

export interface BotSettingsRequest {
  bot_count?: number | null;
  duration_minutes?: number | null;
  bot_tech?: string | null;
  placement_mode?: string | null;
  previous_tree_retention?: string | number | null;
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
  branch_name?: string | null;
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
  branch?: string;
}
// P3-4 / P3-5 types

export interface MergeCommitsRequest {
  target_branch_name: string;
  source_branch_name?: string | null;
  parent_commit_ids?: string[];
  message: string;
  author_id?: string | null;
  manifest?: Record<string, unknown> | null;
  force?: boolean;
  force_reason?: string | null;
  force_bypass_protection?: boolean;
}

export interface MergeCommitsResponse {
  commit_id: string;
  server_id: string;
  branch_name: string;
  parent_commit_ids: string[];
  files?: string[];
  warnings?: unknown[];
  engine?: string;
}

export interface RefreshJournalSummary {
  journal_id: string;
  server_id: string;
  phase: string;
  terminal: boolean;
  target_main_sha: string;
  previous_main_sha: string;
  class_c_snapshot_id: string | null;
  previous_dir: string | null;
  retention_policy: string;
  retain_until: string | null;
  rollback_reason: string | null;
  error_detail: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RefreshStateResponse {
  server_id: string;
  active_journal: RefreshJournalSummary | null;
  latest_journal: RefreshJournalSummary | null;
  can_confirm_upgrade: boolean;
  can_rollback: boolean;
  previous_tree_retention: string;
}

export interface RefreshServerRequest {
  target_main_sha?: string | null;
  retention_policy?: string | number | null;
  stop_timeout_seconds?: number;
  health_timeout_seconds?: number;
}

export interface RollbackRefreshRequest {
  journal_id?: string | null;
  reason?: string;
  stop_timeout_seconds?: number;
  health_timeout_seconds?: number;
}

export interface ConfirmUpgradeRequest {
  journal_id?: string | null;
}

export interface RefreshActionResponse {
  server_id: string;
  journal_id: string | null;
  phase: string | null;
  status: string;
}

export interface ClassCSnapshot {
  snapshot_id: string;
  server_id: string;
  created_at: string | null;
  manifest_sha256: string | null;
  pinned: boolean;
  entry_count: number;
  archive_size_bytes: number;
}

export interface DynamicClassCEntry {
  server_id: string;
  relpath: string;
  promoted_at: string | null;
  main_commit_sha: string | null;
  ast_Node_summary?: unknown;
}

export interface SecretMetadata {
  server_id: string;
  key_name: string;
  placeholder: string;
  kek_version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ExtractSecretRequest {
  branch: string;
  path: string;
  key_name: string;
  secret_value: string;
}

export interface ExtractSecretResponse {
  server_id: string;
  branch: string;
  path: string;
  key_name: string;
  placeholder: string;
  replaced_occurrences: number;
  remaining_findings: Array<Record<string, unknown>>;
}

export interface LiveStateFileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  modified_at: number;
  file_class: "C";
  is_dynamic_class_c: boolean;
  writable: boolean;
}

export interface LiveStateFileListResponse {
  items: LiveStateFileEntry[];
}

export interface LiveStateFileContentResponse {
  server_id: string;
  path: string;
  content: string;
  encoding: string;
  size: number;
  is_dynamic_class_c: boolean;
}

export interface LiveStateWriteRequest {
  path: string;
  content: string;
  reload_command?: string | null;
}

export interface LiveStateWriteResponse {
  status: string;
  server_id: string;
  path: string;
  rcon_flushed: boolean;
  rcon_reloaded: boolean;
  reload_command: string | null;
}

// P4-3 / P4-4 Branch Runs, Port Sets & Data Templates types

export type DataTemplateStatus = "cloning" | "ready" | "failed";
export type DataTemplateSource = "live" | "branch";

export interface DataTemplate {
  id: string;
  server_id: string;
  name: string;
  description: string;
  source_branch_name: string | null;
  source_commit_sha: string | null;
  file_count: number;
  total_bytes: number;
  status: DataTemplateStatus | string;
  operation_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateDataTemplateRequest {
  name: string;
  description?: string;
  source?: DataTemplateSource;
  branch_name?: string | null;
  async_mode?: boolean;
}

export interface DeleteDataTemplateResponse {
  status: string;
  server_id: string;
  template_id: string;
}

export interface PortSet {
  game_port: number;
  rcon_port: number;
  query_port?: number | null;
  plugin_ports?: Record<string, number>;
  container_game_port?: number;
  container_rcon_port?: number;
}

export interface AllocatePortSetRequest {
  include_query?: boolean;
  plugin_port_names?: string[];
  check_os_ports?: boolean;
}

export interface SetPortSetRequest {
  game_port: number;
  rcon_port: number;
  query_port?: number | null;
  plugin_ports?: Record<string, number>;
  check_os_ports?: boolean;
}

export interface BranchPortSetResponse {
  server_id: string;
  branch_name: string;
  port_set: PortSet;
}

export interface BranchRuntimeStatus {
  server_id: string;
  branch_name: string;
  runtime_status: string;
  runtime_id: string | null;
  active_commit_sha: string | null;
  data_template_id: string | null;
  allow_public_test_join: boolean;
  container_liveness: boolean | null;
  port_set: PortSet | null;
  worktree_locked: boolean;
  worktree_lock_reason: string | null;
}

export interface StartBranchRunRequest {
  commit_sha?: string | null;
  data_template_id?: string | null;
  allow_public_test_join?: boolean;
  port_set?: PortSet | null;
  include_query?: boolean;
  plugin_port_names?: string[];
  requested_memory_mb?: number | null;
  requested_cpu_cores?: number | null;
  check_os_ports?: boolean;
}

export interface StartBranchRunResponse {
  runtime_id: string;
  server_id: string;
  branch_name: string;
  commit_sha: string;
  container_name: string;
  container_id: string;
  port_set: PortSet;
  data_template_id: string | null;
  allow_public_test_join: boolean;
  uncommitted_changes_warning: boolean;
  memory_max_mb: number;
  cpu_cores: number;
}

export interface StopBranchRunRequest {
  runtime_id?: string | null;
  timeout_seconds?: number;
  keep_port_assignment?: boolean;
  save_template_name?: string | null;
  save_template_description?: string;
}

export interface StopBranchRunResponse {
  runtime_id: string;
  server_id: string;
  branch_name: string;
  status: string;
  exit_code: number | null;
  oom_killed: boolean;
  saved_template_id: string | null;
  saved_template_name: string | null;
}

export interface SaveBranchDataTemplateRequest {
  name: string;
  description?: string;
  runtime_id?: string | null;
}

export interface BranchConsoleLogsResponse {
  server_id: string;
  branch_name: string;
  runtime_id: string;
  container_name: string;
  lines: string[];
}

export interface BranchConsoleCommandRequest {
  command: string;
}

export interface BranchConsoleCommandResponse {
  server_id: string;
  branch_name: string;
  runtime_id: string;
  command: string;
  output: string;
}
