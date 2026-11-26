export type OperationStatus =
  | "QUEUED"
  | "PREPARING"
  | "RUNNING"
  | "CANCEL_REQUESTED"
  | "CANCELLED"
  | "FAILED"
  | "TIMED_OUT"
  | "COMPLETED";

export type StepStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "FAILED"
  | "SKIPPED"
  | "CANCELLED";

export interface OperationArtifactProgress {
  name: string;
  kind: "backup" | "server_core" | "addon" | string;
  status: "pending" | "cached" | "downloading" | "patching" | "ready" | string;
  progress_pct: number;
  bytes_done?: number;
  bytes_total?: number;
}

export interface OperationHealthCheckItem {
  id: string;
  label: string;
  status: "pending" | "running" | "passed" | "skipped" | "warned" | "failed" | string;
  detail?: string | null;
}

export interface OperationStep {
  id: string;
  step_id: string;
  sequence: number;
  status: StepStatus;
  progress: number | null;
  elapsed_ms: number;
  message_key: string | null;
  safe_to_retry: boolean;
  context: Record<string, unknown> & {
    artifacts?: OperationArtifactProgress[];
    checks?: OperationHealthCheckItem[];
    warnings?: string[];
  };
  started_at: string | null;
  completed_at: string | null;
}

export interface OperationSummary {
  id: string;
  type: string;
  target_type: string;
  target_id: string | null;
  status: OperationStatus;
  current_step_id: string | null;
  last_event_seq: number;
  failure_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_ms: number;
}

export interface OperationDetail {
  id: string;
  type: string;
  target_type: string;
  target_id: string | null;
  actor_id: string | null;
  status: OperationStatus;
  idempotency_key: string | null;
  current_step_id: string | null;
  last_event_seq: number;
  failure_code: string | null;
  error_message: string | null;
  cancellation_requested: boolean;
  timeout_seconds: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_ms: number;
  steps: OperationStep[];
  metadata: Record<string, unknown>;
}

export interface CreateOperationRequest {
  type: string;
  target_type?: string;
  target_id?: string | null;
  idempotency_key?: string | null;
  timeout_seconds?: number;
  metadata?: Record<string, unknown>;
  initial_steps?: Array<Record<string, unknown>>;
}

export interface OperationEvent {
  event_type: string;
  operation_id: string;
  event_seq: number;
  target_type?: string;
  target_id?: string | null;
  server_id?: string | null;
  type?: string;
  step_id?: string;
  step_status?: StepStatus;
  progress?: number | null;
  elapsed_ms?: number;
  message_key?: string | null;
  context?: Record<string, unknown>;
  failure_code?: string;
  error_message?: string;
  failed_step_id?: string | null;
  level?: string;
  line?: string;
  timestamp?: number;
  finished_at?: number;
}
