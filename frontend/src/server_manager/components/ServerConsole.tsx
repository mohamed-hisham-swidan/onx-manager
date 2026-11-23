import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useServerMetrics } from "@/server_manager/hooks/useServerMetrics";
import { useConsoleStream } from "@/hooks/useWebSocket";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState } from "@/websocket/types";
import { Icon } from "@/components/ui/Icon";
import { CrashReportViewerModal } from "./CrashReportViewerModal";

function useApi() {
  return createAuthenticatedApi();
}

interface ServerConsoleProps {
  serverId: string;
  serverStatus?: string;
  tps?: number | null;
  players?: number;
  provider?: string | null;
  host?: string | null;
  port?: number | null;
  compactHeader?: boolean;
}

const containerBadgeClass =
  "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold " +
  "uppercase tracking-wider bg-status-info-bg text-status-info border border-status-info-border font-sans";

const hostBadgeClass =
  "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold " +
  "uppercase tracking-wider bg-accent-primary/10 text-accent-primary border border-accent-primary/30 font-sans";

function getLineStyle(line: string): { className: string; level: string } {
  if (line.startsWith("> ")) {
    return { className: "text-status-success font-semibold", level: "command" };
  }
  const upper = line.toUpperCase();
  if (
    upper.includes("[ERROR]") ||
    upper.includes("[FATAL]") ||
    upper.includes("[SEVERE]") ||
    upper.includes("ERROR:") ||
    upper.includes("FATAL:") ||
    upper.includes("EXCEPTION:")
  ) {
    return { className: "text-rose-400 font-semibold", level: "error" };
  }
  if (upper.includes("[WARN]") || upper.includes("[WARNING]") || upper.includes("WARN:")) {
    return { className: "text-amber-400", level: "warn" };
  }
  if (upper.includes("[INFO]") || upper.includes("INFO:")) {
    return { className: "text-sky-300", level: "info" };
  }
  return { className: "text-gray-300", level: "default" };
}

