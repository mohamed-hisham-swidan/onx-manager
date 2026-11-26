import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ServerIcon } from "@/server_manager/components/ServerIcon";
import { ProvisioningProgress } from "@/server_manager/components/ProvisioningProgress";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import { resolveServerMode, serverModeLabel } from "@/server_manager/utils/serverMode";
import {
  formatMemoryMb,
  formatUptime,
  isRetryableProvisioningFailure,
  resolveJoinAddress,
  type ServerLiveTelemetry,
} from "@/server_manager/components/servers/serversUtils";
import { formatRamGb } from "@/server_manager/utils/telemetryAdapter";
import type { ServerResponse } from "@/server_manager/types";
import type { HostResourceBudget } from "@/types";

export interface DashboardFleetPanelProps {
  servers: ServerResponse[];
  metricsByServerId: Record<string, ServerLiveTelemetry>;
  hostBudget?: HostResourceBudget | null;
  busyServerIds: Set<string>;
  startCooldowns: Record<string, number>;
  nowMs: number;
  copiedAddressId: string | null;
  canPower: (serverId: string) => boolean;
  onStart: (server: ServerResponse, e?: React.MouseEvent) => void;
  onStartAll: (targets: ServerResponse[]) => void;
  onStop: (server: ServerResponse, e?: React.MouseEvent) => void;
  onRestart: (server: ServerResponse, e?: React.MouseEvent) => void;
  onRetryProvisioning: (server: ServerResponse, e?: React.MouseEvent) => void;
  onCopyAddress: (address: string, serverId: string, e: React.MouseEvent) => void;
}

type StatusTab = "all" | "online" | "offline";

const OFFLINE_AND_ATTENTION_STATUSES = new Set([
  "stopped",
  "created",
  "crashed",
  "broken",
  "provisioning_failed",
]);

function isStartable(server: ServerResponse): boolean {
  return (
    server.status === "stopped" ||
    server.status === "created" ||
    server.status === "crashed"
  );
}

function tpsColorClass(tps: number | null): string {
  if (tps == null) return "text-text-muted";
  if (tps >= 18) return "text-status-success";
  if (tps >= 15) return "text-status-warning";
  return "text-status-danger";
}

