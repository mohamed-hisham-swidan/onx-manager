import { useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { useClipboard } from "@/hooks/useClipboard";
import { formatDateTime } from "@/server_manager/utils/format";
import type { CrashReportSummary } from "@/server_manager/types";

export interface CrashReportViewerModalProps {
  isOpen: boolean;
  onClose: () => void;
  reports: CrashReportSummary[];
  isLoading?: boolean;
  serverName?: string;
}

export function CrashReportViewerModal({
  isOpen,
  onClose,
  reports,
  isLoading = false,
  serverName,
}: CrashReportViewerModalProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showFullReport, setShowFullReport] = useState(false);
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  const { copy } = useClipboard();

  // Reset index during rendering when modal opens (React 19 pattern)
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setSelectedIndex(0);
      setShowFullReport(false);
    }
  }

  const currentReport: CrashReportSummary | undefined =
    reports.length > 0 ? reports[Math.min(selectedIndex, reports.length - 1)] : undefined;

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Crash Report Inspector"
      ariaLabel="Crash Report Inspector"
      description={
        serverName ? `Server: ${serverName}` : "Diagnostic Details & Mod Blame"
      }
      size="2xl"
      closeOnBackdrop={true}
      closeOnEscape={true}
      closeButtonAriaLabel="Close crash report viewer"
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-surface-muted hover:bg-surface-hover text-text-primary border border-border-default text-xs font-medium transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      }
    >
      <div className="space-y-4 text-text-primary">
          {isLoading ? (
            <div className="py-12 text-center text-text-muted space-y-2">
              <div className="inline-block w-6 h-6 border-2 border-status-danger border-t-transparent rounded-full animate-spin" />
              <p className="text-xs">Loading crash reports...</p>
            </div>
          ) : reports.length === 0 ? (
            <div className="py-12 text-center space-y-2">
              <Icon name="check" size={32} className="mx-auto text-status-success" />
              <p className="text-sm font-medium text-text-primary">No crash reports found</p>
              <p className="text-xs text-text-muted">
                The server directory does not contain any recorded crash reports in crash-reports/.
              </p>
            </div>
          ) : currentReport ? (
            <>
              {/* Report selector if multiple exist */}
              {reports.length > 1 && (
                <div className="flex items-center gap-2 pb-1 border-b border-border-default overflow-x-auto">
                  <span className="text-xs font-semibold text-text-muted uppercase tracking-wider shrink-0">
                    Reports:
                  </span>
                  {reports.map((r, idx) => (
                    <button
                      key={r.filename}
                      type="button"
                      onClick={() => setSelectedIndex(idx)}
                      className={`px-2.5 py-1 rounded text-xs font-mono transition-colors shrink-0 ${
                        idx === selectedIndex
                          ? "bg-status-danger-bg text-status-danger border border-status-danger-border font-bold"
                          : "bg-surface-muted text-text-muted hover:bg-surface-hover hover:text-text-primary border border-border-subtle"
                      }`}
                    >
                      {r.filename}
                    </button>
                  ))}
                </div>
              )}

              {/* Top metadata grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="p-3 bg-surface-card border border-border-default rounded-lg">
                  <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">
                    File & Timestamp
                  </div>
                  <div className="text-xs font-mono text-text-primary mt-1 break-all">
                    {currentReport.filename}
                  </div>
                  <div className="text-[11px] text-text-muted mt-0.5">
                    {formatDateTime(currentReport.timestamp)}
                  </div>
                </div>

                <div className="p-3 bg-surface-card border border-border-default rounded-lg">
                  <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">
                    Failure Classification
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <span
                      data-testid="failure-code-badge"
                      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold font-mono uppercase bg-status-danger-bg text-status-danger border border-status-danger-border"
                    >
                      {currentReport.failure_code}
                    </span>
                  </div>
                </div>
              </div>

              {/* Blamed Mod Callout */}
              {currentReport.blamed_mod && (
                <div
                  role="alert"
                  data-testid="blamed-mod-callout"
                  className="p-3.5 bg-status-danger-bg border border-status-danger-border rounded-lg flex items-start gap-3 text-status-danger"
                >
                  <div className="p-1.5 rounded-md bg-status-danger-bg text-status-danger border border-status-danger-border shrink-0 mt-0.5">
                    <Icon name="alert" size={16} />
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wider text-status-danger">
                      Blamed Mod Detected
                    </div>
                    <div className="text-sm font-bold text-text-primary flex items-center gap-2">
                      <span>Mod ID:</span>
                      <span className="font-mono bg-surface-card px-2 py-0.5 rounded border border-status-danger-border text-status-danger">
                        {currentReport.blamed_mod}
                      </span>
                    </div>
                    <p className="text-xs text-text-secondary leading-relaxed">
                      The mod loader reported an incompatible or crashing mod exception originating
                      from this mod. Consider updating, replacing, or disabling it in the Mods tab.
                    </p>
                  </div>
                </div>
              )}

              {/* Suggested Remediation */}
              {currentReport.suggested_remediation && (
                <div className="p-3.5 bg-status-info-bg border border-status-info-border rounded-lg flex items-start gap-3 text-status-info">
                  <div className="p-1.5 rounded-md bg-status-info-bg text-status-info border border-status-info-border shrink-0 mt-0.5">
                    <Icon name="info" size={16} />
                  </div>
                  <div className="space-y-0.5">
                    <div className="text-xs font-semibold uppercase tracking-wider text-status-info">
                      Suggested Remediation
                    </div>
                    <p className="text-xs text-text-primary leading-relaxed">
                      {currentReport.suggested_remediation}
                    </p>
                  </div>
                </div>
              )}

              {/* Stack Trace Snippet */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                    Stack Trace Snippet
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      copy(currentReport.stack_trace_snippet, "Stack trace snippet copied!")
                    }
                    className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-subtle px-2 py-1 rounded transition-colors"
                  >
                    <Icon name="copy" size={12} />
                    <span>Copy Snippet</span>
                  </button>
                </div>
                <div
                  tabIndex={0}
                  data-testid="stack-trace-snippet"
                  className="bg-terminal-bg text-terminal-text font-mono text-xs p-3 rounded-lg border border-border-default overflow-x-auto max-h-60 whitespace-pre leading-relaxed select-text focus:outline-none focus:ring-1 focus:ring-border-focus"
                >
                  {currentReport.stack_trace_snippet || "No stack trace extracted."}
                </div>
              </div>

              {/* Collapsible Full Crash Report */}
              <div className="space-y-1.5 pt-2 border-t border-border-default">
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => setShowFullReport((prev) => !prev)}
                    className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary font-medium transition-colors"
                  >
                    <Icon
                      name={showFullReport ? "chevron-up" : "chevron-down"}
                      size={14}
                      className="text-text-muted"
                    />
                    <span>{showFullReport ? "Hide Full Crash Report" : "View Full Crash Report"}</span>
                  </button>
                  {showFullReport && (
                    <button
                      type="button"
                      onClick={() =>
                        copy(currentReport.raw_content, "Full crash report copied!")
                      }
                      className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-subtle px-2 py-1 rounded transition-colors"
                    >
                      <Icon name="copy" size={12} />
                      <span>Copy Full Report</span>
                    </button>
                  )}
                </div>
                {showFullReport && (
                  <div
                    tabIndex={0}
                    data-testid="full-crash-content"
                    className="bg-terminal-bg text-terminal-text font-mono text-[11px] p-3 rounded-lg border border-border-default overflow-x-auto max-h-80 whitespace-pre leading-relaxed select-text focus:outline-none focus:ring-1 focus:ring-border-focus"
                  >
                    {currentReport.raw_content}
                  </div>
                )}
              </div>
            </>
          ) : null}
      </div>
    </Modal>
  );
}
