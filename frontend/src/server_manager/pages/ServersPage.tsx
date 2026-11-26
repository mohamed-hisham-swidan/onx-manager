import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  useServersList,
  useStartServer,
  useStopServer,
  useRestartServer,
  useDeleteServer,
  useRetryProvisioningServer,
} from "@/server_manager/hooks/useServers";
import { useHostResources } from "@/server_manager/hooks/useHostResources";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { Skeleton, TableSkeleton } from "@/components/Skeleton";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Pagination } from "@/components/ui/Pagination";
import { type ViewMode } from "@/components/ui/ViewModeToggle";
import { toast } from "@/stores/toastStore";
import { StartingMonitorBanner } from "@/server_manager/components/StartingMonitorBanner";
import { FleetOverviewStrip } from "@/server_manager/components/servers/FleetOverviewStrip";
import { ServersToolbar } from "@/server_manager/components/servers/ServersToolbar";
import { ServerCard } from "@/server_manager/components/servers/ServerCard";
import { ServerListTable } from "@/server_manager/components/servers/ServerListTable";
import { useFleetMetrics } from "@/server_manager/components/servers/useFleetMetrics";
import {
  STATUS_FILTERS,
  filterAndSortServers,
  readInitialViewMode,
  useFleetPermissions,
  type SortKey,
} from "@/server_manager/components/servers/serversUtils";
import type { ServerResponse } from "@/server_manager/types";

const VALID_SORT_KEYS: readonly SortKey[] = [
  "name",
  "status",
  "players",
  "memory",
  "version",
  "created",
];

const PAGE_SIZE = 15;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function getNow(): number {
  return Date.now();
}