export function DashboardFleetPanel({
  servers,
  metricsByServerId,
  hostBudget,
  busyServerIds,
  startCooldowns,
  nowMs,
  copiedAddressId,
  canPower,
  onStart,
  onStartAll,
  onStop,
  onRestart,
  onRetryProvisioning,
  onCopyAddress,
}: DashboardFleetPanelProps) {
  const [search, setSearch] = useState("");
  const [statusTab, setStatusTab] = useState<StatusTab>("all");
  const [confirmStartAllOpen, setConfirmStartAllOpen] = useState(false);

  const onlineCount = useMemo(
    () => servers.filter((s) => s.status === "running").length,
    [servers],
  );
  const offlineAndAttentionCount = useMemo(
    () => servers.filter((s) => OFFLINE_AND_ATTENTION_STATUSES.has(s.status)).length,
    [servers],
  );

  const startableServers = useMemo(
    () => servers.filter((s) => isStartable(s) && canPower(s.server_id)),
    [servers, canPower],
  );

  const estimatedStartAllRamMb = useMemo(
    () =>
      startableServers.reduce(
        (sum, s) => sum + Math.max(0, s.max_memory_mb ?? 2048),
        0,
      ),
    [startableServers],
  );

  const filteredServers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return servers.filter((s) => {
      if (statusTab === "online" && s.status !== "running") return false;
      if (statusTab === "offline" && !OFFLINE_AND_ATTENTION_STATUSES.has(s.status)) {
        return false;
      }
      if (!q) return true;
      const join = resolveJoinAddress(s).address.toLowerCase();
      return (
        s.name.toLowerCase().includes(q) ||
        String(s.port).includes(q) ||
        join.includes(q) ||
        (s.server_type ?? "").toLowerCase().includes(q) ||
        (s.minecraft_version ?? "").toLowerCase().includes(q)
      );
    });
  }, [servers, search, statusTab]);

  const hasActiveFilters = search.trim().length > 0 || statusTab !== "all";
  const exceedsBudgetForStartAll =
    Boolean(hostBudget) &&
    typeof hostBudget?.available_ram_mb === "number" &&
    estimatedStartAllRamMb > hostBudget.available_ram_mb;

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-card">
      {/* Header Toolbar */}
      <div className="flex flex-col gap-3 border-b border-border-subtle px-4 py-3.5 @lg:flex-row @lg:items-center @lg:justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <h2 className="text-sm font-semibold text-text-primary">Servers</h2>
          <span className="inline-flex items-center rounded-full bg-surface-muted px-2 py-0.5 text-xs font-mono tabular-nums text-text-secondary">
            {servers.length}
          </span>
          <Link
            to="/servers"
            className="inline-flex items-center gap-0.5 text-xs font-medium text-text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus rounded whitespace-nowrap"
          >
            <span>View all</span>
            <Icon name="chevron-right" size={12} />
          </Link>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Search Input */}
          <div className="relative flex-1 sm:flex-initial sm:w-52">
            <Icon
              name="search"
              size={13}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name, port, loader..."
              aria-label="Search servers"
              className="h-8 w-full rounded-lg border border-border-default bg-surface-card pl-8 pr-7 text-xs text-text-primary placeholder:text-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            />
            {search.length > 0 && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => setSearch("")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-text-muted hover:text-text-primary cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
              >
                <Icon name="x" size={12} />
              </button>
            )}
          </div>

          {/* Segmented Status Pills */}
          <div
            role="group"
            aria-label="Filter server list by status"
            className="inline-flex rounded-lg bg-surface-muted p-0.5 text-xs"
          >
            {(
              [
                { id: "all", label: `All (${servers.length})` },
                { id: "online", label: `Online (${onlineCount})` },
                { id: "offline", label: `Offline (${offlineAndAttentionCount})` },
              ] as const
            ).map((pill) => {
              const active = statusTab === pill.id;
              return (
                <button
                  key={pill.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setStatusTab(pill.id)}
                  className={`rounded-md px-2.5 py-1 font-medium transition-colors whitespace-nowrap cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus ${
                    active
                      ? "bg-surface-card text-text-primary shadow-2xs"
                      : "text-text-muted hover:text-text-primary"
                  }`}
                >
                  {pill.label}
                </button>
              );
            })}
          </div>

          {/* Safe Start All */}
          {startableServers.length > 1 && (
            <button
              type="button"
              onClick={() => setConfirmStartAllOpen(true)}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 text-xs font-semibold text-text-primary transition-colors hover:bg-surface-hover hover:border-border-strong cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus whitespace-nowrap"
            >
              <Icon name="play" size={12} className="text-status-success" />
              <span>Start All</span>
            </button>
          )}
        </div>
      </div>

      {/* Server List Body */}
      {filteredServers.length === 0 ? (
        <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
          <div className="mb-2.5 flex h-10 w-10 items-center justify-center rounded-xl bg-surface-muted text-text-muted">
            <Icon name="search" size={18} />
          </div>
          <p className="text-sm font-medium text-text-primary">
            No servers match your current filter.
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Try another search query or reset status filters.
          </p>
          {hasActiveFilters && (
            <button
              type="button"
              onClick={() => {
                setSearch("");
                setStatusTab("all");
              }}
              className="mt-4 inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 text-xs font-semibold text-text-primary transition-colors hover:bg-surface-hover cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
            >
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {filteredServers.map((s) => {
            const telemetry = metricsByServerId[s.server_id];
            const isRunning = s.status === "running";
            const isStarting = s.status === "starting";
            const isStopping = s.status === "stopping";
            const isProvisioning = s.status === "provisioning";
            const isProvisioningError =
              s.status === "provisioning_failed" || s.status === "broken";
            const canPowerServer = canPower(s.server_id);
            const isBusy = busyServerIds.has(s.server_id);
            const cooldownUntil = startCooldowns[s.server_id] ?? 0;
            const isStartCooldown = cooldownUntil > nowMs;

            const { address, isPublic } = resolveJoinAddress(s);
            const isCopied = copiedAddressId === s.server_id;
            const uptimeText = formatUptime(s.uptime_seconds);
            const ramLimitMb = telemetry?.ramLimitMb ?? s.max_memory_mb ?? null;
            const ramUsedMb = telemetry?.ramUsedMb ?? null;
            const ramPct =
              ramUsedMb != null && ramLimitMb && ramLimitMb > 0
                ? Math.min(100, Math.max(0, (ramUsedMb / ramLimitMb) * 100))
                : 0;
            const modeLabel = serverModeLabel(resolveServerMode(s.mode));
            const cleanMotd = s.motd ? stripMinecraftFormatting(s.motd).trim() : "";

            return (
              <article
                key={s.server_id}
                className="group relative flex flex-col gap-2.5 px-4 py-3.5 transition-colors hover:bg-surface-hover/50 cursor-pointer"
              >
                {/* Line 1: Identity + Per-Server Actions */}
                <div className="flex flex-col gap-2.5 @2xl:flex-row @2xl:items-center @2xl:justify-between">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <ServerIcon
                      serverId={s.server_id}
                      serverName={s.name}
                      serverType={s.server_type}
                      status={s.status}
                      iconDataUrl={s.icon_data_url ?? null}
                      size={40}
                    />

                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2 min-w-0">
                        <Link
                          to={`/servers/${s.server_id}/console`}
                          className="truncate text-sm font-semibold text-text-primary transition-colors group-hover:text-text-accent after:absolute after:inset-0 after:z-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus rounded"
                        >
                          {s.name}
                        </Link>
                        <StatusBadge status={s.status} />
                        <LoaderBadge loader={s.server_type} />
                        {s.minecraft_version && (
                          <span className="rounded-md bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">
                            {s.minecraft_version}
                          </span>
                        )}
                        <span className="rounded-md bg-surface-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                          {modeLabel}
                        </span>
                        {s.active_branch && s.active_branch !== "main" && (
                          <span className="inline-flex items-center gap-1 rounded-md bg-surface-muted px-1.5 py-0.5 font-mono text-[10px] text-text-accent">
                            <Icon name="version-branch" size={10} />
                            <span>{s.active_branch}</span>
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Per-server controls (above stretched overlay) */}
                  <div className="relative z-10 flex flex-wrap items-center gap-1.5 shrink-0">
                    {canPowerServer && (
                      <>
                        {(isRunning || isStarting) && (
                          <>
                            {isRunning && (
                              <button
                                type="button"
                                disabled={isBusy}
                                onClick={(e) => onRestart(s, e)}
                                className="inline-flex h-8 items-center gap-1 rounded-lg border border-border-default bg-surface-card px-2.5 text-xs font-medium text-text-primary transition-colors hover:bg-surface-hover disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                              >
                                <Icon name="restart" size={12} />
                                <span>Restart</span>
                              </button>
                            )}
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={(e) => onStop(s, e)}
                              className="inline-flex h-8 items-center gap-1 rounded-lg border border-status-danger/40 bg-status-danger-bg px-2.5 text-xs font-semibold text-status-danger transition-colors hover:opacity-90 disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                            >
                              <Icon name="stop" size={12} />
                              <span>Stop</span>
                            </button>
                          </>
                        )}

                        {isStartable(s) && (
                          <button
                            type="button"
                            disabled={isBusy || isStartCooldown}
                            onClick={(e) => onStart(s, e)}
                            className="inline-flex h-8 items-center gap-1 rounded-lg bg-accent-primary px-3 text-xs font-semibold text-accent-contrast-text transition-colors hover:bg-accent-hover disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                          >
                            <Icon name="play" size={12} />
                            <span>{isBusy ? "Starting..." : isStartCooldown ? "Starting..." : "Start"}</span>
                          </button>
                        )}

                        {isProvisioningError &&
                          (isRetryableProvisioningFailure(s) ||
                            (s.status === "broken" && s.provisioning_retryable !== false)) && (
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={(e) => onRetryProvisioning(s, e)}
                              className="inline-flex h-8 items-center gap-1 rounded-lg border border-status-warning/40 bg-status-warning-bg px-2.5 text-xs font-semibold text-status-warning transition-colors hover:opacity-90 disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                            >
                              <Icon name="restart" size={12} />
                              <span>Retry</span>
                            </button>
                          )}

                        {isStopping && (
                          <span className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-surface-muted px-2.5 text-xs font-medium text-text-muted">
                            <Icon name="clock" size={12} />
                            <span>Stopping...</span>
                          </span>
                        )}
                      </>
                    )}

                    <Link
                      to={`/servers/${s.server_id}/console`}
                      title="Open Console & Terminal"
                      aria-label={`Open Console & Terminal for ${s.name}`}
                      className="relative z-10 inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border-subtle bg-surface-card text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                    >
                      <Icon name="terminal" size={14} />
                    </Link>

                    <Link
                      to={`/servers/${s.server_id}/settings`}
                      title="Configure Server"
                      aria-label={`Configure ${s.name}`}
                      className="relative z-10 inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border-subtle bg-surface-card text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                    >
                      <Icon name="settings" size={14} />
                    </Link>
                  </div>
                </div>

                {/* Line 2: Join Address + Live Telemetry / Provisioning / Offline Specs */}
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border-subtle/60 pt-2 text-xs">
                  <button
                    type="button"
                    onClick={(e) => onCopyAddress(address, s.server_id, e)}
                    aria-label={`Copy join address ${address}`}
                    title={`Copy join address: ${address}`}
                    className="relative z-10 inline-flex shrink-0 items-center gap-1.5 rounded-md bg-surface-muted px-2 py-1 font-mono text-[11px] font-medium text-text-primary transition-colors hover:bg-surface-hover cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                  >
                    {isPublic && (
                      <Icon name="globe" size={11} className="shrink-0 text-status-success" />
                    )}
                    <span className="max-w-[200px] truncate">{address}</span>
                    <Icon
                      name={isCopied ? "check" : "copy"}
                      size={11}
                      className={
                        isCopied ? "shrink-0 text-status-success" : "shrink-0 text-text-muted"
                      }
                    />
                  </button>

                  {isRunning ? (
                    <div className="flex flex-1 min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5 overflow-hidden @lg:justify-end font-mono tabular-nums text-[11px]">
                      <span className="text-text-primary whitespace-nowrap">
                        {telemetry?.players ?? 0} / {s.max_players || 20} Players
                      </span>
                      <span className={`font-semibold whitespace-nowrap ${tpsColorClass(telemetry?.tps ?? null)}`}>
                        {telemetry?.tps != null ? `${telemetry.tps.toFixed(1)} TPS` : "— TPS"}
                      </span>
                      <span className="text-text-secondary whitespace-nowrap">
                        CPU: {telemetry?.cpuPercent != null ? `${telemetry.cpuPercent.toFixed(1)}%` : "0.0%"}
                      </span>
                      <div className="inline-flex items-center gap-2 whitespace-nowrap">
                        <span className="text-text-secondary">
                          RAM: {ramUsedMb != null ? formatRamGb(ramUsedMb) : "0.0 GB"}
                          {ramLimitMb ? ` / ${formatRamGb(ramLimitMb)}` : ""}
                        </span>
                        {ramLimitMb ? (
                          <div className="hidden sm:block h-1.5 w-14 overflow-hidden rounded-full bg-surface-muted">
                            <div
                              className={`h-full transition-all duration-300 ${
                                ramPct >= 85 ? "bg-status-warning" : "bg-accent-primary"
                              }`}
                              style={{ width: `${ramPct}%` }}
                            />
                          </div>
                        ) : null}
                      </div>
                      {uptimeText && (
                        <span className="text-text-muted whitespace-nowrap">{uptimeText}</span>
                      )}
                    </div>
                  ) : isProvisioning ? (
                    <div className="flex-1 min-w-[180px]">
                      <ProvisioningProgress
                        serverId={s.server_id}
                        compact
                        initialSnapshot={s.provisioning_progress ?? null}
                      />
                    </div>
                  ) : isProvisioningError && s.provisioning_error ? (
                    <p className="flex-1 min-w-0 truncate text-[11px] font-medium text-status-danger">
                      {s.provisioning_error}
                    </p>
                  ) : (
                    <div className="flex flex-1 min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 overflow-hidden @lg:justify-end text-[11px] text-text-muted">
                      <span className="capitalize whitespace-nowrap">{s.gamemode}</span>
                      <span aria-hidden="true">·</span>
                      <span className="whitespace-nowrap font-mono tabular-nums">
                        Max {s.max_players || 20}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span className="whitespace-nowrap font-mono tabular-nums">
                        {s.max_memory_mb ? formatMemoryMb(s.max_memory_mb) : "Auto RAM"}
                      </span>
                      {cleanMotd && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="truncate max-w-[220px]">{cleanMotd}</span>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {/* Safe Start All Confirmation */}
      <ConfirmDialog
        open={confirmStartAllOpen}
        title={`Start ${startableServers.length} servers?`}
        description={
          exceedsBudgetForStartAll && hostBudget
            ? `This will start ${startableServers.length} servers requiring ~${formatRamGb(estimatedStartAllRamMb)} RAM, which exceeds ${formatMemoryMb(hostBudget.available_ram_mb)} currently free host memory.`
            : `This will start ${startableServers.length} stopped servers (${startableServers.map((s) => s.name).slice(0, 3).join(", ")}${startableServers.length > 3 ? ` +${startableServers.length - 3} more` : ""}).`
        }
        confirmLabel="Start All Servers"
        cancelLabel="Cancel"
        variant={exceedsBudgetForStartAll ? "danger" : "info"}
        onConfirm={() => {
          setConfirmStartAllOpen(false);
          onStartAll(startableServers);
        }}
        onCancel={() => setConfirmStartAllOpen(false)}
      />
    </div>
  );
}
