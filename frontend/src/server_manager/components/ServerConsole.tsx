import { useState, useRef, useEffect, useMemo, useCallback, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useServerMetrics } from "@/server_manager/hooks/useServerMetrics";
import { useConsoleStream } from "@/hooks/useWebSocket";
import {
  useWSStore,
  useEffectiveConnectionState,
  useIsChannelDegraded,
} from "@/stores/wsStore";
import { ConnectionState } from "@/websocket/types";
import { useClipboard } from "@/hooks/useClipboard";
import { Icon } from "@/components/ui/Icon";
import { CrashReportViewerModal } from "./CrashReportViewerModal";
import {
  MAX_CONSOLE_LINES,
  getLevelTagClass,
  getLevelTextClass,
  mergeDeduplicatedLines,
  parseConsoleLine,
  sliceLinesAfterWatermark,
  stripAnsiAndMcFormatting,
  tokenizeConsoleLine,
  type ConsoleLevelFilter,
} from "./console/consoleLogParser";
import { ConsoleToolbar } from "./console/ConsoleToolbar";
import { ConsoleCommandBar } from "./console/ConsoleCommandBar";

function useApi() {
  return createAuthenticatedApi();
}

const MAX_COMMAND_HISTORY = 50;
const RECENT_CRASH_WINDOW_MS = 10 * 60 * 1000;

interface ServerConsoleProps {
  serverId: string;
  serverName?: string;
  branch?: string;
  serverStatus?: string;
  tps?: number | null;
  players?: number;
  maxPlayers?: number;
  provider?: string | null;
  host?: string | null;
  port?: number | null;
  compactHeader?: boolean;
  canConsole?: boolean;
  uptimeSeconds?: number | null;
}

function renderHighlightedText(text: string, query: string): ReactNode {
  const trimmed = query.trim();
  if (!trimmed) return text;

  const lowerText = text.toLowerCase();
  const lowerQuery = trimmed.toLowerCase();
  const parts: ReactNode[] = [];
  let cursor = 0;
  let matchIdx = lowerText.indexOf(lowerQuery, cursor);
  let keyIdx = 0;

  while (matchIdx !== -1) {
    if (matchIdx > cursor) {
      parts.push(text.slice(cursor, matchIdx));
    }
    parts.push(
      <mark
        key={keyIdx++}
        className="bg-terminal-highlight-bg text-terminal-text rounded-xs px-0.5"
      >
        {text.slice(matchIdx, matchIdx + trimmed.length)}
      </mark>,
    );
    cursor = matchIdx + trimmed.length;
    matchIdx = lowerText.indexOf(lowerQuery, cursor);
  }

  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts.length > 0 ? parts : text;
}

function isCrashRecent(
  timestamp: string | undefined,
  serverStatus: string | undefined,
  uptimeSeconds: number | null | undefined,
): boolean {
  if (serverStatus === "crashed") return true;
  if (!timestamp) return false;
  const parsed = Date.parse(timestamp);
  if (Number.isNaN(parsed)) return false;

  const now = Date.now();
  // If server is running healthy and has been up longer than the crash age, treat crash as historical
  if (serverStatus === "running" && typeof uptimeSeconds === "number" && uptimeSeconds > 0) {
    const startedAtMs = now - uptimeSeconds * 1000;
    if (parsed < startedAtMs) {
      return false;
    }
  }
  return now - parsed <= RECENT_CRASH_WINDOW_MS;
}

