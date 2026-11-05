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
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-800 bg-surface-card shadow-sm overflow-hidden">
      <div className="border-b border-border-subtle px-6 py-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
          Isolated Test Runs
        </h2>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onTestProfiles}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            <Icon name="settings" size={12} />
            Test Profiles
          </button>
          <span className="text-xs text-text-muted">
            {testRuns.length} runs recorded
          </span>
        </div>
      </div>

      {testRuns.length === 0 ? (
        <div className="p-8 text-center text-sm text-text-muted">
          No isolated test runs active or recorded. Launch a test from any commit above.
        </div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {testRuns.map((run) => (
            <div
              key={run.id}
              className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-surface-hover/50 transition-colors"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${
                      run.status === "PASSED"
                        ? "bg-status-success-bg text-status-success border border-status-success/30"
                        : run.status === "FAILED"
                        ? "bg-status-danger-bg text-status-danger border border-status-danger/30"
                        : run.status === "RUNNING"
                        ? "bg-status-info-bg text-status-info border border-status-info/30 animate-pulse"
                        : run.status === "BOOTING"
                        ? "bg-status-warning-bg text-status-warning border border-status-warning/30 animate-pulse"
                        : "bg-surface-hover text-text-muted"
                    }`}
                  >
                    {run.status}
                  </span>
                  <span className="font-mono text-xs text-text-muted">
                    ID: {run.id.slice(0, 8)}
                  </span>
                  <span className="text-xs text-text-muted">
                    Target Commit: <span className="font-mono">{run.commit_id.slice(0, 8)}</span>
                  </span>
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

                <div className="flex flex-wrap items-center gap-3 text-xs text-text-muted">
                  <span>Bots: {run.bot_count} ({run.bot_tech})</span>
                  <span>•</span>
                  <span>Duration: {run.duration_minutes}m</span>
                  <span>•</span>
                  <span>Placement: {run.placement_mode}</span>
                  {run.ephemeral_port && (
                    <>
                      <span>•</span>
                      <span>Port: {run.ephemeral_port}</span>
                    </>
                  )}
                </div>

                {run.failure_reason && (
                  <div className="rounded-lg bg-status-danger-bg border border-status-danger/30 p-2 text-xs text-status-danger mt-2">
                    <span className="font-semibold">Failure / Blame:</span> {run.failure_reason}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onEvidence(run.id)}
                  className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
                  title="View diagnostic evidence and root-cause analysis"
                >
                  <Icon name="activity" size={12} />
                  Evidence
                </button>
                {run.log_output && (
                  <button
                    type="button"
                    onClick={() => onLogs(run)}
                    className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
                  >
                    Logs
                  </button>
                )}

                {run.status === "PASSED" ? (
                  <button
                    type="button"
                    onClick={() => onPromote(run.id)}
                    className="inline-flex items-center gap-1 rounded-lg bg-status-success text-white px-3 py-1 text-xs font-semibold hover:bg-status-success/90 transition-colors shadow-sm cursor-pointer"
                  >
                    <Icon name="check" size={14} />
                    Promote to Live
                  </button>
                ) : run.status === "FAILED" ? (
                  <button
                    type="button"
                    onClick={() => onPromote(run.id)}
                    className="inline-flex items-center gap-1 rounded-lg border border-status-warning/40 bg-status-warning-bg px-2.5 py-1 text-xs font-medium text-status-warning hover:bg-status-warning-bg/80 transition-colors cursor-pointer"
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
                    className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-medium text-status-danger hover:bg-status-danger-bg transition-colors cursor-pointer"
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
