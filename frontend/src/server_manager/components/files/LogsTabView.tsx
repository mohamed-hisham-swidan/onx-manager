import React, { useMemo, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Button, IconButton } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/States";
import { formatBytes, formatDateTime, formatRelativeTime } from "@/server_manager/utils/format";
import type { FileItem, LogCategory } from "@/server_manager/types";

export type LogsCategoryFilter = "all" | LogCategory;

export interface LogsTabViewProps {
  entries: FileItem[];
  isLoading: boolean;
  isFetching: boolean;
  activeBranch?: string;
  isAdvancedMode?: boolean;
  selectedPath?: string | null;
  splitView: boolean;
  embedded?: boolean;
  onToggleSplitView: () => void;
  onRefresh: () => void;
  onOpenLog: (item: FileItem) => void;
  onDownload: (item: FileItem) => void;
}

const CATEGORY_META: Record<
  LogCategory,
  { label: string; badgeClass: string }
> = {
  crash_report: {
    label: "Crash Report",
    badgeClass: "border-status-danger-border bg-status-danger-bg text-status-danger",
  },
  server_log: {
    label: "Server Log",
    badgeClass: "border-status-info-border bg-status-info-bg text-status-info",
  },
  plugin_log: {
    label: "Plugin Log",
    badgeClass: "border-border-default bg-surface-muted text-text-secondary",
  },
};

function inferCategory(item: FileItem): LogCategory {
  if (item.log_category) return item.log_category;
  if (item.path.startsWith("crash-reports/")) return "crash_report";
  if (item.path.startsWith("plugins/")) return "plugin_log";
  return "server_log";
}