export function ServerConsole({
  serverId,
  serverName,
  branch,
  serverStatus,
  tps,
  players,
  maxPlayers,
  provider,
  host,
  port,
  compactHeader = false,
  canConsole = true,
  uptimeSeconds,
}: ServerConsoleProps) {
  const isBranchMode = Boolean(branch && branch !== "main");
  const displayAddress = host ? (port ? `${host}:${port}` : host) : null;
  const api = useApi();
  const queryClient = useQueryClient();
  const { copy } = useClipboard();

  const containerRef = useRef<HTMLDivElement>(null);
  const [streamedLines, setStreamedLines] = useState<string[]>([]);
  const [clearedWatermark, setClearedWatermark] = useState<string[] | null>(null);
  const [sentCommands, setSentCommands] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [levelFilter, setLevelFilter] = useState<ConsoleLevelFilter>("all");
  const [showIsoTimestamps, setShowIsoTimestamps] = useState(false);
  const [followLog, setFollowLog] = useState(true);
  const [isCrashModalOpen, setIsCrashModalOpen] = useState(false);

  const isWsConnected = useWSStore((s) => s.connected);
  const connectionState = useWSStore((s) => s.connectionState);
  const effectiveConnectionState = useEffectiveConnectionState();
  const isConsoleChannelDegraded = useIsChannelDegraded(`server:${serverId}:console`);
  const isRunning = serverStatus === "running" || serverStatus === "starting";

  const consoleScopeKey = `${serverId}:${branch ?? "main"}`;
  const [prevScopeKey, setPrevScopeKey] = useState(consoleScopeKey);
  if (prevScopeKey !== consoleScopeKey) {
    setPrevScopeKey(consoleScopeKey);
    setStreamedLines([]);
    setClearedWatermark(null);
    setSearchQuery("");
    setLevelFilter("all");
    setFollowLog(true);
  }

  // Fetch initial console history (with offline fallback on disk).
  // Disable 3s polling query while WS connection is active and console channel is healthy.
  const { data: history, refetch: refetchHistory } = useQuery({
    queryKey: queryKeys.console.history(serverId, branch),
    queryFn: () => api.getServerConsole(serverId, 200, branch),
    refetchInterval: isBranchMode
      ? isRunning
        ? 3000
        : false
      : !isRunning || (isWsConnected && !isConsoleChannelDegraded)
        ? false
        : 3000,
  });

  // Merge newly fetched HTTP tail lines without wiping existing live/command lines
  // and without resurrecting lines already cleared by the user.
  const syncMissedTail = useCallback(async () => {
    const result = await refetchHistory();
    const fetched = result.data?.lines;
    if (fetched && fetched.length > 0) {
      const linesToMerge = clearedWatermark
        ? sliceLinesAfterWatermark(clearedWatermark, fetched)
        : fetched;
      if (linesToMerge.length > 0) {
        setStreamedLines((prev) => mergeDeduplicatedLines(prev, linesToMerge, MAX_CONSOLE_LINES));
      }
    }
  }, [refetchHistory, clearedWatermark]);

  // Reconnect re-tail: backfill missed lines on WS reconnect without wiping buffer
  const prevConnectionStateRef = useRef(connectionState);
  useEffect(() => {
    const prev = prevConnectionStateRef.current;
    if (
      (prev === ConnectionState.RECONNECTING || prev === ConnectionState.DISCONNECTED) &&
      connectionState === ConnectionState.CONNECTED
    ) {
      void syncMissedTail();
    }
    prevConnectionStateRef.current = connectionState;
  }, [connectionState, syncMissedTail]);

  // Clear stale crash/offline console lines immediately when server transitions into starting
  const prevServerStatusRef = useRef(serverStatus);
  useEffect(() => {
    const prev = prevServerStatusRef.current;
    prevServerStatusRef.current = serverStatus;
    const wasInactive = prev === "crashed" || prev === "stopped" || prev === "created";
    if (wasInactive && serverStatus === "starting") {
      setStreamedLines([]);
      setClearedWatermark(null);
      setFollowLog(true);
      queryClient.setQueryData(queryKeys.console.history(serverId, branch), { lines: [] });
      void refetchHistory();
    }
  }, [serverStatus, serverId, branch, queryClient, refetchHistory]);

  // Tab visibility re-tail: merge missed tail lines without clearing existing live lines
  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        void syncMissedTail();
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [syncMissedTail]);

  // Fetch recent crash reports
  const { data: crashReports, isLoading: isLoadingCrashes } = useQuery({
    queryKey: queryKeys.console.crashReports(serverId),
    queryFn: () => api.getServerCrashReports(serverId, 5),
    enabled: !isBranchMode,
  });

  // Subscribe to WebSocket console stream (main runtime only)
  const handleIncomingLines = useCallback((lines: string[]) => {
    if (!lines.length) return;
    // De-duplicate overlap with already-buffered lines (reconnect / backfill replays).
    setStreamedLines((prev) => mergeDeduplicatedLines(prev, lines, MAX_CONSOLE_LINES));
  }, []);

  useConsoleStream(isBranchMode ? null : serverId, handleIncomingLines);

  const { data: metrics } = useServerMetrics(isBranchMode ? "" : serverId);
  const latestMetric =
    !isBranchMode && metrics?.length
      ? metrics.reduce((latest, m) => (m.timestamp > latest.timestamp ? m : latest))
      : undefined;

  const rawTps = tps !== undefined ? tps : latestMetric?.tps;
  const liveTps = !isBranchMode && isRunning && rawTps != null ? rawTps : null;

  const rawPlayers = players !== undefined ? players : latestMetric?.players;
  const livePlayers = !isBranchMode && isRunning && rawPlayers != null ? rawPlayers : null;

  const sendCommand = useMutation({
    mutationFn: (command: string) =>
      branch
        ? api.sendServerCommand(serverId, { command }, branch)
        : api.sendServerCommand(serverId, { command }),
    onSuccess: (data, command) => {
      const rawOutput = typeof data?.output === "string" ? data.output : "";
      const responseLines = rawOutput
        .replace(/\r\n/g, "\n")
        .split("\n")
        .map((line) => stripAnsiAndMcFormatting(line).trimEnd())
        .filter((line) => line.length > 0);
      setStreamedLines((prev) =>
        [...prev, `> ${command}`, ...responseLines].slice(-MAX_CONSOLE_LINES),
      );
      if (followLog && containerRef.current) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight;
      }
    },
    onError: (err, command) => {
      const msg = err instanceof Error ? err.message : "Failed to execute command";
      setStreamedLines((prev) =>
        [...prev, `> ${command}`, `[ERROR] ${msg}`].slice(-MAX_CONSOLE_LINES),
      );
      if (followLog && containerRef.current) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight;
      }
    },
  });

  // Unified chronological ring buffer capped at MAX_CONSOLE_LINES
  const rawLines = useMemo(() => {
    const historyLines = history?.lines ?? [];
    const base = clearedWatermark
      ? sliceLinesAfterWatermark(clearedWatermark, historyLines)
      : historyLines;
    if (base.length === 0) return streamedLines.slice(-MAX_CONSOLE_LINES);
    if (streamedLines.length === 0) return base.slice(-MAX_CONSOLE_LINES);
    return mergeDeduplicatedLines(base, streamedLines, MAX_CONSOLE_LINES);
  }, [clearedWatermark, history?.lines, streamedLines]);

  const parsedLines = useMemo(
    () => rawLines.map((raw, idx) => parseConsoleLine(raw, idx)),
    [rawLines],
  );

  const levelCounts = useMemo(() => {
    let info = 0;
    let warn = 0;
    let error = 0;
    for (const entry of parsedLines) {
      if (entry.level === "info") info++;
      else if (entry.level === "warn") warn++;
      else if (entry.level === "error") error++;
    }
    return { all: parsedLines.length, info, warn, error };
  }, [parsedLines]);

  // Apply level filter and search filter
  const filteredLines = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return parsedLines.filter((entry) => {
      if (levelFilter !== "all" && entry.level !== levelFilter) {
        return false;
      }
      if (!query) return true;
      const text = showIsoTimestamps ? entry.clean : entry.display;
      return text.toLowerCase().includes(query);
    });
  }, [parsedLines, levelFilter, searchQuery, showIsoTimestamps]);

  // Auto-scroll when followLog is enabled
  useEffect(() => {
    if (!followLog) return;
    const container = containerRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [filteredLines, followLog]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom > 40 && followLog) {
      setFollowLog(false);
    } else if (distanceFromBottom <= 8 && !followLog) {
      setFollowLog(true);
    }
  };

  const handleJumpToLatest = () => {
    setFollowLog(true);
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  };

  const handleSendCommand = (cmd: string) => {
    setSentCommands((prev) => [...prev, cmd].slice(-MAX_COMMAND_HISTORY));
    sendCommand.mutate(cmd);
  };

  const handleClear = () => {
    setClearedWatermark(rawLines.slice(-MAX_CONSOLE_LINES));
    setStreamedLines([]);
  };

  const handleCopyLogs = () => {
    const content = filteredLines
      .map((line) => (showIsoTimestamps ? line.clean : line.display))
      .join("\n");
    void copy(content, "Console logs copied to clipboard");
  };

  const handleDownloadLogs = () => {
    const content = filteredLines
      .map((line) => (showIsoTimestamps ? line.clean : line.display))
      .join("\n");
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const safeName = (serverName || serverId).replace(/[^a-zA-Z0-9_-]+/g, "-");
    link.href = url;
    link.download = `${safeName}-console.log`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const hasCrashReports = Boolean(crashReports && crashReports.length > 0);
  const latestCrash = hasCrashReports ? crashReports![0] : null;
  const showLoudCrashBanner =
    Boolean(latestCrash) &&
    isCrashRecent(latestCrash?.timestamp, serverStatus, uptimeSeconds);

  return (
    <div
      data-testid="server-console-container"
      className="flex flex-col min-h-0 h-[460px] lg:h-[clamp(400px,calc(100dvh-14.5rem),640px)]"
    >
      {/* Smart Crash Detected Alert Banner (loud only when crashed or recent crash) */}
      {showLoudCrashBanner && latestCrash && (
        <div
          data-testid="crash-alert-banner"
          className="mb-3 p-3 rounded-xl bg-status-danger-bg border border-status-danger-border text-status-danger flex items-center justify-between gap-3 shadow-xs animate-fade-in"
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
              <p className="text-text-secondary text-[11px] truncate mt-0.5">
                {latestCrash.filename} • {latestCrash.suggested_remediation}
              </p>
            </div>
          </div>
          <button
            type="button"
            data-testid="crash-banner-view-btn"
            onClick={() => setIsCrashModalOpen(true)}
            className="px-3 py-1.5 rounded-lg bg-status-danger hover:opacity-90 text-accent-contrast-text text-xs font-semibold shrink-0 transition-opacity shadow-xs cursor-pointer"
          >
            View Crash Report
          </button>
        </div>
      )}

      {/* Terminal Frame */}
      <div className="flex flex-col flex-1 min-h-0 bg-terminal-bg text-terminal-text font-mono text-xs rounded-xl border border-terminal-border overflow-hidden mb-3">
        <ConsoleToolbar
          serverId={serverId}
          isRunning={isRunning}
          isBranchMode={isBranchMode}
          branch={branch}
          compactHeader={compactHeader}
          port={port}
          provider={provider}
          displayAddress={displayAddress}
          liveTps={liveTps}
          livePlayers={livePlayers}
          maxPlayers={maxPlayers}
          effectiveConnectionState={effectiveConnectionState}
          isConsoleChannelDegraded={isConsoleChannelDegraded}
          crashReportCount={crashReports?.length ?? 0}
          onOpenCrashReports={() => setIsCrashModalOpen(true)}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          matchCount={filteredLines.length}
          levelFilter={levelFilter}
          onLevelFilterChange={setLevelFilter}
          levelCounts={levelCounts}
          showIsoTimestamps={showIsoTimestamps}
          onToggleIsoTimestamps={() => setShowIsoTimestamps((prev) => !prev)}
          followLog={followLog}
          onToggleFollowLog={() => {
            setFollowLog((prev) => {
              const next = !prev;
              if (next && containerRef.current) {
                containerRef.current.scrollTop = containerRef.current.scrollHeight;
              }
              return next;
            });
          }}
          hasLines={parsedLines.length > 0}
          onCopyLogs={handleCopyLogs}
          onDownloadLogs={handleDownloadLogs}
          onClearLogs={handleClear}
        />

        {/* Responsive Viewport with Floating Jump-to-Latest Pill */}
        <div className="relative flex-1 min-h-0 flex flex-col">
          <div
            ref={containerRef}
            onScroll={handleScroll}
            data-testid="console-output-viewport"
            className="flex-1 min-h-0 overflow-y-auto p-3 space-y-0.5 select-text leading-relaxed"
          >
            {filteredLines.length === 0 ? (
              <p className="text-terminal-muted font-sans">
                {searchQuery || levelFilter !== "all"
                  ? "No logs matching your active filter."
                  : "No console output yet."}
              </p>
            ) : (
              filteredLines.map((entry) => {
                const text = showIsoTimestamps ? entry.clean : entry.display;
                const tokens = tokenizeConsoleLine(text, entry.level);
                const messageClass = getLevelTextClass(entry.level, tokens.isMilestone);
                return (
                  <div
                    key={entry.id}
                    data-log-level={entry.level}
                    title={entry.isoTimestamp ? `Timestamp: ${entry.isoTimestamp}` : undefined}
                    className="whitespace-pre-wrap break-all text-terminal-text"
                  >
                    {tokens.isoPrefix && (
                      <span data-log-token="iso" className="text-terminal-timestamp">
                        {renderHighlightedText(tokens.isoPrefix, searchQuery)}
                      </span>
                    )}
                    {tokens.commandPrompt && (
                      <span data-log-token="prompt" className="text-terminal-info font-bold">
                        {tokens.commandPrompt}
                      </span>
                    )}
                    {tokens.headerPrefix && (
                      <span data-log-token="timestamp" className="text-terminal-timestamp">
                        {renderHighlightedText(tokens.headerPrefix, searchQuery)}
                      </span>
                    )}
                    {tokens.levelTag && (
                      <span data-log-token="level" className={getLevelTagClass(tokens.levelTag)}>
                        {renderHighlightedText(tokens.levelTag, searchQuery)}
                      </span>
                    )}
                    {tokens.headerSuffix && (
                      <span data-log-token="header-close" className="text-terminal-timestamp">
                        {renderHighlightedText(tokens.headerSuffix, searchQuery)}
                      </span>
                    )}
                    {tokens.sourceTag && (
                      <>
                        <span data-log-token="source" className="text-terminal-source font-medium">
                          {renderHighlightedText(tokens.sourceTag, searchQuery)}
                        </span>
                        {tokens.sourceSeparator}
                      </>
                    )}
                    {tokens.message && (
                      <span data-log-token="message" className={messageClass}>
                        {renderHighlightedText(tokens.message, searchQuery)}
                      </span>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {!followLog && filteredLines.length > 0 && (
            <button
              type="button"
              data-testid="console-jump-latest-btn"
              onClick={handleJumpToLatest}
              className="absolute bottom-3 right-4 inline-flex items-center gap-1.5 rounded-full border border-terminal-border bg-terminal-surface px-3 py-1.5 text-[11px] font-sans font-semibold text-terminal-text shadow-md hover:border-terminal-info hover:text-terminal-info transition-colors cursor-pointer"
            >
              <Icon name="chevron-down" size={12} />
              <span>Jump to latest</span>
            </button>
          )}
        </div>
      </div>

      {/* Command Bar with History & Quick Chips */}
      <ConsoleCommandBar
        onSend={handleSendCommand}
        isSending={sendCommand.isPending}
        isRunning={isRunning}
        canConsole={canConsole}
        commandHistory={sentCommands}
      />

      {/* Crash Report Modal */}
      <CrashReportViewerModal
        isOpen={isCrashModalOpen}
        onClose={() => setIsCrashModalOpen(false)}
        reports={crashReports ?? []}
        isLoading={isLoadingCrashes}
        serverName={serverName || serverId}
      />
    </div>
  );
}
