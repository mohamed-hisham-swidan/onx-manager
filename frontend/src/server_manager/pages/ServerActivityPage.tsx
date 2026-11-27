import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams } from "react-router-dom";
import { Icon, type IconName } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { HashBadge } from "@/components/ui/HashBadge";
import type {
  GetActivityParams,
  ServerActivityLog,
  ServerBranch,
} from "@/server_manager/types";

function getCategoryBadge(eventType: string): { label: string; color: string; icon: IconName } {
  if (eventType.startsWith("server.crashed")) {
    return {
      label: "Crash",
      color: "bg-status-danger-bg text-status-danger border-status-danger-border",
      icon: "alert",
    };
  }
  if (eventType.startsWith("server.")) {
    return {
      label: "Lifecycle",
      color: "bg-accent-primary/15 text-accent-primary border-accent-primary/30",
      icon: "server",
    };
  }
  if (eventType.startsWith("plugin.")) {
    return {
      label: "Plugin/Mod",
      color: "bg-status-info-bg text-status-info border-status-info-border",
      icon: "plugin",
    };
  }
  if (eventType.startsWith("backup.")) {
    return {
      label: "Backup",
      color: "bg-status-success-bg text-status-success border-status-success-border",
      icon: "backup",
    };
  }
  if (eventType.startsWith("versioning.")) {
    return {
      label: "Versioning",
      color: "bg-status-warning-bg text-status-warning border-status-warning-border",
      icon: "clock",
    };
  }
  if (eventType.startsWith("exposure.")) {
    return {
      label: "Exposure",
      color: "bg-status-info-bg text-status-info border-status-info-border",
      icon: "activity",
    };
  }
  return {
    label: "Event",
    color: "bg-surface-elevated text-text-secondary border-border-default",
    icon: "activity",
  };
}

