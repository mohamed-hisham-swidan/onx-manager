import { useMemo, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Icon, type IconName } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useActivityStore, type ActivityEvent } from "@/stores/activityStore";
import { useEffectiveConnectionState, useIsChannelDegraded } from "@/stores/wsStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import type { OperationStatus, OperationSummary } from "@/operations/types";
import { formatRelativeTime, parseServerDate } from "@/server_manager/utils/format";
import type { ServerActivityLog, ServerResponse } from "@/server_manager/types";

export interface DashboardActivityPanelProps {
  servers: ServerResponse[];
  serverNames: Record<string, string>;
}

type ActivityFilter = "all" | "tasks" | "events";

interface UnifiedFeedItem {
  key: string;
  category: "task" | "event";
  timestampMs: number;
  icon: IconName;
  toneClass: string;
  title: string;
  subtitle?: string;
  statusBadge?: { label: string; className: string };
  operationId?: string;
}

function presentEventType(
  eventType: string,
  serverName?: string,
): { icon: IconName; toneClass: string; message: string } {
  const name = serverName || "Server";
  const lower = eventType.toLowerCase();

  if (lower.includes("crashed")) {
    return {
      icon: "alert",
      toneClass: "bg-status-danger-bg text-status-danger",
      message: `${name} crashed unexpectedly`,
    };
  }
  if (lower.includes("backup") && lower.includes("fail")) {
    return {
      icon: "backup",
      toneClass: "bg-status-danger-bg text-status-danger",
      message: `Backup failed on ${name}`,
    };
  }
  if (lower.includes("backup")) {
    return {
      icon: "backup",
      toneClass: "bg-status-success-bg text-status-success",
      message: `Backup completed for ${name}`,
    };
  }
  if (lower.includes("plugin") && (lower.includes("remove") || lower.includes("delete"))) {
    return {
      icon: "plugin",
      toneClass: "bg-status-warning-bg text-status-warning",
      message: `Plugin removed from ${name}`,
    };
  }
  if (lower.includes("plugin")) {
    return {
      icon: "plugin",
      toneClass: "bg-status-info-bg text-status-info",
      message: `Plugin installed on ${name}`,
    };
  }
  if (lower.includes("started")) {
    return {
      icon: "play",
      toneClass: "bg-status-success-bg text-status-success",
      message: `${name} came online`,
    };
  }
  if (lower.includes("starting")) {
    return {
      icon: "restart",
      toneClass: "bg-status-warning-bg text-status-warning",
      message: `${name} is starting`,
    };
  }
  if (lower.includes("stopping")) {
    return {
      icon: "stop",
      toneClass: "bg-status-warning-bg text-status-warning",
      message: `${name} is stopping`,
    };
  }
  if (lower.includes("stopped")) {
    return {
      icon: "stop",
      toneClass: "bg-surface-muted text-text-muted",
      message: `${name} stopped`,
    };
  }
  if (lower.includes("restarted")) {
    return {
      icon: "restart",
      toneClass: "bg-status-warning-bg text-status-warning",
      message: `${name} restarted`,
    };
  }
  if (lower.includes("created")) {
    return {
      icon: "plus",
      toneClass: "bg-status-info-bg text-status-info",
      message: `${name} created`,
    };
  }
  if (lower.includes("deleted")) {
    return {
      icon: "trash",
      toneClass: "bg-status-danger-bg text-status-danger",
      message: `${name} deleted`,
    };
  }
  if (lower.includes("config") || lower.includes("property") || lower.includes("settings")) {
    return {
      icon: "settings",
      toneClass: "bg-status-info-bg text-status-info",
      message: `Updated configuration for ${name}`,
    };
  }
  if (lower.includes("provision")) {
    return {
      icon: "server",
      toneClass: "bg-status-info-bg text-status-info",
      message: `Provisioning updated for ${name}`,
    };
  }
  if (lower.includes("discovered")) {
    return {
      icon: "search",
      toneClass: "bg-status-info-bg text-status-info",
      message: `Discovered ${name}`,
    };
  }
  if (lower.includes("vanished")) {
    return {
      icon: "x",
      toneClass: "bg-surface-muted text-text-muted",
      message: `Lost container link for ${name}`,
    };
  }

  return {
    icon: "activity",
    toneClass: "bg-surface-muted text-text-secondary",
    message: `${eventType.replace(/Event$/i, "")} on ${name}`,
  };
}

