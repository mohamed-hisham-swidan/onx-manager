import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { useActivityStore } from "@/stores/activityStore";
import type { DaemonLogEntry } from "@/server_manager/utils/telemetryAdapter";

interface CommandCenterDaemonStreamProps {
  initialLogs: DaemonLogEntry[];
  serverNames?: Record<string, string>;
}

export function CommandCenterDaemonStream({
  initialLogs,
  serverNames = {},
}: CommandCenterDaemonStreamProps) {
  const [logs, setLogs] = useState<DaemonLogEntry[]>(initialLogs);
  const [selectedServerId, setSelectedServerId] = useState("");
  const navigate = useNavigate();
  const liveEvents = useActivityStore((s) => s.events);
  const serverEntries = Object.entries(serverNames);

  function clearLogs() {
    setLogs([]);
  }

  // Combine initial system boot logs with any runtime activity events
  const combinedEntries = [
    ...logs,
    ...liveEvents.map((evt, idx) => {
      const date = new Date(evt.timestamp * 1000);
      const timeStr = date.toTimeString().split(" ")[0];
      const sName = (evt.server_id && serverNames[evt.server_id]) || evt.name || evt.server_id || "node";

      let source: DaemonLogEntry["source"] = "SYS";
      let msg = "";

      if (evt.event_type.includes("Start")) {
        source = "STATE";
        msg = `Instance '${sName}' start event dispatched`;
      } else if (evt.event_type.includes("Stop")) {
        source = "STATE";
        msg = `Instance '${sName}' stop completed gracefully`;
      } else if (evt.event_type.includes("Crash")) {
        source = "SYS";
        msg = `CRASH ALERT: '${sName}' exited abnormally`;
      } else {
        source = "WATCHER";
        msg = `Event ${evt.event_type} on '${sName}'`;
      }

      return {
        id: `activity-${idx}-${evt.timestamp}`,
        timeStr,
        source,
        message: msg,
      };
    }),
  ];

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-border-subtle bg-surface-card p-4 sm:p-5 shadow-2xs">
      {/* Header */}
      <div className="flex items-center justify-between pb-3.5 border-b border-border-subtle">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-success opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-status-success" />
          </span>
          <h2 className="text-xs font-bold uppercase tracking-wider text-text-muted">
            Daemon Event Stream
          </h2>
        </div>
        <button
          type="button"
          onClick={clearLogs}
          className="text-xs font-medium text-text-muted hover:text-text-primary transition-colors cursor-pointer"
        >
          Clear
        </button>
      </div>

      {/* Terminal Well Body */}
      <div
        role="log"
        aria-label="System event logs"
        className="mt-3.5 flex-1 min-h-0 overflow-y-auto rounded-lg bg-surface-elevated p-3 font-mono text-xs leading-relaxed select-text"
      >
        {combinedEntries.length === 0 ? (
          <div className="flex h-full items-center justify-center text-text-muted">
            Event buffer cleared. Awaiting new telemetry signals...
          </div>
        ) : (
          <div className="space-y-1.5">
            {combinedEntries.map((log) => {
              const badgeClass =
                log.source === "DOCKER"
                  ? "text-accent-primary"
                  : log.source === "NET"
                    ? "text-status-success"
                    : log.source === "STATE"
                      ? "text-status-warning"
                      : log.source === "SYS"
                        ? "text-status-info"
                        : "text-text-secondary";

              return (
                <div key={log.id} className="flex flex-wrap items-start gap-x-2 min-w-0">
                  <span className="shrink-0 text-text-muted/70">
                    [{log.timeStr}]
                  </span>
                  <span className={`shrink-0 font-semibold ${badgeClass}`}>
                    [{log.source}]
                  </span>
                  <span className="text-text-primary break-words min-w-0 flex-1 basis-40">
                    {log.message}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer Quick-Terminal Bar */}
      <div className="mt-3.5 flex items-center justify-between gap-2 rounded-lg bg-surface-elevated px-3 py-2 text-xs">
        <div className="flex flex-1 min-w-0 items-center gap-2 font-mono text-text-muted">
          <span className="text-accent-primary font-bold">&gt;</span>
          <select
            aria-label="Select a server to attach console"
            value={selectedServerId}
            onChange={(e) => {
              const targetId = e.target.value;
              setSelectedServerId(targetId);
              if (targetId) {
                navigate(`/servers/${targetId}/console`);
              }
            }}
            className="w-full min-w-0 truncate bg-transparent font-mono text-xs text-text-primary focus:outline-hidden cursor-pointer"
          >
            <option value="">Select a server to attach console...</option>
            {serverEntries.map(([id, name]) => (
              <option key={id} value={id}>
                Attach: {name}
              </option>
            ))}
          </select>
        </div>
        <Link
          to={selectedServerId ? `/servers/${selectedServerId}/console` : "/servers"}
          title={selectedServerId ? "Attach to selected server console" : "View all servers"}
          className="shrink-0 text-xs font-semibold text-accent-primary hover:underline"
        >
          <Icon name="terminal" size={13} />
        </Link>
      </div>
    </div>
  );
}
