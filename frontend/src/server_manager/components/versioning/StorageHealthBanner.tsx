import type { PreflightStatus } from "@/server_manager/types";

interface StorageHealthBannerProps {
  preflight: PreflightStatus | null;
}

export function StorageHealthBanner({ preflight }: StorageHealthBannerProps) {
  if (!preflight) {
    return (
      <div
        className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted border border-border-subtle px-2.5 py-0.5 text-xs text-text-muted"
        title="Checking filesystem capabilities..."
      >
        <span className="h-1.5 w-1.5 rounded-full bg-text-muted animate-pulse" />
        <span>Instant storage cloning: checking...</span>
      </div>
    );
  }

  const isReflink = Boolean(preflight.reflink_supported);

  const tooltipText = isReflink
    ? `copy-on-write / Btrfs / ZFS reflink block cloning supported • ${preflight.available_ram_mb} MB RAM • ${preflight.available_cores} Cores`
    : `Filesystem does not support copy-on-write / Btrfs / ZFS reflink block cloning. Testing requires COW storage.`;

  return (
    <div
      title={tooltipText}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs cursor-help ${
        isReflink
          ? "bg-surface-muted text-text-secondary border border-border-subtle"
          : "bg-status-warning-bg text-status-warning border border-status-warning-border font-semibold"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          isReflink ? "bg-status-success" : "bg-status-warning"
        }`}
      />
      <span>
        Instant storage cloning: {isReflink ? "available" : "unavailable"}
      </span>
    </div>
  );
}
