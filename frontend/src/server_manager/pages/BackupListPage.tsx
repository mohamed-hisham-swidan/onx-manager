import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import * as backupHooks from "@/server_manager/hooks/useBackups";
import {
  useBackupsList,
  useDeleteBackup,
  useRestoreBackup,
  useVerifyBackup,
} from "@/server_manager/hooks/useBackups";
import { useServersList } from "@/server_manager/hooks/useServers";
import { Icon } from "@/components/ui/Icon";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/Skeleton";
import { HashBadge } from "@/components/ui/HashBadge";
import { toast } from "@/stores/toastStore";
import { formatBytes, formatDateTime, formatRelativeTime } from "@/server_manager/utils/format";
import { BackupStatsStrip } from "@/server_manager/components/backups/BackupStatsStrip";
import { CreateBackupModal } from "@/server_manager/components/backups/CreateBackupModal";
import { BackupDetailsDrawer } from "@/server_manager/components/backups/BackupDetailsDrawer";
import { SecretVaultBridgeModal } from "@/server_manager/components/backups/SecretVaultBridgeModal";
import { BackupSchedulesTab } from "@/server_manager/components/backups/BackupSchedulesTab";
import {
  formatShortDateTime,
  getScopeMeta,
  getStatusMeta,
  getTierMeta,
  isBackupSchedule,
  resolveBackupServer,
  useBackupPermissions,
} from "@/server_manager/components/backups/backupUtils";
import type { BackupResponse, ScheduleResponse, VerifyBackupResponse } from "@/types";

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "completed", label: "Completed" },
  { value: "in_progress", label: "In Progress" },
  { value: "pending", label: "Pending" },
  { value: "failed", label: "Failed" },
  { value: "failed_timeout", label: "Timed Out" },
];

