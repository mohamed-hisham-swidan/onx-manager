import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useServerDetail, useServerRuntime } from "@/server_manager/hooks/useServers";
import { useServerExposure } from "@/server_manager/hooks/useServerExposure";
import { subscribeChannels, unsubscribeChannels } from "@/hooks/useWebSocket";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Icon } from "@/components/ui/Icon";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import { resolveAccessAddress } from "@/server_manager/utils/accessAddress";
import { ServerConsole } from "@/server_manager/components/ServerConsole";
import { Sparkline } from "@/server_manager/components/Sparkline";
import { StartingMonitorBanner } from "@/server_manager/components/StartingMonitorBanner";
import { useServerMetrics } from "@/server_manager/hooks/useServerMetrics";
import { useClipboard } from "@/hooks/useClipboard";
import { ApiError } from "@/services/api";

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
  const { data: server, isLoading, error, refetch: refetchServer } = useServerDetail(serverId ?? "");
  const { data: runtime } = useServerRuntime(serverId ?? "");
  const { data: metrics } = useServerMetrics(serverId ?? "");
  const { exposure } = useServerExposure(serverId ?? "");
  const { copy } = useClipboard();

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

  const isRunning = server.status === "running";

  const currentMetric =
    isRunning && metrics?.length
      ? metrics.reduce((latest, m) => (m.timestamp > latest.timestamp ? m : latest))
      : undefined;

  const ramData = isRunning ? (metrics ?? []).map((m) => m.ram_used_mb) : [];
  const cpuData = isRunning ? (metrics ?? []).map((m) => m.cpu_percent) : [];
  const tpsData = isRunning
    ? (metrics ?? []).map((m) => m.tps).filter((t): t is number => t != null)
    : [];

  const ramPercent =
    currentMetric && server?.max_memory_mb && server.max_memory_mb > 0
      ? (currentMetric.ram_used_mb / server.max_memory_mb) * 100
      : null;

  const resolvedAddress = resolveAccessAddress(server, exposure);
  const address = resolvedAddress.address ?? "—";

  const hasLiveTps = isRunning && currentMetric?.tps != null;

  return (
    <div className="flex flex-col gap-4">
      {server.status === "starting" && (
        <StartingMonitorBanner
          targetName={server.name}
          startedAt={server.updated_at}
          timeoutSeconds={server.startup_timeout_seconds ?? 120}
          onCheckNow={async () => {
            await refetchServer();
          }}
        />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {/* Main Column */}
        <div className="lg:col-span-2 xl:col-span-3 flex flex-col gap-4">
          {/* Console */}
          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
                <ServerConsole
                  serverId={serverId}
                  serverStatus={server.status}
                  tps={currentMetric?.tps}
                  players={currentMetric?.players}
                  provider={server.provider}
                  host={server.deployment_host}
                  port={server.deployment_port ?? server.port}
                />
              </div>

          {/* Usage Graphs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
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
            {/* TPS Usage */}
            <div className="rounded-xl border border-gray-200 bg-white p-2.5 px-3 dark:border-gray-700 dark:bg-gray-800">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">TPS & Tick Rate</h3>
                <span
                  data-testid="tps-usage-value"
                  className={`text-xs font-bold ${
                    hasLiveTps
                      ? currentMetric.tps! >= 19.5
                        ? "text-emerald-600 dark:text-emerald-400"
                        : currentMetric.tps! >= 16.0
                          ? "text-amber-600 dark:text-amber-400"
                          : "text-red-600 dark:text-red-400"
                      : "text-gray-400"
                  }`}
                >
                  {hasLiveTps
                    ? `${currentMetric.tps!.toFixed(1)} (${Math.min(100, Math.round((currentMetric.tps! / 20) * 100))}%)`
                    : "—"}
                </span>
              </div>
              <Sparkline
                data={tpsData}
                color={
                  hasLiveTps && currentMetric.tps! < 16
                    ? "#ef4444"
                    : hasLiveTps && currentMetric.tps! < 19.5
                      ? "#f59e0b"
                      : "#10b981"
                }
                fillColor={
                  hasLiveTps && currentMetric.tps! < 16
                    ? "rgba(239, 68, 68, 0.1)"
                    : hasLiveTps && currentMetric.tps! < 19.5
                      ? "rgba(245, 158, 11, 0.1)"
                      : "rgba(16, 185, 129, 0.1)"
                }
                height={20}
              />
            </div>
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
                      <DetailRow label="Provider">
                        {server.provider === "docker"
                          ? "Docker Container"
                          : server.provider === "local_win"
                            ? "Windows Process"
                            : server.provider
                              ? "Host Process"
                              : "Host Process (Default)"}
                      </DetailRow>
                      <DetailRow label={server.provider === "docker" ? "Container IP" : "Host"}>
                        {server.deployment_host
                          ? `${server.deployment_host}:${server.deployment_port ?? "—"}`
                          : "—"}
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
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
              <Icon name="globe" size={14} />
              Address
            </h3>
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

          <div data-testid="server-port-widget" className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
              <Icon name="server" size={14} />
              Server Port
            </h3>
            <div className="flex items-center justify-between">
              <span className="text-base font-bold text-gray-900 dark:text-gray-100 truncate pr-2">{server.port}</span>
              <button
                onClick={() => copy(String(server.port), "Port copied to clipboard")}
                className="shrink-0 p-1 rounded-md text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                title="Copy port"
              >
                <Icon name="copy" size={14} />
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
              <Icon name="clock" size={14} />
              Uptime
            </h3>
            <p className="text-base font-bold text-gray-900 dark:text-gray-100">
              {runtime?.uptime_seconds ? formatUptime(runtime.uptime_seconds) : "—"}
            </p>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
              <Icon name="cpu" size={14} />
              CPU Usage
            </h3>
            <p className="text-base font-bold text-gray-900 dark:text-gray-100">
              {currentMetric ? `${currentMetric.cpu_percent.toFixed(1)}%` : "—"}
            </p>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-3.5 dark:border-gray-700 dark:bg-gray-800">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
              <Icon name="database" size={14} />
              RAM Usage
            </h3>
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
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
                <Icon name="hard-drive" size={14} />
                Storage Usage
              </h3>
              <span className="text-[10px] font-medium text-gray-400 dark:text-gray-500">Coming Soon</span>
            </div>
            <p className="text-base font-bold text-gray-400 dark:text-gray-500">
              —
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
