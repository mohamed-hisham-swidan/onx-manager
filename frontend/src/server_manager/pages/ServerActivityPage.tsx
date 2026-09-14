import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams } from "react-router-dom";
import { Icon, type IconName } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import type { ServerActivityLog } from "@/server_manager/types";

function getCategoryBadge(eventType: string): { label: string; color: string; icon: IconName } {
  if (eventType.startsWith("server.crashed")) {
    return {
      label: "Crash",
      color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 border-red-200 dark:border-red-800",
      icon: "alert",
    };
  }
  if (eventType.startsWith("server.")) {
    return {
      label: "Lifecycle",
      color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-blue-200 dark:border-blue-800",
      icon: "server",
    };
  }
  if (eventType.startsWith("plugin.")) {
    return {
      label: "Plugin/Mod",
      color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 border-purple-200 dark:border-purple-800",
      icon: "plugin",
    };
  }
  if (eventType.startsWith("backup.")) {
    return {
      label: "Backup",
      color: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800",
      icon: "backup",
    };
  }
  if (eventType.startsWith("versioning.")) {
    return {
      label: "Versioning",
      color: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 border-amber-200 dark:border-amber-800",
      icon: "clock",
    };
  }
  if (eventType.startsWith("exposure.")) {
    return {
      label: "Exposure",
      color: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400 border-cyan-200 dark:border-cyan-800",
      icon: "activity",
    };
  }
  return {
    label: "Event",
    color: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border-gray-200 dark:border-gray-700",
    icon: "activity",
  };
}

function formatRelativeTime(timestamp: number): string {
  const tsInSeconds = timestamp > 1e11 ? timestamp / 1000 : timestamp;
  const diff = Math.max(0, Date.now() - tsInSeconds * 1000);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 3600_000);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatDateTime(timestamp: number): string {
  const tsInSeconds = timestamp > 1e11 ? timestamp / 1000 : timestamp;
  const date = new Date(tsInSeconds * 1000);
  return date.toLocaleString();
}

