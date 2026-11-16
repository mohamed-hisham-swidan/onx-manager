import { useMemo } from "react";
import { Icon } from "@/components/ui/Icon";
import { StartingMonitorBanner } from "@/server_manager/components/StartingMonitorBanner";
import type { ServerTestRun } from "@/server_manager/types";

interface TestRunListProps {
  testRuns: ServerTestRun[];
  serverId?: string;
  onTestProfiles: () => void;
  onEvidence: (testId: string) => void;
  onLogs: (run: ServerTestRun) => void;
  onDiscard: (testId: string) => void;
  onCheckNow: (run: ServerTestRun) => Promise<void>;
  onRunTest?: (commitId: string) => void;
}

export function TestRunList({
  testRuns,
  onTestProfiles,
  onEvidence,
  onLogs,
  onDiscard,
  onCheckNow,
  onRunTest,
}: TestRunListProps) {
  const passedCount = useMemo(
    () => testRuns.filter((r) => r.status === "PASSED").length,
    [testRuns]
  );
  const activeCount = useMemo(
    () =>
      testRuns.filter(
        (r) => r.status === "RUNNING" || r.status === "PENDING" || r.status === "BOOTING"
      ).length,
    [testRuns]
  );
  const failedCount = useMemo(
    () => testRuns.filter((r) => r.status === "FAILED" || r.status === "CANCELLED").length,
    [testRuns]
  );

  return (
    <div className="h-full rounded-xl border border-border-subtle bg-surface-card dark:bg-gray-800 shadow-2xs overflow-hidden flex flex-col">
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

      {/* Live Summary Bar */}
      {testRuns.length > 0 && (
        <div className="px-5 py-2.5 bg-surface-muted/60 border-b border-border-subtle/70 flex flex-wrap items-center gap-3 text-xs">
          <span className="text-text-muted font-medium">Summary:</span>
          <span className="inline-flex items-center gap-1 rounded-full bg-status-success-bg px-2 py-0.5 font-semibold text-status-success border border-status-success-border">
            <span className="h-1.5 w-1.5 rounded-full bg-status-success" />
            {passedCount} Passed
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-status-info-bg px-2 py-0.5 font-semibold text-status-info border border-status-info-border">
            <span className="h-1.5 w-1.5 rounded-full bg-status-info" />
            {activeCount} Running / Pending
          </span>
          <span className="inline-flex items-center gap-1 rounded-full bg-status-danger-bg px-2 py-0.5 font-semibold text-status-danger border border-status-danger-border">
            <span className="h-1.5 w-1.5 rounded-full bg-status-danger" />
            {failedCount} Cancelled / Failed
          </span>
        </div>
      )}

      {testRuns.length === 0 ? (
        <div className="p-8 text-center text-sm text-text-muted">
          No isolated test runs active or recorded. Launch a test from any commit on the timeline.
        </div>
      ) : (
        <div className="divide-y divide-border-subtle/50 flex-1">
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

              {/* Clean Horizontal Stepper (without nested bordered boxes) */}
              <div className="flex items-center justify-between rounded-lg bg-surface-muted/60 px-3 py-2 text-xs">
                {/* 1. Clone */}
                <div
                  className="flex items-center gap-1.5 text-status-success font-medium shrink-0"
                  title="Instant storage cloning via copy-on-write reflink / Btrfs / ZFS"
                >
                  <Icon name="check" size={12} />
                  <span>Clone</span>
                </div>

                <div className="flex-1 mx-2 h-0.5 bg-status-success shrink" />

                {/* 2. Boot */}
                <div
                  className={`flex items-center gap-1.5 font-medium shrink-0 ${
                    run.status === "BOOTING"
                      ? "text-status-warning animate-pulse"
                      : run.status === "PENDING"
                      ? "text-text-muted"
                      : "text-status-success"
                  }`}
                  title="Safe test environment startup"
                >
                  <Icon
                    name={
                      run.status === "BOOTING"
                        ? "activity"
                        : run.status === "PENDING"
                        ? "clock"
                        : "check"
                    }
                    size={12}
                  />
                  <span>Boot</span>
                </div>

                <div
                  className={`flex-1 mx-2 h-0.5 shrink ${
                    run.status === "PASSED" || run.status === "FAILED" || run.status === "RUNNING"
                      ? "bg-status-success"
                      : "bg-border-subtle"
                  }`}
                />

                {/* 3. Swarm */}
                <div
                  className={`flex items-center gap-1.5 font-medium shrink-0 ${
                    run.status === "RUNNING"
                      ? "text-status-info animate-pulse"
                      : run.status === "PASSED" || run.status === "FAILED"
                      ? "text-status-success"
                      : "text-text-muted"
                  }`}
                  title="Automated bot simulation and stress testing"
                >
                  <Icon
                    name={
                      run.status === "RUNNING"
                        ? "activity"
                        : run.status === "PASSED" || run.status === "FAILED"
                        ? "check"
                        : "clock"
                    }
                    size={12}
                  />
                  <span>Swarm</span>
                </div>

                <div
                  className={`flex-1 mx-2 h-0.5 shrink ${
                    run.status === "PASSED"
                      ? "bg-status-success"
                      : run.status === "FAILED"
                      ? "bg-status-danger"
                      : "bg-border-subtle"
                  }`}
                />

                {/* 4. Audit */}
                <div
                  className={`flex items-center gap-1.5 font-medium shrink-0 ${
                    run.status === "PASSED"
                      ? "text-status-success"
                      : run.status === "FAILED"
                      ? "text-status-danger"
                      : "text-text-muted"
                  }`}
                  title="Health, TPS, and crash verification"
                >
                  <Icon
                    name={run.status === "PASSED" ? "check" : run.status === "FAILED" ? "x" : "clock"}
                    size={12}
                  />
                  <span>Audit</span>
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
                <span>Placement: {run.placement_mode === "sidecar" ? "Safe test environment" : run.placement_mode}</span>
                {run.ephemeral_port && (
                  <>
                    <span className="text-border-subtle">•</span>
                    <span className="font-mono text-text-secondary">Port: {run.ephemeral_port}</span>
                  </>
                )}
              </div>

              {/* Failure / Blame Card - Toned down on bg-surface-muted */}
              {run.failure_reason && (
                <div className="rounded-lg bg-surface-muted border border-border-subtle p-2.5 text-xs text-status-danger flex items-start gap-2">
                  <Icon name="alert" size={14} className="text-status-danger shrink-0 mt-0.5" />
                  <div>
                    <span className="font-semibold">Failure / Blame:</span> {run.failure_reason}
                  </div>
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
                {onRunTest && (
                  <button
                    type="button"
                    onClick={() => onRunTest(run.commit_id)}
                    className="inline-flex items-center gap-1.5 rounded-md border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-semibold text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                    title="Re-run isolated test against this target commit"
                  >
                    <Icon name="play" size={12} />
                    Re-run
                  </button>
                )}
                {run.log_output && (
                  <button
                    type="button"
                    onClick={() => onLogs(run)}
                    className="rounded-md border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-semibold text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                  >
                    Logs
                  </button>
                )}

                {(run.status === "RUNNING" || run.status === "BOOTING") && (
                  <button
                    type="button"
                    onClick={() => onDiscard(run.id)}
                    className="inline-flex items-center gap-1 rounded-md border border-status-danger-border bg-status-danger-bg px-2.5 py-1 text-xs font-semibold text-status-danger hover:bg-status-danger-bg/80 transition-colors cursor-pointer"
                    title="Cancel active test run"
                  >
                    <Icon name="x" size={12} />
                    Cancel Run
                  </button>
                )}

                {(run.status === "PASSED" || run.status === "FAILED") && (
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
