export interface SoftwareInfo {
  type: string;
  name: string;
  description: string;
  url: string;
  supports_versions: boolean;
}

export type ServerMode = "simple" | "advanced";

export type ProvisioningStepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export interface ProvisioningStepItem {
  id: string;
  label: string;
  status: ProvisioningStepStatus;
  detail?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  elapsed_ms: number;
}

export interface ProvisioningTransferState {
  filename: string;
  bytes_downloaded: number;
  total_bytes: number | null;
  percent: number | null;
  speed_bps: number | null;
  eta_seconds: number | null;
  file_index: number;
  file_total: number;
  phase: "downloading" | "installing" | "verifying" | string;
}

export interface ProvisioningActivityItem {
  timestamp: string;
  message: string;
  level: "info" | "success" | "warning" | "error" | string;
}

export interface ProvisioningArtifactItem {
  id: string;
  label: string;
  value: string;
  status: string;
}

export interface ProvisioningSnapshot {
  server_id: string;
  server_name?: string;
  server_type?: string;
  minecraft_version?: string;
  mode?: string;
  status: "running" | "completed" | "failed" | string;
  started_at: string;
  finished_at?: string | null;
  elapsed_ms: number;
  current_step_id?: string | null;
  percent: number | null;
  message: string;
  error?: string | null;
  failed_step_id?: string | null;
  steps: ProvisioningStepItem[];
  active_transfer?: ProvisioningTransferState | null;
  activity: ProvisioningActivityItem[];
  artifacts: ProvisioningArtifactItem[];
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
  mode?: ServerMode;
  provisioning_error?: string | null;
  provisioning_retryable?: boolean;
  provisioning_progress?: ProvisioningSnapshot | null;
  startup_timeout_seconds?: number | null;
  max_memory_mb?: number | null;
  cpu_cores?: number | null;
  uptime_seconds?: number | null;
  deployment_host?: string | null;
  public_address?: string | null;
  active_branch?: string | null;
  icon_data_url?: string | null;
}