export function ServerActivityPage() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { serverId } = useParams<{ serverId: string }>();

  const [logs, setLogs] = useState<ServerActivityLog[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [limit, setLimit] = useState<number>(25);
  const [offset, setOffset] = useState<number>(0);
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedLogIds, setExpandedLogIds] = useState<Set<string>>(new Set());
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState<number>(0);

  const refresh = useCallback(() => {
    setIsLoading(true);
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!serverId) return;
    let isCancelled = false;

    const eventTypeParam = categoryFilter === "all" ? undefined : categoryFilter;

    const fetchLogs = async () => {
      try {
        const res = await api.getServerActivity(serverId, {
          limit,
          offset,
          event_type: eventTypeParam,
        });
        if (!isCancelled) {
          setLogs(res.items);
          setTotalCount(res.total);
          setError(null);
        }
      } catch (err: unknown) {
        if (!isCancelled) {
          const msg = err instanceof Error ? err.message : "Failed to load activity logs";
          setError(msg);
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    };

    fetchLogs();

    return () => {
      isCancelled = true;
    };
  }, [api, serverId, limit, offset, categoryFilter, refreshKey]);

  const toggleExpand = (id: string) => {
    setExpandedLogIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleCopyDetails = (id: string, details: Record<string, unknown>) => {
    navigator.clipboard.writeText(JSON.stringify(details, null, 2));
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const filteredLogs = useMemo(() => {
    if (!searchQuery.trim()) return logs;
    const q = searchQuery.toLowerCase();
    return logs.filter(
      (l) =>
        l.summary.toLowerCase().includes(q) ||
        l.event_type.toLowerCase().includes(q) ||
        (l.actor_id && l.actor_id.toLowerCase().includes(q))
    );
  }, [logs, searchQuery]);

  const totalPages = Math.ceil(totalCount / limit) || 1;
  const currentPage = Math.floor(offset / limit) + 1;

  const categories = [
    { id: "all", label: "All Events" },
    { id: "server.started", label: "Server Started" },
    { id: "server.stopped", label: "Server Stopped" },
    { id: "server.crashed", label: "Crashes" },
    { id: "server.config_changed", label: "Config Changes" },
    { id: "plugin.installed", label: "Plugins/Mods" },
    { id: "backup.completed", label: "Backups" },
    { id: "versioning.commit_created", label: "Version Snapshots" },
  ];

  return (
    <div className="space-y-6" data-testid="server-activity-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-gray-200 dark:border-gray-700 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2.5">
            <Icon name="clock" size={24} className="text-indigo-600 dark:text-indigo-400" />
            Change History & Activity Log
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Durable operational audit trail for lifecycle transitions, configuration changes, mod/plugin management, and versioning snapshots.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={refresh}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition"
            title="Refresh activity logs"
          >
            <Icon name="restart" size={14} className={isLoading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Category Chips */}
          <div className="flex flex-wrap items-center gap-1.5" data-testid="category-filters">
            {categories.map((cat) => {
              const active = categoryFilter === cat.id;
              return (
                <button
                  key={cat.id}
                  onClick={() => {
                    setCategoryFilter(cat.id);
                    setOffset(0);
                  }}
                  className={`px-3 py-1 text-xs font-medium rounded-full transition ${
                    active
                      ? "bg-indigo-600 text-white shadow-sm"
                      : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
                  }`}
                >
                  {cat.label}
                </button>
              );
            })}
          </div>

          {/* Search box */}
          <div className="relative min-w-[240px]">
            <Icon
              name="search"
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
            />
            <input
              type="text"
              placeholder="Search activity summaries..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700/50 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
        </div>
      </div>

      {/* Error alert */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <Icon name="alert" size={16} />
            <span>{error}</span>
          </div>
          <button
            onClick={refresh}
            className="text-xs font-semibold underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="p-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 flex items-start gap-4 animate-pulse"
            >
              <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-700 shrink-0" />
              <div className="space-y-2 flex-1">
                <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/3" />
                <div className="h-3 bg-gray-100 dark:bg-gray-800 rounded w-1/2" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && filteredLogs.length === 0 && (
        <div
          data-testid="activity-empty-state"
          className="text-center py-16 px-4 rounded-xl border border-dashed border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800"
        >
          <div className="w-12 h-12 mx-auto rounded-full bg-indigo-50 dark:bg-indigo-900/30 flex items-center justify-center text-indigo-600 dark:text-indigo-400 mb-3">
            <Icon name="clock" size={24} />
          </div>
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
            No activity logs found
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm mx-auto mt-1">
            {searchQuery || categoryFilter !== "all"
              ? "No events match the current filter criteria. Try selecting 'All Events' or clearing the search box."
              : "Events will appear here as configuration changes, server starts/stops, or version snapshots occur."}
          </p>
        </div>
      )}

      {/* Timeline List */}
      {!isLoading && !error && filteredLogs.length > 0 && (
        <div className="relative pl-6 sm:pl-8 space-y-4 before:absolute before:left-3 before:top-2 before:bottom-2 before:w-0.5 before:bg-gray-200 dark:before:bg-gray-700">
          {filteredLogs.map((log) => {
            const cat = getCategoryBadge(log.event_type);
            const isExpanded = expandedLogIds.has(log.id);
            const hasDetails = log.details && Object.keys(log.details).length > 0;

            return (
              <div
                key={log.id}
                className="relative bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 transition hover:border-gray-300 dark:hover:border-gray-600 shadow-sm"
                data-testid={`activity-log-item-${log.id}`}
              >
                {/* Dot marker on timeline */}
                <span
                  className="absolute -left-6 sm:-left-8 top-5 w-3 h-3 rounded-full border-2 border-white dark:border-gray-900 bg-indigo-500 ring-4 ring-indigo-50 dark:ring-indigo-950/40"
                  aria-hidden="true"
                />

                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                  <div className="space-y-1.5 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {/* Event category badge */}
                      <span
                        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${cat.color}`}
                      >
                        <Icon name={cat.icon} size={12} />
                        {cat.label}
                      </span>

                      {/* Actor Badge */}
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                        <Icon name={log.actor_type === "user" ? "users" : "settings"} size={11} />
                        {log.actor_type === "user" ? log.actor_id || "User" : "System"}
                      </span>

                      {/* Relative time */}
                      <span
                        className="text-xs text-gray-400 dark:text-gray-500 font-mono"
                        title={formatDateTime(log.timestamp)}
                      >
                        {formatRelativeTime(log.timestamp)}
                      </span>
                    </div>

                    {/* Summary */}
                    <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {log.summary}
                    </div>

                    <div className="text-xs text-gray-400 dark:text-gray-500 font-mono">
                      Event: {log.event_type} • {formatDateTime(log.timestamp)}
                    </div>
                  </div>

                  {/* Actions / Details toggle */}
                  {hasDetails && (
                    <button
                      onClick={() => toggleExpand(log.id)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 transition shrink-0 mt-2 sm:mt-0"
                    >
                      <Icon name={isExpanded ? "chevron-up" : "chevron-down"} size={14} />
                      {isExpanded ? "Hide Details" : "View Details"}
                    </button>
                  )}
                </div>

                {/* Expandable JSON Details */}
                {isExpanded && hasDetails && (
                  <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700/60 space-y-2">
                    <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                      <span className="font-semibold uppercase tracking-wider text-[10px]">
                        Event Payload Details
                      </span>
                      <button
                        onClick={() => handleCopyDetails(log.id, log.details)}
                        className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                        title="Copy details as JSON"
                      >
                        <Icon name={copiedId === log.id ? "check" : "copy"} size={12} />
                        {copiedId === log.id ? "Copied" : "Copy JSON"}
                      </button>
                    </div>
                    <pre className="p-3 bg-gray-50 dark:bg-gray-900/60 rounded-lg text-xs font-mono text-gray-800 dark:text-gray-200 overflow-x-auto border border-gray-200 dark:border-gray-800">
                      {JSON.stringify(log.details, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination Footer */}
      {!isLoading && !error && totalCount > 0 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-4 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400">
          <div>
            Showing <span className="font-semibold">{filteredLogs.length}</span> of{" "}
            <span className="font-semibold">{totalCount}</span> events
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1">
              <span>Per page:</span>
              <select
                value={limit}
                onChange={(e) => {
                  setLimit(Number(e.target.value));
                  setOffset(0);
                }}
                className="px-2 py-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 text-xs"
              >
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </label>

            <button
              disabled={offset <= 0}
              onClick={() => setOffset((o) => Math.max(0, o - limit))}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 font-medium text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700 transition"
            >
              Previous
            </button>
            <span className="px-2 font-medium">
              Page {currentPage} of {totalPages}
            </span>
            <button
              disabled={offset + limit >= totalCount}
              onClick={() => setOffset((o) => o + limit)}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 font-medium text-gray-700 dark:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700 transition"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
