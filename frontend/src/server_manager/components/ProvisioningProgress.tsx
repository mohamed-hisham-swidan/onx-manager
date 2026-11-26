import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { createAuthenticatedApi } from "@/services/api";
import { useProvisionProgress } from "@/server_manager/hooks/useProvisionProgress";
import { resolveJavaMajorForMcVersion } from "@/server_manager/utils/javaRuntime";
import { serverModeLabel } from "@/server_manager/utils/serverMode";
import type {
  ProvisioningActivityItem,
  ProvisioningArtifactItem,
  ProvisioningSnapshot,
  ProvisioningStepItem,
  ProvisioningStepStatus,
  ProvisioningTransferState,
} from "@/server_manager/types";

export interface ProvisioningProgressProps {
  serverId: string;
  className?: string;
  compact?: boolean;
  serverName?: string;
  serverType?: string;
  minecraftVersion?: string;
  mode?: string;
  port?: number;
  initialSnapshot?: ProvisioningSnapshot | null;
  retryable?: boolean;
  retrying?: boolean;
  enablePollingFallback?: boolean;
  onRetryProvisioning?: () => void;
  onOpenConsole?: () => void;
  onStartServer?: () => Promise<void> | void;
}

const CANONICAL_STEPS: Array<{ id: string; label: string }> = [
  { id: "prepare_workspace", label: "Prepare Workspace" },
  { id: "download_core", label: "Download Server Core" },
  { id: "verify_and_install", label: "Verify & Install" },
  { id: "prepare_runtime", label: "Prepare Runtime" },
  { id: "finalize", label: "Finalize" },
];

