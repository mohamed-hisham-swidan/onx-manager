import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useServerDetail, useStartServer, useStopServer, useRestartServer, useDeleteServer, useServerRuntime } from "@/server_manager/hooks/useServers";
import { useServerExposure } from "@/server_manager/hooks/useServerExposure";
import { subscribeChannels, unsubscribeChannels } from "@/hooks/useWebSocket";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ErrorState";
import { ComingSoonState } from "@/components/ComingSoonState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import { ServerConsole } from "@/server_manager/components/ServerConsole";
import { Sparkline } from "@/server_manager/components/Sparkline";
import { useServerMetrics } from "@/server_manager/hooks/useServerMetrics";
import { useClipboard } from "@/hooks/useClipboard";
import { toast } from "@/stores/toastStore";
import { ApiError } from "@/services/api";
import type { ServerDetailResponse } from "@/server_manager/types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="shrink-0 text-sm text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="text-right text-sm font-medium text-gray-900 dark:text-gray-100">{children}</dd>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="p-5 sm:p-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {title}
      </h3>
      <dl className="divide-y divide-gray-100 dark:divide-gray-700/50">{children}</dl>
    </section>
  );
}

function formatUptime(seconds: number): string {
  if (!seconds) return "—";
  const d = Math.floor(seconds / (3600 * 24));
  const h = Math.floor((seconds % (3600 * 24)) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (d > 0) parts.push(`${d}d`);
  if (h > 0) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(" ");
}

function renderMotd(motd: string | undefined): string {
  const cleaned = stripMinecraftFormatting(motd ?? "");
  return cleaned || "—";
}

export function ServerDetailPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const { data: server, isLoading, error } = useServerDetail(serverId ?? "");
  const { data: runtime } = useServerRuntime(serverId ?? "");
  const { data: metrics } = useServerMetrics(serverId ?? "");
  const { exposure } = useServerExposure(serverId ?? "");
  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();
  const deleteServer = useDeleteServer();
  const { copy } = useClipboard();

  const [showDelete, setShowDelete] = useState(false);
  const [infoExpanded, setInfoExpanded] = useState(false);

  useEffect(() => {
    if (!serverId) return;
    const channel = `metrics:${serverId}`;
    subscribeChannels([channel]);
    return () => unsubscribeChannels([channel]);
  }, [serverId]);

  if (!serverId) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400">
        No server ID specified.
      </div>
    );
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

  const isNotFound = error instanceof ApiError && error.status === 404;

  if (error && !isNotFound) {
    return (
      <ErrorState message={error instanceof Error ? error.message : "Failed to load server details"} />
    );
  }

  if (isNotFound || !server) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-6 text-center dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Server not found</h2>
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
          This server does not exist or may have been deleted.
        </p>
      </div>
    );
  }

  const actions = (s: ServerDetailResponse) => (
    <>
      {["stopped", "created", "crashed"].includes(s.status) && (
        <button
          onClick={() =>
            startServer.mutate(serverId, {
              onSuccess: () => toast("success", "Server started", `"${s.name}" is starting.`),
              onError: (err) => toast("error", "Start failed", errorMessage(err)),
            })
          }
          disabled={startServer.isPending}
          className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-50"
        >
          <Icon name="play" size={14} />
          {startServer.isPending ? "Starting..." : "Start"}
        </button>
      )}
      {s.status === "running" && (
        <>
          <button
            onClick={() =>
              stopServer.mutate(serverId, {
                onSuccess: () => toast("success", "Server stopped", `"${s.name}" is stopping.`),
                onError: (err) => toast("error", "Stop failed", errorMessage(err)),
              })
            }
            disabled={stopServer.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-orange-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-orange-700 disabled:opacity-50"
          >
            <Icon name="stop" size={14} />
            {stopServer.isPending ? "Stopping..." : "Stop"}
          </button>
          <button
            onClick={() =>
              restartServer.mutate(serverId, {
                onSuccess: () => toast("success", "Server restarting", `"${s.name}" is restarting.`),
                onError: (err) => toast("error", "Restart failed", errorMessage(err)),
              })
            }
            disabled={restartServer.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-yellow-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-yellow-700 disabled:opacity-50"
          >
            <Icon name="restart" size={14} />
            {restartServer.isPending ? "Restarting..." : "Restart"}
          </button>
        </>
      )}
      <button
        onClick={() => setShowDelete(true)}
        disabled={deleteServer.isPending}
        className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-900/40 dark:text-red-400 dark:hover:bg-red-900/20"
      >
        <Icon name="trash" size={14} />
        Delete
      </button>
    </>
  );

  const currentMetric = metrics?.length
    ? metrics.reduce((latest, m) => (m.timestamp > latest.timestamp ? m : latest))
    : undefined;

  const ramData = (metrics ?? []).map((m) => m.ram_used_mb);
  const cpuData = (metrics ?? []).map((m) => m.cpu_percent);

  const ramPercent =
    currentMetric && server?.max_memory_mb && server.max_memory_mb > 0
      ? (currentMetric.ram_used_mb / server.max_memory_mb) * 100
      : null;

  const address = server.deployment_host ? `${server.deployment_host}:${server.deployment_port ?? server.port}` : "—";

  return (
    <div className="flex flex-col gap-4">
      {/* Top Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
            <Icon name="server" size={20} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-lg font-semibold text-gray-900 dark:text-gray-100">
                {server.name}
              </h2>
              <StatusBadge status={server.status} />
            </div>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400 flex items-center gap-2">
              <span>{server.server_type} · {server.minecraft_version}</span>
              {currentMetric && (
                <span className="flex items-center gap-2 border-l border-gray-300 dark:border-gray-600 pl-2">
                  <span title="TPS"><Icon name="activity" size={12} className="inline mr-1" />{currentMetric.tps.toFixed(1)}</span>
                  <span title="Players"><Icon name="users" size={12} className="inline mr-1" />{currentMetric.players}</span>
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">{actions(server)}</div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {/* Main Column */}
        <div className="lg:col-span-2 xl:col-span-3 flex flex-col gap-4">
          {/* Console */}
          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <ServerConsole serverId={serverId} />
          </div>

          {/* Usage Graphs */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-xl border border-gray-200 bg-white p-2.5 px-3 dark:border-gray-700 dark:bg-gray-800">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">CPU Usage</h3>
                <span className="text-xs font-bold text-red-600 dark:text-red-400">
                  {currentMetric ? `${currentMetric.cpu_percent.toFixed(1)}%` : "—"}
                </span>
              </div>
              <Sparkline data={cpuData} color="#ef4444" fillColor="rgba(239, 68, 68, 0.1)" height={20} />
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-2.5 px-3 dark:border-gray-700 dark:bg-gray-800">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">RAM Usage</h3>
                <span className="text-xs font-bold text-amber-600 dark:text-amber-400">
                  {currentMetric
                    ? ramPercent !== null
                      ? `${(currentMetric.ram_used_mb / 1024).toFixed(1)} GB (${ramPercent.toFixed(1)}%)`
                      : `${(currentMetric.ram_used_mb / 1024).toFixed(1)} GB`
                    : "—"}
                </span>
              </div>
              <Sparkline data={ramData} color="#eab308" fillColor="rgba(234, 179, 8, 0.1)" height={20} />
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-2.5 px-3 dark:border-gray-700 dark:bg-gray-800 flex flex-col justify-between">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Network Usage</h3>
                <span className="text-[11px] font-medium text-gray-400 dark:text-gray-500">Coming soon</span>
              </div>
              <div className="h-5 flex items-center">
                <div className="w-full border-t border-dashed border-gray-200 dark:border-gray-700" />
              </div>
            </div>
          </div>

          {/* Warnings/Alerts */}
          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">Alerts & Warnings</h3>
            <ComingSoonState title="Server Alerts" description="Coming soon" icon="bell" />
          </div>

          {/* Collapsible Info Section */}
          <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 overflow-hidden">
            <button
              onClick={() => setInfoExpanded(!infoExpanded)}
              className="w-full flex items-center justify-between p-3.5 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-700/50 transition-colors"
            >
              <span className="font-semibold text-gray-900 dark:text-gray-100">Server Info & Configuration</span>
              <Icon name={infoExpanded ? "chevron-up" : "chevron-down"} size={16} />
            </button>
            {infoExpanded && (
              <div className="p-4 border-t border-gray-200 dark:border-gray-700">
                <div className="mb-6">
                  <h4 className="mb-4 text-sm font-semibold text-gray-900 dark:text-gray-100">Core Information</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <DetailSection title="General">
                      <DetailRow label="Minecraft Version">{server.minecraft_version}</DetailRow>
                      <DetailRow label="Server Type">{server.server_type}</DetailRow>
                      <DetailRow label="Gamemode">
                        <span className="capitalize">{server.gamemode}</span>
                      </DetailRow>
                      <DetailRow label="Difficulty">
                        <span className="capitalize">{server.difficulty}</span>
                      </DetailRow>
                    </DetailSection>
                    <DetailSection title="Gameplay">
                      <DetailRow label="PVP">{server.pvp ? "Enabled" : "Disabled"}</DetailRow>
                      <DetailRow label="Whitelist">{server.whitelist ? "Enabled" : "Disabled"}</DetailRow>
                      <DetailRow label="Online Mode">{server.online_mode ? "Yes" : "No"}</DetailRow>
                      <DetailRow label="Command Blocks">{server.enable_command_block ? "Enabled" : "Disabled"}</DetailRow>
                      <DetailRow label="Spawn Protection">{server.spawn_protection} blocks</DetailRow>
                    </DetailSection>
                    <DetailSection title="Performance">
                      <DetailRow label="View Distance">{server.view_distance} chunks</DetailRow>
                      <DetailRow label="Simulation Distance">{server.simulation_distance} chunks</DetailRow>
                      <DetailRow label="Memory">
                        {server.min_memory_mb} MB / {server.max_memory_mb} MB
                      </DetailRow>
                      <DetailRow label="Java Args">
                        <span className="block max-w-xs truncate font-mono text-xs" title={server.java_args}>
                          {server.java_args}
                        </span>
                      </DetailRow>
                    </DetailSection>
                  </div>
                </div>

                <div className="pt-6 border-t border-gray-200 dark:border-gray-700">
                  <h4 className="mb-4 text-sm font-semibold text-gray-900 dark:text-gray-100">Network & Deployment</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <DetailSection title="Network">
                      <DetailRow label="Port">{server.port}</DetailRow>
                      <DetailRow label="Max Players">{server.max_players}</DetailRow>
                      <DetailRow label="MOTD">
                        <span className="block max-w-xs text-right">{renderMotd(server.motd)}</span>
                      </DetailRow>
                      <DetailRow label="Public Exposure">
                        {exposure?.desired_state === "ENABLED" && exposure.targets?.[0]?.public_address ? (
                          <div className="flex items-center gap-2">
                            <StatusBadge status={exposure.aggregate_status} />
                            <span className="font-mono text-xs">{exposure.targets[0].public_address}</span>
                            <Link to={`/servers/${serverId}/network`} className="text-blue-600 dark:text-blue-400 hover:underline text-xs">
                              Manage
                            </Link>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-500">Not Exposed</span>
                            <Link to={`/servers/${serverId}/network`} className="text-blue-600 dark:text-blue-400 hover:underline text-xs">
                              Configure
                            </Link>
                          </div>
                        )}
                      </DetailRow>
                    </DetailSection>
                    <DetailSection title="Deployment">
                      <DetailRow label="Provider">{server.provider ?? "—"}</DetailRow>
                      <DetailRow label="Host">
                        {server.deployment_host ? `${server.deployment_host}:${server.deployment_port ?? "—"}` : "—"}
                      </DetailRow>
                      <DetailRow label="PID">{server.deployment_pid ?? "—"}</DetailRow>
                      <DetailRow label="Zone ID">
                        <span className="inline-flex items-center gap-1 font-mono text-xs text-gray-400 dark:text-gray-500">
                          <Icon name="info" size={12} />
                          Coming Soon
                        </span>
                      </DetailRow>
                      <DetailRow label="Root Path">
                        <span className="block max-w-xs truncate font-mono text-xs" title={server.root_path ?? undefined}>
                          {server.root_path ?? "—"}
                        </span>
                      </DetailRow>
                      <DetailRow label="Startup Jar">
                        <span className="block max-w-xs truncate font-mono text-xs" title={server.startup_jar ?? undefined}>
                          {server.startup_jar ?? "—"}
                        </span>
                      </DetailRow>
                    </DetailSection>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Side Column */}
        <div className="flex flex-col gap-3">
          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Address</h3>
            <div className="flex items-center justify-between">
              <span className="text-base font-bold text-gray-900 dark:text-gray-100 truncate pr-2">{address}</span>
              {address !== "—" && (
                <button
                  onClick={() => copy(address, "Address copied to clipboard")}
                  className="shrink-0 p-1 rounded-md text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                  title="Copy address"
                >
                  <Icon name="copy" size={14} />
                </button>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Uptime</h3>
            <p className="text-base font-bold text-gray-900 dark:text-gray-100">
              {runtime?.uptime_seconds ? formatUptime(runtime.uptime_seconds) : "—"}
            </p>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">CPU Usage</h3>
            <p className="text-base font-bold text-gray-900 dark:text-gray-100">
              {currentMetric ? `${currentMetric.cpu_percent.toFixed(1)}%` : "—"}
            </p>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">RAM Usage</h3>
            <p className="text-base font-bold text-gray-900 dark:text-gray-100">
              {currentMetric
                ? ramPercent !== null
                  ? `${(currentMetric.ram_used_mb / 1024).toFixed(1)} GB (${ramPercent.toFixed(1)}%)`
                  : `${(currentMetric.ram_used_mb / 1024).toFixed(1)} GB`
                : "—"}
            </p>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Storage Usage</h3>
              <span className="text-[10px] font-medium text-gray-400 dark:text-gray-500">Coming Soon</span>
            </div>
            <p className="text-base font-bold text-gray-400 dark:text-gray-500">
              —
            </p>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={showDelete}
        title="Delete server?"
        description={`This permanently deletes "${server?.name}" and its data. This action cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={() =>
          deleteServer.mutate(serverId, {
            onSuccess: () => navigate("/servers"),
            onError: (err) => toast("error", "Delete failed", errorMessage(err)),
            onSettled: () => setShowDelete(false),
          })
        }
        onCancel={() => setShowDelete(false)}
      />
    </div>
  );
}