export interface PendingSettingsBranchInfo {
  branch_name: string;
  head_commit_id?: string | null;
  status: "pending" | "needs_resolution" | "merged" | "discarded" | string;
  error_message?: string | null;
  created_at?: string | null;
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
  branch_name?: string | null;
  pending_settings_branch?: PendingSettingsBranchInfo | null;
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

const EXPOSURE_DIAGNOSTIC_BADGES: Record<string, StatusBadge> = {
  BIND_MISMATCH: {
    label: "Restart Required",
    color: "bg-status-warning/15 text-status-warning border border-status-warning/30",
  },
  CGNAT_DETECTED: {
    label: "CGNAT Detected",
    color: "bg-status-danger/15 text-status-danger border border-status-danger/30",
  },
  DOUBLE_NAT_DETECTED: {
    label: "CGNAT Detected",
    color: "bg-status-danger/15 text-status-danger border border-status-danger/30",
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
  ...EXPOSURE_DIAGNOSTIC_BADGES,
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

export type LogCategory = "server_log" | "crash_report" | "plugin_log";

export interface FileItem {
  name: string;
  is_dir: boolean;
  size: number;
  path: string;
  modified_at?: string | null;
  file_class?: string | null;
  editable?: boolean | null;
  log_category?: LogCategory | null;
}

export interface FileContentResponse {
  path: string;
  content: string;
  is_binary?: boolean;
  truncated?: boolean;
  total_size_bytes?: number | null;
  is_compressed?: boolean;
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
  container_provisioned?: boolean;
  port_set?: PortSet | null;
  active_runtime_id?: string | null;
  active_commit_sha?: string | null;
  active_data_template_id?: string | null;
  pending_merge_on_restart?: boolean;
  pending_merge_status?: string | null;
  pending_merge_error?: string | null;
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
  container_provisioned?: boolean;
  container_name?: string | null;
  runtime_id: string | null;
  active_commit_sha: string | null;
  data_template_id: string | null;
  allow_public_test_join: boolean;
  container_liveness: boolean | null;
  port_set: PortSet | null;
  worktree_locked: boolean;
  worktree_lock_reason: string | null;
}

export interface DestroyBranchRunRequest {
  runtime_id?: string | null;
  timeout_seconds?: number;
  keep_port_assignment?: boolean;
}

export interface DestroyBranchRunResponse {
  runtime_id: string;
  server_id: string;
  branch_name: string;
  container_name: string;
  status: string;
  container_provisioned: boolean;
  released_ports: boolean;
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

// P5-3 / P5-4 GitHub Sync types

export type GitHubAuthMethod = "pat" | "ssh_deploy_key";

export type GitHubBranchSyncStatus =
  | "synced"
  | "ahead"
  | "behind"
  | "diverged"
  | "local_only"
  | "remote_only";

export type GitHubSyncStatus =
  | "disconnected"
  | "idle"
  | "synced"
  | "ahead"
  | "behind"
  | "diverged"
  | "conflict"
  | "auth_failed"
  | "error";

export type GitHubWebhookIngestStatus = "queued" | "deduplicated" | "ignored";

export interface GenerateGitHubDeployKeyRequest {
  comment?: string | null;
}

export interface GenerateGitHubDeployKeyResponse {
  server_id: string;
  public_key_openssh: string;
  private_key_pem: string;
  fingerprint_sha256: string;
}

export interface ConnectGitHubRequest {
  remote_url: string;
  auth_method: GitHubAuthMethod;
  credential_secret: string;
  deploy_public_key?: string | null;
  webhook_secret?: string | null;
  enable_webhook: boolean;
}

export interface RotateGitHubCredentialsRequest {
  credential_secret?: string | null;
  auth_method?: GitHubAuthMethod | null;
  deploy_public_key?: string | null;
  webhook_secret?: string | null;
  enable_webhook?: boolean | null;
  regenerate_webhook_secret?: boolean;
  disable_webhook?: boolean;
}

/** Push a branch to GitHub. Force-push is deliberately absent and forbidden. */
export interface PushGitHubBranchRequest {
  branch_name: string;
}

export interface GitHubBranchSyncState {
  branch: string;
  status: GitHubBranchSyncStatus;
  local_sha: string | null;
  remote_sha: string | null;
  ahead_count: number;
  behind_count: number;
}

export interface GitHubConnectionStatusResponse {
  server_id: string;
  connected: boolean;
  remote_url: string | null;
  auth_method: GitHubAuthMethod | string | null;
  credential_hint: string | null;
  deploy_public_key: string | null;
  webhook_enabled: boolean;
  webhook_path: string | null;
  sync_status: GitHubSyncStatus | string;
  needs_reauth: boolean;
  last_error_code: string | null;
  last_error_message: string | null;
  last_fetch_at: string | null;
  last_push_at: string | null;
  remote_default_branch: string | null;
  remote_head_sha: string | null;
  branches: GitHubBranchSyncState[];
  created_at: string | null;
  updated_at: string | null;
  generated_webhook_secret: string | null;
}

export interface GitHubDisconnectResponse {
  server_id: string;
  disconnected: boolean;
  remote_url: string;
  local_history_preserved: boolean;
  purged_deliveries: number;
}

export interface GitHubSyncResponse {
  server_id: string;
  sync_status: GitHubSyncStatus | string;
  trigger: string;
  main_fast_forwarded: boolean;
  previous_main_sha: string | null;
  main_sha: string | null;
  remote_default_branch: string | null;
  remote_head_sha: string | null;
  branches: GitHubBranchSyncState[];
  fetched_at: string;
}

export interface GitHubPushResponse {
  server_id: string;
  branch_name: string;
  commit_sha: string;
  remote_url: string;
  sync_status: GitHubSyncStatus | string;
  branches: GitHubBranchSyncState[];
  pushed_at: string;
}

export interface GitHubWebhookIngestResponse {
  server_id: string;
  delivery_id: string;
  event_type: string;
  status: GitHubWebhookIngestStatus;
  deduplicated: boolean;
  redelivered: boolean;
  redelivery_count: number;
  operation_id: string | null;
  received_at: string | null;
}

/** Secret-free delivery ledger row (deliberately omits raw_payload). */
export interface GitHubWebhookDeliveryResponse {
  id: string;
  server_id: string;
  delivery_id: string;
  event_type: string;
  ref: string | null;
  before_sha: string | null;
  after_sha: string | null;
  payload_sha256: string;
  signature_valid: boolean;
  status: string;
  operation_id: string | null;
  error_message: string | null;
  redelivery_count: number;
  received_at: string;
  processed_at: string | null;
}

// ── P5.5 Modpacks, 1-Click Safe Upgrades, LEC & CurseForge Integration ──────

export type P55LoaderId =
  | "fabric"
  | "quilt"
  | "forge"
  | "neoforge"
  | "paper"
  | "purpur";

export type MatrixStatusType =
  | "warning: unresolved_carried"
  | "blocker: no_target_build"
  | "blocker: missing_dependency"
  | "blocker: missing_transitive_dependency"
  | "blocker: incompatible"
  | "blocker: untrusted_host"
  | "blocker: manual_download_required"
  | "warning"
  | "add"
  | "remove"
  | "carried"
  | "unchanged";

export interface CurseForgeIntegrationKeySetRequest {
  api_key: string;
}

export interface CurseForgeIntegrationStatusResponse {
  configured: boolean;
  source: "panel" | "env" | "none";
  hint: string | null;
}

export interface LecEntryResponse {
  lec_key: string;
  loader_id: string;
  mc_version: string;
  loader_version: string;
  installer_version: string | null;
  java_major: number | null;
  status: string;
  size_bytes: number;
  file_count: number;
  complete_manifest_sha256: string | null;
  ready_on_disk: boolean;
  last_used_at: string | null;
  updated_at: string | null;
}

export interface LecPrewarmRequest {
  lec_key?: string | null;
  loader_id?: P55LoaderId | null;
  mc_version?: string | null;
  loader_version?: string | null;
  installer_version?: string | null;
  async_mode?: boolean;
}

export interface LecPrewarmResponse {
  lec_key: string;
  status: string;
  file_count: number;
  total_bytes: number;
  java_major: number | null;
  unix_args_relpath: string | null;
  operation_id: string | null;
}

export interface LecGcRequest {
  min_age_days: number;
}

export interface LecGcResponse {
  pruned_lec_keys: string[];
  pruned_cas_digests: string[];
  freed_bytes: number;
}

export interface ServerP55SettingsUpdateRequest {
  health_gate_boot_timeout_seconds?: number | null;
  install_optional_server_files?: boolean | null;
  allow_experimental_paper_builds?: boolean | null;
  download_host_allowlist?: string[] | null;
}

export interface ServerP55SettingsResponse {
  server_id: string;
  health_gate_boot_timeout_seconds: number;
  install_optional_server_files: boolean;
  allow_experimental_paper_builds: boolean;
  download_host_allowlist: string[];
  default_allowed_hosts: string[];
}

export interface InstallPlanFileItem {
  path: string;
  sha1: string;
  sha512: string | null;
  sha256: string | null;
  size: number;
  downloads: string[];
  env_server: string;
  optional: boolean;
  origin: string;
  project_id: string | null;
  version_id: string | null;
  source_layer: string;
  curseforge_project_id: number | null;
  curseforge_file_id: number | null;
}

export interface InstallPlanOverrideItem {
  path: string;
  archive_path: string;
  source_layer: string;
  classification: string;
  sha256: string;
  sha512: string;
  sha1: string;
  size: number;
}

export interface ManualDownloadBlockerItem {
  path: string;
  filename: string;
  project_id: number | null;
  file_id: number | null;
  webpage_url: string;
  expected_size: number | null;
  expected_sha1: string | null;
  expected_sha512: string | null;
  required: boolean;
  reason: string;
  blocker_type: string;
  resolved: boolean;
  resolved_sha256: string | null;
}

export interface InstallPlanPayload {
  source: string;
  project_id: string;
  version_id: string;
  version_label: string;
  index_sha256: string;
  mc_version: string;
  loader_id: string;
  loader_version: string;
  files: InstallPlanFileItem[];
  overrides: InstallPlanOverrideItem[];
  manual_blockers: ManualDownloadBlockerItem[];
  skipped_client_files: string[];
  skipped_optional_files: string[];
  skipped_client_override_jars: string[];
  discarded_paths: string[];
  warnings: string[];
}

export interface ModpackInspectResponse {
  server_id: string;
  staged_pack_id: string;
  source: string;
  mc_version: string;
  loader_id: string;
  loader_version: string;
  has_unresolved_blockers: boolean;
  plan: InstallPlanPayload;
}

export interface ModpackInstallRequest {
  staged_pack_id: string;
  lec_key?: string | null;
  build_lec?: boolean;
  fabric_installer_version?: string;
  async_mode?: boolean;
}

export interface ModpackInstallResponse {
  server_id: string;
  upgrade_id: string;
  status: string;
  mc_version: string;
  loader_id: string;
  loader_version: string;
  lec_key: string | null;
  files_installed: number;
  base_overrides_count: number;
  commit_sha: string | null;
  operation_id: string | null;
}

export interface MatrixEntryItem {
  path: string;
  status: MatrixStatusType;
  origin: string;
  source_sha256: string | null;
  source_sha512: string | null;
  source_project_id: string | null;
  source_version_id: string | null;
  target_sha256: string | null;
  target_sha512: string | null;
  target_sha1: string | null;
  target_size: number | null;
  target_project_id: string | null;
  target_version_id: string | null;
  target_version_number: string | null;
  download_url: string | null;
  required_by: string[];
  detail: string;
  manual_blocker: ManualDownloadBlockerItem | null;
  excluded_by_operator: boolean;
  kept_by_operator?: boolean;
  action_label?: string;
  is_blocker: boolean;
}

export interface CompatibilityMatrixPayload {
  source_mc: string;
  target_mc: string;
  source_loader: { id: string; version: string };
  target_loader: { id: string; version: string };
  entries: MatrixEntryItem[];
  bfs_depth_reached: number;
  bfs_projects_resolved: number;
  excluded_paths: string[];
  kept_paths?: string[];
  has_blockers: boolean;
  blockers_count: number;
  warnings_count: number;
  health_gate_checks?: Array<{
    id: string;
    label: string;
    status: string;
    detail?: string | null;
  }>;
  health_gate_warnings?: string[];
}

export interface PlanUpgradeRequest {
  target_mc: string;
  target_loader_id: P55LoaderId;
  target_loader_version: string;
  target_lec_key?: string | null;
  staged_pack_id?: string | null;
  excluded_paths?: string[];
  keep_paths?: string[];
  version_types?: Array<"release" | "beta" | "alpha">;
  verify_public_network?: boolean | null;
}

export interface PrepareUpgradeTestRequest {
  target_slug?: string | null;
  resolved_conflicts?: Record<string, string>;
  start_test?: boolean;
  allow_public_test_join?: boolean;
  requested_memory_mb?: number | null;
  requested_cpu_cores?: number | null;
  check_os_ports?: boolean;
}

export interface ApplyUpgradeRequest {
  resolved_conflicts?: Record<string, string>;
  async_mode?: boolean;
  verify_public_network?: boolean | null;
}

export interface RollbackUpgradeRequest {
  reason: string;
}

export interface ServerUpgradeResponse {
  id: string;
  server_id: string;
  kind: string;
  mode: string;
  status: string;
  source_mc: string | null;
  target_mc: string;
  source_loader_id: string | null;
  source_loader_version: string | null;
  target_loader_id: string;
  target_loader_version: string;
  target_lec_key: string | null;
  upgrade_branch: string | null;
  operation_id: string | null;
  journal_id: string | null;
  previous_main_sha: string | null;
  target_main_sha: string | null;
  pre_upgrade_backup_id: string | null;
  class_c_snapshot_id: string | null;
  data_template_id: string | null;
  plan: InstallPlanPayload | null;
  matrix: CompatibilityMatrixPayload | null;
  manual_blockers: ManualDownloadBlockerItem[] | null;
  pinned_until_confirm: boolean;
  health_gate_passed: boolean;
  reminder_72h_overdue: boolean;
  error_code: string | null;
  error_message: string | null;
  confirmed_at: string | null;
  rolled_back_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ServerUpgradeListResponse {
  server_id: string;
  items: ServerUpgradeResponse[];
  active_upgrade: ServerUpgradeResponse | null;
  banner_active: boolean;
  reminder_72h_overdue: boolean;
}

export interface PrepareUpgradeTestResponse {
  upgrade: ServerUpgradeResponse;
  runtime: StartBranchRunResponse | null;
}
