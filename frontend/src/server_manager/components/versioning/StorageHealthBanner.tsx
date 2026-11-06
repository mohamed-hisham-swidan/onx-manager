import { Icon } from "@/components/ui/Icon";
import type { PreflightStatus } from "@/server_manager/types";

interface StorageHealthBannerProps {
  preflight: PreflightStatus | null;
}

export function StorageHealthBanner({ preflight }: StorageHealthBannerProps) {
  const isReflink = preflight?.reflink_supported;

  const ramMb = preflight?.available_ram_mb ?? 0;
  const cores = preflight?.available_cores ?? 0;
  // Visual headroom ratio
  const ramRatio = Math.min(100, Math.max(10, Math.round((ramMb / 16384) * 100)));
  const coreRatio = Math.min(100, Math.max(10, Math.round((cores / 16) * 100)));

  return (
    <div
      className={`rounded-xl border p-4.5 transition-all shadow-2xs ${
        isReflink
          ? "border-status-success-border/40 bg-status-success-bg/10"
          : "border-status-warning-border/40 bg-status-warning-bg/10"
      }`}
    >
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Left: Engine Status */}
        <div className="flex items-center gap-3.5">
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border transition-all ${
              isReflink
                ? "border-status-success/30 bg-status-success-bg text-status-success ring-2 ring-status-success/20 ring-offset-2 ring-offset-surface-card"
                : "border-status-warning/30 bg-status-warning-bg text-status-warning"
            }`}
          >
            <Icon name={isReflink ? "check" : "alert"} size={22} />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold tracking-tight text-text-primary">
                Storage Copy-On-Write Capability
              </h3>
              <span
                className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold tracking-wide ${
                  isReflink
                    ? "bg-status-success-bg text-status-success border border-status-success-border"
                    : "bg-status-warning-bg text-status-warning border border-status-warning-border"
                }`}
              >
                {isReflink ? "Active (Reflink / Btrfs / ZFS)" : "Reflink Not Supported"}
              </span>
            </div>
            <p className="text-xs text-text-muted mt-1 leading-relaxed">
              {isReflink
                ? "Hardware-accelerated instant world snapshots via filesystem block reflink zero-copy cloning."
                : "Filesystem does not support reflink block cloning. Testing requires COW storage."}
            </p>
          </div>
        </div>

        {/* Right: Host Headroom Meter with Micro-Bars */}
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border-subtle bg-surface-elevated/70 px-4 py-2 text-xs">
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted block">
              Available Host Headroom
            </span>
            <span className="font-mono text-xs font-semibold tabular-nums text-text-primary">
              {preflight ? `${ramMb} MB RAM • ${cores} Cores` : "Checking..."}
            </span>
          </div>

          {preflight && (
            <div className="hidden sm:flex items-center gap-3 border-l border-border-subtle pl-4">
              <div className="space-y-1">
                <div className="flex items-center justify-between text-[10px] text-text-muted font-mono">
                  <span>RAM</span>
                  <span>{ramRatio}%</span>
                </div>
                <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-muted">
                  <div
                    className="h-full rounded-full bg-status-success transition-all duration-300"
                    style={{ width: `${ramRatio}%` }}
                  />
                </div>
              </div>

              <div className="space-y-1">
                <div className="flex items-center justify-between text-[10px] text-text-muted font-mono">
                  <span>CPU</span>
                  <span>{coreRatio}%</span>
                </div>
                <div className="h-1.5 w-16 overflow-hidden rounded-full bg-accent-primary transition-all duration-300"
                  style={{ width: `${coreRatio}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