export const LogsTabView: React.FC<LogsTabViewProps> = ({
  entries,
  isFetching,
  activeBranch,
  isAdvancedMode = false,
  selectedPath,
  splitView,
  embedded = false,
  onToggleSplitView,
  onRefresh,
  onOpenLog,
  onDownload,
}) => {
  const [categoryFilter, setCategoryFilter] = useState<LogsCategoryFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const dragCounterRef = useRef(0);
  const [isBlockedDragOver, setIsBlockedDragOver] = useState(false);

  const counts = useMemo(() => {
    let serverLog = 0;
    let crashReport = 0;
    let pluginLog = 0;
    for (const item of entries) {
      const cat = inferCategory(item);
      if (cat === "crash_report") crashReport++;
      else if (cat === "plugin_log") pluginLog++;
      else serverLog++;
    }
    return {
      all: entries.length,
      server_log: serverLog,
      crash_report: crashReport,
      plugin_log: pluginLog,
    };
  }, [entries]);

  const filteredEntries = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return entries.filter((item) => {
      const cat = inferCategory(item);
      if (categoryFilter !== "all" && cat !== categoryFilter) {
        return false;
      }
      if (!q) return true;
      return (
        item.name.toLowerCase().includes(q) ||
        item.path.toLowerCase().includes(q)
      );
    });
  }, [entries, categoryFilter, searchQuery]);

  const handleBlockedDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    setIsBlockedDragOver(true);
  };

  const handleBlockedDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "none";
  };

  const handleBlockedDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
    if (dragCounterRef.current === 0) {
      setIsBlockedDragOver(false);
    }
  };

  const handleBlockedDrop = (e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsBlockedDragOver(false);
  };

  const categories: Array<{ id: LogsCategoryFilter; label: string; count: number }> = [
    { id: "all", label: "All", count: counts.all },
    { id: "server_log", label: "Server Logs", count: counts.server_log },
    { id: "crash_report", label: "Crash Reports", count: counts.crash_report },
    { id: "plugin_log", label: "Plugin Logs", count: counts.plugin_log },
  ];

  const isNonMainBranch = Boolean(activeBranch && activeBranch !== "main");

  return (
    <div
      data-testid="logs-tab-view"
      onDragEnter={handleBlockedDragEnter}
      onDragOver={handleBlockedDragOver}
      onDragLeave={handleBlockedDragLeave}
      onDrop={handleBlockedDrop}
      className={`flex flex-col flex-1 min-h-0 min-w-0 overflow-hidden ${embedded ? "" : "space-y-3"}`}
    >
      {/* Read-Only Banner */}
      <div
        className={`flex flex-wrap items-center justify-between gap-2 text-xs text-text-secondary shrink-0 bg-surface-card ${
          embedded
            ? "border-b border-border-subtle px-3 py-2"
            : "rounded-xl border border-border-subtle px-4 py-2.5 shadow-2xs"
        }`}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="lock" size={14} className="text-text-muted shrink-0" />
          <span>
            {isAdvancedMode
              ? "Read-only view of live runtime logs (not tracked in Git)"
              : "Read-only view of live runtime logs."}
          </span>
          {activeBranch && (
            <span className="rounded border border-border-subtle bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-text-primary">
              {activeBranch}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="files-split-view-toggle"
            aria-pressed={splitView}
            onClick={onToggleSplitView}
            className={`hidden lg:inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
              splitView
                ? "border-accent-primary bg-accent-primary text-accent-contrast-text"
                : "border-border-subtle bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            <Icon name="columns" size={14} />
            <span>Split View</span>
          </button>

          <Button
            type="button"
            variant="secondary"
            size="sm"
            icon="restart"
            loading={isFetching}
            data-testid="logs-refresh-btn"
            onClick={onRefresh}
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* Fail-closed drop guard notice */}
      {isBlockedDragOver && (
        <div
          data-testid="logs-drop-blocked-notice"
          className={`flex items-center gap-2 shrink-0 bg-status-warning-bg text-xs font-medium text-status-warning ${
            embedded
              ? "border-b border-status-warning-border px-3 py-2"
              : "rounded-xl border border-status-warning-border px-4 py-2"
          }`}
        >
          <Icon name="lock" size={14} />
          <span>Logs &amp; Crashes is read-only — file upload is disabled here.</span>
        </div>
      )}

      {/* Category Filter Pills & Instant Search */}
      <div
        className={`flex flex-wrap items-center justify-between gap-2.5 shrink-0 bg-surface-card p-3 ${
          embedded
            ? "border-b border-border-subtle"
            : "rounded-xl border border-border-subtle shadow-xs"
        }`}
      >
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Log categories">
          {categories.map((cat) => {
            const active = categoryFilter === cat.id;
            return (
              <button
                key={cat.id}
                type="button"
                data-testid={`logs-category-${cat.id}`}
                aria-pressed={active}
                onClick={() => setCategoryFilter(cat.id)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer ${
                  active
                    ? "border-accent-primary bg-accent-primary text-accent-contrast-text shadow-2xs"
                    : "border-border-subtle bg-surface-muted text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                }`}
              >
                <span>{cat.label}</span>
                <span className="font-mono text-[10px] opacity-85">{cat.count}</span>
              </button>
            );
          })}
        </div>

        <div className="relative min-w-[200px] flex-1 max-w-xs">
          <span className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-text-muted">
            <Icon name="search" size={14} />
          </span>
          <input
            type="text"
            data-testid="logs-search-input"
            aria-label="Search logs or plugins"
            placeholder="Search logs or plugins..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-border-subtle bg-surface-page py-1.5 ps-9 pe-8 text-xs text-text-primary placeholder:text-text-muted hover:border-border-hover focus:border-border-focus focus:outline-hidden focus:ring-1 focus:ring-border-focus"
          />
          {searchQuery && (
            <button
              type="button"
              aria-label="Clear logs search"
              onClick={() => setSearchQuery("")}
              className="absolute inset-y-0 end-0 flex items-center pe-2.5 text-text-muted hover:text-text-primary cursor-pointer"
            >
              <Icon name="x" size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Table or Empty State */}
      <div
        className={`flex flex-col flex-1 min-h-0 overflow-hidden bg-surface-card ${
          embedded ? "" : "rounded-xl border border-border-subtle shadow-xs"
        }`}
      >
        {entries.length === 0 ? (
          <EmptyState
            icon="file"
            title={
              isNonMainBranch
                ? `No runtime logs for branch "${activeBranch}" yet`
                : "No runtime logs or crash reports yet"
            }
            description={
              isNonMainBranch
                ? "This branch has no provisioned runtime yet. Start the branch container to generate isolated runtime logs."
                : "Start the server to generate logs in logs/, crash-reports/, or plugins/*/."
            }
            className="border-0 rounded-none flex-1"
          />
        ) : filteredEntries.length === 0 ? (
          <EmptyState
            icon="search"
            title="No matching logs"
            description="No log files matched the active category or search filter."
            className="border-0 rounded-none flex-1"
            action={{
              label: "Clear filters",
              onClick: () => {
                setCategoryFilter("all");
                setSearchQuery("");
              },
            }}
          />
        ) : (
          <div className="flex-1 min-h-0 overflow-x-auto overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 z-10 border-b border-border-subtle bg-surface-muted/90 text-xs font-semibold uppercase tracking-wider text-text-muted backdrop-blur-xs">
                <tr>
                  <th scope="col" className="px-4 py-2.5">File</th>
                  <th scope="col" className="hidden sm:table-cell px-4 py-2.5 w-32">Category</th>
                  <th scope="col" className="hidden sm:table-cell px-4 py-2.5 w-24 text-right">Size</th>
                  <th scope="col" className="hidden md:table-cell px-4 py-2.5 w-36">Modified</th>
                  <th scope="col" className="px-4 py-2.5 w-24 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {filteredEntries.map((item) => {
                  const category = inferCategory(item);
                  const catMeta = CATEGORY_META[category];
                  const relativeMod = formatRelativeTime(item.modified_at);
                  const exactMod = item.modified_at ? formatDateTime(item.modified_at) : undefined;
                  const isSelected = selectedPath === item.path;

                  return (
                    <tr
                      key={item.path}
                      data-testid={`log-row-${item.path}`}
                      onClick={() => onOpenLog(item)}
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-accent-primary/10"
                          : "hover:bg-surface-hover/50"
                      }`}
                    >
                      <td className="px-4 py-2.5 min-w-0">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <Icon name="file" size={15} className="text-text-muted shrink-0" />
                          <div className="min-w-0">
                            <p className="truncate font-medium text-text-primary">{item.name}</p>
                            <p className="truncate font-mono text-[11px] text-text-muted">
                              {item.path}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="hidden sm:table-cell px-4 py-2.5 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${catMeta.badgeClass}`}
                        >
                          {catMeta.label}
                        </span>
                      </td>
                      <td className="hidden sm:table-cell px-4 py-2.5 whitespace-nowrap text-right font-mono text-xs tabular-nums text-text-muted">
                        {formatBytes(item.size)}
                      </td>
                      <td
                        className="hidden md:table-cell px-4 py-2.5 whitespace-nowrap text-xs text-text-muted"
                        title={exactMod}
                      >
                        {relativeMod || "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right whitespace-nowrap">
                        <IconButton
                          icon="download"
                          aria-label={`Download ${item.name}`}
                          title={`Download ${item.name}`}
                          size="sm"
                          variant="ghost"
                          className="text-text-muted hover:bg-surface-muted hover:text-text-primary"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDownload(item);
                          }}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
