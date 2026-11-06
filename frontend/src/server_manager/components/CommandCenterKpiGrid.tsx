import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import type { HostTelemetryMetrics } from "@/server_manager/utils/telemetryAdapter";

interface CommandCenterKpiGridProps {
  counts: Record<string, number>;
  totalServers: number;
  telemetry: HostTelemetryMetrics;
}

export function CommandCenterKpiGrid({
  counts,
  totalServers,
  telemetry,
}: CommandCenterKpiGridProps) {
  const onlineCount = counts.running || 0;
  const offlineCount = (counts.stopped || 0) + (counts.created || 0) + (counts.not_started || 0);
  const crashedCount = (counts.crashed || 0) + (counts.broken || 0);

  // Proportions for segmented bar (defaults to 100% offline if total is 0)
  const safeTotal = totalServers > 0 ? totalServers : 1;
  const onlinePct = (onlineCount / safeTotal) * 100;
  const crashedPct = (crashedCount / safeTotal) * 100;
  const offlinePct = Math.max(0, 100 - onlinePct - crashedPct);

  // Sparkline coordinates for 20 data points inside 120x28 viewBox
  const minVal = Math.min(...telemetry.cpuHistory);
  const maxVal = Math.max(...telemetry.cpuHistory, minVal + 1);
  const points = telemetry.cpuHistory.map((val, idx) => {
    const x = (idx / (telemetry.cpuHistory.length - 1)) * 120;
    const y = 26 - ((val - minVal) / (maxVal - minVal)) * 22;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const pathData = `M ${points.join(" L ")}`;
  const areaData = `${pathData} L 120,28 L 0,28 Z`;

  // RAM calculations
  const usedRamPct = Math.min(100, (telemetry.usedRamGb / telemetry.totalRamGb) * 100);
  const reservedRamPct = Math.min(100, (telemetry.reservedRamGb / telemetry.totalRamGb) * 100);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {/* Card 1: Fleet Availability */}
      <div
        role="region"
        aria-label="Fleet Availability"
        className="flex min-h-[140px] flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-4.5 shadow-2xs transition-all hover:border-border-default hover:shadow-xs"
      >
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wider text-text-muted">
            Fleet Status
          </span>
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-elevated text-text-muted border border-border-subtle">
            <Icon name="server" size={14} />
          </div>
        </div>

        <div className="my-1.5 flex items-baseline gap-2">
          <span className="font-mono text-2xl font-bold tabular-nums text-text-primary">
            {onlineCount} / {totalServers}
          </span>
          <span className="text-xs font-medium text-text-muted">
            Instances Online
          </span>
        </div>

        <div>
          {/* Multi-color segmented progress bar */}
          <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-elevated">
            {onlinePct > 0 && (
              <div
                style={{ width: `${onlinePct}%` }}
                className="bg-status-success transition-all duration-300"
                title={`${onlineCount} Online`}
              />
            )}
            {crashedPct > 0 && (
              <div
                style={{ width: `${crashedPct}%` }}
                className="bg-status-danger transition-all duration-300"
                title={`${crashedCount} Crashed`}
              />
            )}
            {offlinePct > 0 && (
              <div
                style={{ width: `${offlinePct}%` }}
                className="bg-text-muted/40 transition-all duration-300"
                title={`${offlineCount} Offline`}
              />
            )}
          </div>
          <div className="mt-2 flex items-center justify-between text-[11px] text-text-muted">
            <Link
              to="/servers?status=running"
              className="hover:text-status-success transition-colors"
            >
              {onlineCount} Online
            </Link>
            <span>·</span>
            <Link
              to="/servers?status=stopped"
              className="hover:text-text-primary transition-colors"
            >
              {offlineCount} Offline
            </Link>
            <span>·</span>
            <Link
              to="/servers?status=crashed"
              className="hover:text-status-danger transition-colors"
            >
              {crashedCount} Crashed
            </Link>
          </div>
        </div>
      </div>

      {/* Card 2: Host CPU Load & TPS */}
      <div
        role="region"
        aria-label="Compute and Tickrate"
        className="flex min-h-[140px] flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-4.5 shadow-2xs transition-all hover:border-border-default hover:shadow-xs"
      >
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wider text-text-muted">
            Compute &amp; Tickrate
          </span>
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-elevated text-text-muted border border-border-subtle">
            <Icon name="cpu" size={14} />
          </div>
        </div>

        <div className="my-1 flex items-baseline justify-between">
          <span className="font-mono text-2xl font-bold tabular-nums text-text-primary">
            {telemetry.cpuPercent}%
          </span>
          <span
            className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold ${
              telemetry.tpsAvg !== null
                ? "bg-status-success-bg text-status-success border border-status-success-border"
                : "bg-surface-elevated text-text-muted border border-border-subtle"
            }`}
          >
            {telemetry.tpsAvg !== null
              ? `${telemetry.tpsAvg.toFixed(1)} TPS avg`
              : "-- TPS (Idle)"}
          </span>
        </div>

        {/* Inline SVG sparkline chart */}
        <div className="h-7 w-full overflow-hidden">
          <svg
            viewBox="0 0 120 28"
            className="h-full w-full overflow-visible text-accent-primary"
            preserveAspectRatio="none"
          >
            <defs>
              <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="currentColor" stopOpacity="0.25" />
                <stop offset="100%" stopColor="currentColor" stopOpacity="0.0" />
              </linearGradient>
            </defs>
            <path d={areaData} fill="url(#cpuGrad)" />
            <path
              d={pathData}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      </div>

      {/* Card 3: Memory Allocation (RAM) */}
      <div
        role="region"
        aria-label="Memory Allocation"
        className="flex min-h-[140px] flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-4.5 shadow-2xs transition-all hover:border-border-default hover:shadow-xs"
      >
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wider text-text-muted">
            Memory Allocation
          </span>
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-elevated text-text-muted border border-border-subtle">
            <Icon name="hard-drive" size={14} />
          </div>
        </div>

        <div className="my-1.5 flex items-baseline justify-between gap-1">
          <span className="font-mono text-xl font-bold tabular-nums text-text-primary">
            {telemetry.usedRamGb.toFixed(1)} / {telemetry.totalRamGb.toFixed(1)} GB
          </span>
          <span className="rounded-md bg-surface-elevated px-1.5 py-0.5 text-[11px] font-mono font-medium text-text-secondary border border-border-subtle">
            {usedRamPct.toFixed(1)}% Used
          </span>
        </div>

        <div>
          {/* Dual-layer progress bar */}
          <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-surface-elevated">
            {/* Translucent reserved RAM bar */}
            <div
              style={{ width: `${reservedRamPct}%` }}
              className="absolute inset-y-0 start-0 bg-accent-primary/25"
            />
            {/* Solid used RAM bar */}
            <div
              style={{ width: `${usedRamPct}%` }}
              className="absolute inset-y-0 start-0 bg-accent-primary transition-all duration-300"
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-[11px] text-text-muted">
            <span>{telemetry.reservedRamGb.toFixed(1)} GB Reserved</span>
            <span>{(telemetry.totalRamGb - telemetry.usedRamGb).toFixed(1)} GB Free</span>
          </div>
        </div>
      </div>

      {/* Card 4: Storage & Backup Engine */}
      <div
        role="region"
        aria-label="Storage and Snapshots"
        className="flex min-h-[140px] flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-4.5 shadow-2xs transition-all hover:border-border-default hover:shadow-xs"
      >
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wider text-text-muted">
            Storage &amp; Snapshots
          </span>
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-elevated text-text-muted border border-border-subtle">
            <Icon name="database" size={14} />
          </div>
        </div>

        <div className="my-1.5 flex items-baseline gap-2">
          <span className="font-mono text-2xl font-bold tabular-nums text-text-primary">
            {telemetry.storageUsedGb.toFixed(1)} GB
          </span>
          <span className="text-xs font-medium text-text-muted">
            World &amp; Backup Data
          </span>
        </div>

        <div className="flex items-center justify-between border-t border-border-subtle/50 pt-2 text-[11px]">
          <span className="truncate text-text-muted" title="Last backup: 4h ago · Git Engine Ready">
            Last: {telemetry.lastBackupRelative} · Git Engine
          </span>
          <Link
            to="/backups"
            className="shrink-0 rounded-md bg-surface-elevated px-2 py-0.5 text-xs font-semibold text-accent-primary border border-border-subtle hover:bg-surface-hover hover:border-border-default transition-colors"
          >
            Run Backup
          </Link>
        </div>
      </div>
    </div>
  );
}
