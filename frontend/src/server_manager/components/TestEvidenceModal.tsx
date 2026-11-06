import { useState, useEffect, useMemo } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { createAuthenticatedApi } from "@/services/api";
import { useClipboard } from "@/hooks/useClipboard";
import type { ServerTestRun, EvidenceBundle } from "@/server_manager/types";

export interface TestEvidenceModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  testRun?: ServerTestRun | null;
  testId?: string | null;
}

export function TestEvidenceModal({
  isOpen,
  onClose,
  serverId,
  testRun,
  testId,
}: TestEvidenceModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { copy } = useClipboard();

  const [evidence, setEvidence] = useState<EvidenceBundle | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);

  const effectiveTestId = testRun?.id || testId || null;

  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setIsLoading(true);
      setError(null);
      setEvidence(null);
    }
  }

  useEffect(() => {
    if (!isOpen || !effectiveTestId) return;

    let isMounted = true;
    api
      .getTestEvidence(serverId, effectiveTestId)
      .then((data) => {
        if (isMounted) {
          setEvidence(data);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          setError(
            err instanceof Error
              ? err.message
              : "Failed to load diagnostic evidence bundle."
          );
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, serverId, effectiveTestId, api]);

  const culpritMods: string[] = Array.isArray(evidence?.crash_analysis?.suspected_culprit_mods)
    ? (evidence?.crash_analysis?.suspected_culprit_mods as string[])
    : [];

  const handleCopyEvidence = () => {
    if (!evidence) return;
    copy(JSON.stringify(evidence, null, 2), "Evidence bundle copied to clipboard");
  };

  return (
    <Modal
      open={isOpen && Boolean(effectiveTestId)}
      onClose={onClose}
      title="Test Diagnostic Evidence"
      description={
        effectiveTestId ? (
          <span>
            Run ID: <span className="font-mono text-text-secondary">{effectiveTestId.slice(0, 8)}</span>
            {testRun?.commit_id ? (
              <> • Target Commit: <span className="font-mono text-text-secondary">{testRun.commit_id.slice(0, 8)}</span></>
            ) : null}
          </span>
        ) : undefined
      }
      size="xl"
      closeOnBackdrop={true}
      closeOnEscape={true}
    >
      <div className="flex flex-col space-y-4 text-text-primary max-h-[75vh]">
        {error && (
          <div role="alert" className="rounded-lg bg-status-danger-bg border border-status-danger-border p-3 text-xs text-status-danger">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-4 pr-1">
          {isLoading ? (
            <div className="py-12 text-center text-xs text-text-muted">
              Fetching diagnostic evidence bundle...
            </div>
          ) : !evidence ? (
            <div className="py-12 text-center text-xs text-text-muted">
              No diagnostic evidence bundle recorded for this run.
            </div>
          ) : (
            <div className="space-y-4">
              {/* Summary Cards */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg border border-border-default bg-surface-card p-3">
                  <span className="text-[10px] uppercase font-semibold text-text-muted block">
                    Outcome
                  </span>
                  <span className="text-sm font-bold text-status-danger font-mono">
                    {testRun?.status || (evidence.assertions?.boot_passed ? "PASSED" : "FAILED")}
                  </span>
                </div>
                <div className="rounded-lg border border-border-default bg-surface-card p-3">
                  <span className="text-[10px] uppercase font-semibold text-text-muted block">
                    Container Exit Code
                  </span>
                  <span className="text-sm font-bold text-text-primary font-mono">
                    {evidence.runtime?.exit_code !== undefined
                      ? String(evidence.runtime.exit_code)
                      : "N/A"}
                  </span>
                </div>
                <div className="rounded-lg border border-border-default bg-surface-card p-3">
                  <span className="text-[10px] uppercase font-semibold text-text-muted block">
                    Boot Passed
                  </span>
                  <span
                    className={`text-sm font-bold ${
                      evidence.assertions?.boot_passed ? "text-status-success" : "text-status-danger"
                    }`}
                  >
                    {evidence.assertions?.boot_passed ? "YES" : "NO"}
                  </span>
                </div>
              </div>

              {/* Artifact Retention Notice */}
              <div className="flex items-center justify-between px-3 py-2 rounded-lg border border-border-default bg-surface-card text-xs">
                <span className="text-text-muted">
                  Artifact Retention Window (24h debug):
                </span>
                <span
                  className={`font-semibold ${
                    testRun?.artifacts_purged ? "text-status-warning" : "text-status-success"
                  }`}
                >
                  {testRun?.artifacts_purged ? "Pruned (Lazy Reaped)" : "Retained on Disk"}
                </span>
              </div>

              {/* Culprit Mod Blaming */}
              {culpritMods.length > 0 && (
                <div role="alert" className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-status-danger block">
                    Suspected Culprit Mods
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {culpritMods.map((modName) => (
                      <span
                        key={modName}
                        className="inline-flex items-center gap-1 rounded-md bg-surface-card border border-status-danger-border px-2 py-1 text-xs font-mono font-bold text-status-danger"
                      >
                        <Icon name="alert" size={12} />
                        {modName}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Failure Reason */}
              {Boolean(testRun?.failure_reason || evidence.crash_analysis?.root_cause || evidence.crash_analysis?.failure_reason) && (
                <div className="rounded-lg border border-border-default bg-surface-card p-3 space-y-1">
                  <span className="text-xs font-semibold text-text-muted uppercase tracking-wider block">
                    Failure Reason
                  </span>
                  <p className="text-xs text-status-danger font-mono">
                    {String(testRun?.failure_reason || evidence.crash_analysis?.root_cause || evidence.crash_analysis?.failure_reason)}
                  </p>
                </div>
              )}

              {/* Stack Trace / Crash Analysis */}
              {evidence.crash_analysis && typeof evidence.crash_analysis === "object" && (
                <div className="rounded-lg border border-border-default bg-surface-card p-3 space-y-2">
                  <span className="text-xs font-semibold text-text-muted uppercase tracking-wider block">
                    Crash Analysis Details
                  </span>
                  <pre
                    tabIndex={0}
                    className="text-[11px] font-mono text-terminal-text bg-terminal-bg p-2.5 rounded border border-border-default overflow-x-auto max-h-48 whitespace-pre-wrap focus:outline-none focus:ring-1 focus:ring-border-focus"
                  >
                    {typeof evidence.crash_analysis.stack_trace === "string"
                      ? evidence.crash_analysis.stack_trace
                      : typeof evidence.crash_analysis.root_cause === "string"
                      ? evidence.crash_analysis.root_cause
                      : JSON.stringify(evidence.crash_analysis, null, 2)}
                  </pre>
                </div>
              )}

              {/* Log Tail Snippet */}
              {evidence.log_tail && evidence.log_tail.length > 0 && (
                <div className="rounded-lg border border-border-default bg-surface-card p-3 space-y-2">
                  <span className="text-xs font-semibold text-text-muted uppercase tracking-wider block">
                    Log Tail at Failure
                  </span>
                  <pre
                    tabIndex={0}
                    className="text-[11px] font-mono text-terminal-text bg-terminal-bg p-2.5 rounded border border-border-default overflow-x-auto max-h-40 focus:outline-none focus:ring-1 focus:ring-border-focus"
                  >
                    {evidence.log_tail.join("\n")}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex justify-between items-center pt-2 border-t border-border-default">
          <button
            type="button"
            onClick={handleCopyEvidence}
            disabled={!evidence}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-muted px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-surface-hover disabled:opacity-50"
          >
            <Icon name="copy" size={14} />
            Copy Diagnostic JSON
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-accent-primary hover:bg-accent-hover px-4 py-1.5 text-xs font-semibold text-accent-contrast-text transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
