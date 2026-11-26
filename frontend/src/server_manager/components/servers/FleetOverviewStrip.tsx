import { Icon } from "@/components/ui/Icon";
import type { HostResourceBudget } from "@/types";
import { formatMemoryMb } from "./serversUtils";

export interface FleetOverviewStripProps {
  totalServers: number;
  runningCount: number;
  totalOnlinePlayers: number;
  totalOnlineCapacity: number;
  hostBudget?: HostResourceBudget;
  activeStatusFilter: string;
  onToggleRunningFilter: () => void;
  fallbackAllocatedRamMb: number;
}

export function FleetOverviewStrip({
  totalServers,
  runningCount,
  totalOnlinePlayers,
  totalOnlineCapacity,
  hostBudget,
  activeStatusFilter,
  onToggleRunningFilter,
  fallbackAllocatedRamMb,
}: FleetOverviewStripProps) {
  const isRunningFiltered = activeStatusFilter === "running";

  const allocatedRamMb = hostBudget?.allocated_ram_mb ?? fallbackAllocatedRamMb;
  const allocatableRamMb = hostBudget?.allocatable_ram_mb ?? null;
  const ramPct =
    allocatableRamMb && allocatableRamMb > 0
      ? Math.min(100, Math.round((allocatedRamMb / allocatableRamMb) * 100))
      : 0;

  const allocatedCpus = hostBudget?.allocated_cpus ?? null;
  const allocatableCpus = hostBudget?.allocatable_cpus ?? null;
  const isSharedCpu = allocatedCpus === 0 && runningCount > 0;
  const cpuPct =
    allocatedCpus != null && allocatableCpus && allocatableCpus > 0
      ? Math.min(100, Math.round((allocatedCpus / allocatableCpus) * 100))
      : 0;

  return (
    <div
      data-testid="fleet-overview-strip"
      className="grid grid-cols-2 gap-3 lg:grid-cols-4"
    >
      {/* 1. Instances Online */}
      <button
        type="button"
        onClick={onToggleRunningFilter}
        aria-pressed={isRunningFiltered}
        title={isRunningFiltered ? "Show all servers" : "Filter to online servers"}
        className={`group flex flex-col justify-between rounded-xl border p-3.5 text-left transition-colors cursor-pointer ${
          isRunningFiltered
            ? "border-accent-primary bg-accent-primary/10"
            : "border-border-subtle bg-surface-card hover:border-border-default hover:bg-surface-hover/40"
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            Instances Online
          </span>
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-lg ${
              runningCount > 0
                ? "bg-status-success-bg text-status-success"
                : "bg-surface-muted text-text-muted"
            }`}
          >
            {runningCount > 0 ? (
              <span className="h-2 w-2 rounded-full bg-status-success animate-pulse" />
            ) : (
              <Icon name="server" size={13} />
            )}
          </span>
        </div>
        <div className="mt-2 flex items-baseline gap-1.5 font-mono tabular-nums">
          <span className="text-xl font-bold text-text-primary">{runningCount}</span>
          <span className="text-xs text-text-muted">/ {totalServers}</span>
        </div>
      </button>

      {/* 2. Active Players */}
      <div className="flex flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            Active Players
          </span>
          <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-surface-muted text-text-secondary">
            <Icon name="users" size={13} />
          </span>
        </div>
        <div className="mt-2 flex items-baseline gap-1.5 font-mono tabular-nums">
          <span className="text-xl font-bold text-text-primary">
            {runningCount > 0 ? totalOnlinePlayers : 0}
          </span>
          <span className="text-xs text-text-muted">
            / {runningCount > 0 ? totalOnlineCapacity : 0}
          </span>
        </div>
      </div>

      {/* 3. Host Memory */}
      <div className="flex flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            Host Memory
          </span>
          <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-surface-muted text-text-accent">
            <Icon name="hard-drive" size={13} />
          </span>
        </div>
        <div className="mt-2 space-y-1.5">
          <div className="flex items-baseline gap-1.5 font-mono text-sm tabular-nums">
            <span className="text-base font-bold text-text-primary">
              {formatMemoryMb(allocatedRamMb)}
            </span>
            <span className="text-xs text-text-muted">
              {allocatableRamMb ? `/ ${formatMemoryMb(allocatableRamMb)}` : "allocated"}
            </span>
          </div>
          {allocatableRamMb ? (
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted">
              <div
                className={`h-full transition-all duration-300 ${
                  ramPct >= 85 ? "bg-status-warning" : "bg-accent-primary"
                }`}
                style={{ width: `${ramPct}%` }}
              />
            </div>
          ) : null}
        </div>
      </div>

      {/* 4. Host CPU */}
      <div className="flex flex-col justify-between rounded-xl border border-border-subtle bg-surface-card p-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            Host CPU
          </span>
          <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-surface-muted text-text-secondary">
            <Icon name="cpu" size={13} />
          </span>
        </div>
        <div className="mt-2 space-y-1.5">
          <div className="flex items-baseline gap-1.5 font-mono text-sm tabular-nums">
            <span className="text-base font-bold text-text-primary">
              {isSharedCpu
                ? "Shared"
                : allocatedCpus != null
                ? `${allocatedCpus}`
                : "—"}
            </span>
            <span className="text-xs text-text-muted">
              {allocatableCpus != null
                ? `/ ${allocatableCpus} cores`
                : isSharedCpu
                ? "unpinned"
                : "cores reserved"}
            </span>
          </div>
          {!isSharedCpu && allocatableCpus != null && allocatableCpus > 0 ? (
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted">
              <div
                className={`h-full transition-all duration-300 ${
                  cpuPct >= 85 ? "bg-status-warning" : "bg-status-success"
                }`}
                style={{ width: `${cpuPct}%` }}
              />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
