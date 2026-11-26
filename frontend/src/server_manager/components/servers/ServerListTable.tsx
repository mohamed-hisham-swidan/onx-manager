import { Link, useNavigate } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { ServerIcon } from "@/server_manager/components/ServerIcon";
import { ProvisioningProgress } from "@/server_manager/components/ProvisioningProgress";
import { stripMinecraftFormatting } from "@/server_manager/utils/motd";
import { resolveServerMode, serverModeLabel } from "@/server_manager/utils/serverMode";
import type { ServerResponse } from "@/server_manager/types";
import {
  formatMemoryMb,
  formatUptime,
  isRetryableProvisioningFailure,
  resolveJoinAddress,
  type ServerLiveTelemetry,
} from "./serversUtils";

export interface ServerListTableProps {
  servers: ServerResponse[];
  metricsByServerId: Record<string, ServerLiveTelemetry>;
  deletingIds: Record<string, boolean>;
  deleteTargetId: string | null;
  busyServerIds: Set<string>;
  startCooldowns: Record<string, number>;
  now: number;
  copiedAddressId: string | null;
  canPower: (serverId: string) => boolean;
  canDelete: boolean;
  onStart: (server: ServerResponse, e?: React.MouseEvent) => void;
  onStop: (server: ServerResponse, e?: React.MouseEvent) => void;
  onRestart: (server: ServerResponse, e?: React.MouseEvent) => void;
  onDelete: (server: ServerResponse, e?: React.MouseEvent) => void;
  onRetryProvisioning: (server: ServerResponse, e?: React.MouseEvent) => void;
  onCopyAddress: (address: string, serverId: string, e: React.MouseEvent) => void;
}

