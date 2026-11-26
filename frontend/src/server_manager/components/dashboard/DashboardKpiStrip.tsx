import { useId } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { formatBytes } from "@/server_manager/utils/format";
import { formatMemoryMb } from "@/server_manager/components/servers/serversUtils";
import {
  formatRamGb,
  type HostTelemetryMetrics,
  type ServerStatusCounts,
} from "@/server_manager/utils/telemetryAdapter";
import type { HealthDashboardResponse } from "@/types";

export interface DashboardKpiStripProps {
  counts: ServerStatusCounts;
  totalServers: number;
  telemetry: HostTelemetryMetrics;
  healthDashboard?: HealthDashboardResponse | null;
  activeServerIds?: Set<string>;
}

function getTpsToneClass(tps: number | null): string {
  if (tps === null) return "bg-surface-muted text-text-muted";
  if (tps >= 18) return "bg-status-success-bg text-status-success";
  if (tps >= 15) return "bg-status-warning-bg text-status-warning";
  return "bg-status-danger-bg text-status-danger";
}

function CpuSparkline({ points, isCollecting }: { points: number[]; isCollecting: boolean }) {
  const gradId = useId().replace(/:/g, "-");
  const width = 120;
  const height = 32;

  if (points.length < 2) {
    return (
      <div className="flex items-center gap-2 py-0.5">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-7 w-full text-text-muted"
          aria-hidden="true"
        >
          <line
            x1="0"
            y1={height - 6}
            x2={width}
            y2={height - 6}
            stroke="currentColor"
            strokeOpacity="0.28"
            strokeWidth="1.5"
            strokeDasharray="3 3"
          />
        </svg>
        {isCollecting && (
          <span className="shrink-0 text-[10px] font-medium text-text-muted whitespace-nowrap">
            Collecting...
          </span>
        )}
      </div>
    );
  }

  const stepX = width / Math.max(1, points.length - 1);
  const coords = points.map((val, idx) => {
    const x = Math.round(idx * stepX * 10) / 10;
    const clamped = Math.min(100, Math.max(0, val));
    const y = Math.round((height - 4 - (clamped / 100) * (height - 8)) * 10) / 10;
    return { x, y };
  });

  const linePath = coords
    .map((pt, idx) => `${idx === 0 ? "M" : "L"} ${pt.x} ${pt.y}`)
    .join(" ");
  const areaPath = `${linePath} L ${coords[coords.length - 1].x} ${height} L 0 ${height} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="h-7 w-full text-accent-primary overflow-visible"
      role="img"
      aria-label="Server CPU trend sparkline"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.28" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />
      <path
        d={linePath}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function DashboardKpiStrip({
  counts,
  totalServers,
  telemetry,
  healthDashboard,
  activeServerIds,
}: DashboardKpiStripProps) {
  const safeTotal = Math.max(1, totalServers);
  const onlinePct = (counts.onlineCount / safeTotal) * 100;
  const attentionPct = (counts.attentionCount / safeTotal) * 100;

  const backupSafeTotal = Math.max(1, telemetry.backupTotalCount);
  const backupSuccessPct = (telemetry.backupCompletedCount / backupSafeTotal) * 100;
  const backupFailedPct = (telemetry.backupFailedCount / backupSafeTotal) * 100;

  const healthAlertsCount =
    healthDashboard?.servers && healthDashboard.servers.length > 0 && activeServerIds
      ? healthDashboard.servers.filter(
          (entry) =>
            activeServerIds.has(entry.server_id) &&
            (entry.status === "warning" || entry.status === "critical"),
        ).length
      : (healthDashboard?.warning ?? 0) + (healthDashboard?.critical ?? 0);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {/* Card 1: Fleet & Players */}
      <section
        aria-label="Fleet and Players"
        className="flex flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3 min-w-0"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-text-secondary truncate">
            Fleet &amp; Players
          </span>
          <span className="inline-flex h-6 items-center gap-1 rounded-full bg-surface-muted px-2 text-[11px] font-mono tabular-nums text-text-secondary whitespace-nowrap shrink-0">
            <Icon name="users" size={11} className="text-text-muted shrink-0" />
            {counts.onlineCount > 0
              ? `${telemetry.onlinePlayers} / ${telemetry.maxPlayers} players`
              : "Idle"}
          </span>
        </div>

        <div className="flex items-baseline justify-between gap-2">
          <div className="text-xl 2xl:text-2xl font-semibold tracking-tight text-text-primary font-mono tabular-nums whitespace-nowrap shrink-0">
            {counts.onlineCount} / {totalServers}
            <span className="ml-1.5 text-xs font-sans font-normal text-text-muted">
              online
            </span>
          </div>
          {healthAlertsCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-status-warning-bg px-2 py-0.5 text-[10px] font-semibold text-status-warning whitespace-nowrap">
              {healthAlertsCount} health warn
            </span>
          )}
        </div>

        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-muted flex">
          {onlinePct > 0 && (
            <div
              className="h-full bg-status-success transition-all duration-300"
              style={{ width: `${onlinePct}%` }}
            />
          )}
          {attentionPct > 0 && (
            <div
              className="h-full bg-status-danger transition-all duration-300"
              style={{ width: `${attentionPct}%` }}
            />
          )}
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <Link
            to="/servers?status=running"
            className="font-medium text-text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus rounded whitespace-nowrap"
          >
            {counts.onlineCount} Online
          </Link>
          <Link
            to="/servers?status=stopped"
            className="text-text-muted hover:text-text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus rounded whitespace-nowrap"
          >
            {counts.offlineCount} Offline
          </Link>
          <Link
            to="/servers?status=attention"
            className={`hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus rounded whitespace-nowrap ${
              counts.attentionCount > 0
                ? "font-semibold text-status-danger"
                : "text-text-muted hover:text-text-primary"
            }`}
          >
            {counts.attentionCount} Attention
          </Link>
        </div>
      </section>

      {/* Card 2: Compute & Tickrate */}
      <section
        aria-label="Compute and Tickrate"
        className="flex flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3 min-w-0"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-text-secondary truncate">
            Compute &amp; Tickrate
          </span>
          <span
            className={`inline-flex h-6 items-center rounded-full px-2 text-[11px] font-mono font-semibold tabular-nums whitespace-nowrap shrink-0 ${getTpsToneClass(
              counts.onlineCount > 0 ? telemetry.tpsAvg : null,
            )}`}
          >
            {counts.onlineCount > 0 && telemetry.tpsAvg !== null
              ? `${telemetry.tpsAvg.toFixed(1)} TPS`
              : "Idle"}
          </span>
        </div>

        <div className="text-xl 2xl:text-2xl font-semibold tracking-tight text-text-primary font-mono tabular-nums whitespace-nowrap shrink-0">
          {telemetry.cpuPercent.toFixed(1)}%
        </div>

        <CpuSparkline
          points={telemetry.cpuHistory}
          isCollecting={counts.onlineCount > 0 && telemetry.cpuHistory.length < 2}
        />

        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-text-muted truncate">
            Server CPU ({counts.onlineCount} active)
          </span>
          <span
            className={`font-medium whitespace-nowrap ${
              counts.onlineCount > 0 ? "text-status-success" : "text-text-muted"
            }`}
          >
            {counts.onlineCount > 0 ? "Live" : "Standby"}
          </span>
        </div>
      </section>

      {/* Card 3: Memory & Capacity */}
      <section
        aria-label="Memory and Capacity"
        className="flex flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3 min-w-0"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-text-secondary truncate">
            Memory &amp; Capacity
          </span>
          <span className="inline-flex h-6 items-center rounded-full bg-surface-muted px-2 text-[11px] font-mono tabular-nums text-text-secondary whitespace-nowrap shrink-0">
            {telemetry.activeAllocatedMb > 0
              ? `${Math.round(telemetry.liveRssOfAllocatedPct)}% heap`
              : "Idle"}
          </span>
        </div>

        <div className="flex items-baseline gap-1 text-xl 2xl:text-2xl font-semibold tracking-tight text-text-primary font-mono tabular-nums whitespace-nowrap shrink-0">
          <span>{formatRamGb(telemetry.liveRssMb)}</span>
          {telemetry.activeAllocatedMb > 0 && (
            <span className="text-xs font-normal text-text-muted">
              / {formatRamGb(telemetry.activeAllocatedMb)}
            </span>
          )}
        </div>

        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-muted">
          <div
            className={`h-full transition-all duration-300 ${
              telemetry.liveRssOfAllocatedPct >= 85 ? "bg-status-warning" : "bg-accent-primary"
            }`}
            style={{ width: `${telemetry.liveRssOfAllocatedPct}%` }}
          />
        </div>

        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-text-muted whitespace-nowrap">Live RSS</span>
          <span className="font-mono font-medium tabular-nums text-text-secondary whitespace-nowrap">
            {telemetry.availableRamMb !== null
              ? `${formatMemoryMb(telemetry.availableRamMb)} free`
              : "Budget loading"}
          </span>
        </div>
      </section>

      {/* Card 4: Backups & Schedules */}
      <section
        aria-label="Backups and Schedules"
        className="flex flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3 min-w-0"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-text-secondary truncate">
            Backups &amp; Schedules
          </span>
          <Link
            to="/backups"
            className="inline-flex items-center gap-0.5 text-xs font-medium text-text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus rounded whitespace-nowrap shrink-0"
          >
            <span>Manage</span>
            <Icon name="chevron-right" size={12} />
          </Link>
        </div>

        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xl 2xl:text-2xl font-semibold tracking-tight text-text-primary font-mono tabular-nums whitespace-nowrap shrink-0">
            {formatBytes(telemetry.backupTotalBytes)}
          </span>
          <span className="inline-flex h-6 items-center rounded-full bg-surface-muted px-2 text-[11px] font-mono tabular-nums text-text-secondary whitespace-nowrap shrink-0">
            {telemetry.backupCompletedCount} saved
          </span>
        </div>

        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-muted flex">
          {telemetry.backupTotalCount > 0 && backupSuccessPct > 0 && (
            <div
              className="h-full bg-status-success transition-all duration-300"
              style={{ width: `${backupSuccessPct}%` }}
            />
          )}
          {telemetry.backupTotalCount > 0 && backupFailedPct > 0 && (
            <div
              className="h-full bg-status-danger transition-all duration-300"
              style={{ width: `${backupFailedPct}%` }}
            />
          )}
        </div>

        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-text-muted truncate">
            Last: {telemetry.lastBackupRelative}
          </span>
          {telemetry.activeSchedulesCount !== null && (
            <span className="font-medium text-text-secondary whitespace-nowrap">
              {telemetry.activeSchedulesCount > 0
                ? `${telemetry.activeSchedulesCount} scheduled`
                : "No schedules"}
            </span>
          )}
        </div>
      </section>
    </div>
  );
}
