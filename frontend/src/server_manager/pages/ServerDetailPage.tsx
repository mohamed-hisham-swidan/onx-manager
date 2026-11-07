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
      <dt className="shrink-0 text-sm text-text-muted">{label}</dt>
      <dd className="text-right text-sm font-medium text-text-primary">{children}</dd>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="p-5 sm:p-6 bg-surface-card rounded-xl border border-border-subtle">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">
        {title}
      </h3>
      <dl className="divide-y divide-border-subtle/60">{children}</dl>
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
      <div className="rounded-xl border border-status-danger-border bg-status-danger-bg p-6 text-sm text-status-danger">
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
            <div key={i} className="bg-surface-card rounded-xl border border-border-subtle p-4">
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
      <div className="rounded-xl border border-border-subtle bg-surface-card p-6 text-center">
        <h2 className="text-lg font-semibold text-text-primary">Server not found</h2>
        <p className="mt-2 text-sm text-text-muted">
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

  const connectableHost =
    server.deployment_host &&
    server.deployment_host !== "undefined" &&
    server.deployment_host !== "null"
      ? server.deployment_host.trim()
      : "";
  const connectablePort = server.deployment_port ?? server.port;
  const portWidgetDisplay = connectableHost || String(server.port);
  const portWidgetCopyValue = connectableHost
    ? `${connectableHost}:${connectablePort}`
    : String(server.port);

  const hasLiveTps = isRunning && currentMetric?.tps != null;

  return (
    <div className="flex flex-col gap-5">
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

      {/* 12-Column Terminal Workspace Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* Left (col-span-8 or 9 on wide monitors): IDE-Grade Terminal Emulator */}
        <div className="lg:col-span-8 xl:col-span-9 flex flex-col gap-4">
          <div className="rounded-xl border border-border-subtle bg-surface-card p-3 sm:p-4 shadow-2xs">
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

          {/* Collapsible Properties Section */}
          <div className="rounded-xl border border-border-subtle bg-surface-card shadow-2xs overflow-hidden">
            <button
              type="button"
              onClick={() => setInfoExpanded(!infoExpanded)}
              className="w-full flex items-center justify-between p-4 bg-surface-elevated/40 hover:bg-surface-hover/50 transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <Icon name="settings" size={16} className="text-accent-primary" />
                <span className="font-bold text-sm text-text-primary">Server Info & Configuration</span>
              </div>
              <Icon name={infoExpanded ? "chevron-up" : "chevron-down"} size={16} className="text-text-muted" />
            </button>
            {infoExpanded && (
              <div className="p-5 border-t border-border-subtle space-y-6">
                <div>
                  <h4 className="mb-4 text-xs font-bold uppercase tracking-wider text-text-secondary">Core Information</h4>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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

                <div className="pt-4 border-t border-border-subtle/60">
                  <h4 className="mb-4 text-xs font-bold uppercase tracking-wider text-text-secondary">Network & Deployment</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <DetailSection title="Network">
                      <DetailRow label="Port">{server.port}</DetailRow>
                      <DetailRow label="Max Players">{server.max_players}</DetailRow>
                      <DetailRow label="MOTD">
                        <span className="block max-w-xs text-right truncate">{renderMotd(server.motd)}</span>
                      </DetailRow>
                      <DetailRow label="Public Exposure">
                        {exposure?.desired_state === "ENABLED" && exposure.targets?.[0]?.public_address ? (
                          <div className="flex items-center gap-2">
                            <StatusBadge status={exposure.aggregate_status} />
                            <span className="font-mono text-xs">{exposure.targets[0].public_address}</span>
                            <Link to={`/servers/${serverId}/network`} className="text-accent-primary hover:underline text-xs">
                              Manage
                            </Link>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-text-muted">Not Exposed</span>
                            <Link to={`/servers/${serverId}/network`} className="text-accent-primary hover:underline text-xs">
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
                        <span className="inline-flex items-center gap-1 font-mono text-xs text-text-muted">
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

        {/* Right (col-span-4 or 3 on wide monitors): Consolidated Real-Time Telemetry & Diagnostics Stack */}
        <div className="lg:col-span-4 xl:col-span-3 flex flex-col gap-3.5">
          {/* Card 1: Network & Address */}
          <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs">
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
              <Icon name="globe" size={14} className="text-accent-primary" />
              Address
            </h3>
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm font-bold text-text-primary truncate pr-2">{address}</span>
              {address !== "—" && (
                <button
                  type="button"
                  onClick={() => copy(address, "Address copied to clipboard")}
                  className="shrink-0 p-1 rounded-md text-text-muted hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                  title="Copy address"
                >
                  <Icon name="copy" size={14} />
                </button>
              )}
            </div>
          </div>

          {/* Card 2: Port Widget */}
          <div data-testid="server-port-widget" className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs">
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
              <Icon name="server" size={14} className="text-accent-primary" />
              Server Port
            </h3>
            <div className="flex items-center justify-between">
              <span className="font-mono text-base font-bold tabular-nums text-text-primary truncate pr-2">{portWidgetDisplay}</span>
              <button
                type="button"
                onClick={() => copy(portWidgetCopyValue, connectableHost ? "Address copied to clipboard" : "Port copied to clipboard")}
                className="shrink-0 p-1 rounded-md text-text-muted hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                title={connectableHost ? "Copy address" : "Copy port"}
              >
                <Icon name="copy" size={14} />
              </button>
            </div>
          </div>

          {/* Card 3: Uptime */}
          <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs">
            <h3 className="mb-1 text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
              <Icon name="clock" size={14} className="text-accent-primary" />
              Uptime
            </h3>
            <p className="font-mono text-sm font-bold tabular-nums text-text-primary">
              {runtime?.uptime_seconds ? formatUptime(runtime.uptime_seconds) : "—"}
            </p>
          </div>

          {/* Card 4: CPU Usage with Live Sparkline */}
          <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
                <Icon name="cpu" size={14} className="text-status-danger" />
                CPU Usage
              </h3>
              <span className="font-mono text-xs font-bold tabular-nums text-status-danger">
                {currentMetric ? `${currentMetric.cpu_percent.toFixed(1)}%` : "—"}
              </span>
            </div>
            <Sparkline data={cpuData} color="var(--status-danger)" fillColor="var(--status-danger-bg)" height={24} />
          </div>

          {/* Card 5: RAM Usage with Live Sparkline */}
          <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
                <Icon name="hard-drive" size={14} className="text-status-warning" />
                RAM Usage
              </h3>
              <span className="font-mono text-xs font-bold tabular-nums text-status-warning">
                {currentMetric
                  ? ramPercent !== null
                    ? `${(currentMetric.ram_used_mb / 1024).toFixed(1)} GB (${ramPercent.toFixed(1)}%)`
                    : `${(currentMetric.ram_used_mb / 1024).toFixed(1)} GB`
                  : "—"}
              </span>
            </div>
            <Sparkline data={ramData} color="var(--status-warning)" fillColor="var(--status-warning-bg)" height={24} />
          </div>

          {/* Card 6: TPS & Tick Rate with Sparkline */}
          <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
                <Icon name="activity" size={14} className="text-status-success" />
                TPS & Tick Rate
              </h3>
              <span
                data-testid="tps-usage-value"
                className={`font-mono text-xs font-bold tabular-nums ${
                  hasLiveTps
                    ? currentMetric.tps! >= 19.5
                      ? "text-status-success"
                      : currentMetric.tps! >= 16.0
                        ? "text-status-warning"
                        : "text-status-danger"
                    : "text-text-muted"
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
                  ? "var(--status-danger)"
                  : hasLiveTps && currentMetric.tps! < 19.5
                    ? "var(--status-warning)"
                    : "var(--status-success)"
              }
              fillColor={
                hasLiveTps && currentMetric.tps! < 16
                  ? "var(--status-danger-bg)"
                  : hasLiveTps && currentMetric.tps! < 19.5
                    ? "var(--status-warning-bg)"
                    : "var(--status-success-bg)"
              }
              height={24}
            />
          </div>

          {/* Card 7: Allocated Memory */}
          <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
                <Icon name="database" size={14} className="text-accent-primary" />
                Memory Allocation
              </h3>
              <span className="font-mono text-[10px] font-semibold text-text-muted">JVM Heap</span>
            </div>
            <p className="font-mono text-sm font-bold tabular-nums text-text-primary">
              {server.min_memory_mb && server.max_memory_mb
                ? `${server.min_memory_mb} MB – ${server.max_memory_mb} MB`
                : "—"}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
