import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Sparkline } from "@/server_manager/components/Sparkline";
import { useClipboard } from "@/hooks/useClipboard";
import { resolveAccessAddress } from "@/server_manager/utils/accessAddress";
import { resolveJoinAddress } from "@/server_manager/components/servers/serversUtils";
import { OnlinePlayersCard } from "./OnlinePlayersCard";
import type {
  MetricsSnapshot,
  ServerHealthStatusResponse,
} from "@/services/api";
import type {
  RuntimeDiagnosticsResponse,
  ServerDetailResponse,
} from "@/server_manager/types";
import type { ServerExposureResponse } from "@/types";

export interface ServerVitalsRailProps {
  server: ServerDetailResponse;
  serverId: string;
  branch?: string;
  isBranchView: boolean;
  branchGamePort?: number | null;
  isRunning: boolean;
  runtime?: RuntimeDiagnosticsResponse | null;
  metrics?: MetricsSnapshot[];
  exposure?: ServerExposureResponse | null;
  healthStatus?: ServerHealthStatusResponse | null;
  supportsModpacks: boolean;
  canConsole: boolean;
  canWrite: boolean;
  onOpenDiagnostics: () => void;
  onOpenModpackWizard: () => void;
  onOpenSafeUpgradeWizard: () => void;
}

function formatDetailedUptime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const total = Math.floor(seconds);
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/**
 * Filter transient synthetic 0.0 MB RAM outlier points when surrounded by healthy
 * non-zero samples for a running container so legacy SQLite drops never create
 * misleading vertical cliffs.
 */
function sanitizeRamSeries(values: number[]): number[] {
  if (values.length < 3) return values;
  const hasHealthy = values.some((v) => v > 16);
  if (!hasHealthy) return values;
  return values.map((v, i) => {
    if (v <= 0) {
      const prev = i > 0 ? values[i - 1] : 0;
      const next = i < values.length - 1 ? values[i + 1] : 0;
      if (prev > 16 || next > 16) {
        return prev > 16 ? prev : next;
      }
    }
    return v;
  });
}

function getCpuTone(cpuPercent: number | null): {
  textClass: string;
  colorVar: string;
  fillVar: string;
} {
  if (cpuPercent == null) {
    return {
      textClass: "text-text-muted",
      colorVar: "var(--status-info)",
      fillVar: "var(--status-info-bg)",
    };
  }
  if (cpuPercent >= 90) {
    return {
      textClass: "text-status-danger",
      colorVar: "var(--status-danger)",
      fillVar: "var(--status-danger-bg)",
    };
  }
  if (cpuPercent >= 70) {
    return {
      textClass: "text-status-warning",
      colorVar: "var(--status-warning)",
      fillVar: "var(--status-warning-bg)",
    };
  }
  return {
    textClass: "text-status-info",
    colorVar: "var(--status-info)",
    fillVar: "var(--status-info-bg)",
  };
}

function getRamTone(ramPercent: number | null): {
  textClass: string;
  barClass: string;
  colorVar: string;
  fillVar: string;
} {
  if (ramPercent == null) {
    return {
      textClass: "text-text-muted",
      barClass: "bg-status-info",
      colorVar: "var(--status-info)",
      fillVar: "var(--status-info-bg)",
    };
  }
  if (ramPercent >= 90) {
    return {
      textClass: "text-status-danger",
      barClass: "bg-status-danger",
      colorVar: "var(--status-danger)",
      fillVar: "var(--status-danger-bg)",
    };
  }
  if (ramPercent >= 75) {
    return {
      textClass: "text-status-warning",
      barClass: "bg-status-warning",
      colorVar: "var(--status-warning)",
      fillVar: "var(--status-warning-bg)",
    };
  }
  return {
    textClass: "text-status-success",
    barClass: "bg-status-success",
    colorVar: "var(--status-success)",
    fillVar: "var(--status-success-bg)",
  };
}

function getHealthBadgeTone(status: string): string {
  switch (status) {
    case "healthy":
      return "bg-status-success-bg text-status-success border-status-success-border";
    case "warning":
      return "bg-status-warning-bg text-status-warning border-status-warning-border";
    case "critical":
    case "broken":
      return "bg-status-danger-bg text-status-danger border-status-danger-border";
    default:
      return "bg-surface-muted text-text-secondary border-border-subtle";
  }
}

