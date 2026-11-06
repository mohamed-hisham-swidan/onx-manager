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
import { STATUS_MAP } from "@/server_manager/types";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { TableSkeleton } from "@/components/Skeleton";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Pagination } from "@/components/ui/Pagination";
import { ViewModeToggle, type ViewMode } from "@/components/ui/ViewModeToggle";
import { ServerBanner } from "@/components/ui/ServerBanner";
import { toast } from "@/stores/toastStore";
import { ProvisioningProgress } from "@/server_manager/components/ProvisioningProgress";
import { StartingMonitorBanner } from "@/server_manager/components/StartingMonitorBanner";
import type { ServerResponse } from "@/server_manager/types";

type SortKey = "name" | "status" | "version";

const STATUS_FILTERS = [
  "all",
  "running",
  "stopped",
  "starting",
  "provisioning",
  "provisioning_failed",
  "stopping",
  "crashed",
  "broken",
  "created",
  "restoring",
];

const PAGE_SIZE = 15;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function getNow(): number {
  return Date.now();
}

export function ServersPage() {
  const { data: servers, isLoading, error, refetch: refetchServers } = useServersList();
  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();
  const deleteServer = useDeleteServer();
  const retryProvisioning = useRetryProvisioningServer();
  const navigate = useNavigate();

  const [searchParams, setSearchParams] = useSearchParams();
  const statusParam = searchParams.get("status");
  const statusFilter = statusParam && STATUS_FILTERS.includes(statusParam) ? statusParam : "all";

  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [copiedPortId, setCopiedPortId] = useState<string | null>(null);

  const startingServers = useMemo(
    () => (servers ?? []).filter((s) => s.status === "starting"),
    [servers]
  );

  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [deleteTarget, setDeleteTarget] = useState<ServerResponse | null>(null);
  const [stopTarget, setStopTarget] = useState<ServerResponse | null>(null);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const filterRef = useRef<HTMLDivElement>(null);

  const isBusy =
    startServer.isPending ||
    stopServer.isPending ||
    restartServer.isPending ||
    retryProvisioning.isPending;
  const [startCooldowns, setStartCooldowns] = useState<Record<string, number>>({});
  const [now, setNow] = useState<number>(() => getNow());

  const hasActiveCooldown = useMemo(
    () => Object.values(startCooldowns).some((until) => until > now),
    [startCooldowns, now]
  );

  const handleStatusFilterChange = (nextStatus: string) => {
    setCurrentPage(1);
    const newParams = new URLSearchParams(searchParams);
    if (nextStatus === "all") {
      newParams.delete("status");
    } else {
      newParams.set("status", nextStatus);
    }
    setSearchParams(newParams);
  };

  useEffect(() => {
    if (!isFilterOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setIsFilterOpen(false);
    }
    function handleClickOutside(e: MouseEvent) {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setIsFilterOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isFilterOpen]);

  useEffect(() => {
    if (!hasActiveCooldown) return;
    const timer = window.setInterval(() => {
      setNow(getNow());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [hasActiveCooldown]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    const list = (servers ?? []).filter((s) => {
      if (statusFilter !== "all" && s.status !== statusFilter) return false;
      if (query && !s.name.toLowerCase().includes(query)) return false;
      return true;
    });

    return [...list].sort((a, b) => {
      if (sortKey === "status") return (a.status ?? "").localeCompare(b.status ?? "");
      if (sortKey === "version") return (a.minecraft_version ?? "").localeCompare(b.minecraft_version ?? "");
      return a.name.localeCompare(b.name);
    });
  }, [servers, search, statusFilter, sortKey]);

  const paginatedServers = useMemo(() => {
    const startIdx = (currentPage - 1) * PAGE_SIZE;
    return filtered.slice(startIdx, startIdx + PAGE_SIZE);
  }, [filtered, currentPage]);

  const handleStart = (server: ServerResponse, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    const currentTime = getNow();
    setNow(currentTime);
    setStartCooldowns((prev) => ({ ...prev, [server.server_id]: currentTime + 30000 }));

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
    });
  };

  function handleStop(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    setStopTarget(server);
  }

  function handleConfirmStop() {
    if (!stopTarget) return;
    const s = stopTarget;
    setStopTarget(null);
    stopServer.mutate(s.server_id, {
      onSuccess: () => toast("info", "Server stopping", `"${s.name}" is stopping.`),
      onError: (err) => toast("error", "Stop failed", errorMessage(err)),
    });
  }

  function handleRestart(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    restartServer.mutate(server.server_id, {
      onSuccess: () => toast("info", "Server restarting", `"${server.name}" restart initiated.`),
      onError: (err) => toast("error", "Restart failed", errorMessage(err)),
    });
  }

  function handleDeleteClick(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    setDeleteTarget(server);
  }

  function handleConfirmDelete() {
    if (!deleteTarget) return;
    const s = deleteTarget;
    setDeleteTarget(null);
    deleteServer.mutate(s.server_id, {
      onSuccess: () => toast("success", "Server deleted", `"${s.name}" was removed.`),
      onError: (err) => toast("error", "Delete failed", errorMessage(err)),
    });
  }

  function handleRetryProvisioning(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    retryProvisioning.mutate(server.server_id, {
      onSuccess: () => toast("success", "Retry started", `Provisioning retry started for "${server.name}".`),
      onError: (err) => toast("error", "Retry failed", errorMessage(err)),
    });
  }

  const handleCopyPort = (port: number, serverId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(String(port));
    setCopiedPortId(serverId);
    setTimeout(() => setCopiedPortId(null), 2000);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Servers"
        description="Manage, monitor, and deploy your Minecraft instances"
        icon="server"
        actions={
          <div className="flex items-center gap-2">
            <Link to="/servers/import">
              <Button variant="secondary" size="md" icon="upload">
                Import
              </Button>
            </Link>
            <Link to="/servers/create">
              <Button variant="primary" size="md" icon="plus">
                New Server
              </Button>
            </Link>
          </div>
        }
      />

      {isLoading ? (
        <TableSkeleton rows={6} cols={5} />
      ) : error ? (
        <ErrorState message={error instanceof Error ? error.message : "Failed to load servers"} />
      ) : servers && servers.length === 0 ? (
        <EmptyState
          icon="server"
          title="No servers yet"
          description="Create or import your first Minecraft server to get started."
          action={{
            label: "New Server",
            onClick: () => {
              navigate("/servers/create");
            },
          }}
        />
      ) : (
        <>
          {/* Starting servers monitoring banners */}
          {startingServers.map((s) => (
            <div key={s.server_id} className="mb-4">
              <StartingMonitorBanner
                targetName={s.name}
                startedAt={s.updated_at}
                timeoutSeconds={s.startup_timeout_seconds ?? 120}
                onCheckNow={async () => {
                  await refetchServers();
                }}
              />
            </div>
          ))}

          {/* Search, Filter, Sort & View Mode Toolbar */}
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Icon
                name="search"
                size={16}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
              />
              <input
                type="search"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setCurrentPage(1);
                }}
                placeholder="Search servers by name..."
                aria-label="Search servers by name"
                className="w-full rounded-xl border border-border-default bg-surface-card py-2 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus shadow-2xs"
              />
            </div>

            <div className="flex items-center gap-2">
              <ViewModeToggle
                mode={viewMode}
                onChange={setViewMode}
                storageKey="onx_servers_view_mode"
              />

              <div className="relative" ref={filterRef}>
                <button
                  type="button"
                  onClick={() => setIsFilterOpen((prev) => !prev)}
                  aria-expanded={isFilterOpen}
                  aria-label="Filter and sort"
                  title="Filter and sort"
                  className={`inline-flex items-center gap-2 rounded-xl border px-3.5 py-2 text-sm font-medium transition-colors shadow-2xs cursor-pointer ${
                    statusFilter !== "all" || sortKey !== "name"
                      ? "border-accent-primary bg-accent-primary/10 text-accent-primary font-semibold"
                      : "border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                  }`}
                >
                  <Icon name="filter" size={16} />
                  <span>Filters</span>
                  {(statusFilter !== "all" || sortKey !== "name") && (
                    <span className="h-2 w-2 rounded-full bg-accent-primary" />
                  )}
                </button>

                {isFilterOpen && (
                  <div
                    role="dialog"
                    aria-label="Filter and sort options"
                    className="absolute right-0 z-30 mt-2 w-64 rounded-xl border border-border-subtle bg-surface-card p-4 shadow-xl text-text-primary"
                  >
                    <div className="space-y-4">
                      <div>
                        <label
                          htmlFor="status-filter"
                          className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-text-secondary"
                        >
                          Filter by status
                        </label>
                        <select
                          id="status-filter"
                          value={statusFilter}
                          onChange={(e) => handleStatusFilterChange(e.target.value)}
                          className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus"
                        >
                          {STATUS_FILTERS.map((s) => (
                            <option key={s} value={s}>
                              {s === "all" ? "All statuses" : STATUS_MAP[s]?.label ?? s}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="border-t border-border-subtle pt-3">
                        <label
                          htmlFor="sort-key"
                          className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-text-secondary"
                        >
                          Sort by
                        </label>
                        <select
                          id="sort-key"
                          value={sortKey}
                          onChange={(e) => {
                            setSortKey(e.target.value as SortKey);
                            setCurrentPage(1);
                          }}
                          className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus"
                        >
                          <option value="name">Sort by name</option>
                          <option value="status">Sort by status</option>
                          <option value="version">Sort by version</option>
                        </select>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon="search"
              title="No matching servers"
              description="No servers match your current search and filters."
            />
          ) : viewMode === "grid" ? (
            /* Mode A: Grid / Showcase Card Mode */
            <div className="space-y-6">
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {paginatedServers.map((s) => {
                  const isRunning = s.status === "running";
                  return (
                    <div
                      key={s.server_id}
                      onClick={() => navigate(`/servers/${s.server_id}/console`)}
                      className="group relative flex flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-card shadow-2xs transition-all duration-150 hover:-translate-y-0.5 hover:border-border-default hover:bg-surface-hover/30 hover:shadow-md cursor-pointer"
                    >
                      {/* Banner Cover with Vignette */}
                      <ServerBanner seed={s.name} height={124}>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 rounded-md border border-border-subtle/40 bg-surface-card/80 px-2 py-0.5 backdrop-blur-xs">
                            <LoaderBadge loader={s.server_type} />
                            <span className="font-mono text-[11px] text-text-secondary">
                              {s.minecraft_version}
                            </span>
                          </div>
                          <StatusBadge status={s.status} />
                        </div>
                      </ServerBanner>

                      {/* Card Body */}
                      <div className="flex flex-1 flex-col p-4">
                        <div className="flex items-start justify-between gap-2">
                          <Link
                            to={`/servers/${s.server_id}/console`}
                            title={s.name}
                            onClick={(e) => e.stopPropagation()}
                            className="truncate text-base font-bold text-text-primary group-hover:text-accent-primary"
                          >
                            {s.name}
                          </Link>
                          <button
                            type="button"
                            onClick={(e) => handleCopyPort(s.port, s.server_id, e)}
                            className="inline-flex items-center gap-1 rounded border border-border-subtle bg-surface-elevated px-1.5 py-0.5 font-mono text-[11px] text-text-muted hover:border-border-default hover:text-text-primary"
                            title="Click to copy port"
                          >
                            <span>:{s.port}</span>
                            {copiedPortId === s.server_id && (
                              <span className="text-status-success font-semibold">✓</span>
                            )}
                          </button>
                        </div>

                        {/* Telemetry Well */}
                        <div className="mt-3 grid grid-cols-3 gap-2 rounded-lg border border-border-subtle bg-surface-elevated/70 p-2.5 text-center">
                          <div>
                            <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">CPU</div>
                            <div className="mt-0.5 font-mono text-xs tabular-nums text-text-primary">
                              {isRunning ? "1.2%" : "0%"}
                            </div>
                          </div>
                          <div className="border-x border-border-subtle">
                            <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">RAM</div>
                            <div className="mt-0.5 font-mono text-xs tabular-nums text-text-primary">
                              {isRunning ? "1.8G" : "0G"}
                            </div>
                          </div>
                          <div>
                            <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Players</div>
                            <div className="mt-0.5 font-mono text-xs tabular-nums text-text-primary">
                              {isRunning ? "0/20" : "--"}
                            </div>
                          </div>
                        </div>

                        {/* Footer & Actions */}
                        <div className="mt-4 flex items-center justify-between border-t border-border-subtle/60 pt-3">
                          <span className="text-[11px] text-text-muted">
                            {isRunning ? "Active now" : "Offline"}
                          </span>

                          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                            {["stopped", "created", "crashed", "provisioning"].includes(s.status) && (
                              <button
                                type="button"
                                onClick={(e) => handleStart(s, e)}
                                disabled={
                                  isBusy ||
                                  (startCooldowns[s.server_id] !== undefined &&
                                    now < startCooldowns[s.server_id]) ||
                                  s.status === "starting" ||
                                  s.status === "provisioning"
                                }
                                aria-label={`Start ${s.name}`}
                                title="Start"
                                className="rounded-lg p-1.5 text-status-success transition-colors hover:bg-status-success-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                              >
                                <Icon name="play" size={16} />
                              </button>
                            )}

                            {["running", "starting"].includes(s.status) && (
                              <>
                                <button
                                  type="button"
                                  onClick={(e) => handleStop(s, e)}
                                  disabled={isBusy}
                                  aria-label={`Stop ${s.name}`}
                                  title="Stop"
                                  className="rounded-lg p-1.5 text-status-danger transition-colors hover:bg-status-danger-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                                >
                                  <Icon name="stop" size={16} />
                                </button>
                                {s.status === "running" && (
                                  <button
                                    type="button"
                                    onClick={(e) => handleRestart(s, e)}
                                    disabled={isBusy}
                                    aria-label={`Restart ${s.name}`}
                                    title="Restart"
                                    className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                                  >
                                    <Icon name="restart" size={16} />
                                  </button>
                                )}
                              </>
                            )}

                            <Link
                              to={`/servers/${s.server_id}/console`}
                              className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
                              title="Open Console"
                            >
                              <Icon name="console" size={16} />
                            </Link>

                            <button
                              type="button"
                              onClick={(e) => handleDeleteClick(s, e)}
                              disabled={deleteServer.isPending}
                              aria-label={`Delete ${s.name}`}
                              title="Delete"
                              className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-status-danger-bg hover:text-status-danger disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                            >
                              <Icon name="trash" size={16} />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {filtered.length > PAGE_SIZE && (
                <div className="border-t border-border-subtle p-3">
                  <Pagination
                    totalItems={filtered.length}
                    pageSize={PAGE_SIZE}
                    page={currentPage}
                    onPageChange={setCurrentPage}
                  />
                </div>
              )}
            </div>
          ) : (
            /* Mode B: List / Horizontal Strip Mode */
            <div className="overflow-hidden rounded-2xl border border-border-subtle bg-surface-card shadow-2xs">
              <table className="w-full text-sm text-text-primary border-collapse">
                <thead>
                  <tr className="border-b border-border-subtle bg-surface-muted/40 text-xs font-semibold uppercase tracking-wider text-text-secondary">
                    <th scope="col" className="px-4 py-3 text-left">Name</th>
                    <th scope="col" className="hidden px-4 py-3 text-left sm:table-cell">Software / Version</th>
                    <th scope="col" className="hidden px-4 py-3 text-left md:table-cell">Port</th>
                    <th scope="col" className="px-4 py-3 text-left">Status</th>
                    <th scope="col" className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {paginatedServers.map((s) => (
                    <tr
                      key={s.server_id}
                      onClick={() => navigate(`/servers/${s.server_id}/console`)}
                      className="transition-colors hover:bg-surface-hover/50 cursor-pointer"
                    >
                      <td className="max-w-0 px-4 py-3">
                        <Link
                          to={`/servers/${s.server_id}/console`}
                          title={s.name}
                          onClick={(e) => e.stopPropagation()}
                          className="block truncate font-semibold text-accent-primary hover:underline"
                        >
                          {s.name}
                        </Link>
                      </td>
                      <td className="hidden px-4 py-3 text-text-secondary sm:table-cell">
                        <div className="flex items-center gap-1.5">
                          <LoaderBadge loader={s.server_type} />
                          <span>{s.minecraft_version}</span>
                        </div>
                      </td>
                      <td className="hidden px-4 py-3 font-mono text-xs text-text-muted md:table-cell">
                        {s.port}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={s.status} />
                      </td>
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          {["stopped", "created", "crashed", "provisioning"].includes(s.status) && (
                            <button
                              type="button"
                              onClick={(e) => handleStart(s, e)}
                              disabled={
                                isBusy ||
                                (startCooldowns[s.server_id] !== undefined &&
                                  now < startCooldowns[s.server_id]) ||
                                s.status === "starting" ||
                                s.status === "provisioning"
                              }
                              aria-label={`Start ${s.name}`}
                              title="Start"
                              className="rounded-lg p-1.5 text-status-success transition-colors hover:bg-status-success-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                            >
                              <Icon name="play" size={16} />
                            </button>
                          )}
                          {s.status === "provisioning_failed" && s.provisioning_retryable === false && (
                            <button
                              type="button"
                              onClick={(e) => handleRetryProvisioning(s, e)}
                              disabled={isBusy}
                              aria-label={`Retry Provisioning ${s.name}`}
                              title="Retry Provisioning"
                              className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                            >
                              <Icon name="restart" size={16} />
                            </button>
                          )}
                          {["running", "starting"].includes(s.status) && (
                            <>
                              <button
                                type="button"
                                onClick={(e) => handleStop(s, e)}
                                disabled={isBusy}
                                aria-label={`Stop ${s.name}`}
                                title="Stop"
                                className="rounded-lg p-1.5 text-status-danger transition-colors hover:bg-status-danger-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                              >
                                <Icon name="stop" size={16} />
                              </button>
                              {s.status === "running" && (
                                <button
                                  type="button"
                                  onClick={(e) => handleRestart(s, e)}
                                  disabled={isBusy}
                                  aria-label={`Restart ${s.name}`}
                                  title="Restart"
                                  className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                                >
                                  <Icon name="restart" size={16} />
                                </button>
                              )}
                            </>
                          )}
                          {s.status === "stopping" && (
                            <span
                              aria-label={`${s.name} is ${STATUS_MAP[s.status]?.label.toLowerCase()}`}
                              className="inline-flex h-7 w-7 items-center justify-center text-text-muted"
                            >
                              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-border-default border-t-accent-primary" />
                            </span>
                          )}
                          {s.status === "provisioning" && (
                            <ProvisioningProgress serverId={s.server_id} className="min-w-[140px]" />
                          )}
                          <button
                            type="button"
                            onClick={(e) => handleDeleteClick(s, e)}
                            disabled={deleteServer.isPending}
                            aria-label={`Delete ${s.name}`}
                            title="Delete"
                            className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-status-danger-bg hover:text-status-danger disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                          >
                            <Icon name="trash" size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {filtered.length > PAGE_SIZE && (
                <div className="border-t border-border-subtle p-3">
                  <Pagination
                    totalItems={filtered.length}
                    pageSize={PAGE_SIZE}
                    page={currentPage}
                    onPageChange={setCurrentPage}
                  />
                </div>
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
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
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
        confirmLabel="Stop Server"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmStop}
        onCancel={() => setStopTarget(null)}
      />
    </div>
  );
}