function CardsSkeletonGrid() {
  return (
    <div
      data-testid="cards-skeleton"
      className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3"
    >
      {Array.from({ length: 6 }).map((_, idx) => (
        <div
          key={idx}
          className="rounded-2xl border border-border-subtle bg-surface-card p-5 space-y-4"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3.5">
              <Skeleton className="h-[52px] w-[52px] rounded-xl" />
              <div className="space-y-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-24" />
              </div>
            </div>
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          <Skeleton className="h-9 w-full rounded-xl" />
          <Skeleton className="h-16 w-full rounded-xl" />
          <div className="flex justify-between pt-2 border-t border-border-subtle">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-6 w-20" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ServersPage() {
  const { data: servers, isLoading, error, refetch: refetchServers } = useServersList();
  const { data: hostBudget } = useHostResources();
  const permissions = useFleetPermissions();

  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();
  const deleteServer = useDeleteServer();
  const retryProvisioning = useRetryProvisioningServer();
  const navigate = useNavigate();

  const [searchParams, setSearchParams] = useSearchParams();
  const search = searchParams.get("q") ?? "";
  const rawStatus = searchParams.get("status") ?? "all";
  const statusFilter = (STATUS_FILTERS as readonly string[]).includes(rawStatus)
    ? rawStatus
    : "all";
  const loaderFilter = searchParams.get("loader") ?? "all";
  const rawMode = searchParams.get("mode") ?? "all";
  const modeFilter = rawMode === "simple" || rawMode === "advanced" ? rawMode : "all";
  const rawSort = searchParams.get("sort") as SortKey | null;
  const sortKey: SortKey =
    rawSort && VALID_SORT_KEYS.includes(rawSort) ? rawSort : "name";
  const rawPage = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const requestedPage = Number.isNaN(rawPage) || rawPage < 1 ? 1 : rawPage;

  const [viewMode, setViewMode] = useState<ViewMode>(() => readInitialViewMode());
  const [copiedAddressId, setCopiedAddressId] = useState<string | null>(null);
  const copyTimerRef = useRef<number | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<ServerResponse | null>(null);
  const [deletingIds, setDeletingIds] = useState<Record<string, boolean>>({});
  const deletingRef = useRef<Set<string>>(new Set());
  const [stopTarget, setStopTarget] = useState<ServerResponse | null>(null);
  const [busyServerIds, setBusyServerIds] = useState<Set<string>>(() => new Set());
  const [startCooldowns, setStartCooldowns] = useState<Record<string, number>>({});
  const [now, setNow] = useState<number>(() => getNow());

  const serverList = useMemo(() => servers ?? [], [servers]);
  const fleetMetrics = useFleetMetrics(serverList, hostBudget);

  const startingServers = useMemo(
    () => serverList.filter((s) => s.status === "starting"),
    [serverList],
  );

  const availableLoaders = useMemo(() => {
    const set = new Set<string>();
    for (const s of serverList) {
      if (s.server_type) {
        set.add(s.server_type.toLowerCase());
      }
    }
    return Array.from(set).sort();
  }, [serverList]);

  const fallbackAllocatedRamMb = useMemo(
    () =>
      serverList
        .filter((s) => s.status === "running" || s.status === "starting")
        .reduce((sum, s) => sum + (s.max_memory_mb ?? 2048), 0),
    [serverList],
  );

  const hasActiveCooldown = useMemo(
    () => Object.values(startCooldowns).some((until) => until > now),
    [startCooldowns, now],
  );

  useEffect(() => {
    if (!hasActiveCooldown) return;
    const timer = window.setInterval(() => {
      setNow(getNow());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [hasActiveCooldown]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
    };
  }, []);

  const updateParams = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (!value || value === "all" || (key === "sort" && value === "name") || (key === "page" && value === "1")) {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    }
    setSearchParams(next);
  };

  const filtered = useMemo(
    () =>
      filterAndSortServers(serverList, {
        search,
        statusFilter,
        loaderFilter,
        modeFilter,
        sortKey,
        metricsByServerId: fleetMetrics.metricsByServerId,
      }),
    [
      serverList,
      search,
      statusFilter,
      loaderFilter,
      modeFilter,
      sortKey,
      fleetMetrics.metricsByServerId,
    ],
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(requestedPage, totalPages);

  useEffect(() => {
    if (requestedPage > totalPages) {
      const next = new URLSearchParams(searchParams);
      if (totalPages <= 1) {
        next.delete("page");
      } else {
        next.set("page", String(totalPages));
      }
      setSearchParams(next, { replace: true });
    }
  }, [requestedPage, totalPages, searchParams, setSearchParams]);

  const paginatedServers = useMemo(() => {
    const startIdx = (currentPage - 1) * PAGE_SIZE;
    return filtered.slice(startIdx, startIdx + PAGE_SIZE);
  }, [filtered, currentPage]);

  const hasActiveFilters =
    search.trim().length > 0 ||
    statusFilter !== "all" ||
    loaderFilter !== "all" ||
    modeFilter !== "all" ||
    sortKey !== "name";

  const handleClearFilters = () => {
    updateParams({
      q: null,
      status: null,
      loader: null,
      mode: null,
      sort: null,
      page: null,
    });
  };

  const markServerBusy = (serverId: string, busy: boolean) => {
    setBusyServerIds((prev) => {
      const next = new Set(prev);
      if (busy) {
        next.add(serverId);
      } else {
        next.delete(serverId);
      }
      return next;
    });
  };

  const handleStart = (server: ServerResponse, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    const currentTime = getNow();
    setNow(currentTime);
    setStartCooldowns((prev) => ({ ...prev, [server.server_id]: currentTime + 30000 }));
    markServerBusy(server.server_id, true);

    startServer.mutate(server.server_id, {
      onSuccess: () => toast("success", "Server starting", `"${server.name}" start command issued.`),
      onError: (err) => {
        setStartCooldowns((prev) => {
          const next = { ...prev };
          delete next[server.server_id];
          return next;
        });
        toast("error", "Start failed", errorMessage(err));
      },
      onSettled: () => markServerBusy(server.server_id, false),
    });
  };

  function handleStop(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    setStopTarget(server);
  }

  function handleConfirmStop() {
    if (!stopTarget || stopServer.isPending) return;
    const s = stopTarget;
    markServerBusy(s.server_id, true);
    stopServer.mutate(s.server_id, {
      onSuccess: () => {
        setStopTarget(null);
        toast("info", "Server stopping", `"${s.name}" is stopping.`);
      },
      onError: (err) => {
        setStopTarget(null);
        toast("error", "Stop failed", errorMessage(err));
      },
      onSettled: () => markServerBusy(s.server_id, false),
    });
  }

  function handleRestart(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    markServerBusy(server.server_id, true);
    restartServer.mutate(server.server_id, {
      onSuccess: () => toast("info", "Server restarting", `"${server.name}" restart initiated.`),
      onError: (err) => toast("error", "Restart failed", errorMessage(err)),
      onSettled: () => markServerBusy(server.server_id, false),
    });
  }

  function handleDeleteClick(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    if (
      deleteServer.isPending ||
      deletingRef.current.has(server.server_id) ||
      deletingIds[server.server_id]
    ) {
      return;
    }
    setDeleteTarget(server);
  }

  function handleConfirmDelete() {
    if (!deleteTarget) return;
    const s = deleteTarget;
    if (deleteServer.isPending || deletingRef.current.has(s.server_id)) return;
    deletingRef.current.add(s.server_id);
    setDeletingIds((prev) => ({ ...prev, [s.server_id]: true }));
    deleteServer.mutate(s.server_id, {
      onSuccess: () => {
        deletingRef.current.delete(s.server_id);
        setDeletingIds((prev) => {
          const next = { ...prev };
          delete next[s.server_id];
          return next;
        });
        setDeleteTarget(null);
        toast("success", "Server deleted", `"${s.name}" was removed.`);
      },
      onError: (err) => {
        deletingRef.current.delete(s.server_id);
        setDeletingIds((prev) => {
          const next = { ...prev };
          delete next[s.server_id];
          return next;
        });
        setDeleteTarget(null);
        toast("error", "Delete failed", errorMessage(err));
      },
    });
  }

  function handleRetryProvisioning(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    markServerBusy(server.server_id, true);
    retryProvisioning.mutate(server.server_id, {
      onSuccess: () =>
        toast("success", "Retry started", `Provisioning retry started for "${server.name}".`),
      onError: (err) => toast("error", "Retry failed", errorMessage(err)),
      onSettled: () => markServerBusy(server.server_id, false),
    });
  }

  const handleCopyAddress = (address: string, serverId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(address);
    setCopiedAddressId(serverId);
    toast("info", "Address copied", `Copied ${address}`);
    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current);
    }
    copyTimerRef.current = window.setTimeout(() => {
      setCopiedAddressId(null);
    }, 2000);
  };

  return (
    <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-6 space-y-6">
      <PageHeader
        title="Servers"
        description="Monitor, launch, and manage your Minecraft instances."
        icon="server"
        className="mb-0"
        badge={
          servers ? (
            <span
              data-testid="servers-count-pill"
              className="inline-flex h-5 items-center rounded-full border border-border-subtle bg-surface-elevated px-2 font-mono text-xs font-semibold text-text-secondary"
            >
              {serverList.length}
            </span>
          ) : undefined
        }
        actions={
          permissions.canCreate || permissions.canImport ? (
            <div className="flex items-center gap-2">
              {permissions.canImport && (
                <Link to="/servers/import">
                  <Button variant="secondary" size="md" icon="upload">
                    Import
                  </Button>
                </Link>
              )}
              {permissions.canCreate && (
                <Link to="/servers/create">
                  <Button variant="primary" size="md" icon="plus">
                    New Server
                  </Button>
                </Link>
              )}
            </div>
          ) : undefined
        }
      />

      {isLoading ? (
        viewMode === "grid" ? (
          <CardsSkeletonGrid />
        ) : (
          <TableSkeleton rows={6} cols={5} />
        )
      ) : error ? (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load servers"}
          onRetry={() => {
            void refetchServers();
          }}
        />
      ) : serverList.length === 0 ? (
        <EmptyState
          icon="server"
          title="No servers yet"
          description="Create a new instance or import an existing Minecraft directory."
          action={
            permissions.canCreate || permissions.canImport ? (
              <div className="flex flex-wrap items-center justify-center gap-2.5">
                {permissions.canCreate && (
                  <Button
                    variant="primary"
                    size="sm"
                    icon="plus"
                    onClick={() => navigate("/servers/create")}
                  >
                    Create Server
                  </Button>
                )}
                {permissions.canImport && (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon="upload"
                    onClick={() => navigate("/servers/import")}
                  >
                    Import Existing Server
                  </Button>
                )}
              </div>
            ) : undefined
          }
        />
      ) : (
        <>
          <FleetOverviewStrip
            totalServers={serverList.length}
            runningCount={fleetMetrics.runningCount}
            totalOnlinePlayers={fleetMetrics.totalOnlinePlayers}
            totalOnlineCapacity={fleetMetrics.totalOnlineCapacity}
            hostBudget={hostBudget}
            activeStatusFilter={statusFilter}
            onToggleRunningFilter={() =>
              updateParams({
                status: statusFilter === "running" ? null : "running",
                page: null,
              })
            }
            fallbackAllocatedRamMb={fallbackAllocatedRamMb}
          />

          {startingServers.map((s) => (
            <StartingMonitorBanner
              key={s.server_id}
              targetName={s.name}
              startedAt={s.updated_at}
              timeoutSeconds={s.startup_timeout_seconds ?? 120}
              onCheckNow={async () => {
                await refetchServers();
              }}
            />
          ))}

          <ServersToolbar
            search={search}
            onSearchChange={(val) => updateParams({ q: val || null, page: null })}
            statusFilter={statusFilter}
            onStatusFilterChange={(val) => updateParams({ status: val, page: null })}
            loaderFilter={loaderFilter}
            onLoaderFilterChange={(val) => updateParams({ loader: val, page: null })}
            availableLoaders={availableLoaders}
            modeFilter={modeFilter}
            onModeFilterChange={(val) => updateParams({ mode: val, page: null })}
            sortKey={sortKey}
            onSortKeyChange={(val) => updateParams({ sort: val, page: null })}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            totalCount={serverList.length}
            filteredCount={filtered.length}
            hasActiveFilters={hasActiveFilters}
            onClearFilters={handleClearFilters}
          />

          {filtered.length === 0 ? (
            <EmptyState
              icon="search"
              title="No matching servers"
              description="No servers match your current search and filters."
              action={
                hasActiveFilters
                  ? {
                      label: "Clear filters",
                      icon: "x",
                      onClick: handleClearFilters,
                    }
                  : undefined
              }
            />
          ) : viewMode === "grid" ? (
            (() => {
              const showQuickDeploy =
                serverList.length === 1 && !hasActiveFilters && permissions.canCreate;
              const renderedCardCount = paginatedServers.length + (showQuickDeploy ? 1 : 0);
              const cardsGridClass =
                renderedCardCount <= 2
                  ? "grid grid-cols-1 gap-5 md:grid-cols-2"
                  : "grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3";

              return (
                <div className="space-y-6">
                  <div data-testid="servers-cards-grid" className={cardsGridClass}>
                    {paginatedServers.map((s) => {
                      const isDeleting =
                        Boolean(deletingIds[s.server_id]) ||
                        deleteTarget?.server_id === s.server_id;
                      const isCooldown =
                        startCooldowns[s.server_id] !== undefined &&
                        now < startCooldowns[s.server_id];

                      return (
                        <ServerCard
                          key={s.server_id}
                          server={s}
                          telemetry={fleetMetrics.metricsByServerId[s.server_id]}
                          isDeleting={isDeleting}
                          isBusy={busyServerIds.has(s.server_id)}
                          isStartCooldown={isCooldown}
                          copiedAddressId={copiedAddressId}
                          canPower={permissions.canPower(s.server_id)}
                          canFiles={permissions.canFiles(s.server_id)}
                          onStart={handleStart}
                          onStop={handleStop}
                          onRestart={handleRestart}
                          onRetryProvisioning={handleRetryProvisioning}
                          onCopyAddress={handleCopyAddress}
                        />
                      );
                    })}

                    {showQuickDeploy && (
                      <div
                        data-testid="quick-deploy-card"
                        className="hidden md:flex flex-col items-center justify-center rounded-2xl border border-dashed border-border-default bg-surface-card/40 p-6 text-center"
                      >
                        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-border-subtle bg-surface-muted text-text-muted">
                          <Icon name="plus" size={20} />
                        </div>
                        <h3 className="text-sm font-semibold text-text-primary">
                          Deploy Another Instance
                        </h3>
                        <p className="mt-1 max-w-[220px] text-xs text-text-muted">
                          Launch a fresh world or import an existing server directory.
                        </p>
                        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                          <Link to="/servers/create">
                            <Button variant="primary" size="xs" icon="plus">
                              New Server
                            </Button>
                          </Link>
                          {permissions.canImport && (
                            <Link to="/servers/import">
                              <Button variant="secondary" size="xs" icon="upload">
                                Import Existing
                              </Button>
                            </Link>
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  {filtered.length > PAGE_SIZE && (
                    <Pagination
                      totalItems={filtered.length}
                      pageSize={PAGE_SIZE}
                      page={currentPage}
                      onPageChange={(nextPage) => updateParams({ page: String(nextPage) })}
                    />
                  )}
                </div>
              );
            })()
          ) : (
            <div className="space-y-4">
              <ServerListTable
                servers={paginatedServers}
                metricsByServerId={fleetMetrics.metricsByServerId}
                deletingIds={deletingIds}
                deleteTargetId={deleteTarget?.server_id ?? null}
                busyServerIds={busyServerIds}
                startCooldowns={startCooldowns}
                now={now}
                copiedAddressId={copiedAddressId}
                canPower={permissions.canPower}
                canDelete={permissions.canDelete}
                onStart={handleStart}
                onStop={handleStop}
                onRestart={handleRestart}
                onDelete={handleDeleteClick}
                onRetryProvisioning={handleRetryProvisioning}
                onCopyAddress={handleCopyAddress}
              />

              {filtered.length > PAGE_SIZE && (
                <Pagination
                  totalItems={filtered.length}
                  pageSize={PAGE_SIZE}
                  page={currentPage}
                  onPageChange={(nextPage) => updateParams({ page: String(nextPage) })}
                />
              )}
            </div>
          )}
        </>
      )}

      {/* Shared Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete server?"
        description={
          deleteTarget
            ? `This permanently deletes "${deleteTarget.name}" and all of its files and world data. This action cannot be undone.`
            : undefined
        }
        confirmLabel={deleteServer.isPending ? "Deleting..." : "Delete"}
        cancelLabel="Cancel"
        variant="danger"
        isPending={deleteServer.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => {
          if (deleteServer.isPending) return;
          setDeleteTarget(null);
        }}
      />

      {/* Shared Stop Confirmation Dialog */}
      <ConfirmDialog
        open={stopTarget !== null}
        title="Stop server?"
        description={
          stopTarget
            ? `Are you sure you want to stop "${stopTarget.name}"? Active players will be safely disconnected.`
            : undefined
        }
        confirmLabel={stopServer.isPending ? "Stopping..." : "Stop Server"}
        cancelLabel="Cancel"
        variant="danger"
        isPending={stopServer.isPending}
        onConfirm={handleConfirmStop}
        onCancel={() => {
          if (stopServer.isPending) return;
          setStopTarget(null);
        }}
      />
    </div>
  );
}
