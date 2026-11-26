import { Link, useInRouterContext } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { ConnectionState } from "@/websocket/types";
import type { ConsoleLevelFilter } from "./consoleLogParser";

export interface ConsoleLevelCounts {
  all: number;
  info: number;
  warn: number;
  error: number;
}

export interface ConsoleToolbarProps {
  serverId: string;
  isRunning: boolean;
  isBranchMode: boolean;
  branch?: string;
  compactHeader: boolean;
  port?: number | null;
  provider?: string | null;
  displayAddress?: string | null;
  liveTps: number | null;
  livePlayers: number | null;
  maxPlayers?: number;
  effectiveConnectionState: ConnectionState;
  isConsoleChannelDegraded: boolean;
  crashReportCount: number;
  onOpenCrashReports: () => void;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  matchCount: number;
  levelFilter: ConsoleLevelFilter;
  onLevelFilterChange: (level: ConsoleLevelFilter) => void;
  levelCounts: ConsoleLevelCounts;
  showIsoTimestamps: boolean;
  onToggleIsoTimestamps: () => void;
  followLog: boolean;
  onToggleFollowLog: () => void;
  hasLines: boolean;
  onCopyLogs: () => void;
  onDownloadLogs: () => void;
  onClearLogs: () => void;
}

function getStreamBadge(
  isRunning: boolean,
  isBranchMode: boolean,
  effectiveState: ConnectionState,
  isDegraded: boolean,
): { label: string; dotClass: string; badgeClass: string } {
  if (!isRunning) {
    return {
      label: "Offline",
      dotClass: "bg-terminal-muted",
      badgeClass: "border-terminal-border bg-terminal-bg text-terminal-muted",
    };
  }
  if (isBranchMode) {
    return {
      label: "Polling",
      dotClass: "bg-terminal-info",
      badgeClass: "border-terminal-border bg-terminal-bg text-terminal-info",
    };
  }
  if (effectiveState === ConnectionState.CONNECTED && !isDegraded) {
    return {
      label: "Live",
      dotClass: "bg-terminal-command animate-pulse",
      badgeClass: "border-status-success-border bg-status-success-bg text-terminal-command",
    };
  }
  if (
    effectiveState === ConnectionState.RECONNECTING ||
    effectiveState === ConnectionState.CONNECTING
  ) {
    return {
      label: "Reconnecting...",
      dotClass: "bg-terminal-warn animate-pulse",
      badgeClass: "border-status-warning-border bg-status-warning-bg text-terminal-warn",
    };
  }
  return {
    label: "Polling",
    dotClass: "bg-terminal-warn",
    badgeClass: "border-status-warning-border bg-status-warning-bg text-terminal-warn",
  };
}

