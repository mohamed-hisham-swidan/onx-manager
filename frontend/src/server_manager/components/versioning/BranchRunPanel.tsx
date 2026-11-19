import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import type {
  BranchRuntimeStatus,
  DataTemplate,
  ServerBranch,
} from "@/server_manager/types";

export interface BranchRunPanelProps {
  branchName: string;
  runtime: BranchRuntimeStatus | null;
  branchObj: ServerBranch | null;
  dataTemplates: DataTemplate[];
  uncommittedWarning: { commitSha: string } | null;
  onDismissUncommittedWarning: () => void;
  onOpenStartModal: () => void;
  onOpenStopModal: () => void;
  onOpenPortSetModal: () => void;
  onOpenConsoleActivityModal: (initialTab: "console" | "activity") => void;
  onOpenSaveTemplateModal: () => void;
}

function statusBadgeClasses(status: string): string {
  if (status === "running") {
    return "bg-status-success-bg text-status-success border-status-success-border";
  }
  if (status === "starting") {
    return "bg-status-warning-bg text-status-warning border-status-warning-border";
  }
  if (status === "crashed" || status === "failed") {
    return "bg-status-danger-bg text-status-danger border-status-danger-border";
  }
  return "bg-surface-elevated text-text-muted border-border-default";
}

function capitalize(value: string): string {
  if (!value) return value;
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function BranchRunPanel({
  branchName,
  runtime,
  branchObj,
  dataTemplates,
  uncommittedWarning,
  onDismissUncommittedWarning,
  onOpenStartModal,
  onOpenStopModal,
  onOpenPortSetModal,
  onOpenConsoleActivityModal,
  onOpenSaveTemplateModal,
}: BranchRunPanelProps) {
  const [copied, setCopied] = useState(false);
  const copyTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current !== null) {
        window.clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  const rawRuntimeStatus =
    runtime?.runtime_status ?? branchObj?.runtime_status ?? "stopped";
  const runtimeStatus = rawRuntimeStatus.toLowerCase();
  const isActive = runtimeStatus === "running" || runtimeStatus === "starting";
  const activeCommitSha =
    runtime?.active_commit_sha ?? branchObj?.active_commit_sha ?? null;
  const portSet = runtime?.port_set ?? branchObj?.port_set ?? null;
  const worktreeLocked = Boolean(
    runtime?.worktree_locked ?? branchObj?.worktree_locked,
  );
  const worktreeLockReason =
    runtime?.worktree_lock_reason ?? branchObj?.worktree_lock_reason ?? null;
  const activeTemplateId =
    runtime?.data_template_id ?? branchObj?.active_data_template_id ?? null;
  const activeTemplate = dataTemplates.find((t) => t.id === activeTemplateId);
  const isArchived = branchObj?.status === "archived";

  const handleCopyGamePort = useCallback(() => {
    if (!portSet) return;
    void navigator.clipboard
      ?.writeText(String(portSet.game_port))
      .catch(() => undefined);
    setCopied(true);
    if (copyTimeoutRef.current !== null) {
      window.clearTimeout(copyTimeoutRef.current);
    }
    copyTimeoutRef.current = window.setTimeout(() => setCopied(false), 2000);
  }, [portSet]);

  return (
    <div
      data-testid="branch-run-panel"
      className="rounded-xl border border-border-default bg-surface-card p-3.5 space-y-3 shadow-2xs"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Icon name="version-branch" size={16} className="text-accent-primary" />
          <span className="text-xs font-semibold text-text-secondary">
            Branch Runtime
          </span>
          <span className="rounded-md border border-border-default bg-surface-page px-2 py-0.5 text-[11px] font-mono font-semibold text-text-primary">
            {branchName}
          </span>

          <span
            data-testid="branch-runtime-status-badge"
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusBadgeClasses(runtimeStatus)}`}
          >
            {runtime?.container_liveness === true && (
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  runtimeStatus === "running"
                    ? "bg-status-success animate-pulse"
                    : "bg-status-warning animate-pulse"
                }`}
                aria-hidden="true"
              />
            )}
            {capitalize(runtimeStatus)}
          </span>

          {activeCommitSha && (
            <span className="rounded-md border border-border-default bg-surface-page px-2 py-0.5 text-[11px] font-mono text-text-secondary">
              Commit {activeCommitSha.slice(0, 8)}
            </span>
          )}

          {isActive && (
            <span className="rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 text-[11px] font-medium text-text-secondary">
              {activeTemplate
                ? `Template: ${activeTemplate.name}`
                : "Fresh world from seed"}
            </span>
          )}

          {isActive && (
            <span
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
                runtime?.allow_public_test_join
                  ? "bg-status-warning-bg text-status-warning border-status-warning-border"
                  : "bg-status-info-bg text-status-info border-status-info-border"
              }`}
            >
              <Icon
                name={runtime?.allow_public_test_join ? "alert" : "lock"}
                size={11}
              />
              {runtime?.allow_public_test_join
                ? "Public Test Join"
                : "Whitelisted Test Join"}
            </span>
          )}

          {worktreeLocked && (
            <span
              data-testid="worktree-lock-badge"
              title={worktreeLockReason ?? "Worktree locked by active runtime"}
              className="inline-flex items-center gap-1 rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 text-[11px] font-semibold text-text-secondary"
            >
              <Icon name="lock" size={12} />
              Worktree Locked
              {worktreeLockReason ? ` — ${worktreeLockReason}` : ""}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {!isActive ? (
            <>
              <button
                type="button"
                onClick={onOpenStartModal}
                disabled={isArchived}
                title={
                  isArchived
                    ? "Archived branches cannot be started"
                    : "Launch an isolated branch container"
                }
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover transition-colors shadow-xs cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Icon name="play" size={13} />
                Start Branch Run
              </button>
              <button
                type="button"
                onClick={onOpenPortSetModal}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
              >
                <Icon name="network" size={13} />
                Configure Ports
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={onOpenStopModal}
                className="inline-flex items-center gap-1.5 rounded-lg bg-status-danger-bg px-3 py-1.5 text-xs font-semibold text-status-danger border border-status-danger-border hover:bg-status-danger/10 transition-colors cursor-pointer"
              >
                <Icon name="stop" size={13} />
                Stop Branch Run
              </button>
              <button
                type="button"
                onClick={onOpenSaveTemplateModal}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
              >
                <Icon name="database" size={13} />
                Save Data Template
              </button>
              <button
                type="button"
                disabled
                title="Stop the active branch runtime before changing ports"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-muted opacity-50 cursor-not-allowed"
              >
                <Icon name="network" size={13} />
                Configure Ports
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => onOpenConsoleActivityModal("console")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
          >
            <Icon name="terminal" size={13} />
            Branch Console
          </button>
          <button
            type="button"
            onClick={() => onOpenConsoleActivityModal("activity")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
          >
            <Icon name="clock" size={13} />
            Branch Activity
          </button>
        </div>
      </div>

      {uncommittedWarning && (
        <div
          role="alert"
          data-testid="uncommitted-changes-warning"
          className="flex items-start justify-between gap-3 rounded-lg border border-status-warning-border bg-status-warning-bg p-3 text-xs text-status-warning"
        >
          <div className="flex items-start gap-2">
            <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
            <span>
              Uncommitted changes in worktree were not included. This branch run
              is serving the last committed snapshot (
              {uncommittedWarning.commitSha.slice(0, 8)}).
            </span>
          </div>
          <button
            type="button"
            onClick={onDismissUncommittedWarning}
            aria-label="Dismiss uncommitted changes warning"
            className="rounded p-0.5 hover:bg-status-warning/10 transition-colors cursor-pointer"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      )}

      <div
        data-testid="branch-port-set-strip"
        className="flex flex-wrap items-center gap-2 rounded-lg border border-border-subtle bg-surface-page p-2.5 text-[11px]"
      >
        <Icon name="network" size={13} className="text-text-muted" />
        {portSet ? (
          <>
            <span className="font-mono font-semibold text-text-primary">
              Game: {portSet.game_port}
            </span>
            <span className="font-mono text-text-secondary">
              RCON: {portSet.rcon_port}
            </span>
            {typeof portSet.query_port === "number" && (
              <span className="font-mono text-text-secondary">
                Query: {portSet.query_port}
              </span>
            )}
            {Object.entries(portSet.plugin_ports ?? {}).map(([name, port]) => (
              <span
                key={name}
                className="rounded border border-border-subtle bg-surface-elevated px-1.5 py-0.5 font-mono text-text-secondary"
              >
                {name}: {port}
              </span>
            ))}
            <button
              type="button"
              onClick={handleCopyGamePort}
              aria-label="Copy join port"
              className="ml-auto inline-flex items-center gap-1 rounded-md border border-border-default bg-surface-card px-2 py-1 text-[11px] font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
            >
              <Icon name="copy" size={11} />
              {copied ? "Copied!" : "Copy Game Port"}
            </button>
          </>
        ) : (
          <span className="text-text-muted">
            No port set assigned (will auto-allocate on start)
          </span>
        )}
      </div>
    </div>
  );
}
