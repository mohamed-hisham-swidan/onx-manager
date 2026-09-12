import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useServerMetrics } from "@/server_manager/hooks/useServerMetrics";
import { Icon } from "@/components/ui/Icon";

function useApi() {
  return createAuthenticatedApi();
}

interface ServerConsoleProps {
  serverId: string;
  serverStatus?: string;
  tps?: number | null;
  players?: number;
  provider?: string | null;
}

const containerBadgeClass =
  "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold " +
  "uppercase tracking-wider bg-cyan-950/90 text-cyan-300 border border-cyan-700/60 font-sans";

const hostBadgeClass =
  "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold " +
  "uppercase tracking-wider bg-purple-950/90 text-purple-300 border border-purple-700/60 font-sans";

export function ServerConsole({
  serverId,
  serverStatus,
  tps,
  players,
  provider,
}: ServerConsoleProps) {
  const isContainer = provider === "docker" || provider === "container";
  const api = useApi();
  const containerRef = useRef<HTMLDivElement>(null);
  const [input, setInput] = useState("");
  const [commandHistory, setCommandHistory] = useState<string[]>([]);

  const { data: history } = useQuery({
    queryKey: queryKeys.console.history(serverId),
    queryFn: () => api.getServerConsole(serverId, 200),
    refetchInterval: 3000,
  });

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
      if (containerRef.current) {
        containerRef.current.scrollTop = containerRef.current.scrollHeight;
      }
    },
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
    if (isNearBottom) {
      container.scrollTop = container.scrollHeight;
    }
  }, [history, commandHistory]);

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sendCommand.isPending) return;
    sendCommand.mutate(input.trim());
    setInput("");
  };

  const allLines = [...(history?.lines ?? []), ...commandHistory];

  const tpsColorClass =
    liveTps != null
      ? liveTps >= 19.5
        ? "text-emerald-400"
        : liveTps >= 16.0
          ? "text-amber-400"
          : "text-red-400"
      : "text-gray-500";

  return (
    <div>
      <div className="bg-gray-950 text-green-400 font-mono text-xs rounded-xl border border-gray-700 overflow-hidden mb-3">
        {/* Console Header Bar */}
        <div className="flex items-center justify-between px-3.5 py-2 bg-gray-900/90 border-b border-gray-800 text-xs select-none">
          <div className="flex items-center gap-2 text-gray-300 font-sans font-medium text-xs">
            <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>Server Console</span>
            {isContainer ? (
              <span
                data-testid="console-provider-badge"
                className={containerBadgeClass}
                title="Runtime: Docker Container"
              >
                <Icon name="server" size={11} className="text-cyan-400" />
                <span>Container</span>
              </span>
            ) : (
              <span
                data-testid="console-provider-badge"
                className={hostBadgeClass}
                title="Runtime: Host Filesystem / Process"
              >
                <Icon name="folder" size={11} className="text-purple-400" />
                <span>File / Host</span>
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* TPS Usage Badge */}
            <div
              data-testid="console-tps-badge"
              className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-md bg-gray-950 border border-gray-800 font-mono text-[11px]"
              title={liveTps != null ? `Server Tick Rate: ${liveTps.toFixed(1)} / 20.0 TPS` : "TPS unknown"}
            >
              <span className="text-gray-400 font-sans font-semibold text-[10px] uppercase tracking-wider">TPS</span>
              <span className={`font-bold ${tpsColorClass}`}>
                {liveTps != null ? liveTps.toFixed(1) : "—"}
              </span>
              {liveTps != null && (
                <span className="text-[10px] text-gray-500">
                  ({Math.min(100, Math.round((liveTps / 20) * 100))}%)
                </span>
              )}
            </div>

            {/* Players Badge */}
            {livePlayers != null && (
              <div
                data-testid="console-players-badge"
                className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-gray-950 border border-gray-800 text-[11px] text-gray-300 font-mono"
                title={`${livePlayers} player(s) online`}
              >
                <Icon name="users" size={12} className="text-gray-400" />
                <span>{livePlayers}</span>
              </div>
            )}

            {/* Clear History Button */}
            {commandHistory.length > 0 && (
              <button
                type="button"
                onClick={() => setCommandHistory([])}
                className="text-gray-400 hover:text-gray-200 transition-colors text-[11px] font-sans px-1.5 py-0.5 rounded hover:bg-gray-800"
                title="Clear local command history"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Output container */}
        <div ref={containerRef} className="h-[420px] overflow-y-auto p-3 space-y-0.5">
          {allLines.length === 0 ? (
            <p className="text-gray-500">No console output yet.</p>
          ) : (
            allLines.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-all">
                {line}
              </div>
            ))
          )}
        </div>
      </div>
      <form onSubmit={handleSend} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Enter a command..."
          className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={sendCommand.isPending || !input.trim()}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
        >
          {sendCommand.isPending ? "Sending..." : "Send"}
        </button>
      </form>
    </div>
  );
}