function formatMb(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatSpeed(bps: number): string {
  if (bps >= 1024 * 1024) {
    return `${(bps / (1024 * 1024)).toFixed(1)} MB/s`;
  }
  if (bps >= 1024) {
    return `${Math.round(bps / 1024)} KB/s`;
  }
  return `${Math.round(bps)} B/s`;
}

function formatEta(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `~${s}s left`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `~${m}m ${rem}s left` : `~${m}m left`;
}

function formatStopwatch(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatTerminalDuration(ms: number): string {
  const secs = Math.max(0, Math.round(ms / 1000));
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function formatStepDuration(step: ProvisioningStepItem, nowMs: number, parentTerminal: boolean): string {
  let ms = step.elapsed_ms || 0;
  if (!parentTerminal && step.status === "running" && step.started_at) {
    const startEpoch = Date.parse(step.started_at);
    if (!Number.isNaN(startEpoch)) {
      ms = Math.max(ms, nowMs - startEpoch);
    }
  }
  if (ms > 0) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  if (step.status === "running") return "Active";
  if (step.status === "completed") return "Done";
  if (step.status === "skipped") return "Skipped";
  if (step.status === "failed") return "Failed";
  return "Pending";
}

function formatActivityTime(ts: string): string {
  const parsed = Date.parse(ts);
  if (Number.isNaN(parsed)) return "";
  return new Date(parsed).toLocaleTimeString([], {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function getStageLabel(stage: string): string {
  switch (stage) {
    case "prepare_workspace":
      return "Preparing workspace";
    case "download_core":
      return "Downloading server core";
    case "verify_and_install":
      return "Verifying & installing";
    case "prepare_runtime":
      return "Preparing Java runtime";
    case "finalize":
      return "Finalizing server";
    case "downloading_libraries":
      return "Downloading libraries";
    case "downloading_forge":
      return "Downloading loader";
    case "installing_profile":
      return "Installing profile";
    case "installing_minecraft":
      return "Installing Minecraft";
    case "success":
      return "Server Ready";
    case "failed":
      return "Creation Failed";
    case "timeout":
      return "Creation Timed Out";
    default:
      return stage.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

function mapLegacyStageToStepId(stage: string): string {
  switch (stage) {
    case "prepare_workspace":
      return "prepare_workspace";
    case "download_core":
    case "downloading_forge":
      return "download_core";
    case "verify_and_install":
    case "downloading_libraries":
    case "installing_profile":
    case "installing_minecraft":
    case "installing":
      return "verify_and_install";
    case "prepare_runtime":
      return "prepare_runtime";
    case "finalize":
    case "success":
      return "finalize";
    default:
      return "download_core";
  }
}

function deriveFallbackSteps(
  stage: string,
  message: string,
  isCompleted: boolean,
  isFailed: boolean,
): ProvisioningStepItem[] {
  const activeStepId = mapLegacyStageToStepId(stage);
  const activeIndex = CANONICAL_STEPS.findIndex((s) => s.id === activeStepId);
  return CANONICAL_STEPS.map((s, idx) => {
    let status: ProvisioningStepStatus = "pending";
    if (isCompleted) {
      status = "completed";
    } else if (isFailed) {
      if (idx < activeIndex) status = "completed";
      else if (idx === activeIndex) status = "failed";
      else status = "pending";
    } else {
      if (idx < activeIndex) status = "completed";
      else if (idx === activeIndex) status = "running";
      else status = "pending";
    }
    return {
      id: s.id,
      label: s.label,
      status,
      detail: idx === activeIndex ? message || null : null,
      elapsed_ms: 0,
    };
  });
}

function StepStatusIcon({ status }: { status: ProvisioningStepStatus }) {
  switch (status) {
    case "completed":
      return (
        <span
          data-testid="provision-step-icon-completed"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-status-success-bg text-status-success"
        >
          <Icon name="check" size={14} />
        </span>
      );
    case "running":
      return (
        <span
          data-testid="provision-step-icon-running"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-status-info-bg text-status-info"
        >
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-status-info/30 border-t-status-info" />
        </span>
      );
    case "failed":
      return (
        <span
          data-testid="provision-step-icon-failed"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-status-danger-bg text-status-danger"
        >
          <Icon name="x" size={14} />
        </span>
      );
    case "skipped":
      return (
        <span
          data-testid="provision-step-icon-skipped"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-muted text-text-muted"
        >
          <Icon name="chevron-right" size={14} />
        </span>
      );
    default:
      return (
        <span
          data-testid="provision-step-icon-pending"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-border-default bg-surface-card"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-text-muted/50" />
        </span>
      );
  }
}

function buildFallbackArtifacts(
  serverType?: string,
  minecraftVersion?: string,
  mode?: string,
  port?: number,
): ProvisioningArtifactItem[] {
  const loaderLabel = serverType
    ? serverType.charAt(0).toUpperCase() + serverType.slice(1)
    : "Server Core";
  const versionLabel = minecraftVersion ? ` ${minecraftVersion}` : "";
  const javaMajor = minecraftVersion ? resolveJavaMajorForMcVersion(minecraftVersion) : 21;
  const modeDisplay = `${serverModeLabel(mode)} Mode${mode === "advanced" ? " (Git initialized)" : ""}`;
  return [
    {
      id: "core_jar",
      label: "Server JAR",
      value: `${loaderLabel}${versionLabel} · Verified`,
      status: "verified",
    },
    {
      id: "runtime",
      label: "Runtime & Mode",
      value: `Java ${javaMajor} · ${modeDisplay}`,
      status: "ready",
    },
    {
      id: "config",
      label: "Configuration",
      value: `server.properties, eula.txt · Port ${port ?? 25565}`,
      status: "completed",
    },
  ];
}

export function ProvisioningProgress({
  serverId,
  className = "",
  compact = false,
  serverName,
  serverType,
  minecraftVersion,
  mode,
  port,
  initialSnapshot = null,
  retryable = true,
  retrying = false,
  enablePollingFallback = false,
  onRetryProvisioning,
  onOpenConsole,
  onStartServer,
}: ProvisioningProgressProps) {
  const navigate = useNavigate();
  const api = useMemo(() => createAuthenticatedApi(), []);
  const liveProgress = useProvisionProgress(serverId, { enablePollingFallback });
  const snapshot: ProvisioningSnapshot | null = liveProgress?.snapshot ?? initialSnapshot;

  const effectiveStage =
    liveProgress?.stage ??
    (snapshot?.status === "completed"
      ? "success"
      : snapshot?.status === "failed"
        ? "failed"
        : snapshot?.current_step_id ?? "download_core");

  const isCompleted =
    snapshot?.status === "completed" || effectiveStage === "success";
  const isFailed =
    snapshot?.status === "failed" ||
    effectiveStage === "failed" ||
    effectiveStage === "timeout";
  const isTerminal = isCompleted || isFailed;

  const [mountStartEpoch] = useState(() => Date.now());
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [activityExpanded, setActivityExpanded] = useState(true);
  const [startingServer, setStartingServer] = useState(false);
  const [retryingLocal, setRetryingLocal] = useState(false);
  const activityListRef = useRef<HTMLDivElement | null>(null);

  const parsedStartedAt = snapshot?.started_at ? Date.parse(snapshot.started_at) : Number.NaN;
  const startedAtEpoch = !Number.isNaN(parsedStartedAt) ? parsedStartedAt : mountStartEpoch;

  useEffect(() => {
    if (isTerminal) return;
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isTerminal]);

  const activeTransfer: ProvisioningTransferState | null =
    snapshot?.active_transfer ?? null;

  const activityItems: ProvisioningActivityItem[] =
    snapshot?.activity && snapshot.activity.length > 0
      ? snapshot.activity
      : liveProgress?.message
        ? [
            {
              timestamp: new Date(liveProgress.timestamp).toISOString(),
              message: liveProgress.message,
              level: isFailed ? "error" : isCompleted ? "success" : "info",
            },
          ]
        : [];

  useEffect(() => {
    if (activityListRef.current && activityExpanded) {
      activityListRef.current.scrollTop = activityListRef.current.scrollHeight;
    }
  }, [activityItems.length, activityExpanded]);

  const elapsedMs = isTerminal
    ? snapshot?.elapsed_ms && snapshot.elapsed_ms > 0
      ? snapshot.elapsed_ms
      : Math.max(0, nowMs - startedAtEpoch)
    : Math.max(snapshot?.elapsed_ms ?? 0, nowMs - startedAtEpoch);

  const percent = isCompleted
    ? 100
    : liveProgress?.percent ?? snapshot?.percent ?? 0;
  const stageLabel = getStageLabel(effectiveStage);
  const displayMessage =
    snapshot?.error ||
    liveProgress?.message ||
    snapshot?.message ||
    "Preparing server files...";

  if (compact) {
    const transferPct =
      activeTransfer?.percent ?? (percent > 0 ? percent : 0);
    return (
      <div
        data-testid="provisioning-progress-compact"
        className={`flex flex-col gap-1.5 min-w-[140px] ${className}`}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={`h-4 w-4 shrink-0 rounded-full border-2 ${
                isFailed
                  ? "border-status-danger-border border-t-status-danger"
                  : isCompleted
                    ? "border-status-success-border border-t-status-success"
                    : "animate-spin border-border-default border-t-accent-primary"
              }`}
            />
            <span className="truncate text-xs font-medium text-text-secondary">
              {stageLabel}
            </span>
          </div>
          <span
            data-testid="provisioning-elapsed-timer"
            className="shrink-0 font-mono text-[10px] text-text-muted tabular-nums"
          >
            {formatStopwatch(elapsedMs)}
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={Math.round(Math.min(100, Math.max(0, transferPct)))}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-1.5 w-full bg-surface-muted rounded-full overflow-hidden"
        >
          <div
            className={`h-full transition-all duration-300 ease-out ${
              isFailed
                ? "bg-status-danger"
                : isCompleted
                  ? "bg-status-success"
                  : "bg-accent-primary"
            }`}
            style={{ width: `${Math.min(100, Math.max(0, transferPct))}%` }}
          />
        </div>
        <p className="text-[10px] text-text-muted truncate">
          {activeTransfer && activeTransfer.phase === "downloading"
            ? `${activeTransfer.filename}${
                activeTransfer.speed_bps ? ` · ${formatSpeed(activeTransfer.speed_bps)}` : ""
              }${activeTransfer.eta_seconds != null ? ` · ${formatEta(activeTransfer.eta_seconds)}` : ""}`
            : displayMessage}
        </p>
      </div>
    );
  }

  const resolvedName = snapshot?.server_name || serverName || "New Server";
  const resolvedType = snapshot?.server_type || serverType;
  const resolvedVersion = snapshot?.minecraft_version || minecraftVersion;
  const resolvedMode = snapshot?.mode || mode || "simple";

  const steps: ProvisioningStepItem[] =
    snapshot?.steps && snapshot.steps.length > 0
      ? snapshot.steps
      : deriveFallbackSteps(effectiveStage, displayMessage, isCompleted, isFailed);

  const artifacts: ProvisioningArtifactItem[] =
    snapshot?.artifacts && snapshot.artifacts.length > 0
      ? snapshot.artifacts
      : buildFallbackArtifacts(resolvedType, resolvedVersion, resolvedMode, port);

  const handleOpenConsole = () => {
    if (onOpenConsole) {
      onOpenConsole();
      return;
    }
    navigate(`/servers/${serverId}/console`);
  };

  const handleStartServer = async () => {
    if (startingServer) return;
    setStartingServer(true);
    try {
      if (onStartServer) {
        await onStartServer();
      } else if (typeof api.startServer === "function") {
        await api.startServer(serverId);
        navigate(`/servers/${serverId}/console`);
      }
    } finally {
      setStartingServer(false);
    }
  };

  const handleRetry = async () => {
    if (onRetryProvisioning) {
      onRetryProvisioning();
      return;
    }
    if (retryingLocal || typeof api.retryProvisioning !== "function") return;
    setRetryingLocal(true);
    try {
      await api.retryProvisioning(serverId);
    } finally {
      setRetryingLocal(false);
    }
  };

  const transferPercent =
    activeTransfer?.percent != null
      ? Math.min(100, Math.max(0, Math.round(activeTransfer.percent)))
      : Math.min(100, Math.max(0, Math.round(percent)));

  const statusBadgeClass = isFailed
    ? "border-status-danger-border bg-status-danger-bg text-status-danger"
    : isCompleted
      ? "border-status-success-border bg-status-success-bg text-status-success"
      : "border-status-info-border bg-status-info-bg text-status-info";

  const statusBadgeText = isFailed
    ? "Creation Failed"
    : isCompleted
      ? "Server Ready"
      : "Creating Server...";

  return (
    <div
      data-testid="provisioning-progress-card"
      className={`rounded-xl border border-border-default bg-surface-card p-5 shadow-xs space-y-5 text-left ${className}`}
    >
      {/* 1. Header with Live Elapsed Stopwatch */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-subtle pb-4">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-bold text-text-primary truncate">
              {resolvedName}
            </h3>
            {resolvedType && <LoaderBadge loader={resolvedType} />}
            {resolvedVersion && (
              <span className="rounded-md border border-border-default bg-surface-muted px-2 py-0.5 font-mono text-[11px] font-medium text-text-secondary">
                MC {resolvedVersion}
              </span>
            )}
            <span
              data-testid="provisioning-status-badge"
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${statusBadgeClass}`}
            >
              {!isTerminal && (
                <span className="h-2 w-2 rounded-full bg-status-info animate-pulse" />
              )}
              {statusBadgeText}
            </span>
          </div>
          <p className="text-xs text-text-muted">{displayMessage}</p>
        </div>

        <div
          data-testid="provisioning-elapsed-timer"
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-muted px-3 py-1.5 font-mono text-xs font-semibold text-text-primary tabular-nums shrink-0"
        >
          <Icon name="clock" size={14} className="text-text-muted" />
          <span>
            {isCompleted
              ? `Completed in ${formatTerminalDuration(elapsedMs)}`
              : isFailed
                ? `Failed after ${formatTerminalDuration(elapsedMs)}`
                : formatStopwatch(elapsedMs)}
          </span>
        </div>
      </div>

      {/* 2. Active Transfer & ETA Banner (when downloading or installing) */}
      {!isTerminal && (activeTransfer || liveProgress) && (
        <div
          data-testid="provisioning-transfer-banner"
          className="rounded-xl border border-status-info-border bg-surface-muted p-4 space-y-2.5"
        >
          {activeTransfer?.phase === "installing" ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-status-info/30 border-t-status-info" />
                  <span className="font-semibold text-text-primary truncate">
                    Installing loader libraries...
                  </span>
                </div>
                <span className="font-mono text-[11px] text-text-muted tabular-nums">
                  {activeTransfer.percent != null
                    ? `${Math.round(activeTransfer.percent)}%`
                    : formatStopwatch(elapsedMs)}
                </span>
              </div>
              <div
                role="progressbar"
                aria-label="Installer progress"
                aria-valuenow={transferPercent}
                aria-valuemin={0}
                aria-valuemax={100}
                className="h-2 w-full overflow-hidden rounded-full bg-surface-card"
              >
                <div
                  className={`h-full rounded-full bg-accent-primary transition-all duration-300 ${
                    activeTransfer.percent == null ? "animate-pulse" : ""
                  }`}
                  style={{
                    width: `${activeTransfer.percent != null ? Math.max(4, transferPercent) : 65}%`,
                  }}
                />
              </div>
              <p className="text-[11px] text-text-muted truncate">{displayMessage}</p>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <Icon name="download" size={14} className="shrink-0 text-accent-primary" />
                  <span className="font-mono font-semibold text-text-primary truncate">
                    {activeTransfer?.filename || "Preparing server download..."}
                  </span>
                  {activeTransfer && activeTransfer.file_total > 1 && (
                    <span className="rounded-full border border-border-default bg-surface-card px-2 py-0.5 text-[10px] font-medium text-text-secondary shrink-0">
                      File {activeTransfer.file_index} of {activeTransfer.file_total}
                    </span>
                  )}
                </div>
                <span className="font-mono text-xs font-bold text-text-primary tabular-nums shrink-0">
                  {activeTransfer?.total_bytes != null || activeTransfer?.percent != null
                    ? `${transferPercent}%`
                    : activeTransfer
                      ? formatMb(activeTransfer.bytes_downloaded)
                      : `${transferPercent}%`}
                </span>
              </div>

              <div
                role="progressbar"
                aria-label="Download progress"
                aria-valuenow={transferPercent}
                aria-valuemin={0}
                aria-valuemax={100}
                className="h-2 w-full overflow-hidden rounded-full bg-surface-card"
              >
                <div
                  className="h-full rounded-full bg-accent-primary transition-all duration-300 ease-out"
                  style={{ width: `${Math.max(2, transferPercent)}%` }}
                />
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono text-text-muted tabular-nums">
                <span>
                  {activeTransfer
                    ? activeTransfer.total_bytes != null
                      ? `${formatMb(activeTransfer.bytes_downloaded)} / ${formatMb(activeTransfer.total_bytes)}`
                      : `${formatMb(activeTransfer.bytes_downloaded)} downloaded`
                    : displayMessage}
                </span>
                <div className="flex items-center gap-3">
                  {activeTransfer?.speed_bps != null && activeTransfer.speed_bps > 0 && (
                    <span>{formatSpeed(activeTransfer.speed_bps)}</span>
                  )}
                  {activeTransfer?.eta_seconds != null && (
                    <span className="font-semibold text-text-primary">
                      {formatEta(activeTransfer.eta_seconds)}
                    </span>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* 3. Clear 5-Step Vertical Timeline */}
      <div className="space-y-2" data-testid="provisioning-step-timeline">
        <h4 className="text-xs font-bold uppercase tracking-wider text-text-muted">
          Provisioning Steps
        </h4>
        <div className="space-y-2">
          {steps.map((step) => {
            const isCurrent = !isTerminal && step.status === "running";
            const rowTone =
              step.status === "failed"
                ? "border-status-danger-border bg-status-danger-bg/50"
                : isCurrent
                  ? "border-status-info-border bg-status-info-bg/50"
                  : "border-border-subtle bg-surface-card";
            return (
              <div
                key={step.id}
                data-testid={`provisioning-step-${step.id}`}
                data-status={step.status}
                className={`flex items-start gap-3 rounded-lg border p-2.5 transition-colors ${rowTone}`}
              >
                <div className="pt-0.5">
                  <StepStatusIcon status={step.status} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="font-medium text-text-primary truncate">
                      {step.label}
                    </span>
                    <span className="font-mono text-xs text-text-muted tabular-nums shrink-0">
                      {formatStepDuration(step, nowMs, isTerminal)}
                    </span>
                  </div>
                  {step.detail && (
                    <p
                      className={`mt-0.5 text-xs break-words ${
                        step.status === "failed"
                          ? "text-status-danger"
                          : "text-text-muted"
                      }`}
                    >
                      {step.detail}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 4. Collapsible / Compact Live Activity Feed */}
      {activityItems.length > 0 && (
        <div
          data-testid="provisioning-activity-feed"
          className="rounded-xl border border-border-subtle bg-surface-muted overflow-hidden"
        >
          <button
            type="button"
            onClick={() => setActivityExpanded((prev) => !prev)}
            className="flex w-full items-center justify-between px-3.5 py-2 text-xs font-semibold text-text-secondary hover:bg-surface-hover/50 transition-colors cursor-pointer"
          >
            <span className="flex items-center gap-2">
              <Icon name="activity" size={13} className="text-text-muted" />
              <span>Activity Log ({activityItems.length})</span>
            </span>
            <Icon
              name={activityExpanded ? "chevron-up" : "chevron-down"}
              size={14}
              className="text-text-muted"
            />
          </button>
          {activityExpanded && (
            <div
              ref={activityListRef}
              className="max-h-36 overflow-y-auto border-t border-border-subtle px-3.5 py-2 font-mono text-[11px] space-y-1"
            >
              {activityItems.map((item, idx) => {
                const timeStr = formatActivityTime(item.timestamp);
                const msgColor =
                  item.level === "error"
                    ? "text-status-danger"
                    : item.level === "success"
                      ? "text-status-success"
                      : item.level === "warning"
                        ? "text-status-warning"
                        : "text-text-secondary";
                return (
                  <div key={`${item.timestamp}-${idx}`} className="flex items-start gap-2">
                    {timeStr && (
                      <span className="shrink-0 text-text-muted tabular-nums">
                        [{timeStr}]
                      </span>
                    )}
                    <span className={`break-words ${msgColor}`}>{item.message}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 5A. Completion Summary Card ("What Was Created & Installed") */}
      {isCompleted && (
        <div
          data-testid="provisioning-completion-summary"
          className="rounded-xl border border-status-success-border bg-status-success-bg/40 p-4 space-y-3"
        >
          <div className="flex items-center gap-2 text-status-success">
            <Icon name="check" size={16} />
            <h4 className="text-xs font-bold uppercase tracking-wider">
              What Was Created &amp; Installed
            </h4>
          </div>
          <ul className="space-y-1.5 text-xs">
            {artifacts.map((art) => (
              <li
                key={art.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-subtle bg-surface-card px-3 py-2"
              >
                <span className="flex items-center gap-2 font-medium text-text-secondary">
                  <Icon name="check" size={13} className="text-status-success shrink-0" />
                  <span>{art.label}</span>
                </span>
                <span className="font-mono text-[11px] font-medium text-text-primary text-right">
                  {art.value}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center justify-end gap-2.5 pt-1">
            <button
              type="button"
              onClick={handleStartServer}
              disabled={startingServer}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-4 py-2 text-xs font-semibold text-text-primary hover:bg-surface-hover disabled:opacity-50 transition-colors cursor-pointer"
            >
              <Icon name="play" size={13} />
              <span>{startingServer ? "Starting..." : "Start Server Now"}</span>
            </button>
            <button
              type="button"
              onClick={handleOpenConsole}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover transition-colors shadow-xs cursor-pointer"
            >
              <Icon name="terminal" size={13} />
              <span>Open Server Console</span>
            </button>
          </div>
        </div>
      )}

      {/* 5B. Failure Card with Retry */}
      {isFailed && (
        <div
          data-testid="provisioning-failure-summary"
          role="alert"
          className="rounded-xl border border-status-danger-border bg-status-danger-bg p-4 space-y-3"
        >
          <div className="flex items-start gap-2.5 text-status-danger">
            <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
            <div className="min-w-0 space-y-1">
              <h4 className="text-xs font-bold uppercase tracking-wider">
                Provisioning Failed
              </h4>
              <p className="text-xs text-text-secondary break-words">
                {snapshot?.error || liveProgress?.message || "An unexpected error occurred during setup."}
              </p>
            </div>
          </div>
          {retryable && (
            <div className="flex justify-end">
              <button
                type="button"
                data-testid="provisioning-retry-btn"
                disabled={retrying || retryingLocal}
                onClick={() => void handleRetry()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-status-danger px-4 py-2 text-xs font-semibold text-accent-contrast-text hover:opacity-90 disabled:opacity-50 transition-opacity cursor-pointer"
              >
                <Icon name="restart" size={13} />
                <span>{retrying || retryingLocal ? "Retrying..." : "Retry Provisioning"}</span>
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
