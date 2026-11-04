import type { IconName } from "@/components/ui/Icon";
import { Icon } from "@/components/ui/Icon";
import { STATUS_MAP } from "@/server_manager/types";
import { Link } from "react-router-dom";

interface StatusOverviewCardsProps {
  counts: Record<string, number>;
}

const STATUS_ORDER = [
  "running",
  "stopped",
  "starting",
  "stopping",
  "crashed",
  "broken",
  "provisioning",
  "created",
  "restoring",
];

const STATUS_ICONS: Record<string, IconName> = {
  running: "activity",
  stopped: "stop",
  starting: "restart",
  stopping: "restart",
  crashed: "alert",
  broken: "alert",
  provisioning: "server",
  created: "server",
  restoring: "backup",
};

export function StatusOverviewCards({ counts }: StatusOverviewCardsProps) {
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);

  return (
    <div className="rounded-2xl border border-border-subtle bg-surface-card p-4 shadow-2xs">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="activity" size={16} className="text-accent-primary" />
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
            Fleet Overview
          </h2>
        </div>
        <span className="text-xs text-text-muted">
          {total} total server{total === 1 ? "" : "s"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {STATUS_ORDER.map((status) => {
          const config = STATUS_MAP[status];
          if (!config) return null;
          const count = counts[status] ?? 0;
          const hasCount = count > 0;
          const isCritical = (status === "crashed" || status === "broken") && hasCount;

          return (
            <Link
              key={status}
              to="/servers"
              className={`group flex items-center gap-2.5 rounded-xl border p-2.5 transition-all hover:bg-surface-hover ${
                isCritical
                  ? "border-status-danger-border bg-status-danger-bg/40 text-status-danger font-medium shadow-2xs"
                  : hasCount
                  ? "border-border-default bg-surface-muted/30 text-text-primary"
                  : "border-border-subtle/70 bg-transparent text-text-muted opacity-70 hover:opacity-100"
              }`}
            >
              <div
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                  isCritical
                    ? "bg-status-danger/20 text-status-danger"
                    : hasCount
                    ? "bg-accent-primary/10 text-accent-primary"
                    : "bg-surface-muted text-text-muted"
                }`}
              >
                <Icon name={STATUS_ICONS[status] ?? "server"} size={16} />
              </div>
              <div className="min-w-0">
                <p className="text-lg font-bold leading-none text-text-primary">
                  {count}
                </p>
                <p className="mt-0.5 truncate text-[11px] font-medium text-text-secondary">
                  {config.label}
                </p>
              </div>
            </Link>
          );
        })}

        {/* Total Summary */}
        <Link
          to="/servers"
          className="group flex items-center gap-2.5 rounded-xl border border-dashed border-border-default bg-surface-muted/20 p-2.5 transition-all hover:bg-surface-hover hover:border-accent-primary"
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-text-secondary">
            <Icon name="server" size={16} />
          </div>
          <div className="min-w-0">
            <p className="text-lg font-bold leading-none text-text-primary">
              {total}
            </p>
            <p className="mt-0.5 truncate text-[11px] font-medium text-text-secondary">
              Total
            </p>
          </div>
        </Link>
      </div>
    </div>
  );
}