export function ConsoleToolbar({
  serverId,
  isRunning,
  isBranchMode,
  branch,
  compactHeader,
  port,
  provider,
  displayAddress,
  liveTps,
  livePlayers,
  maxPlayers = 20,
  effectiveConnectionState,
  isConsoleChannelDegraded,
  crashReportCount,
  onOpenCrashReports,
  searchQuery,
  onSearchChange,
  matchCount,
  levelFilter,
  onLevelFilterChange,
  levelCounts,
  showIsoTimestamps,
  onToggleIsoTimestamps,
  followLog,
  onToggleFollowLog,
  hasLines,
  onCopyLogs,
  onDownloadLogs,
  onClearLogs,
}: ConsoleToolbarProps) {
  const inRouter = useInRouterContext();
  const isContainer = provider === "docker" || provider === "container";
  const logsHref = `/servers/${encodeURIComponent(serverId)}/files?tab=logs${
    isBranchMode && branch ? `&branch=${encodeURIComponent(branch)}` : ""
  }`;
  const streamBadge = getStreamBadge(
    isRunning,
    isBranchMode,
    effectiveConnectionState,
    isConsoleChannelDegraded,
  );

  const tpsColorClass =
    liveTps != null
      ? liveTps >= 19.5
        ? "text-terminal-command"
        : liveTps >= 16.0
          ? "text-terminal-warn"
          : "text-terminal-error"
      : "text-terminal-muted";

  const filterButtons: Array<{ id: ConsoleLevelFilter; label: string; count: number }> = [
    { id: "all", label: "All", count: levelCounts.all },
    { id: "info", label: "Info", count: levelCounts.info },
    { id: "warn", label: "Warn", count: levelCounts.warn },
    { id: "error", label: "Error", count: levelCounts.error },
  ];

  return (
    <div className="bg-terminal-surface border-b border-terminal-border select-none">
      {/* Row 1: Console Title, Stream Status & Actions */}
      <div className="flex items-center justify-between px-3.5 py-2 border-b border-terminal-border/60 text-xs flex-wrap gap-2">
        <div className="flex items-center gap-2 text-terminal-text font-sans font-medium text-xs flex-wrap">
          <span
            className={`flex h-2 w-2 rounded-full ${
              isRunning ? "bg-terminal-command animate-pulse" : "bg-terminal-muted"
            }`}
          />
          <span>Server Console</span>

          <span
            data-testid="console-stream-status"
            className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${streamBadge.badgeClass}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${streamBadge.dotClass}`} />
            {streamBadge.label}
          </span>

          {isBranchMode && branch && (
            <span
              data-testid="console-branch-badge"
              className="inline-flex items-center gap-1 rounded border border-terminal-border bg-terminal-bg px-1.5 py-0.5 font-mono text-[10px] font-semibold text-terminal-info"
            >
              Branch: {branch}
            </span>
          )}

          {!compactHeader && (
            <>
              {isRunning ? (
                <span
                  data-testid="console-status-capsule"
                  className="inline-flex items-center gap-1.5 rounded-full border border-status-success-border bg-status-success-bg px-2.5 py-0.5 font-mono text-[11px] font-bold text-terminal-command"
                >
                  <span className="text-[9px] leading-none" aria-hidden="true">
                    ●
                  </span>
                  <span>ONLINE · PORT {port ?? 25565}</span>
                </span>
              ) : (
                <span
                  data-testid="console-status-capsule"
                  className="inline-flex items-center gap-1.5 rounded-full border border-terminal-border bg-terminal-bg px-2.5 py-0.5 font-mono text-[11px] font-bold text-terminal-muted"
                >
                  <span className="text-[9px] leading-none" aria-hidden="true">
                    ○
                  </span>
                  <span>OFFLINE · CONTAINER HALTED</span>
                </span>
              )}

              <div
                data-testid="console-player-counter-capsule"
                className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-terminal-bg border border-terminal-border text-[11px] text-terminal-text font-mono"
                title="Active Players"
              >
                <Icon name="users" size={12} className="text-terminal-muted" />
                <span>
                  {livePlayers ?? 0} / {maxPlayers} Players
                </span>
              </div>

              <span
                data-testid="console-provider-badge"
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-terminal-bg text-terminal-info border border-terminal-border font-sans"
                title={isContainer ? "Runtime: Docker Container" : "Runtime: Host Process"}
              >
                <Icon name={isContainer ? "server" : "folder"} size={11} className="text-terminal-info" />
                <span>{isContainer ? "Container" : "File / Host"}</span>
              </span>

              {displayAddress && (
                <span
                  data-testid="console-ip-badge"
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-terminal-bg text-terminal-text border border-terminal-border"
                  title={`Server Address: ${displayAddress}`}
                >
                  <Icon name="globe" size={10} className="text-terminal-muted" />
                  <span>{displayAddress}</span>
                </span>
              )}
            </>
          )}
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {crashReportCount > 0 && (
            <button
              type="button"
              data-testid="view-crash-reports-btn"
              onClick={onOpenCrashReports}
              className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-status-danger-bg text-terminal-error border border-status-danger-border hover:opacity-90 text-[11px] font-sans font-medium transition-opacity cursor-pointer"
              title="View Crash Reports"
            >
              <Icon name="alert" size={11} className="text-terminal-error" />
              <span>Crash ({crashReportCount})</span>
            </button>
          )}

          {/* TPS Pill */}
          <div
            data-testid="console-tps-badge"
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-terminal-bg border border-terminal-border font-mono text-[11px]"
            title={
              liveTps != null
                ? `Server Tick Rate: ${liveTps.toFixed(1)} / 20.0 TPS`
                : "TPS unknown"
            }
          >
            <span className="text-terminal-muted font-sans font-semibold text-[10px] uppercase tracking-wider">
              TPS
            </span>
            <span className={`font-bold ${tpsColorClass}`}>
              {liveTps != null ? liveTps.toFixed(1) : "—"}
            </span>
            {liveTps != null && (
              <span className="text-[10px] text-terminal-muted">
                ({Math.min(100, Math.round((liveTps / 20) * 100))}%)
              </span>
            )}
          </div>

          {/* Players Pill */}
          {livePlayers != null && (
            <div
              data-testid="console-players-badge"
              className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-terminal-bg border border-terminal-border text-[11px] text-terminal-text font-mono"
              title={`${livePlayers} player(s) online`}
            >
              <Icon name="users" size={12} className="text-terminal-muted" />
              <span>{livePlayers}</span>
            </div>
          )}

          <div className="h-3.5 w-px bg-terminal-border mx-0.5 hidden sm:block" />

          {/* ISO Timestamp Toggle */}
          <button
            type="button"
            data-testid="console-iso-toggle"
            onClick={onToggleIsoTimestamps}
            aria-pressed={showIsoTimestamps}
            className={`px-1.5 py-0.5 rounded text-[11px] font-mono transition-colors cursor-pointer border ${
              showIsoTimestamps
                ? "bg-terminal-bg text-terminal-info border-terminal-info"
                : "bg-transparent text-terminal-muted border-transparent hover:text-terminal-text hover:bg-terminal-bg"
            }`}
            title={showIsoTimestamps ? "Showing raw ISO timestamps" : "Show raw Docker ISO timestamps"}
          >
            ISO
          </button>

          {/* Copy Logs */}
          <button
            type="button"
            data-testid="console-copy-btn"
            disabled={!hasLines}
            onClick={onCopyLogs}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-sans text-terminal-muted hover:text-terminal-text hover:bg-terminal-bg disabled:opacity-40 transition-colors cursor-pointer"
            title="Copy visible console logs"
          >
            <Icon name="copy" size={12} />
            <span className="hidden sm:inline">Copy</span>
          </button>

          {/* Download Logs */}
          <button
            type="button"
            data-testid="console-download-btn"
            disabled={!hasLines}
            onClick={onDownloadLogs}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-sans text-terminal-muted hover:text-terminal-text hover:bg-terminal-bg disabled:opacity-40 transition-colors cursor-pointer"
            title="Download visible console logs"
          >
            <Icon name="download" size={12} />
            <span className="hidden sm:inline">Download</span>
          </button>

          {/* Open Logs & Crashes Tab */}
          {inRouter ? (
            <Link
              to={logsHref}
              data-testid="console-open-logs-link"
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-sans text-terminal-muted hover:text-terminal-text hover:bg-terminal-bg transition-colors"
              title="Open full Logs & Crashes viewer"
            >
              <Icon name="file" size={12} />
              <span className="hidden sm:inline">Logs</span>
            </Link>
          ) : (
            <a
              href={logsHref}
              data-testid="console-open-logs-link"
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-sans text-terminal-muted hover:text-terminal-text hover:bg-terminal-bg transition-colors"
              title="Open full Logs & Crashes viewer"
            >
              <Icon name="file" size={12} />
              <span className="hidden sm:inline">Logs</span>
            </a>
          )}

          {/* Clear Logs */}
          {hasLines && (
            <button
              type="button"
              data-testid="console-clear-btn"
              onClick={onClearLogs}
              className="px-1.5 py-0.5 rounded text-[11px] font-sans text-terminal-muted hover:text-terminal-text hover:bg-terminal-bg transition-colors cursor-pointer"
              title="Clear console output"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Row 2: Search, Level Filters & Follow Log */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-terminal-bg/60 text-xs gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-md">
          <div className="relative flex-1">
            <span className="absolute inset-y-0 left-0 flex items-center pl-2 pointer-events-none text-terminal-muted">
              <Icon name="search" size={12} />
            </span>
            <input
              data-testid="console-search-input"
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search logs (case-insensitive)..."
              className="w-full pl-7 pr-7 py-1 text-xs font-mono bg-terminal-bg border border-terminal-border rounded-md text-terminal-text placeholder:text-terminal-muted focus:outline-none focus:border-border-focus"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => onSearchChange("")}
                className="absolute inset-y-0 right-0 pr-2 flex items-center text-terminal-muted hover:text-terminal-text cursor-pointer"
                aria-label="Clear search"
              >
                <Icon name="x" size={11} />
              </button>
            )}
          </div>
          {searchQuery && (
            <span
              data-testid="console-search-matches"
              className="text-terminal-muted text-[11px] font-sans whitespace-nowrap"
            >
              {matchCount} {matchCount === 1 ? "match" : "matches"}
            </span>
          )}
        </div>

        {/* Log Level Filter Pills */}
        <div className="flex items-center gap-1" role="group" aria-label="Filter log level">
          {filterButtons.map((btn) => {
            const active = levelFilter === btn.id;
            const activeTone =
              btn.id === "error"
                ? "border-status-danger-border bg-status-danger-bg text-terminal-error"
                : btn.id === "warn"
                  ? "border-status-warning-border bg-status-warning-bg text-terminal-warn"
                  : btn.id === "info"
                    ? "border-terminal-info bg-terminal-bg text-terminal-info"
                    : "border-terminal-border bg-terminal-surface text-terminal-text";
            return (
              <button
                key={btn.id}
                type="button"
                data-testid={`console-filter-${btn.id}`}
                aria-pressed={active}
                onClick={() => onLevelFilterChange(btn.id)}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-sans font-medium border transition-colors cursor-pointer ${
                  active
                    ? activeTone
                    : "border-transparent text-terminal-muted hover:text-terminal-text hover:bg-terminal-bg"
                }`}
              >
                <span>{btn.label}</span>
                {btn.count > 0 && (
                  <span className="font-mono text-[10px] opacity-85">{btn.count}</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Follow Log Toggle */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="follow-log-toggle"
            onClick={onToggleFollowLog}
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-sans font-medium border transition-colors cursor-pointer ${
              followLog
                ? "bg-status-success-bg text-terminal-command border-status-success-border"
                : "bg-terminal-bg text-terminal-muted border-terminal-border hover:text-terminal-text"
            }`}
            title={followLog ? "Auto-scrolling enabled" : "Auto-scrolling paused"}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                followLog ? "bg-terminal-command" : "bg-terminal-muted"
              }`}
            />
            <span>Follow Log</span>
          </button>
        </div>
      </div>
    </div>
  );
}
