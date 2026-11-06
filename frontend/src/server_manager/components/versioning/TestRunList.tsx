import { Icon } from "@/components/ui/Icon";
import { StartingMonitorBanner } from "@/server_manager/components/StartingMonitorBanner";
import type { ServerTestRun } from "@/server_manager/types";

interface TestRunListProps {
  testRuns: ServerTestRun[];
  serverId?: string;
  onTestProfiles: () => void;
  onEvidence: (testId: string) => void;
  onLogs: (run: ServerTestRun) => void;
  onPromote: (testId: string) => void;
  onDiscard: (testId: string) => void;
  onCheckNow: (run: ServerTestRun) => Promise<void>;
}

export function TestRunList({
  testRuns,
  onTestProfiles,
  onEvidence,
  onLogs,
  onPromote,
  onDiscard,
  onCheckNow,
}: TestRunListProps) {
  return (
    <div className="rounded-xl border border-border-subtle bg-surface-card dark:bg-gray-800 shadow-2xs overflow-hidden">
      {/* Header */}
      <div className="border-b border-border-subtle px-5 py-3.5 flex items-center justify-between bg-surface-elevated/40">
        <div className="flex items-center gap-2">
          <Icon name="activity" size={16} className="text-accent-primary" />
          <h2 className="text-xs font-bold uppercase tracking-wider text-text-primary">
            Isolated Test Runs
          </h2>
        </div>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onTestProfiles}
            className="inline-flex items-center gap-1.5 rounded-md border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
          >
            <Icon name="settings" size={12} />
            Test Profiles
          </button>
          <span className="font-mono text-xs tabular-nums text-text-muted">
            {testRuns.length} runs recorded
          </span>
        </div>
      </div>

      {testRuns.length === 0 ? (
        <div className="p-8 text-center text-sm text-text-muted">
          No isolated test runs active or recorded. Launch a test from any commit on the timeline.
        </div>
      ) : (
        <div className="divide-y divide-border-subtle/50">
          {testRuns.map((run) => (
            <div
              key={run.id}
              className="p-4.5 space-y-3 transition-colors hover:bg-surface-hover/30"
            >
              {/* Card Header & Status */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      run.status === "PASSED"
                        ? "bg-status-success-bg text-status-success border border-status-success-border"
                        : run.status === "FAILED"
                        ? "bg-status-danger-bg text-status-danger border border-status-danger-border"
                        : run.status === "RUNNING"
                        ? "bg-status-info-bg text-status-info border border-status-info-border animate-pulse"
                        : run.status === "BOOTING"
                        ? "bg-status-warning-bg text-status-warning border border-status-warning-border animate-pulse"
                        : "bg-surface-elevated text-text-muted"
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${
                        run.status === "PASSED"
                          ? "bg-status-success"
                          : run.status === "FAILED"
                          ? "bg-status-danger"
                          : run.status === "RUNNING"
                          ? "bg-status-info"
                          : "bg-status-warning"
                      }`}
                    />
                    {run.status}
                  </span>
                  <span className="font-mono text-xs tabular-nums text-text-muted">
                    ID: {run.id.slice(0, 8)}
                  </span>
                </div>

                <span className="text-xs text-text-muted">
                  Target Commit: <span className="font-mono font-semibold tabular-nums text-text-secondary">{run.commit_id.slice(0, 8)}</span>
                </span>
              </div>

              {/* 4-Step Visual Mini-Stepper */}
              <div className="grid grid-cols-4 gap-1 rounded-lg border border-border-subtle bg-surface-elevated/60 p-2 text-center text-[11px]">
                <div className="flex items-center justify-center gap-1 font-mono text-status-success font-semibold">
                  <span>✓</span>
                  <span>1. CoW Clone</span>
                </div>
                <div
                  className={`flex items-center justify-center gap-1 font-mono font-semibold ${
                    run.status !== "BOOTING" ? "text-status-success" : "text-status-warning animate-pulse"
                  }`}
                >
                  <span>{run.status !== "BOOTING" ? "✓" : "▶"}</span>
                  <span>2. Sidecar Boot</span>
                </div>
                <div
                  className={`flex items-center justify-center gap-1 font-mono font-semibold ${
                    run.status === "PASSED" || run.status === "FAILED"
                      ? "text-status-success"
                      : run.status === "RUNNING"
                      ? "text-status-info animate-pulse"
                      : "text-text-muted"
                  }`}
                >
                  <span>{run.status === "PASSED" || run.status === "FAILED" ? "✓" : "•"}</span>
                  <span>3. Bot Swarm</span>
                </div>
                <div
                  className={`flex items-center justify-center gap-1 font-mono font-semibold ${
                    run.status === "PASSED"
                      ? "text-status-success"
                      : run.status === "FAILED"
                      ? "text-status-danger"
                      : "text-text-muted"
                  }`}
                >
                  <span>{run.status === "PASSED" ? "✓" : run.status === "FAILED" ? "×" : "•"}</span>
                  <span>4. Audit</span>
                </div>
              </div>

              {run.status === "BOOTING" && (
                <div className="mt-2">
                  <StartingMonitorBanner
                    targetName={`Test Run ${run.id.slice(0, 8)}`}
                    startedAt={run.created_at}
                    timeoutSeconds={120}
                    isTestRun={true}
                    onCheckNow={() => onCheckNow(run)}
                  />
                </div>
              )}

              {/* Specs Telemetry Strip */}
              <div className="flex flex-wrap items-center gap-2.5 text-xs text-text-muted">
                <span>Bots: {run.bot_count} ({run.bot_tech})</span>
                <span className="text-border-subtle">•</span>
                <span>Duration: {run.duration_minutes}m</span>
                <span className="text-border-subtle">•</span>
                <span>Placement: {run.placement_mode}</span>
                {run.ephemeral_port && (
                  <>
                    <span className="text-border-subtle">•</span>
                    <span className="font-mono text-text-secondary">Port: {run.ephemeral_port}</span>
                  </>
                )}
              </div>

              {run.failure_reason && (
                <div className="rounded-lg bg-status-danger-bg border border-status-danger-border p-2.5 text-xs text-status-danger">
                  <span className="font-semibold">Failure / Blame:</span> {run.failure_reason}
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border-subtle/50">
                <button
                  type="button"
                  onClick={() => onEvidence(run.id)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-semibold text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                  title="View diagnostic evidence and root-cause analysis"
                >
                  <Icon name="activity" size={12} />
                  Evidence
                </button>
                {run.log_output && (
                  <button
                    type="button"
                    onClick={() => onLogs(run)}
                    className="rounded-md border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-semibold text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                  >
                    Logs
                  </button>
                )}

                {run.status === "PASSED" ? (
                  <button
                    type="button"
                    onClick={() => onPromote(run.id)}
                    className="inline-flex items-center gap-1 rounded-md bg-status-success text-accent-contrast-text px-3 py-1 text-xs font-bold hover:bg-status-success/90 transition-colors shadow-2xs cursor-pointer ml-auto"
                  >
                    <Icon name="check" size={14} />
                    Promote to Live
                  </button>
                ) : run.status === "FAILED" ? (
                  <button
                    type="button"
                    onClick={() => onPromote(run.id)}
                    className="inline-flex items-center gap-1 rounded-md border border-status-warning-border bg-status-warning-bg px-2.5 py-1 text-xs font-semibold text-status-warning hover:bg-status-warning-bg/80 transition-colors cursor-pointer ml-auto"
                    title="Force promotion with administrative override"
                  >
                    <Icon name="alert" size={14} />
                    Force Promote
                  </button>
                ) : null}

                {(run.status === "RUNNING" || run.status === "PASSED" || run.status === "FAILED") && (
                  <button
                    type="button"
                    onClick={() => onDiscard(run.id)}
                    className="rounded-md border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-medium text-status-danger hover:bg-status-danger-bg transition-colors cursor-pointer"
                  >
                    Discard
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
