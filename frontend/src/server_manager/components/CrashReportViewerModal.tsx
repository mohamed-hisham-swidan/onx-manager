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
    >
      <div className="flex flex-col space-y-4 text-gray-100 max-h-[75vh]">
        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-1 space-y-4">
          {isLoading ? (
            <div className="py-12 text-center text-gray-400 space-y-2">
              <div className="inline-block w-6 h-6 border-2 border-rose-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-xs">Loading crash reports...</p>
            </div>
          ) : reports.length === 0 ? (
            <div className="py-12 text-center space-y-2">
              <Icon name="check" size={32} className="mx-auto text-emerald-400" />
              <p className="text-sm font-medium text-gray-200">No crash reports found</p>
              <p className="text-xs text-gray-400">
                The server directory does not contain any recorded crash reports in crash-reports/.
              </p>
            </div>
          ) : currentReport ? (
            <>
              {/* Report selector if multiple exist */}
              {reports.length > 1 && (
                <div className="flex items-center gap-2 pb-1 border-b border-gray-800 overflow-x-auto">
                  <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider shrink-0">
                    Reports:
                  </span>
                  {reports.map((r, idx) => (
                    <button
                      key={r.filename}
                      type="button"
                      onClick={() => setSelectedIndex(idx)}
                      className={`px-2.5 py-1 rounded text-xs font-mono transition-colors shrink-0 ${
                        idx === selectedIndex
                          ? "bg-rose-900/60 text-rose-200 border border-rose-700/80 font-bold"
                          : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200"
                      }`}
                    >
                      {r.filename}
                    </button>
                  ))}
                </div>
              )}

              {/* Top metadata grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="p-3 bg-gray-950/70 border border-gray-800 rounded-lg">
                  <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                    File & Timestamp
                  </div>
                  <div className="text-xs font-mono text-gray-200 mt-1 break-all">
                    {currentReport.filename}
                  </div>
                  <div className="text-[11px] text-gray-400 mt-0.5">
                    {formatDateTime(currentReport.timestamp)}
                  </div>
                </div>

                <div className="p-3 bg-gray-950/70 border border-gray-800 rounded-lg">
                  <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                    Failure Classification
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <span
                      data-testid="failure-code-badge"
                      className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold font-mono uppercase bg-rose-950 text-rose-300 border border-rose-800/80"
                    >
                      {currentReport.failure_code}
                    </span>
                  </div>
                </div>
              </div>

              {/* Blamed Mod Callout */}
              {currentReport.blamed_mod && (
                <div
                  data-testid="blamed-mod-callout"
                  className="p-3.5 bg-rose-950/40 border border-rose-600/60 rounded-lg flex items-start gap-3 text-rose-200"
                >
                  <div className="p-1.5 rounded-md bg-rose-600/20 text-rose-300 border border-rose-500/40 shrink-0 mt-0.5">
                    <Icon name="alert" size={16} />
                  </div>
                  <div className="space-y-1">
                    <div className="text-xs font-semibold uppercase tracking-wider text-rose-300">
                      Blamed Mod Detected
                    </div>
                    <div className="text-sm font-bold text-rose-100 flex items-center gap-2">
                      <span>Mod ID:</span>
                      <span className="font-mono bg-rose-900/60 px-2 py-0.5 rounded border border-rose-700/80">
                        {currentReport.blamed_mod}
                      </span>
                    </div>
                    <p className="text-xs text-rose-200/90 leading-relaxed">
                      The mod loader reported an incompatible or crashing mod exception originating
                      from this mod. Consider updating, replacing, or disabling it in the Mods tab.
                    </p>
                  </div>
                </div>
              )}

              {/* Suggested Remediation */}
              {currentReport.suggested_remediation && (
                <div className="p-3.5 bg-sky-950/40 border border-sky-800/60 rounded-lg flex items-start gap-3 text-sky-200">
                  <div className="p-1.5 rounded-md bg-sky-600/20 text-sky-300 border border-sky-500/40 shrink-0 mt-0.5">
                    <Icon name="info" size={16} />
                  </div>
                  <div className="space-y-0.5">
                    <div className="text-xs font-semibold uppercase tracking-wider text-sky-300">
                      Suggested Remediation
                    </div>
                    <p className="text-xs text-sky-100 leading-relaxed">
                      {currentReport.suggested_remediation}
                    </p>
                  </div>
                </div>
              )}

              {/* Stack Trace Snippet */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
                    Stack Trace Snippet
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      copy(currentReport.stack_trace_snippet, "Stack trace snippet copied!")
                    }
                    className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-100 bg-gray-800 hover:bg-gray-700 px-2 py-1 rounded transition-colors"
                  >
                    <Icon name="copy" size={12} />
                    <span>Copy Snippet</span>
                  </button>
                </div>
                <div
                  data-testid="stack-trace-snippet"
                  className="bg-gray-950 text-rose-300 font-mono text-xs p-3 rounded-lg border border-gray-800 overflow-x-auto max-h-60 whitespace-pre leading-relaxed select-text"
                >
                  {currentReport.stack_trace_snippet || "No stack trace extracted."}
                </div>
              </div>

              {/* Collapsible Full Crash Report */}
              <div className="space-y-1.5 pt-2 border-t border-gray-800">
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => setShowFullReport((prev) => !prev)}
                    className="flex items-center gap-1.5 text-xs text-gray-300 hover:text-gray-100 font-medium transition-colors"
                  >
                    <Icon
                      name={showFullReport ? "chevron-up" : "chevron-down"}
                      size={14}
                      className="text-gray-400"
                    />
                    <span>{showFullReport ? "Hide Full Crash Report" : "View Full Crash Report"}</span>
                  </button>
                  {showFullReport && (
                    <button
                      type="button"
                      onClick={() =>
                        copy(currentReport.raw_content, "Full crash report copied!")
                      }
                      className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-100 bg-gray-800 hover:bg-gray-700 px-2 py-1 rounded transition-colors"
                    >
                      <Icon name="copy" size={12} />
                      <span>Copy Full Report</span>
                    </button>
                  )}
                </div>
                {showFullReport && (
                  <div
                    data-testid="full-crash-content"
                    className="bg-gray-950 text-gray-300 font-mono text-[11px] p-3 rounded-lg border border-gray-800 overflow-x-auto max-h-80 whitespace-pre leading-relaxed select-text"
                  >
                    {currentReport.raw_content}
                  </div>
                )}
              </div>
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 pt-3 border-t border-gray-800">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs font-medium transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