const TIER_OPTIONS: Array<{ value: "all" | "tier_1" | "tier_2"; label: string }> = [
  { value: "all", label: "All types" },
  { value: "tier_1", label: "Quick Snapshot" },
  { value: "tier_2", label: "Encrypted Archive" },
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function restoreDescription(backup: BackupResponse): string {
  if (backup.tier === "tier_2") {
    return "Replaces current server files with this verified backup.";
  }
  return "Replaces current server files with this verified backup.";
}

function useSafeSchedulesCount(scopedServerId?: string): number {
  const fn = (backupHooks as Record<string, unknown>).useSchedulesList;
  const hook =
    typeof fn === "function"
      ? (fn as () => { data?: ScheduleResponse[] })
      : () => ({ data: undefined });
  const schedules = hook()?.data ?? [];
  return schedules.filter(
    (s) =>
      isBackupSchedule(s) &&
      s.enabled &&
      (!scopedServerId || String(s.params?.server_id ?? "") === scopedServerId),
  ).length;
}

export function BackupListPage() {
  const navigate = useNavigate();
  const { serverId: routeServerId } = useParams<{ serverId: string }>();
  const isServerScoped = Boolean(routeServerId);
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") === "schedules" ? "schedules" : "list";
  const deepLinkedServerId = searchParams.get("server_id") ?? searchParams.get("server");

  const backupsQuery = useBackupsList();
  const serversQuery = useServersList();
  const rawBackups = backupsQuery.data;
  const backups = useMemo(
    () =>
      rawBackups && routeServerId
        ? rawBackups.filter((b) => b.server_id === routeServerId)
        : rawBackups,
    [rawBackups, routeServerId],
  );
  const servers = serversQuery.data;
  const serversResolved = servers !== undefined;

  const restoreBackup = useRestoreBackup();
  const verifyBackup = useVerifyBackup();
  const deleteBackup = useDeleteBackup();
  const { canCreate, canRestore, canDelete, canManageSchedules } = useBackupPermissions();

  const [showCreate, setShowCreate] = useState(false);
  const [vaultOpen, setVaultOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const serverFilter = routeServerId ?? deepLinkedServerId ?? "all";
  const scopedFilterServerId =
    serverFilter !== "all" && serverFilter !== "deleted" ? serverFilter : undefined;
  const activeSchedulesCount = useSafeSchedulesCount(scopedFilterServerId);
  const [statusFilter, setStatusFilter] = useState("all");
  const [tierFilter, setTierFilter] = useState("all");
  const [deleteTarget, setDeleteTarget] = useState<BackupResponse | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<BackupResponse | null>(null);
  const [drawerBackup, setDrawerBackup] = useState<BackupResponse | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [verifyResults, setVerifyResults] = useState<Record<string, VerifyBackupResponse>>({});

  const serverList = useMemo(() => servers ?? [], [servers]);
  const serverMap = useMemo(
    () => new Map(serverList.map((s) => [s.server_id, s.name])),
    [serverList],
  );
  const serverObjMap = useMemo(
    () => new Map(serverList.map((s) => [s.server_id, s])),
    [serverList],
  );

  const hasDeletedServerBackups = useMemo(() => {
    if (!backups || !serversResolved) return false;
    return backups.some(
      (b) => b.server_deleted || (!serverMap.has(b.server_id) && !b.server_name),
    );
  }, [backups, serversResolved, serverMap]);

  const hasActiveFilters = Boolean(
    searchQuery.trim() ||
      (!isServerScoped && serverFilter !== "all") ||
      statusFilter !== "all" ||
      tierFilter !== "all",
  );

  const serverScopedBackups = useMemo(() => {
    if (!backups) return backups;
    if (serverFilter === "all") return backups;
    if (serverFilter === "deleted") {
      return backups.filter(
        (b) => resolveBackupServer(b, serverMap, serversResolved).deleted,
      );
    }
    return backups.filter((b) => b.server_id === serverFilter);
  }, [backups, serverFilter, serverMap, serversResolved]);

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return (serverScopedBackups ?? []).filter((b) => {
      const resolved = resolveBackupServer(b, serverMap, serversResolved);

      if (statusFilter !== "all") {
        if (statusFilter === "in_progress") {
          if (b.status !== "in_progress" && b.status !== "running") return false;
        } else if (b.status !== statusFilter) {
          return false;
        }
      }

      if (tierFilter !== "all" && b.tier !== tierFilter) {
        return false;
      }

      if (q) {
        const haystack = [
          resolved.name,
          b.backup_id,
          b.backup_type,
          b.error_message,
          getTierMeta(b.tier).label,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }

      return true;
    });
  }, [serverScopedBackups, statusFilter, tierFilter, searchQuery, serverMap, serversResolved]);

  function handleTabChange(nextTab: "list" | "schedules") {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (nextTab === "list") {
          next.delete("tab");
        } else {
          next.set("tab", nextTab);
        }
        return next;
      },
      { replace: true },
    );
  }

  function handleServerFilterChange(nextServer: string) {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("server");
        if (nextServer === "all") {
          next.delete("server_id");
        } else {
          next.set("server_id", nextServer);
        }
        return next;
      },
      { replace: true },
    );
  }

  function clearAllFilters() {
    setSearchQuery("");
    setStatusFilter("all");
    setTierFilter("all");
    if (!isServerScoped) {
      handleServerFilterChange("all");
    }
  }

  function handleFilterFailed() {
    const hasPlainFailed = (serverScopedBackups ?? []).some((b) => b.status === "failed");
    setStatusFilter(hasPlainFailed ? "failed" : "failed_timeout");
  }

  function handleConfirmRestore() {
    if (!restoreTarget) return;
    restoreBackup.mutate(restoreTarget.backup_id, {
      onSuccess: (result) => {
        const deferred = Boolean((result as Record<string, unknown> | null)?.deferred);
        if (deferred) {
          toast(
            "info",
            "Restore Scheduled",
            "Server is active. Restore will execute once the server is stopped.",
          );
        } else {
          toast("success", "Restore Started", "Restoring server data from backup.");
        }
      },
      onError: (err) => toast("error", "Restore failed", errorMessage(err)),
      onSettled: () => setRestoreTarget(null),
    });
  }

  async function handleVerify(backup: BackupResponse) {
    setVerifyingId(backup.backup_id);
    try {
      const result = await verifyBackup.mutateAsync(backup.backup_id);
      setVerifyResults((prev) => ({ ...prev, [backup.backup_id]: result }));
      toast(
        result.valid ? "success" : "error",
        result.valid ? "Backup verified" : "Backup integrity failed",
        result.artifact_error ?? undefined,
      );
    } catch (err) {
      toast("error", "Verification failed", errorMessage(err));
    } finally {
      setVerifyingId(null);
    }
  }

  function handleConfirmDelete() {
    if (!deleteTarget) return;
    deleteBackup.mutate(deleteTarget.backup_id, {
      onSuccess: () => {
        toast("success", "Backup deleted", "The backup was removed.");
        if (drawerBackup?.backup_id === deleteTarget.backup_id) {
          setDrawerBackup(null);
        }
      },
      onError: (err) => toast("error", "Delete failed", errorMessage(err)),
      onSettled: () => setDeleteTarget(null),
    });
  }

  const restoreTargetServer = restoreTarget
    ? serverObjMap.get(restoreTarget.server_id)
    : undefined;
  const restoreTargetRunning =
    restoreTargetServer?.status === "running" || restoreTargetServer?.status === "starting";

  return (
    <div
      className={
        isServerScoped
          ? "space-y-6"
          : "mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-6 space-y-6"
      }
    >
      {/* Header Row */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-text-primary">
            Backups
          </h1>
          <p className="mt-1 text-sm text-text-muted">
            Snapshots, encrypted archives, and automated backup schedules.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => {
              if (
                scopedFilterServerId &&
                serverObjMap.get(scopedFilterServerId)?.mode === "advanced"
              ) {
                navigate(`/servers/${scopedFilterServerId}/versioning?openVault=true`);
                return;
              }
              setVaultOpen(true);
            }}
            aria-label="Secret Vault"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3.5 py-2 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer shadow-2xs"
          >
            <Icon name="lock" size={14} />
            <span>Secret Vault</span>
          </button>

          <button
            type="button"
            onClick={() => setShowCreate(true)}
            disabled={!canCreate}
            title={!canCreate ? "You do not have permission to create backups" : undefined}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed shadow-2xs transition-colors cursor-pointer"
          >
            <Icon name="plus" size={14} />
            <span>New Backup</span>
          </button>
        </div>
      </div>

      {/* Underline Tab Bar */}
      <div
        role="tablist"
        aria-label="Backups sections"
        className="flex items-center gap-6 border-b border-border-subtle"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "list"}
          onClick={() => handleTabChange("list")}
          className={`relative pb-3 text-sm font-medium transition-colors cursor-pointer inline-flex items-center gap-2 ${
            activeTab === "list"
              ? "text-text-primary font-semibold"
              : "text-text-muted hover:text-text-primary"
          }`}
        >
          <span>Backups</span>
          {serverScopedBackups && (
            <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-mono tabular-nums text-text-secondary">
              {serverScopedBackups.length}
            </span>
          )}
          {activeTab === "list" && (
            <span
              aria-hidden="true"
              className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-accent-primary"
            />
          )}
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "schedules"}
          onClick={() => handleTabChange("schedules")}
          className={`relative pb-3 text-sm font-medium transition-colors cursor-pointer inline-flex items-center gap-2 ${
            activeTab === "schedules"
              ? "text-text-primary font-semibold"
              : "text-text-muted hover:text-text-primary"
          }`}
        >
          <span>Schedules</span>
          <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-mono tabular-nums text-text-secondary">
            {activeSchedulesCount}
          </span>
          {activeTab === "schedules" && (
            <span
              aria-hidden="true"
              className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-accent-primary"
            />
          )}
        </button>
      </div>

      {activeTab === "schedules" ? (
        <BackupSchedulesTab
          servers={serverList}
          serverMap={serverMap}
          canManageSchedules={canManageSchedules}
          scopedServerId={scopedFilterServerId}
        />
      ) : backupsQuery.isLoading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : backupsQuery.error ? (
        <ErrorState
          message={
            backupsQuery.error instanceof Error
              ? backupsQuery.error.message
              : "Failed to load backups"
          }
          onRetry={() => {
            backupsQuery.refetch?.();
            serversQuery.refetch?.();
          }}
        />
      ) : backups && backups.length === 0 ? (
        <EmptyState
          icon="backup"
          title="No backups yet"
          description="Create your first quick snapshot or encrypted archive to protect your worlds."
          action={
            canCreate ? (
              <button
                type="button"
                onClick={() => setShowCreate(true)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-xs font-semibold text-accent-contrast-text transition-colors hover:bg-accent-hover shadow-2xs cursor-pointer"
              >
                <Icon name="plus" size={14} />
                <span>New Backup</span>
              </button>
            ) : undefined
          }
        />
      ) : (
        <>
          <BackupStatsStrip
            backups={serverScopedBackups ?? []}
            serverMap={serverMap}
            serversResolved={serversResolved}
            onFilterFailed={handleFilterFailed}
          />

          {/* Filter Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2.5 flex-1">
              {/* Search Input */}
              <div className="relative min-w-[200px] max-w-xs flex-1">
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted">
                  <Icon name="search" size={14} />
                </span>
                <input
                  type="text"
                  aria-label="Search backups"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search server, ID, scope, error..."
                  className="w-full rounded-lg border border-border-default bg-surface-card pl-8 pr-8 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus shadow-2xs"
                />
                {searchQuery && (
                  <button
                    type="button"
                    aria-label="Clear search"
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-text-muted hover:text-text-primary cursor-pointer"
                  >
                    <Icon name="x" size={13} />
                  </button>
                )}
              </div>

              {!isServerScoped && (
                <select
                  id="backup-server-filter"
                  aria-label="Filter by server"
                  value={serverFilter}
                  onChange={(e) => handleServerFilterChange(e.target.value)}
                  className="rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus shadow-2xs"
                >
                  <option value="all">All servers</option>
                  {serverList.map((s) => (
                    <option key={s.server_id} value={s.server_id}>
                      {s.name}
                    </option>
                  ))}
                  {hasDeletedServerBackups && (
                    <option value="deleted">Deleted servers</option>
                  )}
                </select>
              )}

              <select
                id="backup-status-filter"
                aria-label="Filter by status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus shadow-2xs"
              >
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>

              <select
                id="backup-tier-filter"
                aria-label="Filter by type"
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value)}
                className="rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus shadow-2xs"
              >
                {TIER_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-3 text-xs text-text-muted">
              <span className="tabular-nums">
                Showing {filtered.length} of {(serverScopedBackups ?? []).length}
              </span>
              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={clearAllFilters}
                  className="rounded-md px-2 py-1 font-medium text-text-accent hover:bg-surface-hover transition-colors cursor-pointer"
                >
                  Clear filters
                </button>
              )}
            </div>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon="search"
              title="No matching backups"
              description="No backups match your current search or filter selection."
              action={
                hasActiveFilters ? (
                  <button
                    type="button"
                    onClick={clearAllFilters}
                    className="rounded-lg border border-border-default bg-surface-card px-3.5 py-2 text-xs font-medium text-text-primary hover:bg-surface-hover cursor-pointer"
                  >
                    Clear filters
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
                      <th className="px-4 py-3 text-left">Server</th>
                      <th className="px-4 py-3 text-left">Backup</th>
                      <th className="px-4 py-3 text-left">Status</th>
                      <th className="px-4 py-3 text-left">Size</th>
                      <th className="px-4 py-3 text-left">Created</th>
                      <th className="px-4 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle">
                    {filtered.map((b) => {
                      const server = resolveBackupServer(b, serverMap, serversResolved);
                      const tierMeta = getTierMeta(b.tier);
                      const scopeMeta = getScopeMeta(b.backup_type);
                      const statusMeta = getStatusMeta(b.status);
                      const verification = verifyResults[b.backup_id];
                      const isRowVerifying = verifyingId === b.backup_id;

                      return (
                        <tr
                          key={b.backup_id}
                          onClick={() => setDrawerBackup(b)}
                          className="transition-colors hover:bg-surface-hover/50 cursor-pointer"
                        >
                          <td className="px-4 py-3">
                            <div className="flex flex-col gap-1 items-start">
                              {server.deleted ? (
                                <span className="inline-flex items-center rounded-md bg-surface-muted px-2 py-0.5 text-xs font-medium text-text-muted">
                                  Deleted Server
                                </span>
                              ) : (
                                <span className="font-semibold text-text-primary">
                                  {server.name}
                                </span>
                              )}
                              <HashBadge hash={b.backup_id} />
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span
                                className={`rounded-full px-2.5 py-0.5 text-xs font-medium border ${
                                  b.tier === "tier_2"
                                    ? "bg-surface-elevated text-text-primary border-border-default"
                                    : "bg-surface-muted text-text-secondary border-border-subtle"
                                }`}
                                title={tierMeta.subtitle}
                              >
                                {tierMeta.label}
                              </span>
                              <span className="text-xs font-medium text-text-secondary">
                                {scopeMeta.shortLabel}
                              </span>
                              {b.pinned && (
                                <span
                                  className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-surface-elevated px-2 py-0.5 text-[11px] font-medium text-text-muted"
                                  title="Pinned backup — exempt from automated retention pruning"
                                >
                                  <Icon name="lock" size={10} />
                                  <span>Pinned</span>
                                </span>
                              )}
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <div className="space-y-1">
                              <span
                                className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${statusMeta.badgeClass}`}
                              >
                                <span
                                  className={`mr-1.5 h-1.5 w-1.5 rounded-full bg-current ${
                                    statusMeta.pulse ? "animate-pulse" : "opacity-80"
                                  }`}
                                  aria-hidden="true"
                                />
                                {statusMeta.label}
                              </span>
                              {b.error_message && (
                                <div className="flex items-center gap-1.5 text-xs text-text-muted max-w-[220px]">
                                  <span className="truncate">{b.error_message}</span>
                                </div>
                              )}
                            </div>
                          </td>

                          <td className="px-4 py-3 font-mono text-xs tabular-nums text-text-secondary">
                            {formatBytes(b.size_bytes)}
                          </td>

                          <td
                            className="px-4 py-3"
                            title={formatDateTime(b.created_at)}
                          >
                            <div className="text-xs font-medium text-text-primary">
                              {formatRelativeTime(b.created_at) || "just now"}
                            </div>
                            <div className="text-[11px] text-text-muted">
                              {formatShortDateTime(b.created_at)}
                            </div>
                          </td>

                          <td
                            className="px-4 py-3"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <div className="flex items-center justify-end gap-1.5">
                              {b.status === "completed" && canRestore && (
                                <button
                                  type="button"
                                  onClick={() => setRestoreTarget(b)}
                                  disabled={restoreBackup.isPending}
                                  aria-label={`Restore ${b.backup_id}`}
                                  title="Restore Backup"
                                  className="inline-flex items-center gap-1 rounded-md border border-status-warning-border bg-status-warning-bg px-2.5 py-1 text-xs font-semibold text-status-warning transition-colors hover:opacity-90 disabled:opacity-40 cursor-pointer"
                                >
                                  <Icon name="restart" size={13} />
                                  <span>Restore</span>
                                </button>
                              )}

                              {b.status === "completed" && (
                                <button
                                  type="button"
                                  onClick={() =>
                                    verification
                                      ? setDrawerBackup(b)
                                      : handleVerify(b)
                                  }
                                  disabled={isRowVerifying}
                                  aria-label={`Verify ${b.backup_id}`}
                                  title={
                                    verification
                                      ? verification.valid
                                        ? "Verified — click to inspect details"
                                        : verification.artifact_error ?? "Invalid — click to inspect details"
                                      : "Verify integrity"
                                  }
                                  className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-40 cursor-pointer ${
                                    verification
                                      ? verification.valid
                                        ? "border-status-success-border bg-status-success-bg text-status-success"
                                        : "border-status-danger-border bg-status-danger-bg text-status-danger"
                                      : "border-border-default bg-surface-elevated text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                                  }`}
                                >
                                  {isRowVerifying ? (
                                    <span
                                      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                                      aria-hidden="true"
                                    />
                                  ) : (
                                    <Icon
                                      name={verification && !verification.valid ? "alert" : "check"}
                                      size={13}
                                    />
                                  )}
                                  <span>
                                    {isRowVerifying
                                      ? "Verifying..."
                                      : verification
                                      ? verification.valid
                                        ? "Verified"
                                        : "Invalid"
                                      : "Verify"}
                                  </span>
                                </button>
                              )}

                              <button
                                type="button"
                                onClick={() => setDrawerBackup(b)}
                                aria-label={`Details ${b.backup_id}`}
                                title="Inspect backup details"
                                className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer"
                              >
                                <Icon name="info" size={15} />
                              </button>

                              {canDelete && (
                                <button
                                  type="button"
                                  onClick={() => setDeleteTarget(b)}
                                  disabled={b.pinned || deleteBackup.isPending}
                                  aria-label="Delete backup"
                                  title={
                                    b.pinned
                                      ? "Pinned for upgrade rollback. Confirm the upgrade or release pins to unlock deletion."
                                      : "Delete backup"
                                  }
                                  className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-status-danger-bg hover:text-status-danger disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                                >
                                  <Icon name="trash" size={15} />
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Mobile Card List */}
              <div className="md:hidden space-y-3">
                {filtered.map((b) => {
                  const server = resolveBackupServer(b, serverMap, serversResolved);
                  const tierMeta = getTierMeta(b.tier);
                  const scopeMeta = getScopeMeta(b.backup_type);
                  const statusMeta = getStatusMeta(b.status);
                  const verification = verifyResults[b.backup_id];
                  const isRowVerifying = verifyingId === b.backup_id;

                  return (
                    <div
                      key={b.backup_id}
                      onClick={() => setDrawerBackup(b)}
                      className="rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3 shadow-2xs cursor-pointer"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 space-y-1">
                          {server.deleted ? (
                            <span className="inline-flex items-center rounded-md bg-surface-muted px-2 py-0.5 text-xs font-medium text-text-muted">
                              Deleted Server
                            </span>
                          ) : (
                            <div className="font-semibold text-sm text-text-primary truncate">
                              {server.name}
                            </div>
                          )}
                          <HashBadge hash={b.backup_id} />
                        </div>
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold shrink-0 ${statusMeta.badgeClass}`}
                        >
                          <span
                            className={`mr-1.5 h-1.5 w-1.5 rounded-full bg-current ${
                              statusMeta.pulse ? "animate-pulse" : "opacity-80"
                            }`}
                            aria-hidden="true"
                          />
                          {statusMeta.label}
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-xs text-text-secondary">
                        <span className="rounded-full border border-border-subtle bg-surface-muted px-2 py-0.5 font-medium text-text-primary">
                          {tierMeta.label}
                        </span>
                        <span>{scopeMeta.shortLabel}</span>
                        {b.pinned && (
                          <span className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-surface-elevated px-2 py-0.5 text-[11px] text-text-muted">
                            <Icon name="lock" size={10} />
                            <span>Pinned</span>
                          </span>
                        )}
                        <span>·</span>
                        <span className="font-mono tabular-nums">{formatBytes(b.size_bytes)}</span>
                        <span>·</span>
                        <span>{formatRelativeTime(b.created_at) || "just now"}</span>
                      </div>

                      {b.error_message && (
                        <p className="rounded-lg border border-status-danger-border bg-status-danger-bg/40 px-2.5 py-1.5 font-mono text-[11px] text-status-danger line-clamp-2">
                          {b.error_message}
                        </p>
                      )}

                      <div
                        className="flex flex-wrap items-center justify-end gap-2 pt-2 border-t border-border-subtle"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {b.status === "completed" && canRestore && (
                          <button
                            type="button"
                            onClick={() => setRestoreTarget(b)}
                            disabled={restoreBackup.isPending}
                            className="inline-flex items-center gap-1 rounded-md border border-status-warning-border bg-status-warning-bg px-2.5 py-1 text-xs font-semibold text-status-warning disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                          >
                            <Icon name="restart" size={12} />
                            <span>Restore</span>
                          </button>
                        )}
                        {b.status === "completed" && (
                          <button
                            type="button"
                            onClick={() =>
                              verification ? setDrawerBackup(b) : handleVerify(b)
                            }
                            disabled={isRowVerifying}
                            className="inline-flex items-center gap-1 rounded-md border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-medium text-text-secondary cursor-pointer"
                          >
                            <Icon name="check" size={12} />
                            <span>
                              {isRowVerifying
                                ? "Verifying..."
                                : verification
                                ? verification.valid
                                  ? "Verified"
                                  : "Invalid"
                                : "Verify"}
                            </span>
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => setDrawerBackup(b)}
                          className="inline-flex items-center gap-1 rounded-md border border-border-subtle px-2.5 py-1 text-xs font-medium text-text-secondary cursor-pointer"
                        >
                          <Icon name="info" size={12} />
                          <span>Details</span>
                        </button>
                        {canDelete && (
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(b)}
                            disabled={b.pinned || deleteBackup.isPending}
                            title={
                              b.pinned
                                ? "Pinned for upgrade rollback. Confirm the upgrade or release pins to unlock deletion."
                                : "Delete backup"
                            }
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-status-danger hover:bg-status-danger-bg disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                          >
                            <Icon name="trash" size={12} />
                            <span>Delete</span>
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </>
      )}

      {/* Create Backup Modal */}
      <CreateBackupModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        defaultServerId={serverFilter !== "all" ? serverFilter : undefined}
      />

      {/* Slide-Over Details Drawer */}
      <BackupDetailsDrawer
        backup={drawerBackup}
        serverMap={serverMap}
        serversResolved={serversResolved}
        verification={drawerBackup ? verifyResults[drawerBackup.backup_id] : null}
        isVerifying={Boolean(drawerBackup && verifyingId === drawerBackup.backup_id)}
        canRestore={canRestore}
        canDelete={canDelete}
        onClose={() => setDrawerBackup(null)}
        onVerify={handleVerify}
        onRestore={(b) => setRestoreTarget(b)}
        onDelete={(b) => setDeleteTarget(b)}
      />

      {/* Secret Vault Bridge Modal */}
      <SecretVaultBridgeModal
        open={vaultOpen}
        onClose={() => setVaultOpen(false)}
        servers={serverList}
        scopedServerId={scopedFilterServerId}
      />

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete backup?"
        description={
          deleteTarget
            ? `Are you sure you want to delete this backup from ${formatDateTime(deleteTarget.created_at)}? This action cannot be undone.`
            : undefined
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        isPending={deleteBackup.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Restore Confirmation Dialog */}
      <ConfirmDialog
        open={restoreTarget !== null}
        title="Restore backup?"
        description={restoreTarget ? restoreDescription(restoreTarget) : undefined}
        confirmLabel="Restore"
        cancelLabel="Cancel"
        variant="danger"
        isPending={restoreBackup.isPending}
        onConfirm={handleConfirmRestore}
        onCancel={() => setRestoreTarget(null)}
      >
        {restoreTargetRunning && (
          <div className="rounded-lg border border-status-warning-border bg-status-warning-bg/50 p-3 text-xs text-status-warning flex items-start gap-2">
            <Icon name="alert" size={14} className="shrink-0 mt-0.5" />
            <span>
              This server is currently running. Restoring now will queue the restore to apply automatically on next startup.
            </span>
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