export function ServerListTable({
  servers,
  metricsByServerId,
  deletingIds,
  deleteTargetId,
  busyServerIds,
  startCooldowns,
  now,
  copiedAddressId,
  canPower,
  canDelete,
  onStart,
  onStop,
  onRestart,
  onDelete,
  onRetryProvisioning,
  onCopyAddress,
}: ServerListTableProps) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto rounded-2xl border border-border-subtle bg-surface-card shadow-2xs">
      <table className="w-full text-sm text-text-primary border-collapse">
        <thead>
          <tr className="border-b border-border-subtle bg-surface-muted/40 text-xs font-semibold uppercase tracking-wider text-text-secondary">
            <th scope="col" className="px-4 py-3 text-left">Server</th>
            <th scope="col" className="hidden px-4 py-3 text-left sm:table-cell">Software</th>
            <th scope="col" className="hidden px-4 py-3 text-left md:table-cell">Join Address</th>
            <th scope="col" className="hidden px-4 py-3 text-left lg:table-cell">Telemetry</th>
            <th scope="col" className="px-4 py-3 text-left">Status</th>
            <th scope="col" className="px-4 py-3 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {servers.map((s) => {
            const isDeleting =
              Boolean(deletingIds[s.server_id]) || deleteTargetId === s.server_id;
            const isBusy = busyServerIds.has(s.server_id);
            const isCooldown =
              startCooldowns[s.server_id] !== undefined && now < startCooldowns[s.server_id];
            const telemetry = metricsByServerId[s.server_id];
            const { address, isPublic } = resolveJoinAddress(s);
            const isCopied = copiedAddressId === s.server_id;
            const cleanMotd = s.motd ? stripMinecraftFormatting(s.motd) : "";
            const serverMode = resolveServerMode(s.mode);
            const isRunning = s.status === "running";
            const isStarting = s.status === "starting";
            const isStopping = s.status === "stopping";
            const isProvisioning = s.status === "provisioning";
            const canRetry = isRetryableProvisioningFailure(s);
            const ramLimitMb = telemetry?.ramLimitMb ?? s.max_memory_mb ?? null;
            const uptimeText = isRunning ? formatUptime(s.uptime_seconds) : null;
            const allowPower = canPower(s.server_id);

            return (
              <tr
                key={s.server_id}
                onClick={() => {
                  if (isDeleting) return;
                  navigate(`/servers/${s.server_id}/console`);
                }}
                className={`transition-colors ${
                  isDeleting
                    ? "opacity-60 pointer-events-none"
                    : "hover:bg-surface-hover/50 cursor-pointer"
                }`}
              >
                {/* Server Identity (+ mobile metadata fallback) */}
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <ServerIcon
                      serverId={s.server_id}
                      serverName={s.name}
                      serverType={s.server_type}
                      status={s.status}
                      iconDataUrl={s.icon_data_url}
                      size={40}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Link
                          to={`/servers/${s.server_id}/console`}
                          title={s.name}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (isDeleting) e.preventDefault();
                          }}
                          className="truncate font-semibold text-text-primary hover:text-text-accent hover:underline"
                        >
                          {s.name}
                        </Link>
                        {s.active_branch && s.active_branch !== "main" && (
                          <span className="hidden sm:inline-flex items-center gap-1 rounded bg-accent-primary/10 px-1.5 py-0.5 font-mono text-[10px] text-text-accent">
                            {s.active_branch}
                          </span>
                        )}
                      </div>
                      {cleanMotd && (
                        <p className="mt-0.5 max-w-[260px] truncate text-xs text-text-muted">
                          {cleanMotd}
                        </p>
                      )}
                      {/* Mobile-only summary so loader, version, and address remain visible */}
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 sm:hidden">
                        <LoaderBadge loader={s.server_type} />
                        <span className="font-mono text-[11px] text-text-secondary">
                          {s.minecraft_version}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => onCopyAddress(address, s.server_id, e)}
                          aria-label={`Copy join address ${address}`}
                          className="inline-flex items-center gap-1 rounded border border-border-subtle bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-text-primary"
                        >
                          <span>{address}</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </td>

                {/* Software / Version / Mode */}
                <td className="hidden px-4 py-3 text-text-secondary sm:table-cell">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <LoaderBadge loader={s.server_type} />
                    <span className="font-mono text-xs">{s.minecraft_version}</span>
                    <span className="rounded border border-border-subtle bg-surface-elevated px-1.5 py-0.5 text-[10px] text-text-muted">
                      {serverModeLabel(serverMode)}
                    </span>
                  </div>
                </td>

                {/* Copyable Join Address */}
                <td className="hidden px-4 py-3 md:table-cell" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    onClick={(e) => onCopyAddress(address, s.server_id, e)}
                    aria-label={`Copy join address ${address}`}
                    title={`Copy join address: ${address}`}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-muted/70 px-2 py-1 font-mono text-xs text-text-primary transition-colors hover:border-border-default hover:bg-surface-hover cursor-pointer"
                  >
                    {isPublic && <Icon name="globe" size={12} className="text-status-success" />}
                    <span className="max-w-[180px] truncate">{address}</span>
                    <Icon
                      name={isCopied ? "check" : "copy"}
                      size={12}
                      className={isCopied ? "text-status-success" : "text-text-muted"}
                    />
                  </button>
                </td>

                {/* Live Telemetry or Static Specs */}
                <td className="hidden px-4 py-3 lg:table-cell">
                  {isRunning ? (
                    <div className="space-y-1 font-mono text-xs tabular-nums">
                      <div className="flex items-center gap-2.5 text-text-primary">
                        <span>
                          {telemetry?.players ?? 0}/{s.max_players || 20} players
                        </span>
                        <span className="text-text-muted">·</span>
                        <span>
                          {telemetry?.tps != null ? `${telemetry.tps.toFixed(1)} TPS` : "— TPS"}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-text-muted">
                        <span>
                          RAM {telemetry?.ramUsedMb != null ? formatMemoryMb(telemetry.ramUsedMb) : "0 MB"}
                          {ramLimitMb ? ` / ${formatMemoryMb(ramLimitMb)}` : ""}
                        </span>
                        <span>·</span>
                        <span>
                          CPU {telemetry?.cpuPercent != null ? `${telemetry.cpuPercent.toFixed(1)}%` : "0.0%"}
                        </span>
                        {uptimeText && (
                          <>
                            <span>·</span>
                            <span>{uptimeText}</span>
                          </>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="font-mono text-xs text-text-muted capitalize">
                      {s.gamemode || "survival"} · {s.max_players || 20} slots ·{" "}
                      {ramLimitMb ? formatMemoryMb(ramLimitMb) : "Auto"}
                    </div>
                  )}
                </td>

                {/* Status / Provisioning */}
                <td className="px-4 py-3">
                  <div className="flex flex-col items-start gap-1">
                    <StatusBadge status={s.status} />
                    {isProvisioning && (
                      <ProvisioningProgress
                        serverId={s.server_id}
                        compact
                        initialSnapshot={s.provisioning_progress ?? null}
                        className="min-w-[140px]"
                      />
                    )}
                    {s.status === "provisioning_failed" && s.provisioning_error && (
                      <span
                        title={s.provisioning_error}
                        className="max-w-[180px] truncate text-[11px] text-status-danger"
                      >
                        {s.provisioning_error}
                      </span>
                    )}
                  </div>
                </td>

                {/* Actions */}
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center justify-end gap-1">
                    {allowPower && ["stopped", "created", "crashed"].includes(s.status) && (
                      <button
                        type="button"
                        onClick={(e) => onStart(s, e)}
                        disabled={isBusy || isCooldown}
                        aria-label={`Start ${s.name}`}
                        title="Start"
                        className="rounded-lg p-1.5 text-status-success transition-colors hover:bg-status-success-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                      >
                        <Icon name="play" size={16} />
                      </button>
                    )}

                    {allowPower && canRetry && (
                      <button
                        type="button"
                        onClick={(e) => onRetryProvisioning(s, e)}
                        disabled={isBusy}
                        aria-label={`Retry Provisioning ${s.name}`}
                        title="Retry Provisioning"
                        className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                      >
                        <Icon name="restart" size={16} />
                      </button>
                    )}

                    {allowPower && (isRunning || isStarting) && (
                      <>
                        {isRunning && (
                          <button
                            type="button"
                            onClick={(e) => onRestart(s, e)}
                            disabled={isBusy}
                            aria-label={`Restart ${s.name}`}
                            title="Restart"
                            className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                          >
                            <Icon name="restart" size={16} />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={(e) => onStop(s, e)}
                          disabled={isBusy}
                          aria-label={`Stop ${s.name}`}
                          title="Stop"
                          className="rounded-lg p-1.5 text-status-danger transition-colors hover:bg-status-danger-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                        >
                          <Icon name="stop" size={16} />
                        </button>
                      </>
                    )}

                    {isStopping && (
                      <span
                        aria-label={`${s.name} is stopping`}
                        className="inline-flex h-7 w-7 items-center justify-center text-text-muted"
                      >
                        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-border-default border-t-accent-primary" />
                      </span>
                    )}

                    <Link
                      to={`/servers/${s.server_id}/console`}
                      onClick={(e) => {
                        if (isDeleting) e.preventDefault();
                      }}
                      title="Open Console"
                      aria-label={`Open Console ${s.name}`}
                      className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
                    >
                      <Icon name="console" size={16} />
                    </Link>

                    {canDelete && (
                      <button
                        type="button"
                        onClick={(e) => onDelete(s, e)}
                        disabled={isDeleting}
                        aria-label={`Delete ${s.name}`}
                        title="Delete"
                        className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-status-danger-bg hover:text-status-danger disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                      >
                        <Icon name="trash" size={16} />
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
  );
}
