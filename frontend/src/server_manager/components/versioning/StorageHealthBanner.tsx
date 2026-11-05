import { Icon } from "@/components/ui/Icon";
import type { PreflightStatus } from "@/server_manager/types";

interface StorageHealthBannerProps {
  preflight: PreflightStatus | null;
}

export function StorageHealthBanner({ preflight }: StorageHealthBannerProps) {
  const isReflink = preflight?.reflink_supported;

  return (
    <div className="rounded-xl border border-border-default bg-surface-card p-4 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-lg ${
              isReflink
                ? "bg-status-success-bg text-status-success"
                : "bg-status-warning-bg text-status-warning"
            }`}
          >
            <Icon name={isReflink ? "check" : "alert"} size={20} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-text-primary">
                Storage Copy-On-Write Capability
              </h3>
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  isReflink
                    ? "bg-status-success-bg text-status-success border border-status-success/30"
                    : "bg-status-warning-bg text-status-warning border border-status-warning/30"
                }`}
              >
                {isReflink ? "Active (Reflink / Btrfs / ZFS)" : "Reflink Not Supported"}
              </span>
            </div>
            <p className="text-xs text-text-muted mt-0.5">
              {isReflink
                ? "Instant world snapshots enabled via zero-copy reflink cloning."
                : "Filesystem does not support reflink block cloning. Testing requires COW storage."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs">
          <div className="text-right">
            <span className="text-text-muted block">Available Host Headroom</span>
            <span className="font-semibold text-text-primary">
              {preflight
                ? `${preflight.available_ram_mb} MB RAM • ${preflight.available_cores} Cores`
                : "Checking..."}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
