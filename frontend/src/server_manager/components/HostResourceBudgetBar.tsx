import { Icon } from "@/components/ui/Icon";
import type { HostResourceBudget } from "@/types";

function formatMb(mb: number): string {
  if (mb >= 1024) {
    const gb = mb / 1024;
    return `${gb % 1 === 0 ? gb.toFixed(0) : gb.toFixed(1)} GB`;
  }
  return `${mb} MB`;
}

interface HostResourceBudgetBarProps {
  budget: HostResourceBudget;
  requestedRamMb?: number | null;
  requestedCpuCores?: number | null;
  compact?: boolean;
}

export function HostResourceBudgetBar({
  budget,
  requestedRamMb,
  requestedCpuCores,
  compact = false,
}: HostResourceBudgetBarProps) {
  const totalRam = Math.max(1, budget.total_ram_mb);
  const reservePct = Math.min(100, (budget.os_reserve_ram_mb / totalRam) * 100);
  const allocatedPct = Math.min(
    100 - reservePct,
    (budget.allocated_ram_mb / totalRam) * 100,
  );
  const availablePct = Math.max(0, 100 - reservePct - allocatedPct);

  const reqRam = typeof requestedRamMb === "number" && requestedRamMb > 0 ? requestedRamMb : 0;
  const reqCpu = typeof requestedCpuCores === "number" && requestedCpuCores > 0 ? requestedCpuCores : 0;

  const exceedsAllocatableRam = reqRam > budget.allocatable_ram_mb;
  const exceedsAvailableRam = !exceedsAllocatableRam && reqRam > budget.available_ram_mb;
  const exceedsAllocatableCpu = reqCpu > budget.allocatable_cpus;
  const exceedsAvailableCpu = !exceedsAllocatableCpu && reqCpu > budget.available_cpus;

  return (
    <div
      role="region"
      aria-label="Host Resource Budget"
      className={`rounded-xl border border-border-default bg-surface-card ${
        compact ? "p-3.5 space-y-2.5" : "p-4 space-y-3"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-muted text-text-accent border border-border-subtle">
            <Icon name="hard-drive" size={14} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-text-primary">
                Host Resource Budget
              </span>
              <span className="inline-flex items-center rounded-full border border-border-subtle bg-surface-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                {budget.profile === "local" ? "Desktop Safe Reserve" : "VPS Reserve"}
              </span>
            </div>
            {!compact && (
              <p className="text-[11px] text-text-muted">
                Allocatable ceiling after protecting {formatMb(budget.os_reserve_ram_mb)} RAM &amp;{" "}
                {budget.reserved_cpus} CPU cores for OS and panel services.
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs font-mono tabular-nums">
          <span className="text-text-primary font-semibold">
            {formatMb(budget.available_ram_mb)} free
          </span>
          <span className="text-text-muted">·</span>
          <span className="text-text-secondary">
            {budget.allocated_cpus === 0 && budget.allocations.length > 0
              ? `Shared CPU (${budget.allocatable_cpus} cores)`
              : `${budget.available_cpus} / ${budget.allocatable_cpus} CPU avail`}
          </span>
        </div>
      </div>

      {/* Segmented Host Memory Budget Bar */}
      <div className="space-y-1.5">
        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-muted border border-border-subtle">
          {reservePct > 0 && (
            <div
              style={{ width: `${reservePct}%` }}
              className="bg-status-warning/70 transition-all duration-300"
              title={`OS Reserve: ${formatMb(budget.os_reserve_ram_mb)}`}
            />
          )}
          {allocatedPct > 0 && (
            <div
              style={{ width: `${allocatedPct}%` }}
              className="bg-accent-primary transition-all duration-300"
              title={`Allocated to Running Servers: ${formatMb(budget.allocated_ram_mb)}`}
            />
          )}
          {availablePct > 0 && (
            <div
              style={{ width: `${availablePct}%` }}
              className="bg-status-success/55 transition-all duration-300"
              title={`Available: ${formatMb(budget.available_ram_mb)}`}
            />
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-text-muted">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-status-warning/70" />
            OS Reserve: {formatMb(budget.os_reserve_ram_mb)}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-accent-primary" />
            Allocated: {formatMb(budget.allocated_ram_mb)} ({budget.allocations.length})
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-status-success/75" />
            Available: {formatMb(budget.available_ram_mb)} / {formatMb(budget.allocatable_ram_mb)} max
          </span>
        </div>
      </div>

      {(exceedsAllocatableRam || exceedsAllocatableCpu) && (
        <div
          role="alert"
          className="rounded-lg border border-status-danger/40 bg-status-danger-bg px-3 py-2 text-xs text-status-danger"
        >
          {exceedsAllocatableRam
            ? `Requested ${formatMb(reqRam)} exceeds the ${formatMb(budget.allocatable_ram_mb)} host allocatable ceiling after OS reserve (${formatMb(budget.os_reserve_ram_mb)}).`
            : `Requested ${reqCpu} CPU cores exceeds the ${budget.allocatable_cpus} allocatable core limit.`}
        </div>
      )}

      {(exceedsAvailableRam || exceedsAvailableCpu) && (
        <div
          role="status"
          className="rounded-lg border border-status-warning/40 bg-status-warning-bg px-3 py-2 text-xs text-status-warning"
        >
          {exceedsAvailableRam
            ? `Requested ${formatMb(reqRam)} exceeds currently unallocated RAM (${formatMb(budget.available_ram_mb)} free). Stop another running server before starting.`
            : `Requested ${reqCpu} CPU cores exceeds currently free cores (${budget.available_cpus} free).`}
        </div>
      )}
    </div>
  );
}