export function ServerConsole({
  serverId,
  serverStatus,
  tps,
  players,
  provider,
  host,
  port,
  compactHeader = false,
}: ServerConsoleProps) {
  const isContainer = provider === "docker" || provider === "container";
  const displayAddress = host ? (port ? `${host}:${port}` : host) : null;
  const api = useApi();
  const containerRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [liveLines, setLiveLines] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [followLog, setFollowLog] = useState(true);
  const [isCrashModalOpen, setIsCrashModalOpen] = useState(false);

  const isWsConnected = useWSStore((s) => s.connected);
  const connectionState = useWSStore((s) => s.connectionState);

  // Fetch initial console history (with offline fallback on disk)
  // Stage E: Disable 3s polling query while WS connection is active to avoid double-fetching.
  const { data: history, refetch: refetchHistory } = useQuery({
    queryKey: queryKeys.console.history(serverId),
    queryFn: () => api.getServerConsole(serverId, 200),
    refetchInterval: isWsConnected ? false : 3000,
  });

  // Reconnect re-tail: when WS connection re-establishes (from RECONNECTING/DISCONNECTED to CONNECTED),
  // or when returning to a hidden tab, backfill recent lines via HTTP tail and reset accumulated live lines.
  const prevConnectionStateRef = useRef(connectionState);
  useEffect(() => {
    const prev = prevConnectionStateRef.current;
    if (
      (prev === ConnectionState.RECONNECTING || prev === ConnectionState.DISCONNECTED) &&
      connectionState === ConnectionState.CONNECTED
    ) {
      refetchHistory().then(() => {
        setLiveLines([]);
      });
    }
    prevConnectionStateRef.current = connectionState;
  }, [connectionState, refetchHistory]);

  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        refetchHistory().then(() => {
          setLiveLines([]);
        });
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [refetchHistory]);

  // Fetch recent crash reports for crash detection banner
  const { data: crashReports, isLoading: isLoadingCrashes } = useQuery({
    queryKey: queryKeys.console.crashReports(serverId),
    queryFn: () => api.getServerCrashReports(serverId, 5),
  });

  // Subscribe to WebSocket console stream
  const handleIncomingLines = useCallback((lines: string[]) => {
    setLiveLines((prev) => [...prev, ...lines]);
  }, []);

  useConsoleStream(serverId, handleIncomingLines);

  const { data: metrics } = useServerMetrics(serverId);
  const latestMetric = metrics?.length
    ? metrics.reduce((latest, m) => (m.timestamp > latest.timestamp ? m : latest))
    : undefined;

  const isRunning = serverStatus === "running";
  const rawTps = tps !== undefined ? tps : latestMetric?.tps;
  const liveTps = isRunning && rawTps != null ? rawTps : null;

  const rawPlayers = players !== undefined ? players : latestMetric?.players;
  const livePlayers = isRunning && rawPlayers != null ? rawPlayers : null;

  const sendCommand = useMutation({
    mutationFn: (command: string) => api.sendServerCommand(serverId, { command }),
    onSuccess: (_data, command) => {
      setCommandHistory((prev) => [...prev, `> ${command}`]);
      if (followLog && containerRef.current) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight;
      }
    },
  });

  // Combine initial history, WS live lines, and local command history
  const allLines = useMemo(() => {
    const base = history?.lines ?? [];
    return [...base, ...liveLines, ...commandHistory];
  }, [history?.lines, liveLines, commandHistory]);

  // Filter lines by search query if present
  const filteredLines = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return allLines;
    return allLines.filter((l) => l.toLowerCase().includes(query));
  }, [allLines, searchQuery]);

  // Handle auto-scrolling with followLog
  useEffect(() => {
    if (!followLog) return;
    const container = containerRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [allLines, followLog]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sendCommand.isPending) return;
    sendCommand.mutate(input.trim());
    setInput("");
  };

  const handleClear = () => {
    setCommandHistory([]);
    setLiveLines([]);
  };

  const tpsColorClass =
    liveTps != null
      ? liveTps >= 19.5
        ? "text-status-success"
        : liveTps >= 16.0
          ? "text-status-warning"
          : "text-status-danger"
      : "text-text-muted";

  const hasCrashReports = Boolean(crashReports && crashReports.length > 0);
  const latestCrash = hasCrashReports ? crashReports![0] : null;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Crash Detected Alert Banner */}
      {hasCrashReports && latestCrash && (
        <div
          data-testid="crash-alert-banner"
          className="mb-3 p-3 rounded-xl bg-status-danger-bg border border-status-danger-border text-status-danger flex items-center justify-between gap-3 shadow-lg animate-fade-in"
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="p-1.5 rounded-lg bg-status-danger-bg text-status-danger border border-status-danger-border shrink-0">
              <Icon name="alert" size={16} />
            </div>
            <div className="min-w-0 text-xs">
              <div className="font-semibold text-text-primary flex items-center gap-2 flex-wrap">
                <span>Crash Detected:</span>
                <span className="font-mono text-[11px] bg-status-danger-bg px-1.5 py-0.5 rounded border border-status-danger-border">
                  {latestCrash.failure_code}
                </span>
                {latestCrash.blamed_mod && (
                  <span
                    data-testid="crash-banner-blamed-mod"
                    className="font-mono text-[11px] bg-status-warning-bg text-status-warning px-1.5 py-0.5 rounded border border-status-warning-border font-bold"
                  >
                    Blamed: {latestCrash.blamed_mod}
                  </span>
                )}
              </div>
              <p className="text-text-muted text-[11px] truncate mt-0.5">
                {latestCrash.filename} • {latestCrash.suggested_remediation}
              </p>
            </div>
          </div>
          <button
            type="button"
            data-testid="crash-banner-view-btn"
            onClick={() => setIsCrashModalOpen(true)}
            className="px-3 py-1.5 rounded-lg bg-status-danger hover:opacity-90 text-accent-contrast-text text-xs font-semibold shrink-0 transition-colors shadow"
          >
            View Crash Report
          </button>
        </div>
      )}

      <div className="flex flex-col flex-1 min-h-0 bg-terminal-bg text-terminal-text font-mono text-xs rounded-xl border border-border-default overflow-hidden mb-3">
        {/* Console Header Bar */}
        <div className="flex items-center justify-between px-3.5 py-2 bg-surface-card/90 border-b border-border-subtle text-xs select-none flex-wrap gap-2">
          <div className="flex items-center gap-2 text-text-secondary font-sans font-medium text-xs flex-wrap">
            <span
              className={`flex h-2 w-2 rounded-full ${
                isRunning ? "bg-status-success animate-pulse" : "bg-text-muted"
              }`}
            />
            <span>Server Console</span>

            {!compactHeader && (
              <>
                {/* High-Contrast Status Capsule */}
                {isRunning ? (
                  <span
                    data-testid="console-status-capsule"
                    className="inline-flex items-center gap-1.5 rounded-full border border-status-success/40 bg-status-success-bg px-2.5 py-0.5 font-mono text-[11px] font-bold text-status-success shadow-xs"
                  >
                    <span className="text-[9px] leading-none" aria-hidden="true">●</span>
                    <span>ONLINE · PORT {port ?? 25565}</span>
                  </span>
                ) : (
                  <span
                    data-testid="console-status-capsule"
                    className="inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-elevated px-2.5 py-0.5 font-mono text-[11px] font-bold text-text-secondary shadow-xs"
                  >
                    <span className="text-[9px] leading-none" aria-hidden="true">○</span>
                    <span>OFFLINE · CONTAINER HALTED</span>
                  </span>
                )}

                {/* Active Player Counter Badge */}
                <div
                  data-testid="console-player-counter-capsule"
                  className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-elevated border border-border-default text-[11px] text-text-secondary font-mono"
                  title="Active Players"
                >
                  <Icon name="users" size={12} className="text-text-muted" />
                  <span>{livePlayers ?? 0} / 20 Players</span>
                </div>
                {isContainer ? (
                  <span
                    data-testid="console-provider-badge"
                    className={containerBadgeClass}
                    title="Runtime: Docker Container"
                  >
                    <Icon name="server" size={11} className="text-status-info" />
                    <span>Container</span>
                  </span>
                ) : (
                  <span
                    data-testid="console-provider-badge"
                    className={hostBadgeClass}
                    title="Runtime: Host Filesystem / Process"
                  >
                    <Icon name="folder" size={11} className="text-accent-primary" />
                    <span>File / Host</span>
                  </span>
                )}
                {displayAddress && (
                  <span
                    data-testid="console-ip-badge"
                    className={
                      "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono " +
                      "font-medium bg-surface-muted text-text-secondary border border-border-default font-sans"
                    }
                    title={
                      isContainer
                        ? `Container IP: ${displayAddress}`
                        : `Host IP: ${displayAddress}`
                    }
                  >
                    <Icon name="globe" size={10} className="text-text-muted" />
                    <span className="font-mono">{displayAddress}</span>
                  </span>
                )}
              </>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Crash Reports Button */}
            {hasCrashReports && (
              <button
                type="button"
                data-testid="view-crash-reports-btn"
                onClick={() => setIsCrashModalOpen(true)}
                className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-status-danger-bg text-status-danger border border-status-danger-border hover:opacity-90 text-[11px] font-sans font-medium transition-colors"
                title="View Crash Reports"
              >
                <Icon name="alert" size={11} className="text-status-danger" />
                <span>Crash ({crashReports!.length})</span>
              </button>
            )}

            {/* TPS Usage Badge */}
            <div
              data-testid="console-tps-badge"
              className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-md bg-terminal-bg border border-border-subtle font-mono text-[11px]"
              title={
                liveTps != null
                  ? `Server Tick Rate: ${liveTps.toFixed(1)} / 20.0 TPS`
                  : "TPS unknown"
              }
            >
              <span className="text-text-muted font-sans font-semibold text-[10px] uppercase tracking-wider">
                TPS
              </span>
              <span className={`font-bold ${tpsColorClass}`}>
                {liveTps != null ? liveTps.toFixed(1) : "—"}
              </span>
              {liveTps != null && (
                <span className="text-[10px] text-text-muted">
                  ({Math.min(100, Math.round((liveTps / 20) * 100))}%)
                </span>
              )}
            </div>

            {/* Players Badge */}
            {livePlayers != null && (
              <div
                data-testid="console-players-badge"
                className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-terminal-bg border border-border-subtle text-[11px] text-terminal-text font-mono"
                title={`${livePlayers} player(s) online`}
              >
                <Icon name="users" size={12} className="text-text-muted" />
                <span>{livePlayers}</span>
              </div>
            )}

            {/* Clear History Button */}
            {(commandHistory.length > 0 || liveLines.length > 0) && (
              <button
                type="button"
                onClick={handleClear}
                className="text-text-muted hover:text-text-primary transition-colors text-[11px] font-sans px-1.5 py-0.5 rounded hover:bg-surface-hover"
                title="Clear local command history"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Console Search & Control Subheader Toolbar */}
        <div className="flex items-center justify-between px-3 py-1.5 bg-surface-muted/60 border-b border-border-subtle text-xs gap-3">
          <div className="flex items-center gap-2 flex-1 max-w-md">
            <div className="relative flex-1">
              <span className="absolute inset-y-0 left-0 flex items-center pl-2 pointer-events-none text-text-muted">
                <Icon name="search" size={12} />
              </span>
              <input
                data-testid="console-search-input"
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search logs (case-insensitive)..."
                className="w-full pl-7 pr-7 py-1 text-xs font-mono bg-terminal-bg border border-border-subtle rounded-md text-terminal-text placeholder:text-text-muted focus:outline-none focus:border-border-focus"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute inset-y-0 right-0 pr-2 flex items-center text-text-muted hover:text-text-primary"
                  aria-label="Clear search"
                >
                  <Icon name="x" size={11} />
                </button>
              )}
            </div>
            {searchQuery && (
              <span
                data-testid="console-search-matches"
                className="text-text-muted text-[11px] font-sans whitespace-nowrap"
              >
                {filteredLines.length} {filteredLines.length === 1 ? "match" : "matches"}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Follow Log Auto-Scroll Toggle */}
            <button
              type="button"
              data-testid="follow-log-toggle"
              onClick={() => setFollowLog((prev) => !prev)}
              className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-sans font-medium transition-colors ${
                followLog
                  ? "bg-status-success-bg text-status-success border border-status-success-border"
                  : "bg-surface-muted text-text-muted border border-border-subtle hover:text-text-primary"
              }`}
              title={followLog ? "Auto-scrolling enabled" : "Auto-scrolling paused"}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  followLog ? "bg-status-success" : "bg-text-muted"
                }`}
              />
              <span>Follow Log</span>
            </button>
          </div>
        </div>

        {/* Output container (33rem is a tunable constant for estimated chrome above and below the log) */}
        <div ref={containerRef} className="h-[calc(100dvh-33rem)] min-h-[420px] overflow-y-auto p-3 space-y-0.5 select-text">
          {filteredLines.length === 0 ? (
            <p className="text-text-muted font-sans">
              {searchQuery ? "No logs matching your search filter." : "No console output yet."}
            </p>
          ) : (
            filteredLines.map((line, i) => {
              const { className } = getLineStyle(line);
              return (
                <div key={i} className={`whitespace-pre-wrap break-all ${className}`}>
                  {line}
                </div>
              );
            })
          )}
        </div>
      </div>

      <form onSubmit={handleSend} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Enter a command..."
          className="flex-1 px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-border-focus"
        />
        <button
          type="submit"
          disabled={sendCommand.isPending || !input.trim()}
          className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors disabled:opacity-50"
        >
          {sendCommand.isPending ? "Sending..." : "Send"}
        </button>
      </form>

      {/* Crash Report Modal */}
      <CrashReportViewerModal
        isOpen={isCrashModalOpen}
        onClose={() => setIsCrashModalOpen(false)}
        reports={crashReports ?? []}
        isLoading={isLoadingCrashes}
        serverName={serverId}
      />
    </div>
  );
}