const OPERATION_TITLE_MAP: Record<string, string> = {
  MODPACK_INSTALL: "Modpack Install",
  RUN_TEST: "Isolated Test",
  SAFE_UPGRADE: "Safe Upgrade",
  BACKUP_CREATE: "Backup Create",
  BACKUP_RESTORE: "Backup Restore",
  WORLD_IMPORT: "World Import",
  SERVER_CREATE: "Create Server",
  SERVER_START: "Start Server",
  SERVER_STOP: "Stop Server",
  SERVER_RESTART: "Restart Server",
};

function formatOperationTitle(opType: string): string {
  const key = opType.trim().toUpperCase().replace(/[\s.-]+/g, "_");
  if (OPERATION_TITLE_MAP[key]) {
    return OPERATION_TITLE_MAP[key];
  }
  return opType
    .trim()
    .toLowerCase()
    .replace(/[_.-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const SUMMARY_HEX_PLUGIN_RE = /'([0-9a-f]{32})'/i;

function formatActivitySummary(log: ServerActivityLog, fallback: string): string {
  const raw = log.summary?.trim();
  if (!raw) return fallback;

  if (SUMMARY_HEX_PLUGIN_RE.test(raw) && log.details && typeof log.details === "object") {
    const details = log.details as Record<string, unknown>;
    const rawName =
      typeof details.plugin_name === "string"
        ? details.plugin_name
        : typeof details.name === "string"
          ? details.name
          : typeof details.filename === "string"
            ? details.filename.replace(/\.(jar\.disabled|jar|disabled)$/i, "")
            : typeof details.file_name === "string"
              ? details.file_name.replace(/\.(jar\.disabled|jar|disabled)$/i, "")
              : "";
    if (rawName.trim()) {
      return raw.replace(SUMMARY_HEX_PLUGIN_RE, `'${rawName.trim()}'`);
    }
  }
  return raw;
}

function getOperationBadge(status: OperationStatus): {
  label: string;
  className: string;
  icon: IconName;
  toneClass: string;
} {
  if (status === "RUNNING" || status === "PREPARING" || status === "QUEUED") {
    return {
      label: "Running",
      className: "bg-status-info-bg text-status-info",
      icon: "activity",
      toneClass: "bg-status-info-bg text-status-info",
    };
  }
  if (status === "CANCEL_REQUESTED" || status === "CANCELLED") {
    return {
      label: "Cancelled",
      className: "bg-surface-muted text-text-muted",
      icon: "x",
      toneClass: "bg-surface-muted text-text-muted",
    };
  }
  if (status === "FAILED" || status === "TIMED_OUT") {
    return {
      label: "Failed",
      className: "bg-status-danger-bg text-status-danger",
      icon: "alert",
      toneClass: "bg-status-danger-bg text-status-danger",
    };
  }
  return {
    label: "Done",
    className: "bg-status-success-bg text-status-success",
    icon: "check",
    toneClass: "bg-status-success-bg text-status-success",
  };
}

function toMs(ts: string | number | null | undefined): number {
  return parseServerDate(ts)?.getTime() ?? 0;
}

export function DashboardActivityPanel({
  servers,
  serverNames,
}: DashboardActivityPanelProps) {
  const navigate = useNavigate();
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const liveEvents = useActivityStore((s) => s.events);
  const clearLiveEvents = useActivityStore((s) => s.clear);
  const connectionState = useEffectiveConnectionState();
  const serverChannelDegraded = useIsChannelDegraded("server:*");

  const [selectedConsoleId, setSelectedConsoleId] = useState<string>("");

  const resolvedConsoleId = useMemo(() => {
    if (selectedConsoleId && servers.some((s) => s.server_id === selectedConsoleId)) {
      return selectedConsoleId;
    }
    const running = servers.find((s) => s.status === "running");
    return running?.server_id ?? servers[0]?.server_id ?? "";
  }, [servers, selectedConsoleId]);

  const canFetchOps = typeof api?.listOperations === "function";
  const operationsQuery = useQuery({
    queryKey: queryKeys.operations.list(15),
    queryFn: () => api.listOperations({ limit: 15 }),
    enabled: canFetchOps,
    staleTime: 15_000,
    retry: false,
  });

  const activityTargetServers = useMemo(() => servers.slice(0, 5), [servers]);
  const canFetchActivity = typeof api?.getServerActivity === "function";
  const activityQueries = useQueries({
    queries: activityTargetServers.map((s) => ({
      queryKey: queryKeys.activity.server(s.server_id),
      queryFn: () => api.getServerActivity(s.server_id, { limit: 5 }),
      enabled: canFetchActivity && Boolean(s.server_id),
      staleTime: 30_000,
      retry: false,
    })),
  });

  const activityQueriesKey = activityQueries
    .map(
      (q, idx) =>
        `${activityTargetServers[idx]?.server_id ?? ""}:${q.dataUpdatedAt}:${Array.isArray(q.data?.items) ? q.data.items.length : 0}`,
    )
    .join("|");

  const feedItems = useMemo<UnifiedFeedItem[]>(() => {
    const items: UnifiedFeedItem[] = [];
    const seenEventKeys = new Set<string>();

    // 1. Live WebSocket events
    for (const ev of liveEvents as ActivityEvent[]) {
      const resolvedName =
        ev.name ?? (ev.server_id ? serverNames[ev.server_id] : undefined);
      const pres = presentEventType(ev.event_type, resolvedName);
      const ms = toMs(ev.timestamp);
      const dedupeKey = `${ev.server_id ?? ""}:${ev.event_type}:${Math.floor(ms / 2000)}`;
      seenEventKeys.add(dedupeKey);

      items.push({
        key: `ws-${ev.id}`,
        category: "event",
        timestampMs: ms,
        icon: pres.icon,
        toneClass: pres.toneClass,
        title: pres.message,
      });
    }

    // 2. Persisted operations (skip stale operations belonging to deleted servers)
    const ops = Array.isArray(operationsQuery.data)
      ? (operationsQuery.data as OperationSummary[])
      : [];
    for (const op of ops) {
      if (op.target_type === "server" && op.target_id && !serverNames[op.target_id]) {
        continue;
      }
      const badge = getOperationBadge(op.status);
      const targetName = op.target_id ? serverNames[op.target_id] : undefined;
      const ms = toMs(op.started_at || op.created_at);
      items.push({
        key: `op-${op.id}`,
        category: "task",
        timestampMs: ms,
        icon: badge.icon,
        toneClass: badge.toneClass,
        title: formatOperationTitle(op.type),
        subtitle:
          targetName ??
          (op.target_type === "server"
            ? "Deleted Server"
            : op.target_type !== "system"
              ? formatOperationTitle(op.target_type)
              : undefined),
        statusBadge: { label: badge.label, className: badge.className },
        operationId: op.id,
      });
    }

    // 3. Persisted per-server activity
    if (activityQueriesKey) {
      activityTargetServers.forEach((srv) => {
        const cached = queryClient.getQueryData<{ items?: ServerActivityLog[] }>(
          queryKeys.activity.server(srv.server_id),
        );
        const logs = Array.isArray(cached?.items) ? cached.items : [];
        for (const log of logs) {
          const ms = toMs(log.timestamp);
          const dedupeKey = `${log.server_id}:${log.event_type}:${Math.floor(ms / 2000)}`;
          if (seenEventKeys.has(dedupeKey)) continue;
          seenEventKeys.add(dedupeKey);

          const resolvedName = serverNames[log.server_id];
          const pres = presentEventType(log.event_type, resolvedName);
          items.push({
            key: `act-${log.id}`,
            category: "event",
            timestampMs: ms,
            icon: pres.icon,
            toneClass: pres.toneClass,
            title: formatActivitySummary(log, pres.message),
            subtitle: resolvedName,
          });
        }
      });
    }

    items.sort((a, b) => b.timestampMs - a.timestampMs);
    return items.filter((item) => {
      if (filter === "tasks") return item.category === "task";
      if (filter === "events") return item.category === "event";
      return true;
    });
  }, [
    liveEvents,
    serverNames,
    operationsQuery.data,
    activityTargetServers,
    activityQueriesKey,
    queryClient,
    filter,
  ]);

  async function handleOpenOperation(operationId: string) {
    try {
      if (typeof api?.getOperation === "function") {
        const detail = await api.getOperation(operationId);
        useOperationStore.getState().setOperation(detail);
      }
    } catch {
      // If fetch fails, drawer checks cached entry
    }
    useOperationStore.getState().openDrawer(operationId);
  }

  const isWsHealthy = connectionState === "connected" && !serverChannelDegraded;
  const dotClass = isWsHealthy
    ? "bg-status-success"
    : connectionState === "reconnecting" || connectionState === "connecting" || serverChannelDegraded
      ? "bg-status-warning"
      : "bg-text-muted";

  const singleServer = servers.length === 1 ? servers[0] : null;

  return (
    <section
      aria-label="Activity and Tasks"
      className="flex h-full min-h-[280px] max-h-[520px] flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-card"
    >
      {/* Panel Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-subtle px-4 py-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
            {isWsHealthy && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-success opacity-75" />
            )}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${dotClass}`} />
          </span>
          <h2 className="text-sm font-semibold text-text-primary truncate">
            Activity &amp; Tasks
          </h2>
        </div>

        <div className="flex items-center gap-1.5">
          <div
            role="group"
            aria-label="Filter activity"
            className="inline-flex rounded-lg bg-surface-muted p-0.5 text-[11px]"
          >
            {(["all", "tasks", "events"] as const).map((tab) => {
              const active = filter === tab;
              const label = tab === "all" ? "All" : tab === "tasks" ? "Tasks" : "Events";
              return (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setFilter(tab)}
                  aria-pressed={active}
                  className={`rounded-md px-2 py-1 font-medium transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus ${
                    active
                      ? "bg-surface-card text-text-primary shadow-2xs"
                      : "text-text-muted hover:text-text-primary"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>

          {liveEvents.length > 0 && (
            <button
              type="button"
              onClick={clearLiveEvents}
              className="rounded-md px-2 py-1 text-[11px] font-medium text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Feed Content */}
      <div className="flex-1 overflow-y-auto px-4">
        {feedItems.length === 0 ? (
          <div className="flex h-full min-h-[160px] flex-col items-center justify-center py-6 text-center">
            <div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-surface-muted text-text-muted">
              <Icon name="activity" size={16} />
            </div>
            <p className="text-xs text-text-muted max-w-[230px]">
              No recent activity yet. Server actions, backups, and tasks appear here.
            </p>
          </div>
        ) : (
          <ul role="list" className="divide-y divide-border-subtle/70">
            {feedItems.map((item) => {
              const relTime = item.timestampMs
                ? formatRelativeTime(item.timestampMs) || "just now"
                : "";
              const content = (
                <div className="flex items-center gap-2.5 py-2.5 text-left w-full">
                  <div
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${item.toneClass}`}
                  >
                    <Icon name={item.icon} size={13} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="truncate text-xs font-medium text-text-primary">
                        {item.title}
                      </span>
                      {item.statusBadge && (
                        <span
                          className={`inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${item.statusBadge.className}`}
                        >
                          {item.statusBadge.label}
                        </span>
                      )}
                    </div>
                    {item.subtitle && (
                      <p className="truncate text-[11px] text-text-muted">
                        {item.subtitle}
                      </p>
                    )}
                  </div>
                  {relTime && (
                    <span className="shrink-0 text-[11px] font-mono tabular-nums text-text-muted whitespace-nowrap">
                      {relTime}
                    </span>
                  )}
                </div>
              );

              return (
                <li key={item.key}>
                  {item.operationId ? (
                    <button
                      type="button"
                      onClick={() => {
                        void handleOpenOperation(item.operationId!);
                      }}
                      className="w-full rounded-lg transition-colors hover:bg-surface-hover/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus cursor-pointer"
                    >
                      {content}
                    </button>
                  ) : (
                    content
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Honest Quick Console Footer */}
      {servers.length > 0 && (
        <div className="border-t border-border-subtle bg-surface-muted/40 px-4 py-3 space-y-2">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            <Icon name="terminal" size={12} />
            <span>Quick Console</span>
          </div>

          {singleServer ? (
            <button
              type="button"
              onClick={() => navigate(`/servers/${singleServer.server_id}/console`)}
              className="flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 text-xs font-semibold text-text-accent transition-colors hover:bg-surface-hover hover:border-border-strong cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            >
              <span>Open {singleServer.name} Console</span>
              <Icon name="chevron-right" size={13} />
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <select
                aria-label="Select server console"
                value={resolvedConsoleId}
                onChange={(e) => setSelectedConsoleId(e.target.value)}
                className="h-8 min-w-0 flex-1 rounded-lg border border-border-default bg-surface-card px-2.5 text-xs text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
              >
                {servers.map((s) => (
                  <option key={s.server_id} value={s.server_id}>
                    {s.name} ({s.status.replace(/_/g, " ")})
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!resolvedConsoleId}
                onClick={() => {
                  if (resolvedConsoleId) {
                    navigate(`/servers/${resolvedConsoleId}/console`);
                  }
                }}
                className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-border-default bg-surface-card px-3 text-xs font-semibold text-text-accent transition-colors hover:bg-surface-hover hover:border-border-strong disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
              >
                <span>Open Console</span>
                <Icon name="chevron-right" size={13} />
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
