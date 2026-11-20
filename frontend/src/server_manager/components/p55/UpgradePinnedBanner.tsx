import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";

export interface UpgradePinnedBannerProps {
  serverId: string;
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : "Action failed";
}

export function UpgradePinnedBanner({ serverId }: UpgradePinnedBannerProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const hasUpgradeApi = typeof api.listServerUpgrades === "function";

  const upgradesQuery = useQuery({
    queryKey: queryKeys.p55.upgrades(serverId),
    queryFn: async () => api.listServerUpgrades?.(serverId) ?? null,
    enabled: hasUpgradeApi && Boolean(serverId),
    refetchInterval: 60_000,
  });

  const [showRollbackConfirm, setShowRollbackConfirm] = useState(false);
  const [rollbackReason, setRollbackReason] = useState("operator emergency rollback");
  const [isConfirming, setIsConfirming] = useState(false);
  const [isRollingBack, setIsRollingBack] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const data = upgradesQuery.data ?? null;
  const active = data?.active_upgrade ?? null;

  if (!hasUpgradeApi || !data?.banner_active || !active) {
    return null;
  }

  const overdue = data.reminder_72h_overdue || active.reminder_72h_overdue;

  async function handleConfirm() {
    if (typeof api.confirmServerUpgrade !== "function") return;
    setIsConfirming(true);
    setActionError(null);
    try {
      await api.confirmServerUpgrade(serverId, active!.id);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.p55.upgrades(serverId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.servers.detail(serverId),
      });
      toast(
        "success",
        "Upgrade confirmed",
        "The pinned pre-upgrade rollback backup was released.",
      );
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setIsConfirming(false);
    }
  }

  async function handleRollback() {
    if (typeof api.rollbackServerUpgrade !== "function") return;
    setIsRollingBack(true);
    setActionError(null);
    try {
      await api.rollbackServerUpgrade(serverId, active!.id, {
        reason: rollbackReason.trim() || "operator emergency rollback",
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.p55.upgrades(serverId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.servers.detail(serverId),
      });
      setShowRollbackConfirm(false);
      toast(
        "success",
        "Emergency rollback complete",
        "The pre-upgrade world and Class-C snapshot were restored.",
      );
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setIsRollingBack(false);
    }
  }

  return (
    <div
      data-testid="upgrade-pinned-banner"
      className={`mb-3 rounded-xl border p-4 shadow-xs ${
        overdue
          ? "border-status-warning-border bg-status-warning-bg"
          : "border-status-info-border bg-status-info-bg"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span
            className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
              overdue
                ? "bg-status-warning-bg text-status-warning"
                : "bg-status-info-bg text-status-info"
            }`}
          >
            <Icon name="backup" size={18} />
          </span>
          <div className="min-w-0 space-y-1">
            <h3 className="text-sm font-bold text-text-primary">
              Upgrade Active — Pre-Upgrade Rollback Snapshot is Pinned
            </h3>
            <p className="text-xs text-text-secondary">
              Target{" "}
              <span className="font-mono font-semibold">
                MC {active.target_mc} ({active.target_loader_id}{" "}
                {active.target_loader_version})
              </span>
              {" · "}pre-upgrade backup{" "}
              <span className="font-mono">{active.pre_upgrade_backup_id ?? "pinned"}</span>
              {" · "}Class-C snapshot{" "}
              <span className="font-mono">{active.class_c_snapshot_id ?? "pinned"}</span>
            </p>
            {overdue && (
              <div
                data-testid="upgrade-72h-overdue-badge"
                className="inline-flex items-center gap-1.5 rounded-md border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[11px] font-semibold text-status-warning"
              >
                <Icon name="alert" size={12} />
                Pinned &gt; 72h — Confirm upgrade to release disk space or rollback if
                dimension migration issues occurred
              </div>
            )}
            {actionError && (
              <p className="text-xs font-medium text-status-danger">{actionError}</p>
            )}

            {showRollbackConfirm && (
              <div className="mt-2 rounded-lg border border-status-danger-border bg-surface-card p-3 space-y-2">
                <p className="text-xs text-text-secondary">
                  Live Class A/B files, the Class-C vault snapshot, and the pre-upgrade
                  world backup will be restored atomically. Active player sessions will
                  be interrupted.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <label htmlFor="rollback-reason" className="sr-only">
                    Rollback reason
                  </label>
                  <input
                    id="rollback-reason"
                    value={rollbackReason}
                    onChange={(event) => setRollbackReason(event.target.value)}
                    className="w-64 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary focus:border-accent-primary focus:outline-none"
                  />
                  <Button
                    type="button"
                    data-testid="confirm-emergency-rollback-btn"
                    size="sm"
                    variant="danger"
                    icon="restart"
                    loading={isRollingBack}
                    onClick={handleRollback}
                  >
                    Confirm Emergency Rollback
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setShowRollbackConfirm(false)}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button
            type="button"
            data-testid="banner-confirm-upgrade-btn"
            size="sm"
            variant="primary"
            icon="check"
            loading={isConfirming}
            onClick={handleConfirm}
          >
            Confirm Upgrade &amp; Unpin Rollback Backup
          </Button>
          <Button
            type="button"
            data-testid="banner-emergency-rollback-btn"
            size="sm"
            variant="danger"
            icon="restart"
            disabled={isRollingBack}
            onClick={() => setShowRollbackConfirm(true)}
          >
            Emergency Rollback to Pre-Upgrade World
          </Button>
        </div>
      </div>
    </div>
  );
}