function formatRelativeTime(timestamp: number): string {
  const tsInSeconds = timestamp > 1e11 ? timestamp / 1000 : timestamp;
  const diff = Math.max(0, Date.now() - tsInSeconds * 1000);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
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
  const branchCtx = useServerBranchContext();
  const gitBacked = Boolean(branchCtx?.gitBacked);
  const isAdvancedMode = branchCtx?.serverMode === "advanced";
  const activeContextBranch = gitBacked ? branchCtx?.branch : undefined;

  const [logs, setLogs] = useState<ServerActivityLog[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const limit = 25;
  const [offset, setOffset] = useState<number>(0);
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [branchFilter, setBranchFilter] = useState<string>(
    activeContextBranch || "all",
  );
  const [branches, setBranches] = useState<ServerBranch[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedLogIds, setExpandedLogIds] = useState<Set<string>>(new Set());

  const [prevServerId, setPrevServerId] = useState<string | undefined>(serverId);
  if (serverId !== prevServerId) {
    setPrevServerId(serverId);
    setOffset(0);
    setCategoryFilter("all");
    setSearchQuery("");
    setExpandedLogIds(new Set());
    setBranches([]);
    setBranchFilter(activeContextBranch || "all");
  }
  const [prevContextBranch, setPrevContextBranch] = useState<string | undefined>(
    activeContextBranch,
  );
  if (activeContextBranch !== prevContextBranch) {
    setPrevContextBranch(activeContextBranch);
    setBranchFilter(activeContextBranch || "all");
    setOffset(0);
  }

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState<number>(0);

  const refresh = useCallback(() => {
    setIsLoading(true);
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!serverId || !isAdvancedMode) return;
    let isCancelled = false;

    const loadBranches = async () => {
      try {
        const branchData =
          await (api.getServerBranches?.(serverId)?.catch(() => []) ?? Promise.resolve([]));
        if (!isCancelled) {
          setBranches(Array.isArray(branchData) ? branchData : []);
        }
      } catch {
        // Branch filters are optional; activity logs remain usable without them.
        if (!isCancelled) setBranches([]);
      }
    };

    void loadBranches();

    return () => {
      isCancelled = true;
    };
  }, [serverId, isAdvancedMode, api]);

  useEffect(() => {
    if (!serverId) return;
    let isCancelled = false;

    const fetchLogs = async () => {
      try {
        setError(null);
        const params: GetActivityParams = {
          limit,
          offset,
        };
        if (categoryFilter !== "all") {
          params.event_type = categoryFilter;
        }
        if (branchFilter !== "all") {
          params.branch = branchFilter;
        }

        const data = await api.getServerActivity(serverId, params);
        if (!isCancelled) {
          setLogs(data.items || []);
          setTotalCount(data.total || 0);
        }
      } catch (err: unknown) {
        if (!isCancelled) {
          setError(err instanceof Error ? err.message : "Failed to load activity logs.");
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
  }, [serverId, limit, offset, categoryFilter, branchFilter, api, refreshKey]);

  const toggleExpand = (logId: string) => {
    setExpandedLogIds((prev) => {
      const next = new Set(prev);
      if (next.has(logId)) {
        next.delete(logId);
      } else {
        next.add(logId);
      }
      return next;
    });
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
    { id: "plugin.", label: "Plugins/Mods" },
    { id: "backup.", label: "Backups" },
    { id: "versioning.", label: "Version Snapshots" },
  ];

  return (
    <div className="space-y-6" data-testid="server-activity-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border-subtle pb-4">
        <div>
          <h1 className="text-xl font-bold text-text-primary flex items-center gap-2.5">
            <Icon name="clock" size={22} className="text-accent-primary" />
            Change History
          </h1>
          <p className="text-xs text-text-muted mt-1">
            Recent server events, config edits, and snapshots.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={refresh}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer shadow-2xs"
            title="Refresh activity logs"
          >
            <Icon name="restart" size={14} className={isLoading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-surface-card rounded-xl border border-border-subtle p-4 space-y-3 shadow-2xs">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Category Chips */}
          <div className="flex flex-wrap items-center gap-1.5" data-testid="category-filters">
            {categories.map((cat) => {
              const active = categoryFilter === cat.id;
              return (
                <button
                  type="button"
                  key={cat.id}
                  onClick={() => {
                    setCategoryFilter(cat.id);
                    setOffset(0);
                  }}
                  className={`px-3 py-1 text-xs font-semibold rounded-full transition-colors cursor-pointer ${
                    active
                      ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                      : "bg-surface-elevated text-text-secondary hover:bg-surface-hover hover:text-text-primary border border-border-subtle"
                  }`}
                >
                  {cat.label}
                </button>
              );
            })}
          </div>

          {/* Branch filter */}
          {isAdvancedMode && branches.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {activeContextBranch && (
                <button
                  type="button"
                  data-testid="activity-branch-filter-toggle"
                  onClick={() => {
                    setBranchFilter((prev) =>
                      prev === "all" ? activeContextBranch : "all",
                    );
                    setOffset(0);
                  }}
                  className="rounded-lg border border-border-default bg-surface-elevated px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer"
                >
                  {branchFilter === "all"
                    ? `Show Current Branch (${activeContextBranch})`
                    : `Showing Branch: ${branchFilter} (Show All)`}
                </button>
              )}
              <Icon name="version-branch" size={13} className="text-text-muted" />
              <select
                aria-label="Filter by branch"
                value={branchFilter}
                onChange={(e) => {
                  setBranchFilter(e.target.value);
                  setOffset(0);
                }}
                className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
              >
                <option value="all">All Branches</option>
                {branches.map((branch) => (
                  <option key={branch.id} value={branch.name}>
                    {branch.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Search box */}
          <div className="relative min-w-[240px]">
            <Icon
              name="search"
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
            />
            <input
              type="text"
              placeholder="Search activity summaries..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-border-default bg-surface-page text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-hidden focus:ring-1 focus:ring-border-focus"
            />
          </div>
        </div>
      </div>

      {/* Error alert */}
      {error && (
        <div className="p-4 rounded-xl bg-status-danger-bg border border-status-danger-border text-status-danger flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <Icon name="alert" size={16} />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={refresh}
            className="text-xs font-semibold underline hover:no-underline cursor-pointer"
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
              className="p-4 rounded-xl border border-border-subtle bg-surface-card flex items-start gap-4 animate-pulse"
            >
              <div className="w-10 h-10 rounded-full bg-surface-muted shrink-0" />
              <div className="space-y-2 flex-1">
                <div className="h-4 bg-surface-muted rounded w-1/3" />
                <div className="h-3 bg-surface-muted rounded w-1/2" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && filteredLogs.length === 0 && (
        <div
          data-testid="activity-empty-state"
          className="text-center py-16 px-4 rounded-xl border border-dashed border-border-default bg-surface-card"
        >
          <div className="w-12 h-12 mx-auto rounded-full bg-accent-primary/10 flex items-center justify-center text-accent-primary mb-3">
            <Icon name="clock" size={24} />
          </div>
          <h3 className="text-base font-semibold text-text-primary">
            No activity logs found
          </h3>
          <p className="text-sm text-text-muted max-w-sm mx-auto mt-1">
            {searchQuery || categoryFilter !== "all" || branchFilter !== "all"
              ? "No events match the current filter criteria. Try selecting 'All Events' or clearing the search box."
              : "Events will appear here as configuration changes, server starts/stops, or version snapshots occur."}
          </p>
        </div>
      )}

      {/* Timeline List */}
      {!isLoading && !error && filteredLogs.length > 0 && (
        <div className="relative pl-6 sm:pl-8 space-y-4 before:absolute before:left-3 before:top-2 before:bottom-2 before:w-0.5 before:bg-border-subtle">
          {filteredLogs.map((log) => {
            const cat = getCategoryBadge(log.event_type);
            const isExpanded = expandedLogIds.has(log.id);
            const hasDetails = log.details && Object.keys(log.details).length > 0;

            return (
              <div
                key={log.id}
                className="relative bg-surface-card rounded-xl border border-border-subtle p-4 transition-all hover:border-border-default shadow-2xs"
                data-testid={`activity-log-item-${log.id}`}
              >
                {/* Dot marker on timeline */}
                <span
                  className="absolute -left-6 sm:-left-8 top-5 w-3 h-3 rounded-full border-2 border-surface-card bg-accent-primary ring-4 ring-accent-primary/15"
                  aria-hidden="true"
                />

                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      {/* Event category badge */}
                      <span
                        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${cat.color}`}
                      >
                        <Icon name={cat.icon} size={12} />
                        {cat.label}
                      </span>

                      {/* Actor Badge */}
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-surface-elevated text-text-secondary border border-border-subtle">
                        <Icon name={log.actor_type === "user" ? "users" : "settings"} size={11} />
                        {log.actor_type === "user" ? log.actor_id || "User" : "System"}
                      </span>

                      {/* Branch badge */}
                      {log.branch_name && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-status-warning-bg text-status-warning border border-status-warning-border">
                          <Icon name="version-branch" size={11} />
                          {log.branch_name}
                        </span>
                      )}

                      {/* Relative time */}
                      <span
                        className="text-xs text-text-muted font-mono"
                        title={formatDateTime(log.timestamp)}
                      >
                        {formatRelativeTime(log.timestamp)}
                      </span>

                      <HashBadge hash={log.id} className="ml-auto sm:ml-0" />
                    </div>

                    {/* Summary */}
                    <div className="text-sm font-bold text-text-primary">
                      {log.summary}
                    </div>

                    <div className="text-xs text-text-muted font-mono">
                      Event: {log.event_type} • {formatDateTime(log.timestamp)}
                    </div>
                  </div>

                  {/* Actions / Details toggle */}
                  {hasDetails && (
                    <button
                      type="button"
                      onClick={() => toggleExpand(log.id)}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-accent-primary hover:underline transition-colors shrink-0 mt-2 sm:mt-0 cursor-pointer"
                    >
                      <Icon name={isExpanded ? "chevron-up" : "chevron-down"} size={14} />
                      {isExpanded ? "Hide Details" : "View Details"}
                    </button>
                  )}
                </div>

                {/* Expandable JSON Details */}
                {isExpanded && hasDetails && (
                  <div className="mt-3 pt-3 border-t border-border-subtle/60 space-y-2">
                    <div className="text-xs font-bold uppercase tracking-wider text-text-secondary">
                      Event Payload Details
                    </div>
                    <pre className="p-3 rounded-lg bg-surface-elevated border border-border-subtle text-xs font-mono text-text-primary overflow-x-auto leading-relaxed">
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
      {!isLoading && !error && totalCount > limit && (
        <div className="flex items-center justify-between border-t border-border-subtle pt-4 text-xs text-text-muted">
          <span>
            Showing {offset + 1}–{Math.min(offset + limit, totalCount)} of {totalCount} events
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
              className="px-3 py-1.5 rounded-lg border border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:opacity-40 transition-colors cursor-pointer"
            >
              Previous
            </button>
            <span className="font-mono tabular-nums">
              Page {currentPage} of {totalPages}
            </span>
            <button
              type="button"
              disabled={offset + limit >= totalCount}
              onClick={() => setOffset((prev) => prev + limit)}
              className="px-3 py-1.5 rounded-lg border border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:opacity-40 transition-colors cursor-pointer"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