export function ServerVitalsRail({
  server,
  serverId,
  branch,
  isBranchView,
  branchGamePort,
  isRunning,
  runtime,
  metrics,
  exposure,
  healthStatus,
  supportsModpacks,
  canConsole,
  canWrite,
  onOpenDiagnostics,
  onOpenModpackWizard,
  onOpenSafeUpgradeWizard,
}: ServerVitalsRailProps) {
  const { copy } = useClipboard();

  // Live 1-second ticking uptime seeded from runtime or server detail
  const baseUptimeSeconds = !isBranchView && isRunning
    ? (runtime?.uptime_seconds && runtime.uptime_seconds > 0
        ? runtime.uptime_seconds
        : (server.uptime_seconds ?? 0))
    : 0;

  const [tickState, setTickState] = useState<{ base: number; offset: number }>({
    base: baseUptimeSeconds,
    offset: 0,
  });

  useEffect(() => {
    if (!isRunning || baseUptimeSeconds <= 0) return;
    const timer = window.setInterval(() => {
      setTickState((prev) =>
        prev.base === baseUptimeSeconds
          ? { base: baseUptimeSeconds, offset: prev.offset + 1 }
          : { base: baseUptimeSeconds, offset: 1 },
      );
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isRunning, baseUptimeSeconds]);

  const elapsedOffset = tickState.base === baseUptimeSeconds ? tickState.offset : 0;
  const liveUptimeSeconds =
    isRunning && baseUptimeSeconds > 0 ? baseUptimeSeconds + elapsedOffset : 0;

  // Canonical Join Address (never leaks 172.17.x.x or 0.0.0.0)
  const resolvedAccess = resolveAccessAddress(server, exposure);
  const fallbackJoin = resolveJoinAddress(server);
  const joinAddress = isBranchView
    ? exposure?.targets?.[0]?.public_address ||
      (branchGamePort ? `localhost:${branchGamePort}` : "—")
    : resolvedAccess.address ?? fallbackJoin.address;
  const isPublicAddress = isBranchView
    ? Boolean(exposure?.targets?.[0]?.public_address)
    : resolvedAccess.kind === "playit" ||
      resolvedAccess.kind === "cloudflare" ||
      fallbackJoin.isPublic;

  // Real numeric Server Port (NEVER the Docker bridge IP!)
  const displayPort = isBranchView
    ? branchGamePort
      ? String(branchGamePort)
      : "Unallocated"
    : String(server.deployment_port ?? server.port);

  // Metrics & Sparklines
  const sortedMetrics =
    !isBranchView && isRunning && metrics?.length
      ? [...metrics].sort((a, b) => {
          const ta = Date.parse(a.timestamp);
          const tb = Date.parse(b.timestamp);
          if (!Number.isNaN(ta) && !Number.isNaN(tb)) return ta - tb;
          return String(a.timestamp).localeCompare(String(b.timestamp));
        })
      : [];

  const currentMetric =
    sortedMetrics.length > 0 ? sortedMetrics[sortedMetrics.length - 1] : undefined;

  const rawRamData = sortedMetrics.map((m) => m.ram_used_mb);
  const ramData = sanitizeRamSeries(rawRamData);
  const cpuData = sortedMetrics.map((m) => m.cpu_percent);
  const tpsData = sortedMetrics
    .map((m) => m.tps)
    .filter((t): t is number => t != null);

  const maxMemoryMb = server.max_memory_mb > 0 ? server.max_memory_mb : 2048;
  const effectiveRamMb =
    currentMetric && currentMetric.ram_used_mb <= 0 && ramData.length > 0
      ? ramData[ramData.length - 1]
      : currentMetric?.ram_used_mb;

  const ramPercent =
    effectiveRamMb != null && maxMemoryMb > 0
      ? Math.min(100, (effectiveRamMb / maxMemoryMb) * 100)
      : null;

  const cpuTone = getCpuTone(currentMetric?.cpu_percent ?? null);
  const ramTone = getRamTone(ramPercent);
  const hasLiveTps = !isBranchView && isRunning && currentMetric?.tps != null;
  const conflictCount = runtime?.owner_conflicts?.length ?? 0;

  return (
    <div className="flex flex-col gap-3.5">
      {/* Card 1: Connection & Health */}
      <div
        data-testid="connection-health-card"
        className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs space-y-3"
      >
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
            <Icon name="globe" size={14} className="text-accent-primary" />
            <span>Connection &amp; Health</span>
          </h3>
          {!isBranchView && healthStatus && healthStatus.status !== "unknown" && (
            <span
              data-testid="server-health-badge"
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize ${getHealthBadgeTone(
                healthStatus.status,
              )}`}
              title={
                healthStatus.contributing_factors?.length
                  ? healthStatus.contributing_factors.join(" • ")
                  : `Health: ${healthStatus.status}`
              }
            >
              {healthStatus.status}
            </span>
          )}
        </div>

        {/* Join Address Row */}
        <div className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              <span>{isPublicAddress ? "Public Join Address" : "Join Address"}</span>
            </div>
            <p
              data-testid="vitals-join-address"
              className="font-mono text-xs font-bold text-text-primary truncate mt-0.5"
              title={joinAddress}
            >
              {joinAddress}
            </p>
          </div>
          {joinAddress !== "—" && (
            <button
              type="button"
              data-testid="vitals-copy-address-btn"
              onClick={() => copy(joinAddress, "Join address copied to clipboard")}
              className="shrink-0 p-1.5 rounded-md text-text-muted hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
              title="Copy join address"
              aria-label="Copy join address"
            >
              <Icon name="copy" size={14} />
            </button>
          )}
        </div>

        {/* Port & Uptime 2-Column Compact Grid */}
        <div className="grid grid-cols-2 gap-2.5">
          <div
            data-testid="server-port-widget"
            className="rounded-lg border border-border-subtle bg-surface-muted px-2.5 py-2"
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                Server Port
              </span>
              {displayPort !== "Unallocated" && (
                <button
                  type="button"
                  onClick={() => copy(displayPort, "Port copied to clipboard")}
                  className="p-0.5 rounded text-text-muted hover:text-text-primary transition-colors cursor-pointer"
                  title="Copy server port"
                  aria-label="Copy server port"
                >
                  <Icon name="copy" size={11} />
                </button>
              )}
            </div>
            <p className="font-mono text-sm font-bold tabular-nums text-text-primary mt-0.5">
              {displayPort}
            </p>
          </div>

          <div
            data-testid="server-uptime-widget"
            className="rounded-lg border border-border-subtle bg-surface-muted px-2.5 py-2"
          >
            <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted block">
              Uptime
            </span>
            <p className="font-mono text-sm font-bold tabular-nums text-text-primary mt-0.5">
              {liveUptimeSeconds > 0 ? formatDetailedUptime(liveUptimeSeconds) : "—"}
            </p>
          </div>
        </div>

        {/* Owner Conflicts Warning if present */}
        {conflictCount > 0 && (
          <button
            type="button"
            data-testid="runtime-conflict-alert"
            onClick={onOpenDiagnostics}
            className="w-full flex items-center justify-between gap-2 rounded-lg border border-status-warning-border bg-status-warning-bg px-2.5 py-1.5 text-[11px] font-medium text-status-warning hover:opacity-90 transition-opacity cursor-pointer"
          >
            <span className="flex items-center gap-1.5 truncate">
              <Icon name="alert" size={12} />
              <span>
                {conflictCount} runtime ownership {conflictCount === 1 ? "conflict" : "conflicts"}
              </span>
            </span>
            <span className="shrink-0 underline">Inspect</span>
          </button>
        )}
      </div>

      {/* Card 2: Unified Live Performance Card */}
      <div
        data-testid="live-performance-card"
        className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs space-y-3.5"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
            <Icon name="activity" size={14} className="text-accent-primary" />
            <span>Live Performance</span>
          </h3>
          <span className="font-mono text-[10px] text-text-muted">
            {server.min_memory_mb}–{server.max_memory_mb} MB
          </span>
        </div>

        {/* CPU Row */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-text-secondary flex items-center gap-1.5">
              <Icon name="cpu" size={13} className={cpuTone.textClass} />
              <span>CPU Usage</span>
            </span>
            <span className={`font-mono font-bold tabular-nums ${cpuTone.textClass}`}>
              {currentMetric ? `${currentMetric.cpu_percent.toFixed(1)}%` : "—"}
            </span>
          </div>
          <Sparkline
            data={cpuData}
            color={cpuTone.colorVar}
            fillColor={cpuTone.fillVar}
            minDomain={0}
            maxDomain={Math.max(100, ...cpuData, 100)}
            height={22}
          />
        </div>

        {/* RAM Row */}
        <div className="space-y-1.5 pt-2.5 border-t border-border-subtle/60">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-text-secondary flex items-center gap-1.5">
              <Icon name="hard-drive" size={13} className={ramTone.textClass} />
              <span>RAM Usage</span>
            </span>
            <span className={`font-mono font-bold tabular-nums ${ramTone.textClass}`}>
              {effectiveRamMb != null
                ? ramPercent !== null
                  ? `${(effectiveRamMb / 1024).toFixed(1)} GB (${ramPercent.toFixed(1)}%)`
                  : `${(effectiveRamMb / 1024).toFixed(1)} GB`
                : "—"}
            </span>
          </div>
          {/* Inset heap utilization bar (bg-surface-muted track inside bg-surface-card) */}
          <div className="h-1.5 w-full rounded-full bg-surface-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-300 ${ramTone.barClass}`}
              style={{ width: `${ramPercent ?? 0}%` }}
            />
          </div>
          <Sparkline
            data={ramData}
            color={ramTone.colorVar}
            fillColor={ramTone.fillVar}
            minDomain={0}
            maxDomain={maxMemoryMb}
            height={22}
          />
        </div>

        {/* TPS Row */}
        <div className="space-y-1.5 pt-2.5 border-t border-border-subtle/60">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-text-secondary flex items-center gap-1.5">
              <Icon name="activity" size={13} className="text-status-success" />
              <span>TPS &amp; Tick Rate</span>
            </span>
            <span
              data-testid="tps-usage-value"
              className={`font-mono font-bold tabular-nums ${
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
            minDomain={0}
            maxDomain={20}
            height={22}
          />
        </div>
      </div>

      {/* Card 3: Online Players */}
      {!isBranchView && (
        <OnlinePlayersCard
          serverId={serverId}
          branch={branch}
          isRunning={isRunning}
          livePlayersCount={currentMetric?.players ?? null}
          maxPlayers={server.max_players}
          canConsole={canConsole}
        />
      )}

      {/* Card 4: Maintenance & Diagnostics */}
      <div
        data-testid="modpack-upgrade-quick-actions"
        className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs space-y-2"
      >
        <h3 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-1.5">
          <Icon name="sliders" size={14} className="text-accent-primary" />
          <span>Maintenance &amp; Diagnostics</span>
        </h3>

        <button
          type="button"
          data-testid="open-diagnostics-drawer-btn"
          onClick={onOpenDiagnostics}
          className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-xs font-medium text-text-primary transition-colors hover:border-border-hover hover:bg-surface-hover cursor-pointer"
        >
          <Icon name="info" size={14} />
          <span>Runtime &amp; Server Info</span>
        </button>

        {canWrite && supportsModpacks && (
          <button
            type="button"
            data-testid="detail-open-modpack-wizard-btn"
            onClick={onOpenModpackWizard}
            className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-border-subtle bg-surface-card px-3 py-2 text-xs font-medium text-text-primary shadow-2xs transition-colors hover:border-border-hover hover:bg-surface-hover cursor-pointer"
          >
            <Icon name="download" size={14} />
            <span>Install Modpack</span>
          </button>
        )}

        {canWrite && (
          <button
            type="button"
            data-testid="detail-open-safe-upgrade-wizard-btn"
            onClick={onOpenSafeUpgradeWizard}
            className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-border-subtle bg-surface-card px-3 py-2 text-xs font-medium text-text-primary shadow-2xs transition-colors hover:border-border-hover hover:bg-surface-hover cursor-pointer"
          >
            <Icon name="restart" size={14} />
            <span>Change Version</span>
          </button>
        )}
      </div>
    </div>
  );
}
