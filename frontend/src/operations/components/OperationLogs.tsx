import React, { useEffect, useRef } from "react";
import type { OperationLogLine } from "../stores/operationStore";

export interface OperationLogsProps {
  logs: OperationLogLine[];
}

export const OperationLogs: React.FC<OperationLogsProps> = ({ logs }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs]);

  if (!logs || logs.length === 0) {
    return (
      <div
        data-testid="operation-logs-empty"
        className="rounded-lg border border-border-subtle bg-terminal-bg p-4 text-center font-mono text-xs text-text-muted"
      >
        Waiting for operation logs...
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      role="log"
      aria-label="Operation logs"
      aria-live="polite"
      data-testid="operation-logs-container"
      className="h-48 overflow-y-auto rounded-lg border border-border-subtle bg-terminal-bg p-3 font-mono text-xs text-terminal-text"
    >
      <div className="space-y-1">
        {logs.map((log, index) => {
          const isError = log.level === "error";
          const isWarn = log.level === "warning" || log.level === "warn";
          const colorClass = isError
            ? "text-status-danger"
            : isWarn
            ? "text-status-warning"
            : "text-terminal-text";

          return (
            <div key={index} className="flex items-start gap-2 leading-relaxed">
              <span className="shrink-0 text-text-muted select-none">
                {new Date(log.timestamp * 1000).toLocaleTimeString([], {
                  hour12: false,
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
              <span className={`shrink-0 uppercase text-[10px] font-semibold px-1 rounded ${
                isError
                  ? "bg-status-danger-bg text-status-danger"
                  : isWarn
                  ? "bg-status-warning-bg text-status-warning"
                  : "bg-surface-muted text-text-muted"
              }`}>
                {log.level}
              </span>
              <span className={`flex-1 break-all ${colorClass}`}>{log.line}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
