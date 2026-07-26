import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useServerDetail, useStartServer, useStopServer, useRestartServer, useDeleteServer } from "@/server_manager/hooks/useServers";
import { STATUS_MAP } from "@/server_manager/types";
import { Skeleton } from "@/components/Skeleton";
import { ServerConfigEditor } from "@/server_manager/components/ServerConfigEditor";
import { ServerConsole } from "@/server_manager/components/ServerConsole";
import { ServerMetricsCharts } from "@/server_manager/components/ServerMetricsCharts";

export function ServerDetailPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const { data: server, isLoading, error } = useServerDetail(serverId ?? "");
  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();
  const deleteServer = useDeleteServer();
  const [activeTab, setActiveTab] = useState<"info" | "config" | "console" | "metrics">("info");

  if (!serverId) {
    return <p className="text-red-600 dark:text-red-400">No server ID specified.</p>;
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-96" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <Skeleton className="h-4 w-16 mb-2" />
              <Skeleton className="h-6 w-24" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-red-600 dark:text-red-400">
        {error instanceof Error ? error.message : "Failed to load server details"}
      </p>
    );
  }

  if (!server) {
    return <p className="text-gray-500 dark:text-gray-400">Server not found.</p>;
  }

  const tabs = [
    { key: "info" as const, label: "Information" },
    { key: "config" as const, label: "Configuration" },
    { key: "console" as const, label: "Console" },
    { key: "metrics" as const, label: "Metrics" },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate("/servers")}
            className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
          >
            &larr; Back
          </button>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">{server.name}</h2>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_MAP[server.status]?.color ?? "bg-gray-100 text-gray-600"}`}>
            {STATUS_MAP[server.status]?.label ?? server.status}
          </span>
        </div>
        <div className="flex gap-2">
          {["stopped", "created", "crashed"].includes(server.status) ? (
            <button
              onClick={() => startServer.mutate(serverId)}
              disabled={startServer.isPending}
              className="px-3 py-1.5 text-xs rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50 disabled:opacity-50 font-medium"
            >
              {startServer.isPending ? "Starting..." : "Start"}
            </button>
          ) : null}
          {server.status === "running" ? (
            <>
              <button
                onClick={() => stopServer.mutate(serverId)}
                disabled={stopServer.isPending}
                className="px-3 py-1.5 text-xs rounded bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400 hover:bg-orange-200 dark:hover:bg-orange-900/50 disabled:opacity-50 font-medium"
              >
                {stopServer.isPending ? "Stopping..." : "Stop"}
              </button>
              <button
                onClick={() => restartServer.mutate(serverId)}
                disabled={restartServer.isPending}
                className="px-3 py-1.5 text-xs rounded bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400 hover:bg-yellow-200 dark:hover:bg-yellow-900/50 disabled:opacity-50 font-medium"
              >
                {restartServer.isPending ? "Restarting..." : "Restart"}
              </button>
            </>
          ) : null}
          <button
            onClick={() => {
              if (confirm(`Delete ${server.name}?`)) {
                deleteServer.mutate(serverId, { onSuccess: () => navigate("/servers") });
              }
            }}
            disabled={deleteServer.isPending}
            className="px-3 py-1.5 text-xs rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50 font-medium"
          >
            Delete
          </button>
        </div>
      </div>

      <div className="flex gap-1 mb-6 border-b border-gray-200 dark:border-gray-700">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.key
                ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400"
                : "border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "info" && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Minecraft Version</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.minecraft_version}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Port</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.port}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Max Players</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.max_players}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Gamemode</p>
              <p className="text-sm text-gray-900 dark:text-gray-100 capitalize">{server.gamemode}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Difficulty</p>
              <p className="text-sm text-gray-900 dark:text-gray-100 capitalize">{server.difficulty}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">PVP</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.pvp ? "Enabled" : "Disabled"}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Whitelist</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.whitelist ? "Enabled" : "Disabled"}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Online Mode</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.online_mode ? "Yes" : "No"}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">View Distance</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.view_distance} chunks</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Simulation Distance</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.simulation_distance} chunks</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Memory</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.min_memory_mb} MB / {server.max_memory_mb} MB</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Java Args</p>
              <p className="text-sm text-gray-900 dark:text-gray-100 font-mono">{server.java_args}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">MOTD</p>
              <p className="text-sm text-gray-900 dark:text-gray-100">{server.motd}</p>
            </div>
          </div>
          {server.deployment_host && (
            <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">Deployment</p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Provider</p>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{server.provider ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Host</p>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{server.deployment_host}:{server.deployment_port}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">PID</p>
                  <p className="text-sm text-gray-900 dark:text-gray-100">{server.deployment_pid ?? "—"}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "config" && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Server Configuration</h3>
          <ServerConfigEditor serverId={serverId} server={server} />
        </div>
      )}

      {activeTab === "console" && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Server Console</h3>
          <ServerConsole serverId={serverId} />
        </div>
      )}

      {activeTab === "metrics" && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Server Metrics</h3>
          <ServerMetricsCharts serverId={serverId} />
        </div>
      )}
    </div>
  );
}
