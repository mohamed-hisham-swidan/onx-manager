import { useMemo, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { TableSkeleton } from "@/components/Skeleton";
import {
  useCreateSchedule,
  useDeleteSchedule,
  useSchedulesList,
} from "@/server_manager/hooks/useBackups";
import { toast } from "@/stores/toastStore";
import { ApiError } from "@/services/api";
import { formatDateTime, formatRelativeTime } from "@/server_manager/utils/format";
import {
  BACKUP_SCOPES,
  SCHEDULE_PRESETS,
  describeCronExpression,
  getScopeMeta,
  getTierMeta,
  isBackupSchedule,
} from "./backupUtils";
import type { ServerResponse } from "@/server_manager/types";
import type { ScheduleResponse } from "@/types";

export interface BackupSchedulesTabProps {
  servers: ServerResponse[];
  serverMap: Map<string, string>;
  canManageSchedules: boolean;
  scopedServerId?: string;
}

function isForbiddenError(err: unknown): boolean {
  if (err instanceof ApiError && err.status === 403) return true;
  if (err instanceof Error && /\b403\b|forbidden|permission/i.test(err.message)) return true;
  return false;
}

export function BackupSchedulesTab({
  servers,
  serverMap,
  canManageSchedules,
  scopedServerId,
}: BackupSchedulesTabProps) {
  const schedulesQuery = useSchedulesList();
  const createSchedule = useCreateSchedule();
  const deleteSchedule = useDeleteSchedule();

  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ScheduleResponse | null>(null);

  const [selectedServerId, setSelectedServerId] = useState("");
  const [scheduleName, setScheduleName] = useState("");
  const [nameEdited, setNameEdited] = useState(false);
  const [presetId, setPresetId] = useState("daily_3am");
  const [customCron, setCustomCron] = useState("0 3 * * *");
  const [tier, setTier] = useState<"tier_1" | "tier_2">("tier_1");
  const [backupType, setBackupType] = useState("full");
  const [formError, setFormError] = useState<string | null>(null);

  const backupSchedules = useMemo(
    () =>
      (schedulesQuery.data ?? []).filter(
        (s) =>
          isBackupSchedule(s) &&
          (!scopedServerId || String(s.params?.server_id ?? "") === scopedServerId),
      ),
    [schedulesQuery.data, scopedServerId],
  );

  const openCreateModal = () => {
    const preferredServer = scopedServerId
      ? servers.find((s) => s.server_id === scopedServerId)
      : servers[0];
    const defaultSrv = preferredServer?.server_id ?? scopedServerId ?? "";
    const defaultName = preferredServer?.name
      ? `${preferredServer.name} Daily Backup`
      : "Automated Daily Backup";
    setSelectedServerId(defaultSrv);
    setScheduleName(defaultName);
    setNameEdited(false);
    setPresetId("daily_3am");
    setCustomCron("0 3 * * *");
    setTier("tier_1");
    setBackupType("full");
    setFormError(null);
    setCreateOpen(true);
  };

  const handleServerChange = (nextId: string) => {
    setSelectedServerId(nextId);
    if (!nameEdited) {
      const srvName = serverMap.get(nextId);
      setScheduleName(srvName ? `${srvName} Daily Backup` : "Automated Daily Backup");
    }
  };

  const activeCron =
    presetId === "custom"
      ? customCron.trim()
      : SCHEDULE_PRESETS.find((p) => p.id === presetId)?.cron ?? "0 3 * * *";

  const handleCreateSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFormError(null);
    if (!selectedServerId) {
      setFormError("Please select a target server.");
      return;
    }
    if (!activeCron) {
      setFormError("Please enter a valid 5-field cron expression.");
      return;
    }

    try {
      await createSchedule.mutateAsync({
        name: scheduleName.trim() || undefined,
        cron_expression: activeCron,
        task_name: "run_backup_task",
        params: {
          server_id: selectedServerId,
          backup_type: backupType,
          tier,
        },
        enabled: true,
      });
      toast("success", "Schedule created", "Automated backup schedule saved.");
      setCreateOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create schedule");
    }
  };

  const handleConfirmDelete = () => {
    if (!deleteTarget) return;
    deleteSchedule.mutate(deleteTarget.id, {
      onSuccess: () => {
        toast("success", "Schedule deleted", `Removed schedule "${deleteTarget.name}".`);
        setDeleteTarget(null);
      },
      onError: (err) => {
        toast("error", "Delete failed", err instanceof Error ? err.message : "Could not delete schedule");
        setDeleteTarget(null);
      },
    });
  };

  const readOnlyMode = !canManageSchedules || isForbiddenError(schedulesQuery.error);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-text-muted">
          Run automatic backups on a recurring schedule.
        </p>
        <button
          type="button"
          onClick={openCreateModal}
          disabled={readOnlyMode}
          title={readOnlyMode ? "Settings permission required to manage schedules" : undefined}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shadow-2xs"
        >
          <Icon name="plus" size={14} />
          <span>New Schedule</span>
        </button>
      </div>

      {readOnlyMode && (
        <div className="rounded-xl border border-status-info-border bg-status-info-bg/40 px-4 py-2.5 text-xs text-status-info flex items-center gap-2">
          <Icon name="lock" size={14} className="shrink-0" />
          <span>Read-only access: administrator permissions are required to create or delete backup schedules.</span>
        </div>
      )}

      {schedulesQuery.isLoading ? (
        <TableSkeleton rows={3} cols={6} />
      ) : schedulesQuery.error && !isForbiddenError(schedulesQuery.error) ? (
        <ErrorState
          message={
            schedulesQuery.error instanceof Error
              ? schedulesQuery.error.message
              : "Failed to load schedules"
          }
          onRetry={() => schedulesQuery.refetch()}
        />
      ) : backupSchedules.length === 0 ? (
        <EmptyState
          icon="clock"
          title="No backup schedules yet"
          description="Set up recurring snapshots or encrypted archives so your worlds stay protected automatically."
          action={
            !readOnlyMode ? (
              <button
                type="button"
                onClick={openCreateModal}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer shadow-2xs"
              >
                <Icon name="plus" size={14} />
                <span>Create First Schedule</span>
              </button>
            ) : undefined
          }
        />
      ) : (
        <>
          {/* Desktop Table */}
          <div className="hidden md:block overflow-hidden rounded-xl border border-border-subtle bg-surface-card shadow-2xs">
            <table className="w-full text-sm text-text-primary border-collapse">
              <thead>
                <tr className="border-b border-border-subtle bg-surface-muted/40 text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  <th className="px-4 py-3 text-left">Schedule</th>
                  <th className="px-4 py-3 text-left">Server</th>
                  <th className="px-4 py-3 text-left">Frequency</th>
                  <th className="px-4 py-3 text-left">Backup Type</th>
                  <th className="px-4 py-3 text-left">Last Run</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {backupSchedules.map((sched) => {
                  const params = sched.params ?? {};
                  const srvId = typeof params.server_id === "string" ? params.server_id : "";
                  const srvName = srvId ? serverMap.get(srvId) ?? "Deleted Server" : "All / Custom";
                  const schedTier = typeof params.tier === "string" ? params.tier : "tier_1";
                  const schedScope = typeof params.backup_type === "string" ? params.backup_type : "full";
                  const tierMeta = getTierMeta(schedTier);
                  const scopeMeta = getScopeMeta(schedScope);
                  return (
                    <tr key={sched.id} className="hover:bg-surface-hover/40 transition-colors">
                      <td className="px-4 py-3 font-semibold text-text-primary">{sched.name}</td>
                      <td className="px-4 py-3 text-text-secondary">{srvName}</td>
                      <td className="px-4 py-3">
                        <div className="text-xs font-medium text-text-primary">
                          {describeCronExpression(sched.cron_expression)}
                        </div>
                        <span className="inline-block mt-0.5 rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-text-muted">
                          {sched.cron_expression}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="rounded-full border border-border-subtle bg-surface-muted px-2.5 py-0.5 text-xs font-medium text-text-primary">
                            {tierMeta.label}
                          </span>
                          <span className="text-xs text-text-muted">{scopeMeta.shortLabel}</span>
                        </div>
                      </td>
                      <td
                        className="px-4 py-3 text-xs text-text-muted"
                        title={sched.last_run_at ? formatDateTime(sched.last_run_at) : undefined}
                      >
                        {sched.last_run_at ? formatRelativeTime(sched.last_run_at) || "just now" : "Never"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border ${
                            sched.enabled
                              ? "bg-status-success-bg text-status-success border-status-success-border"
                              : "bg-surface-elevated text-text-muted border-border-subtle"
                          }`}
                        >
                          {sched.enabled ? "Active" : "Paused"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => setDeleteTarget(sched)}
                          disabled={readOnlyMode}
                          aria-label={`Delete schedule ${sched.name}`}
                          title={readOnlyMode ? "Settings permission required" : "Delete schedule"}
                          className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-status-danger-bg hover:text-status-danger disabled:opacity-40 cursor-pointer"
                        >
                          <Icon name="trash" size={15} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile Cards */}
          <div className="md:hidden space-y-3">
            {backupSchedules.map((sched) => {
              const params = sched.params ?? {};
              const srvId = typeof params.server_id === "string" ? params.server_id : "";
              const srvName = srvId ? serverMap.get(srvId) ?? "Deleted Server" : "All / Custom";
              const schedTier = typeof params.tier === "string" ? params.tier : "tier_1";
              const schedScope = typeof params.backup_type === "string" ? params.backup_type : "full";
              const tierMeta = getTierMeta(schedTier);
              const scopeMeta = getScopeMeta(schedScope);
              return (
                <div
                  key={sched.id}
                  className="rounded-xl border border-border-subtle bg-surface-card p-4 space-y-2.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-semibold text-sm text-text-primary">{sched.name}</div>
                      <div className="text-xs text-text-muted">{srvName}</div>
                    </div>
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border ${
                        sched.enabled
                          ? "bg-status-success-bg text-status-success border-status-success-border"
                          : "bg-surface-elevated text-text-muted border-border-subtle"
                      }`}
                    >
                      {sched.enabled ? "Active" : "Paused"}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                    <span>{describeCronExpression(sched.cron_expression)}</span>
                    <span className="font-mono text-[11px] bg-surface-muted px-1.5 py-0.5 rounded">
                      {sched.cron_expression}
                    </span>
                    <span>·</span>
                    <span>{tierMeta.label}</span>
                    <span>·</span>
                    <span>{scopeMeta.shortLabel}</span>
                  </div>
                  <div className="flex items-center justify-between pt-2 border-t border-border-subtle text-xs text-text-muted">
                    <span>
                      Last run: {sched.last_run_at ? formatRelativeTime(sched.last_run_at) || "just now" : "Never"}
                    </span>
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(sched)}
                      disabled={readOnlyMode}
                      aria-label={`Delete schedule ${sched.name}`}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-status-danger hover:bg-status-danger-bg disabled:opacity-40 cursor-pointer"
                    >
                      <Icon name="trash" size={13} />
                      <span>Delete</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Create Schedule Modal */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New Backup Schedule"
        description="Automate recurring snapshots or encrypted archives."
        size="lg"
        closeOnEscape={!createSchedule.isPending}
        closeOnBackdrop={!createSchedule.isPending}
      >
        <form onSubmit={handleCreateSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="schedule-server"
                className="block text-xs font-medium text-text-secondary mb-1.5"
              >
                Target Server
              </label>
              <select
                id="schedule-server"
                aria-label="Target server"
                value={selectedServerId}
                onChange={(e) => handleServerChange(e.target.value)}
                disabled={createSchedule.isPending}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              >
                <option value="">Select a server...</option>
                {servers.map((s) => (
                  <option key={s.server_id} value={s.server_id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="schedule-name"
                className="block text-xs font-medium text-text-secondary mb-1.5"
              >
                Schedule Name
              </label>
              <input
                id="schedule-name"
                type="text"
                value={scheduleName}
                onChange={(e) => {
                  setNameEdited(true);
                  setScheduleName(e.target.value);
                }}
                placeholder="Survival Daily Backup"
                disabled={createSchedule.isPending}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              />
            </div>
          </div>

          <div className="space-y-2">
            <span className="block text-xs font-medium text-text-secondary">
              Frequency
            </span>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {SCHEDULE_PRESETS.map((preset) => {
                const selected = presetId === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => setPresetId(preset.id)}
                    className={`rounded-lg border px-3 py-2 text-left text-xs font-medium transition-colors cursor-pointer ${
                      selected
                        ? "border-accent-primary bg-accent-primary/10 text-text-primary"
                        : "border-border-subtle bg-surface-page text-text-secondary hover:bg-surface-hover"
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>
            {presetId === "custom" && (
              <div className="pt-1">
                <label
                  htmlFor="schedule-custom-cron"
                  className="block text-xs font-medium text-text-secondary mb-1"
                >
                  5-Field Cron Expression (minute hour day month weekday)
                </label>
                <input
                  id="schedule-custom-cron"
                  type="text"
                  value={customCron}
                  onChange={(e) => setCustomCron(e.target.value)}
                  placeholder="0 3 * * *"
                  className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 font-mono text-xs text-text-primary focus:border-border-focus focus:outline-hidden"
                />
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="schedule-tier"
                className="block text-xs font-medium text-text-secondary mb-1.5"
              >
                Backup Type
              </label>
              <select
                id="schedule-tier"
                value={tier}
                onChange={(e) => setTier(e.target.value as "tier_1" | "tier_2")}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-hidden"
              >
                <option value="tier_1">Quick Snapshot</option>
                <option value="tier_2">Encrypted Archive</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="schedule-scope"
                className="block text-xs font-medium text-text-secondary mb-1.5"
              >
                Scope
              </label>
              <select
                id="schedule-scope"
                value={backupType}
                onChange={(e) => setBackupType(e.target.value)}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-hidden"
              >
                {BACKUP_SCOPES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {formError && (
            <p role="alert" className="rounded-lg border border-status-danger-border bg-status-danger-bg/60 px-3 py-2 text-xs text-status-danger">
              {formError}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2 border-t border-border-subtle">
            <button
              type="button"
              onClick={() => setCreateOpen(false)}
              disabled={createSchedule.isPending}
              className="rounded-lg border border-border-default bg-surface-page px-3.5 py-2 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createSchedule.isPending}
              className="rounded-lg bg-accent-primary px-4 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer"
            >
              {createSchedule.isPending ? "Saving..." : "Save Schedule"}
            </button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete schedule?"
        description={
          deleteTarget
            ? `Stop automated backups for "${deleteTarget.name}"? Existing backups will not be deleted.`
            : undefined
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isPending={deleteSchedule.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
