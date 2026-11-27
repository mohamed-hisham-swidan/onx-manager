import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { useOperationStore } from "@/operations/stores/operationStore";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";

export interface UpgradePinnedBannerProps {
  serverId: string;
}

const TERMINAL_STATUSES = new Set(["confirmed", "rolled_back", "failed"]);
const ATTENTION_STATUSES = new Set([
  "blocked",
  "awaiting_manual_uploads",
  "needs_resolution",
]);

const STEP_TITLES: Record<string, string> = {
  PREPARE_AND_DOWNLOAD: "Preparing backup & artifacts",
  STAGE_FILES: "Staging server core & plugins",
  SWAP_LIVE_TREE: "Swapping live tree safely",
  HEALTH_GATE: "Health Gate",
  FINALIZE: "Finalizing",
};

function readDismissedOutcomeId(serverId: string): string | null {
  try {
    return window.sessionStorage.getItem(`onx.dismissedUpgradeOutcome.${serverId}`);
  } catch {
    return null;
  }
}

function writeDismissedOutcomeId(serverId: string, upgradeId: string): void {
  try {
    window.sessionStorage.setItem(`onx.dismissedUpgradeOutcome.${serverId}`, upgradeId);
  } catch {
    // ignore storage errors
  }
}

function describeNonPinnedStatus(status: string, upgradeBranch: string | null): string {
  switch (status) {
    case "applying":
      return "Applying version change behind backup + Health Gate safeguards…";
    case "blocked":
      return "Action needed: compatibility blockers must be resolved before testing or applying.";
    case "awaiting_manual_uploads":
      return "Action needed: manual download uploads are required before continuing.";
    case "needs_resolution":
      return "Action needed: merge conflicts must be resolved before test/apply.";
    case "staging":
      return "Test branch ready — start the container below to test, or apply directly.";
    case "testing":
      return upgradeBranch
        ? `Test container running on ${upgradeBranch} — inspect Console & Plugins, then Apply to Live or Discard.`
        : "Test container running — inspect Console & Plugins, then Apply to Live or Discard.";
    default:
      return "Version change plan is ready — resume to test on an isolated branch or apply live.";
  }
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
  const navigate = useNavigate();
  const branchCtx = useServerBranchContext();
  const queryClient = useQueryClient();
  const hasUpgradeApi = typeof api.listServerUpgrades === "function";

  const upgradesQuery = useQuery({
    queryKey: queryKeys.p55.upgrades(serverId),
    queryFn: async () => api.listServerUpgrades?.(serverId) ?? null,
    enabled: hasUpgradeApi && Boolean(serverId),
    refetchInterval: (query) =>
      query.state.data?.active_upgrade?.status === "applying" ? 2_000 : 60_000,
  });

  const [showRollbackConfirm, setShowRollbackConfirm] = useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);
  const [showApplyConfirm, setShowApplyConfirm] = useState(false);
  const [rollbackReason, setRollbackReason] = useState("operator emergency rollback");
  const [isConfirming, setIsConfirming] = useState(false);
  const [isRollingBack, setIsRollingBack] = useState(false);
  const [isApplyingLive, setIsApplyingLive] = useState(false);
  const [isDiscarding, setIsDiscarding] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [dismissedOutcomeId, setDismissedOutcomeId] = useState<string | null>(() =>
    readDismissedOutcomeId(serverId),
  );

  const data = upgradesQuery.data ?? null;
  const active = data?.active_upgrade ?? null;
  const applyingOpId =
    active?.status === "applying" ? (active.operation_id ?? null) : null;

  const liveOpQuery = useQuery({
    queryKey: ["p55", "banner-op", applyingOpId],
    queryFn: async () => api.getOperation(applyingOpId!),
    enabled: Boolean(applyingOpId) && typeof api.getOperation === "function",
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && ["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(status)) {
        return false;
      }
      return 1_500;
    },
    retry: false,
  });

  const liveOpStatus = liveOpQuery.data?.status;
  useEffect(() => {
    if (
      !applyingOpId ||
      !liveOpStatus ||
      !["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(liveOpStatus)
    ) {
      return;
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.p55.upgrades(serverId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.versioning.branches(serverId) });
  }, [applyingOpId, liveOpStatus, queryClient, serverId]);

  const latestItem = data?.items?.[0] ?? null;
  const recentOutcome =
    !active &&
    latestItem &&
    (latestItem.status === "rolled_back" || latestItem.status === "failed") &&
    dismissedOutcomeId !== latestItem.id
      ? latestItem
      : null;

  if (!hasUpgradeApi) {
    return null;
  }

  if (!active || TERMINAL_STATUSES.has(active.status)) {
    if (!recentOutcome) {
      return null;
    }
    const isRolledBack = recentOutcome.status === "rolled_back";
    const sourceDesc = recentOutcome.source_mc
      ? `${recentOutcome.source_loader_id ?? "server"} ${recentOutcome.source_mc}`.trim()
      : "its previous state";
    return (
      <div
        data-testid="upgrade-outcome-banner"
        className="mb-3 rounded-xl border border-status-danger-border bg-status-danger-bg p-4 shadow-xs"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-card text-status-danger border border-status-danger-border">
              <Icon name="alert" size={18} />
            </span>
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-bold text-text-primary">
                  {isRolledBack
                    ? `Change Version Rolled Back (Target MC ${recentOutcome.target_mc})`
                    : `Change Version Failed (Target MC ${recentOutcome.target_mc})`}
                </h3>
                <span className="inline-flex items-center rounded-full border border-status-danger-border bg-surface-card px-2 py-0.5 text-[10px] font-semibold text-status-danger">
                  {isRolledBack ? "Rolled Back Automatically" : "Version Change Failed"}
                </span>
              </div>
              <p className="text-xs text-text-secondary">
                {isRolledBack
                  ? `Your server was restored to ${sourceDesc} safely.`
                  : "No unverified version changes remain active."}
              </p>
              {recentOutcome.error_message && (
                <p className="font-mono text-[11px] text-status-danger break-words">
                  {recentOutcome.error_message}
                </p>
              )}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              type="button"
              data-testid="outcome-banner-dismiss-btn"
              size="sm"
              variant="ghost"
              onClick={() => {
                writeDismissedOutcomeId(serverId, recentOutcome.id);
                setDismissedOutcomeId(recentOutcome.id);
              }}
            >
              Dismiss
            </Button>
            <Button
              type="button"
              data-testid="outcome-banner-retry-btn"
              size="sm"
              variant="primary"
              icon="restart"
              onClick={() =>
                navigate(
                  `/servers/${serverId}/settings?tab=lifecycle&action=change-version`,
                )
              }
            >
              Try Again
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const isPinned = active.status === "active_pinned" && active.pinned_until_confirm;
  const overdue = data?.reminder_72h_overdue || active.reminder_72h_overdue;

  if (!isPinned) {
    const needsAttention = ATTENTION_STATUSES.has(active.status);
    const canApplyDirect =
      active.status === "staging" ||
      active.status === "testing" ||
      active.status === "ready";
    const onUpgradeBranch = Boolean(
      active.upgrade_branch && branchCtx?.branch === active.upgrade_branch,
    );

    async function handleBannerApplyLive() {
      if (!active || typeof api.applyServerUpgrade !== "function") return;
      setIsApplyingLive(true);
      setActionError(null);
      try {
        await api.applyServerUpgrade(serverId, active.id, {
          resolved_conflicts: {},
          async_mode: false,
        });
        if (onUpgradeBranch && branchCtx) {
          branchCtx.setBranch("main");
        }
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: queryKeys.p55.upgrades(serverId),
          }),
          queryClient.invalidateQueries({
            queryKey: queryKeys.versioning.branches(serverId),
          }),
          queryClient.invalidateQueries({
            queryKey: queryKeys.servers.detail(serverId),
          }),
        ]);
        setShowApplyConfirm(false);
        toast(
          "success",
          "Version change applied",
          `Live server is now running MC ${active.target_mc} (${active.target_loader_id}).`,
        );
      } catch (error) {
        setActionError(errorMessage(error));
      } finally {
        setIsApplyingLive(false);
      }
    }

    async function handleBannerDiscard() {
      if (!active) return;
      setIsDiscarding(true);
      setActionError(null);
      try {
        const targetBranch = active.upgrade_branch;
        if (targetBranch) {
          if (branchCtx?.branch === targetBranch) {
            branchCtx.setBranch("main");
          }
          if (typeof api.stopBranchRun === "function") {
            try {
              await api.stopBranchRun(serverId, targetBranch, {});
            } catch {
              // best-effort cleanup
            }
          }
          if (typeof api.destroyBranchRun === "function") {
            try {
              await api.destroyBranchRun(serverId, targetBranch, {});
            } catch {
              // best-effort cleanup
            }
          }
          if (typeof api.deleteServerBranch === "function") {
            try {
              await api.deleteServerBranch(serverId, targetBranch);
            } catch {
              // best-effort cleanup
            }
          }
        }
        if (typeof api.rollbackServerUpgrade === "function") {
          await api.rollbackServerUpgrade(serverId, active.id, {
            reason: "operator discarded upgrade plan",
          });
        }
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: queryKeys.p55.upgrades(serverId),
          }),
          queryClient.invalidateQueries({
            queryKey: queryKeys.versioning.branches(serverId),
          }),
        ]);
        setShowDiscardConfirm(false);
        toast(
          "success",
          "Upgrade plan discarded",
          targetBranch
            ? `Cleaned up branch "${targetBranch}" and abandoned the pending plan.`
            : "Abandoned the pending version change plan.",
        );
      } catch (error) {
        setActionError(errorMessage(error));
      } finally {
        setIsDiscarding(false);
      }
    }

    const opSteps = liveOpQuery.data?.steps ?? [];
    const currentStepId = liveOpQuery.data?.current_step_id ?? null;
    const currentStepIdx = currentStepId
      ? Math.max(
          1,
          opSteps.findIndex((s) => s.step_id === currentStepId) + 1,
        )
      : 1;
    const liveProgressSummary =
      active.status === "applying"
        ? `Applying MC ${active.target_mc}${
            currentStepId
              ? ` — Step ${currentStepIdx}/${Math.max(opSteps.length, 5)}: ${
                  STEP_TITLES[currentStepId] ?? currentStepId
                }…`
              : " — Preparing…"
          }`
        : describeNonPinnedStatus(active.status, active.upgrade_branch);

    return (
      <div
        data-testid="upgrade-pinned-banner"
        className={`mb-3 rounded-xl border p-4 shadow-xs ${
          needsAttention
            ? "border-status-warning-border bg-status-warning-bg"
            : "border-status-info-border bg-status-info-bg"
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <span
              className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                needsAttention
                  ? "bg-status-warning-bg text-status-warning"
                  : "bg-status-info-bg text-status-info"
              }`}
            >
              <Icon name={needsAttention ? "alert" : "restart"} size={18} />
            </span>
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-bold text-text-primary">
                  {active.status === "applying"
                    ? "Applying Version Change"
                    : "Change Version in Progress"}
                </h3>
                <span className="inline-flex items-center rounded-full border border-border-default bg-surface-card px-2 py-0.5 font-mono text-[10px] font-semibold text-text-secondary">
                  {active.status}
                </span>
              </div>
              <p className="text-xs text-text-secondary">
                Target{" "}
                <span className="font-mono font-semibold">
                  MC {active.target_mc} ({active.target_loader_id}{" "}
                  {active.target_loader_version})
                </span>
                . {liveProgressSummary}
              </p>
              {actionError && (
                <p
                  data-testid="banner-action-error"
                  className="text-xs font-medium text-status-danger"
                >
                  {actionError}
                </p>
              )}

              {showApplyConfirm && (
                <div className="mt-2 rounded-lg border border-border-default bg-surface-card p-3 space-y-2">
                  <p className="text-xs text-text-secondary">
                    Stop the live server, create a rollback backup, upgrade to MC {active.target_mc} ({active.target_loader_id}), and run startup checks?
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      data-testid="confirm-banner-apply-live-btn"
                      size="sm"
                      variant="primary"
                      icon="download"
                      loading={isApplyingLive}
                      onClick={() => void handleBannerApplyLive()}
                    >
                      Confirm Apply to Live
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={isApplyingLive}
                      onClick={() => setShowApplyConfirm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              {showDiscardConfirm && (
                <div className="mt-2 rounded-lg border border-status-danger-border bg-surface-card p-3 space-y-2">
                  <p className="text-xs text-text-secondary">
                    Abandon this version change plan
                    {active.upgrade_branch
                      ? ` and remove isolated branch "${active.upgrade_branch}"`
                      : ""}
                    ? Live <span className="font-mono">main</span> will not be modified.
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      data-testid="confirm-discard-upgrade-btn"
                      size="sm"
                      variant="danger"
                      icon="x"
                      loading={isDiscarding}
                      onClick={() => void handleBannerDiscard()}
                    >
                      Confirm Discard
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={isDiscarding}
                      onClick={() => setShowDiscardConfirm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 shrink-0">
            {active.status === "applying" && active.operation_id && (
              <Button
                type="button"
                data-testid="banner-view-progress-btn"
                size="sm"
                variant="secondary"
                icon="activity"
                onClick={() =>
                  useOperationStore.getState().openDrawer(active.operation_id!)
                }
              >
                View Progress
              </Button>
            )}
            {active.upgrade_branch && branchCtx && (
              onUpgradeBranch ? (
                <Button
                  type="button"
                  data-testid="banner-back-to-main-btn"
                  size="sm"
                  variant="secondary"
                  icon="chevron-left"
                  onClick={() => branchCtx.setBranch("main")}
                >
                  Back to main
                </Button>
              ) : (
                <Button
                  type="button"
                  data-testid="banner-switch-branch-btn"
                  size="sm"
                  variant="secondary"
                  icon="server"
                  onClick={() => branchCtx.setBranch(active.upgrade_branch!)}
                >
                  Switch to {active.upgrade_branch}
                </Button>
              )
            )}
            {canApplyDirect && (
              <Button
                type="button"
                data-testid="banner-apply-live-btn"
                size="sm"
                variant="primary"
                icon="download"
                disabled={isApplyingLive || isDiscarding}
                onClick={() => {
                  setShowDiscardConfirm(false);
                  setShowApplyConfirm(true);
                }}
              >
                Apply to Live
              </Button>
            )}
            <Button
              type="button"
              data-testid="banner-resume-upgrade-btn"
              size="sm"
              variant={canApplyDirect ? "secondary" : "primary"}
              icon="restart"
              onClick={() =>
                navigate(
                  `/servers/${serverId}/settings?tab=lifecycle&action=change-version`,
                )
              }
            >
              Resume
            </Button>
            <Button
              type="button"
              data-testid="banner-discard-upgrade-btn"
              size="sm"
              variant="danger"
              icon="x"
              disabled={isApplyingLive || isDiscarding}
              onClick={() => {
                setShowApplyConfirm(false);
                setShowDiscardConfirm(true);
              }}
            >
              Discard
            </Button>
          </div>
        </div>
      </div>
    );
  }

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
        "Server files, configs, and the pre-upgrade world backup were restored.",
      );
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setIsRollingBack(false);
    }
  }

  const healthWarnings = active.matrix?.health_gate_warnings ?? [];
  const healthChecks = active.matrix?.health_gate_checks ?? [];
  const hasHealthWarning =
    healthWarnings.length > 0 ||
    healthChecks.some((c) => c.status === "warned");

  return (
    <div
      data-testid="upgrade-pinned-banner"
      className={`mb-3 rounded-xl border p-4 shadow-xs ${
        overdue || hasHealthWarning
          ? "border-status-warning-border bg-status-warning-bg"
          : "border-status-info-border bg-status-info-bg"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span
            className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
              overdue || hasHealthWarning
                ? "bg-status-warning-bg text-status-warning"
                : "bg-status-info-bg text-status-info"
            }`}
          >
            <Icon name={hasHealthWarning ? "alert" : "backup"} size={18} />
          </span>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold text-text-primary">
                Upgrade Active — Pre-Upgrade Rollback Snapshot is Pinned
              </h3>
              <span className="inline-flex items-center rounded-full border border-border-default bg-surface-card px-2 py-0.5 text-[10px] font-semibold text-text-secondary">
                Waiting for Confirmation
              </span>
              {hasHealthWarning && (
                <span
                  data-testid="banner-network-warning-pill"
                  className="inline-flex items-center rounded-full border border-status-warning-border bg-surface-card px-2 py-0.5 text-[10px] font-semibold text-status-warning"
                >
                  Public Network Warning
                </span>
              )}
            </div>
            <p className="text-xs text-text-secondary">
              Target{" "}
              <span className="font-mono font-semibold">
                MC {active.target_mc} ({active.target_loader_id}{" "}
                {active.target_loader_version})
              </span>
              {" · "}pre-upgrade backup{" "}
              <span className="font-mono">{active.pre_upgrade_backup_id ?? "pinned"}</span>
              {" · "}live data snapshot{" "}
              <span className="font-mono">{active.class_c_snapshot_id ?? "pinned"}</span>
            </p>
            {healthWarnings.length > 0 && (
              <div
                data-testid="banner-health-warning"
                className="rounded-lg border border-status-warning-border bg-surface-card px-2.5 py-1.5 text-xs text-status-warning"
              >
                {healthWarnings.map((warning, idx) => (
                  <p key={idx} className="break-words">
                    {warning}
                  </p>
                ))}
              </div>
            )}
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
                  Server files, configs, and the pre-upgrade world backup will be restored. Active player sessions will be interrupted.
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
            Confirm &amp; Keep MC {active.target_mc}
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
            Rollback to {active.source_mc || "Pre-Upgrade"}
          </Button>
        </div>
      </div>
    </div>
  );
}
