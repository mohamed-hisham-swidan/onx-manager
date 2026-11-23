import { useState, useMemo, useEffect } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  useStartServer,
  useStopServer,
  useRestartServer,
} from "@/server_manager/hooks/useServers";
import { toast } from "@/stores/toastStore";
import type { ServerDetailResponse, ServerResponse } from "@/server_manager/types";
import type { MetricsSnapshot } from "@/services/api";

interface CommandCenterFleetListProps {
  servers: ServerResponse[];
  detailsMap?: Record<string, ServerDetailResponse | undefined>;
  metricsMap?: Record<string, MetricsSnapshot[] | undefined>;
}

export function CommandCenterFleetList({
  servers,
  detailsMap,
  metricsMap,
}: CommandCenterFleetListProps) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "running" | "stopped">("all");
  const [copiedPort, setCopiedPort] = useState<number | null>(null);

  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();

  const [stopTarget, setStopTarget] = useState<{ id: string; name: string } | null>(null);
  const [startCooldowns, setStartCooldowns] = useState<Record<string, number>>({});
  const [now, setNow] = useState<number>(() => Date.now());

  const hasCooldown = useMemo(
    () => Object.values(startCooldowns).some((until) => until > now),
    [startCooldowns, now],
  );

  useEffect(() => {
    if (!hasCooldown) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [hasCooldown]);

  const filteredServers = useMemo(() => {
    return servers.filter((s) => {
      const matchesSearch =
        search.trim() === "" ||
        s.name.toLowerCase().includes(search.toLowerCase()) ||
        s.port?.toString().includes(search) ||
        s.server_type.toLowerCase().includes(search.toLowerCase());

      if (!matchesSearch) return false;
      if (filter === "running") return s.status === "running";
      if (filter === "stopped") return s.status === "stopped" || s.status === "created";
      return true;
    });
  }, [servers, search, filter]);

  const onlineCount = servers.filter((s) => s.status === "running").length;
  const offlineCount = servers.filter((s) => s.status === "stopped" || s.status === "created").length;

  function copyPort(port: number) {
    navigator.clipboard.writeText(port.toString());
    setCopiedPort(port);
    toast("info", "Port copied", `Port ${port} copied to clipboard`);
    setTimeout(() => setCopiedPort(null), 2000);
  }

  function handleStart(serverId: string, name: string) {
    const cur = Date.now();
    setNow(cur);
    setStartCooldowns((prev) => ({ ...prev, [serverId]: cur + 3000 }));
    startServer.mutate(serverId, {
      onSuccess: () => toast("success", "Server started", `"${name}" is starting.`),
      onError: (err) =>
        toast("error", "Start failed", err instanceof Error ? err.message : "Start failed"),
    });
  }

  function handleStop(serverId: string, name: string) {
    setStopTarget({ id: serverId, name });
  }

  function confirmStop() {
    if (!stopTarget) return;
    const { id, name } = stopTarget;
    setStopTarget(null);
    stopServer.mutate(id, {
      onSuccess: () => toast("success", "Server stopped", `"${name}" is stopping.`),
      onError: (err) =>
        toast("error", "Stop failed", err instanceof Error ? err.message : "Stop failed"),
    });
  }

  function handleStartAll() {
    const stopped = servers.filter((s) => s.status === "stopped" || s.status === "created");
    if (stopped.length === 0) {
      toast("info", "No stopped servers", "All instances are already active.");
      return;
    }
    stopped.forEach((s) => handleStart(s.server_id, s.name));
    toast("info", "Starting fleet", `Triggered startup for ${stopped.length} instances.`);
  }

  const isBusy = startServer.isPending || stopServer.isPending || restartServer.isPending;

  return (
    <div className="rounded-xl border border-border-subtle bg-surface-card p-4 sm:p-5 shadow-2xs">
      {/* Container Header & Toolbar */}
      <div className="flex flex-col gap-3 pb-4 border-b border-border-subtle @lg:flex-row @lg:items-center @lg:justify-between">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-bold text-text-primary tracking-wide">
            Server Instances
          </h2>
          <span className="flex h-5 items-center justify-center rounded-full bg-surface-muted px-2 font-mono text-xs font-semibold text-text-secondary">
            {filteredServers.length}
          </span>
          <Link
            to="/servers"
            className="ms-2 text-xs font-medium text-accent-primary hover:underline"
          >
            View all
          </Link>
        </div>

        {/* Toolbar: Search + Filter Pills + Start All Action */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Search Input */}
          <div className="relative">
            <span className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-2.5 text-text-muted">
              <Icon name="search" size={13} />
            </span>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by name, port, or tag..."
              className="h-8 w-44 @lg:w-56 rounded-lg border border-border-subtle bg-surface-elevated ps-8 pe-2.5 font-mono text-xs text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-hidden"
            />
          </div>

          {/* Filter Pills */}
          <div className="flex items-center rounded-lg bg-surface-muted p-0.5 text-xs font-medium">
            <button
              type="button"
              onClick={() => setFilter("all")}
              className={`rounded-md px-2 py-1 transition-colors ${
                filter === "all"
                  ? "bg-surface-card text-text-primary shadow-2xs font-bold"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              All ({servers.length})
            </button>
            <button
              type="button"
              onClick={() => setFilter("running")}
              className={`rounded-md px-2 py-1 transition-colors ${
                filter === "running"
                  ? "bg-surface-card text-status-success shadow-2xs font-bold"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              Online ({onlineCount})
            </button>
            <button
              type="button"
              onClick={() => setFilter("stopped")}
              className={`rounded-md px-2 py-1 transition-colors ${
                filter === "stopped"
                  ? "bg-surface-card text-text-primary shadow-2xs font-bold"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              Offline ({offlineCount})
            </button>
          </div>

          {/* Bulk Action */}
          <button
            type="button"
            onClick={handleStartAll}
            disabled={isBusy || offlineCount === 0}
            className="flex h-8 items-center gap-1.5 rounded-lg border border-status-success-border bg-status-success-bg px-2.5 text-xs font-semibold text-status-success hover:bg-status-success/20 disabled:opacity-40 transition-colors"
          >
            <Icon name="play" size={12} />
            <span>Start All</span>
          </button>
        </div>
      </div>

      {/* Server Rows */}
      <div className="mt-4 space-y-2.5">
        {filteredServers.length === 0 ? (
          <div className="py-8 text-center text-xs text-text-muted">
            No server instances match the current filter.
          </div>
        ) : (
          filteredServers.map((server) => {
            const isOnline = server.status === "running";
            const isStarting = server.status === "starting";
            const isCrashed = server.status === "crashed";
            const isCooldown =
              startCooldowns[server.server_id] !== undefined &&
              now < startCooldowns[server.server_id];

            return (
              <div
                key={server.server_id}
                className="group relative flex flex-col gap-3 rounded-lg border border-border-subtle bg-surface-elevated p-3.5 transition-all cursor-pointer hover:border-border-default hover:bg-surface-card/80 hover:shadow-xs @3xl:flex-row @3xl:items-center @3xl:justify-between min-w-0"
              >
                {/* Col 1: Identity */}
                <div className="flex items-center gap-3 min-w-0">
                  {/* Status Indicator Dot */}
                  <div className="flex shrink-0 items-center justify-center">
                    {isOnline ? (
                      <span className="relative flex h-2.5 w-2.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-success opacity-75" />
                        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-status-success" />
                      </span>
                    ) : isCrashed ? (
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-status-danger" />
                    ) : (
                      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-text-muted/50" />
                    )}
                  </div>

                  <div className="min-w-0">
                    <Link
                      to={`/servers/${server.server_id}`}
                      className="block truncate text-sm font-bold text-text-primary hover:text-accent-primary transition-colors after:absolute after:inset-0 after:rounded-lg focus:outline-hidden focus-visible:after:ring-2 focus-visible:after:ring-border-focus"
                    >
                      {server.name}
                    </Link>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      <span className="rounded bg-surface-muted px-2 py-0.5 font-mono text-xs text-text-secondary">
                        {server.server_type} {server.minecraft_version}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Col 2: Network & Players */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs min-w-0">
                  {server.port ? (
                    <button
                      type="button"
                      onClick={() => copyPort(server.port)}
                      aria-label={`Copy port ${server.port}`}
                      title="Click to copy server port"
                      className="relative z-10 flex shrink-0 items-center gap-1 rounded bg-surface-muted px-2 py-0.5 font-mono text-xs text-text-secondary hover:text-text-primary transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus cursor-pointer"
                    >
                      <span>:{server.port}</span>
                      <Icon
                        name={copiedPort === server.port ? "check" : "copy"}
                        size={11}
                        className={copiedPort === server.port ? "text-status-success" : "text-text-muted"}
                      />
                    </button>
                  ) : null}

                  <div className="flex items-center gap-1.5 text-text-muted whitespace-nowrap">
                    <Icon name="users" size={13} />
                    <span className="font-mono tabular-nums">
                      {(() => {
                        const snaps = metricsMap?.[server.server_id];
                        const latest = Array.isArray(snaps) && snaps.length
                          ? snaps.reduce((a, b) => (b.timestamp > a.timestamp ? b : a))
                          : undefined;
                        return isOnline ? String(latest?.players ?? 0) : "--";
                      })()}{" "}
                      / {server.max_players || 20} Players
                    </span>
                  </div>
                </div>

                {/* Col 3: Live Instance Telemetry */}
                <div className="min-w-0 flex-1 overflow-hidden text-xs">
                  {(() => {
                    const detail = detailsMap?.[server.server_id];
                    const maxMb = detail?.max_memory_mb ?? 2048;
                    const maxGb = +(maxMb / 1024).toFixed(1);
                    const snaps = metricsMap?.[server.server_id];
                    const latest = Array.isArray(snaps) && snaps.length
                      ? snaps.reduce((a, b) => (b.timestamp > a.timestamp ? b : a))
                      : undefined;
                    const cpuPct = isOnline && latest ? Math.min(100, Math.max(0, latest.cpu_percent)) : 0;
                    const usedMb = isOnline && latest ? latest.ram_used_mb : 0;
                    const usedGb = +(usedMb / 1024).toFixed(1);
                    const ramPct = maxMb > 0 ? Math.min(100, Math.max(0, (usedMb / maxMb) * 100)) : 0;

                    return isOnline ? (
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 font-mono text-[11px] text-text-secondary">
                          <span className="whitespace-nowrap">CPU: {latest ? `${cpuPct.toFixed(1)}%` : "0.0%"}</span>
                          <span className="whitespace-nowrap">RAM: {usedGb.toFixed(1)} / {maxGb.toFixed(1)} GB</span>
                        </div>
                        <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-card">
                          <div style={{ width: `${cpuPct}%` }} className="bg-status-success" />
                          <div style={{ width: `${ramPct}%` }} className="bg-accent-primary" />
                        </div>
                      </div>
                    ) : (
                      <span className="font-mono text-[11px] text-text-muted">
                        Instance halted · {maxGb.toFixed(1)} GB max heap
                      </span>
                    );
                  })()}
                </div>

                {/* Col 4: Action Control Group */}
                <div className="relative z-10 flex items-center justify-end gap-1.5 shrink-0">
                  {isOnline || isStarting ? (
                    <button
                      type="button"
                      onClick={() => handleStop(server.server_id, server.name)}
                      disabled={isBusy || isStarting}
                      className="relative z-10 flex h-8 items-center gap-1.5 rounded-lg border border-status-danger-border bg-status-danger-bg px-3 text-xs font-semibold text-status-danger hover:bg-status-danger/20 disabled:opacity-40 transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus"
                    >
                      <Icon name="stop" size={12} />
                      <span>Stop</span>
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleStart(server.server_id, server.name)}
                      disabled={isBusy || isCooldown}
                      className="relative z-10 flex h-8 items-center gap-1.5 rounded-lg border border-status-success-border bg-status-success-bg px-3 text-xs font-semibold text-status-success hover:bg-status-success/20 disabled:opacity-40 transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus"
                    >
                      <Icon name="play" size={12} />
                      <span>Start</span>
                    </button>
                  )}

                  {/* Terminal / Console Quick Button */}
                  <Link
                    to={`/servers/${server.server_id}/console`}
                    title="Open Console & Terminal"
                    aria-label={`Open terminal for ${server.name}`}
                    className="relative z-10 flex h-8 w-8 items-center justify-center rounded-lg bg-surface-muted text-text-secondary hover:text-text-primary transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus"
                  >
                    <Icon name="terminal" size={14} />
                  </Link>

                  {/* Settings / Configuration Quick Button */}
                  <Link
                    to={`/servers/${server.server_id}/settings`}
                    title="Configure Server"
                    aria-label={`Configure server ${server.name}`}
                    className="relative z-10 flex h-8 w-8 items-center justify-center rounded-lg bg-surface-muted text-text-secondary hover:text-text-primary transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus"
                  >
                    <Icon name="settings" size={14} />
                  </Link>
                </div>
              </div>
            );
          })
        )}
      </div>

      <ConfirmDialog
        open={stopTarget !== null}
        title="Stop Server?"
        description={
          stopTarget
            ? `Are you sure you want to stop "${stopTarget.name}"? Active players will be disconnected.`
            : undefined
        }
        confirmLabel="Stop Server"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={confirmStop}
        onCancel={() => setStopTarget(null)}
      />
    </div>
  );
}
