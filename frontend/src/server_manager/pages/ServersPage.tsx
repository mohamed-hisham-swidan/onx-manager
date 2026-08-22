import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useServersList, useStartServer, useStopServer, useRestartServer, useDeleteServer, useRetryProvisioningServer } from "@/server_manager/hooks/useServers";
import { STATUS_MAP } from "@/server_manager/types";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import { ProvisioningProgress } from "@/server_manager/components/ProvisioningProgress";
import type { ServerResponse } from "@/server_manager/types";

type SortKey = "name" | "status" | "version";

const STATUS_FILTERS = ["all", "running", "stopped", "starting", "provisioning", "provisioning_failed", "stopping", "crashed", "broken", "created"];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

export function ServersPage() {
  const { data: servers, isLoading, error } = useServersList();
  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();
  const deleteServer = useDeleteServer();
  const retryProvisioning = useRetryProvisioningServer();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [deleteTarget, setDeleteTarget] = useState<ServerResponse | null>(null);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);

  const isBusy = startServer.isPending || stopServer.isPending || restartServer.isPending || retryProvisioning.isPending;
  const [startCooldowns, setStartCooldowns] = useState<Record<string, number>>({});
  const [now, setNow] = useState<number>(() => Date.now());

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
    const hasActive = Object.values(startCooldowns).some((t) => t > Date.now());
    if (!hasActive) return;
    const timer = setInterval(() => {
      const current = Date.now();
      setNow(current);
    }, 200);
    return () => clearInterval(timer);
  }, [startCooldowns]);

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

  function handleStart(server: ServerResponse) {
    setStartCooldowns((prev) => ({ ...prev, [server.server_id]: Date.now() + 3000 }));
    setNow(Date.now());
    startServer.mutate(server.server_id, {
      onSuccess: () => toast("success", "Server started", `"${server.name}" is starting.`),
      onError: (err) => toast("error", "Start failed", errorMessage(err)),
    });
  }

  function handleStop(server: ServerResponse) {
    stopServer.mutate(server.server_id, {
      onSuccess: () => toast("success", "Server stopped", `"${server.name}" is stopping.`),
      onError: (err) => toast("error", "Stop failed", errorMessage(err)),
    });
  }

  function handleRestart(server: ServerResponse) {
    restartServer.mutate(server.server_id, {
      onSuccess: () => toast("success", "Server restarting", `"${server.name}" is restarting.`),
      onError: (err) => toast("error", "Restart failed", errorMessage(err)),
    });
  }

  function handleRetryProvisioning(server: ServerResponse) {
    retryProvisioning.mutate(server.server_id, {
      onSuccess: () => toast("success", "Retry started", `Provisioning retry started for "${server.name}".`),
      onError: (err) => toast("error", "Retry failed", errorMessage(err)),
    });
  }

  function handleConfirmDelete() {
    if (!deleteTarget) return;
    deleteServer.mutate(deleteTarget.server_id, {
      onSuccess: () => toast("success", "Server deleted", `"${deleteTarget.name}" was removed.`),
      onError: (err) => toast("error", "Delete failed", errorMessage(err)),
      onSettled: () => setDeleteTarget(null),
    });
  }

  return (
    <div>
      <PageHeader
        title="Servers"
        description="Manage and monitor your Minecraft servers"
        icon="server"
        actions={
          <>
            <Link
              to="/servers/import"
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              Import
            </Link>
            <Link
              to="/servers/create"
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              <Icon name="plus" size={16} />
              New Server
            </Link>
          </>
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
          action={
            <Link
              to="/servers/create"
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              <Icon name="plus" size={16} />
              New Server
            </Link>
          }
        />
      ) : (
        <>
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Icon
                name="search"
                size={16}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-500"
              />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name..."
                aria-label="Search servers by name"
                className="w-full rounded-lg border border-gray-300 bg-white py-2 pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </div>
            <div className="relative" ref={filterRef}>
              <button
                type="button"
                onClick={() => setIsFilterOpen((prev) => !prev)}
                aria-expanded={isFilterOpen}
                aria-label="Filter and sort"
                title="Filter and sort"
                className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                  statusFilter !== "all" || sortKey !== "name"
                    ? "border-blue-500 bg-blue-50 text-blue-700 dark:border-blue-500 dark:bg-blue-900/30 dark:text-blue-300"
                    : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
                }`}
              >
                <Icon name="filter" size={16} />
                <span>Filters</span>
                {(statusFilter !== "all" || sortKey !== "name") && (
                  <span className="h-2 w-2 rounded-full bg-blue-600 dark:bg-blue-400" />
                )}
              </button>

              {isFilterOpen && (
                <div
                  role="dialog"
                  aria-label="Filter and sort options"
                  className="absolute right-0 z-30 mt-2 w-64 rounded-xl border border-gray-200 bg-white p-4 shadow-lg dark:border-gray-700 dark:bg-gray-800"
                >
                  <div className="space-y-4">
                    <div>
                      <label htmlFor="status-filter" className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                        Filter by status
                      </label>
                      <select
                        id="status-filter"
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value)}
                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200"
                      >
                        {STATUS_FILTERS.map((s) => (
                          <option key={s} value={s}>
                            {s === "all" ? "All statuses" : STATUS_MAP[s]?.label ?? s}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="border-t border-gray-100 pt-3 dark:border-gray-700/60">
                      <label htmlFor="sort-key" className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                        Sort by
                      </label>
                      <select
                        id="sort-key"
                        value={sortKey}
                        onChange={(e) => setSortKey(e.target.value as SortKey)}
                        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200"
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

          {filtered.length === 0 ? (
            <EmptyState
              icon="search"
              title="No matching servers"
              description="No servers match your current search and filters."
            />
          ) : (
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
                    <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">Name</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 sm:table-cell">Version</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 md:table-cell">Port</th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">Status</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-400">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((s) => (
                    <tr
                      key={s.server_id}
                      className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                    >
                      <td className="max-w-0 px-4 py-3">
                        <Link
                          to={`/servers/${s.server_id}/console`}
                          title={s.name}
                          className="block truncate font-medium text-blue-600 hover:underline dark:text-blue-400"
                        >
                          {s.name}
                        </Link>
                      </td>
                      <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 sm:table-cell">
                        {s.minecraft_version}
                      </td>
                      <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 md:table-cell">{s.port}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={s.status} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          {["stopped", "created", "crashed", "provisioning"].includes(s.status) && (
                            <button
                              onClick={() => handleStart(s)}
                              disabled={isBusy || (startCooldowns[s.server_id] !== undefined && now < startCooldowns[s.server_id]) || s.status === "starting" || s.status === "provisioning"}
                              aria-label={`Start ${s.name}`}
                              title="Start"
                              className="rounded-lg p-1.5 text-green-600 transition-colors hover:bg-green-100 hover:text-green-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-green-400 dark:hover:bg-green-900/30 dark:hover:text-green-300"
                            >
                              <Icon name="play" size={16} />
                            </button>
                          )}
                          {s.status === "provisioning_failed" && s.provisioning_retryable === false && (
                            <button
                              onClick={() => handleRetryProvisioning(s)}
                              disabled={isBusy}
                              aria-label={`Retry Provisioning ${s.name}`}
                              title="Retry Provisioning"
                              className="rounded-lg p-1.5 text-amber-600 transition-colors hover:bg-amber-100 hover:text-amber-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-amber-400 dark:hover:bg-amber-900/30 dark:hover:text-amber-300"
                            >
                              <Icon name="restart" size={16} />
                            </button>
                          )}
                          {["running", "starting"].includes(s.status) && (
                            <>
                              <button
                                onClick={() => handleStop(s)}
                                disabled={isBusy}
                                aria-label={`Stop ${s.name}`}
                                title="Stop"
                                className="rounded-lg p-1.5 text-orange-600 transition-colors hover:bg-orange-100 hover:text-orange-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-orange-400 dark:hover:bg-orange-900/30 dark:hover:text-orange-300"
                              >
                                <Icon name="stop" size={16} />
                              </button>
                              {s.status === "running" && (
                                <button
                                  onClick={() => handleRestart(s)}
                                  disabled={isBusy}
                                  aria-label={`Restart ${s.name}`}
                                  title="Restart"
                                  className="rounded-lg p-1.5 text-yellow-600 transition-colors hover:bg-yellow-100 hover:text-yellow-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-yellow-400 dark:hover:bg-yellow-900/30 dark:hover:text-yellow-300"
                                >
                                  <Icon name="restart" size={16} />
                                </button>
                              )}
                            </>
                          )}
                          {s.status === "stopping" && (
                            <span
                              aria-label={`${s.name} is ${STATUS_MAP[s.status]?.label.toLowerCase()}`}
                              className="inline-flex h-7 w-7 items-center justify-center text-gray-400 dark:text-gray-500"
                            >
                              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600 dark:border-gray-600 dark:border-t-gray-300" />
                            </span>
                          )}
                          {s.status === "provisioning" && (
                            <ProvisioningProgress serverId={s.server_id} className="min-w-[140px]" />
                          )}
                          <button
                            onClick={() => setDeleteTarget(s)}
                            disabled={deleteServer.isPending}
                            aria-label={`Delete ${s.name}`}
                            title="Delete"
                            className="rounded-lg p-1.5 text-red-600 transition-colors hover:bg-red-100 hover:text-red-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-red-400 dark:hover:bg-red-900/30 dark:hover:text-red-300"
                          >
                            <Icon name="trash" size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete server?"
        description={
          deleteTarget
            ? `This permanently deletes "${deleteTarget.name}" and its data. This action cannot be undone.`
            : undefined
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
