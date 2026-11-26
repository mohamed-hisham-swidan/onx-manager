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

export interface ServerCardProps {
  server: ServerResponse;
  telemetry?: ServerLiveTelemetry;
  isDeleting: boolean;
  isBusy: boolean;
  isStartCooldown: boolean;
  copiedAddressId: string | null;
  canPower: boolean;
  canFiles?: boolean;
  onStart: (server: ServerResponse, e?: React.MouseEvent) => void;
  onStop: (server: ServerResponse, e?: React.MouseEvent) => void;
  onRestart: (server: ServerResponse, e?: React.MouseEvent) => void;
  onRetryProvisioning: (server: ServerResponse, e?: React.MouseEvent) => void;
  onCopyAddress: (address: string, serverId: string, e: React.MouseEvent) => void;
}

function tpsColorClass(tps: number | null): string {
  if (tps == null) return "text-text-muted";
  if (tps >= 18) return "text-status-success";
  if (tps >= 15) return "text-status-warning";
  return "text-status-danger";
}

export function ServerCard({
  server: s,
  telemetry,
  isDeleting,
  isBusy,
  isStartCooldown,
  copiedAddressId,
  canPower,
  canFiles = true,
  onStart,
  onStop,
  onRestart,
  onRetryProvisioning,
  onCopyAddress,
}: ServerCardProps) {
  const navigate = useNavigate();
  const isRunning = s.status === "running";
  const isStarting = s.status === "starting";
  const isStopping = s.status === "stopping";
  const isProvisioning = s.status === "provisioning";
  const isProvisioningFailed = s.status === "provisioning_failed";
  const isBroken = s.status === "broken";
  const showStartButton = ["stopped", "created", "crashed"].includes(s.status);
  const canRetry =
    isRetryableProvisioningFailure(s) ||
    (isBroken && s.provisioning_retryable !== false);

  const serverMode = resolveServerMode(s.mode);
  const cleanMotd = s.motd ? stripMinecraftFormatting(s.motd) : "";
  const { address, isPublic } = resolveJoinAddress(s);
  const isCopied = copiedAddressId === s.server_id;
  const uptimeText = isRunning ? formatUptime(s.uptime_seconds) : null;

  const ramLimitMb = telemetry?.ramLimitMb ?? s.max_memory_mb ?? null;
  const ramUsedMb = telemetry?.ramUsedMb ?? null;
  const ramPct =
    ramUsedMb != null && ramLimitMb && ramLimitMb > 0
      ? Math.min(100, Math.round((ramUsedMb / ramLimitMb) * 100))
      : 0;

  const cpuPercent = telemetry?.cpuPercent ?? null;
  const cpuBarPct =
    cpuPercent != null ? Math.min(100, Math.max(0, Math.round(cpuPercent))) : 0;

  return (
    <article
      data-testid={`server-card-${s.server_id}`}
      onClick={() => {
        if (isDeleting) return;
        navigate(`/servers/${s.server_id}/console`);
      }}
      className={`group relative flex flex-col justify-between rounded-2xl border border-border-subtle bg-surface-card p-5 shadow-2xs transition-all duration-150 ${
        isDeleting
          ? "opacity-60 pointer-events-none"
          : "hover:-translate-y-0.5 hover:border-border-default hover:bg-surface-hover/25 hover:shadow-md cursor-pointer"
      }`}
    >
      <div className="space-y-4">
        {/* Zone 1: Identity Header */}
        <div className="space-y-2.5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3.5">
              <ServerIcon
                serverId={s.server_id}
                serverName={s.name}
                serverType={s.server_type}
                status={s.status}
                iconDataUrl={s.icon_data_url}
                size={48}
              />
              <div className="min-w-0">
                <Link
                  to={`/servers/${s.server_id}/console`}
                  title={s.name}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (isDeleting) e.preventDefault();
                  }}
                  className="block truncate text-base font-semibold text-text-primary transition-colors group-hover:text-text-accent"
                >
                  {s.name}
                </Link>
              </div>
            </div>

            <div className="shrink-0">
              <StatusBadge
                status={s.status}
                className={isRunning || isStarting ? "animate-none" : ""}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <LoaderBadge loader={s.server_type} />
            <span className="whitespace-nowrap rounded-md border border-border-subtle bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">
              {s.minecraft_version}
            </span>
            <span className="whitespace-nowrap rounded-md border border-border-subtle bg-surface-elevated px-1.5 py-0.5 text-[11px] font-medium text-text-muted">
              {serverModeLabel(serverMode)}
            </span>
            {s.active_branch && s.active_branch !== "main" && (
              <span className="inline-flex whitespace-nowrap items-center gap-1 rounded-md border border-accent-primary/25 bg-accent-primary/10 px-1.5 py-0.5 font-mono text-[11px] font-medium text-text-accent">
                <Icon name="version-branch" size={11} />
                <span>{s.active_branch}</span>
              </span>
            )}
            {uptimeText && (
              <span
                data-testid="server-card-uptime"
                className="ml-auto whitespace-nowrap font-mono text-[11px] text-text-muted"
              >
                {uptimeText}
              </span>
            )}
          </div>
        </div>

        {/* Zone 2: MOTD & 1-Click Copyable Join Address */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border-subtle bg-surface-muted/60 px-3 py-2">
          <p
            className="min-w-0 flex-1 truncate text-xs text-text-secondary"
            title={cleanMotd || "No MOTD configured"}
          >
            {cleanMotd || "Ready for players"}
          </p>

          <button
            type="button"
            onClick={(e) => onCopyAddress(address, s.server_id, e)}
            aria-label={`Copy join address ${address}`}
            title={`Copy join address: ${address}`}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-card px-2 py-1 font-mono text-[11px] font-medium text-text-primary transition-colors hover:border-border-default hover:bg-surface-hover cursor-pointer"
          >
            {isPublic && (
              <Icon name="globe" size={11} className="text-status-success shrink-0" />
            )}
            <span className="max-w-[165px] truncate">{address}</span>
            <Icon
              name={isCopied ? "check" : "copy"}
              size={11}
              className={isCopied ? "text-status-success shrink-0" : "text-text-muted shrink-0"}
            />
          </button>
        </div>

        {/* Zone 3: Alive Telemetry / Provisioning / Offline Specs */}
        {isRunning ? (
          <div className="space-y-2.5 rounded-xl border border-border-subtle bg-surface-elevated/70 p-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[11px] text-text-muted">Players</div>
                <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums text-text-primary">
                  {telemetry?.players != null ? telemetry.players : 0}{" "}
                  <span className="text-xs font-normal text-text-muted">
                    / {s.max_players || 20}
                  </span>
                </div>
              </div>

              <div>
                <div className="text-[11px] text-text-muted">TPS</div>
                <div
                  className={`mt-0.5 font-mono text-sm font-semibold tabular-nums ${tpsColorClass(
                    telemetry?.tps ?? null,
                  )}`}
                >
                  {telemetry?.tps != null ? telemetry.tps.toFixed(1) : "—"}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 border-t border-border-subtle/70 pt-2.5">
              <div>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-text-muted">Memory</span>
                  <span className="font-mono tabular-nums text-text-secondary">
                    {ramUsedMb != null ? formatMemoryMb(ramUsedMb) : "0 MB"}
                    {ramLimitMb ? ` / ${formatMemoryMb(ramLimitMb)}` : ""}
                  </span>
                </div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-muted">
                  <div
                    className={`h-full transition-all duration-300 ${
                      ramPct >= 85 ? "bg-status-warning" : "bg-accent-primary"
                    }`}
                    style={{ width: `${ramPct}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-text-muted">CPU</span>
                  <span className="font-mono tabular-nums text-text-secondary">
                    {cpuPercent != null ? `${cpuPercent.toFixed(1)}%` : "0.0%"}
                  </span>
                </div>
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-muted">
                  <div
                    className={`h-full transition-all duration-300 ${
                      cpuBarPct >= 85 ? "bg-status-warning" : "bg-status-success"
                    }`}
                    style={{ width: `${cpuBarPct}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        ) : isProvisioning ? (
          <div className="rounded-xl border border-border-subtle bg-surface-elevated/70 p-3">
            <ProvisioningProgress
              serverId={s.server_id}
              compact
              initialSnapshot={s.provisioning_progress ?? null}
            />
          </div>
        ) : isProvisioningFailed || isBroken ? (
          <div
            role="status"
            className="flex flex-col gap-2 rounded-xl border border-status-danger-border bg-status-danger-bg/60 p-3 text-xs"
          >
            <div className="flex items-start gap-2 text-status-danger">
              <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
              <span className="line-clamp-2">
                {s.provisioning_error ||
                  (isBroken
                    ? "Server files require repair before starting."
                    : "Provisioning failed.")}
              </span>
            </div>
            {(isProvisioningFailed || isBroken) && canRetry && canPower && (
              <button
                type="button"
                onClick={(e) => onRetryProvisioning(s, e)}
                disabled={isBusy}
                aria-label={
                  isBroken
                    ? `Retry ${s.name}`
                    : `Retry Provisioning ${s.name}`
                }
                className="inline-flex w-fit items-center gap-1.5 rounded-lg border border-status-warning-border bg-surface-card px-2.5 py-1 text-xs font-semibold text-status-warning transition-colors hover:bg-status-warning-bg disabled:opacity-40 cursor-pointer"
              >
                <Icon name="restart" size={12} />
                <span>{isBroken ? "Retry" : "Retry Provisioning"}</span>
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-3 divide-x divide-border-subtle rounded-xl bg-surface-muted/50 py-2.5 text-center">
            <div className="px-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                Gamemode
              </div>
              <div className="mt-0.5 truncate font-mono text-xs capitalize text-text-primary">
                {s.gamemode || "survival"}
              </div>
            </div>
            <div className="px-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                Max Players
              </div>
              <div className="mt-0.5 font-mono text-xs tabular-nums text-text-primary">
                {s.max_players || 20}
              </div>
            </div>
            <div className="px-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                Memory
              </div>
              <div className="mt-0.5 font-mono text-xs tabular-nums text-text-primary">
                {ramLimitMb ? formatMemoryMb(ramLimitMb) : "Auto"}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Zone 4: Footer Action Bar */}
      <div
        className="mt-4 flex items-center justify-between border-t border-border-subtle/70 pt-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-1">
          <Link
            to={`/servers/${s.server_id}/console`}
            onClick={(e) => {
              if (isDeleting) e.preventDefault();
            }}
            title="Open Console"
            aria-label={`Open Console ${s.name}`}
            className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
          >
            <Icon name="console" size={15} />
          </Link>
          {canFiles && (
            <Link
              to={`/servers/${s.server_id}/files`}
              onClick={(e) => {
                if (isDeleting) e.preventDefault();
              }}
              title="Browse Files"
              aria-label={`Browse Files ${s.name}`}
              className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
            >
              <Icon name="files" size={15} />
            </Link>
          )}
          <Link
            to={`/servers/${s.server_id}/backups`}
            onClick={(e) => {
              if (isDeleting) e.preventDefault();
            }}
            title="View Backups"
            aria-label={`View Backups ${s.name}`}
            className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
          >
            <Icon name="backup" size={15} />
          </Link>
          <Link
            to={`/servers/${s.server_id}/settings`}
            onClick={(e) => {
              if (isDeleting) e.preventDefault();
            }}
            title="Server Settings"
            aria-label={`Server Settings ${s.name}`}
            className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
          >
            <Icon name="settings" size={15} />
          </Link>
        </div>

        <div className="flex items-center gap-1">
          {canPower && showStartButton && (
            <button
              type="button"
              onClick={(e) => onStart(s, e)}
              disabled={isBusy || isStartCooldown}
              aria-label={`Start ${s.name}`}
              title="Start"
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-status-success transition-colors hover:bg-status-success-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
            >
              <Icon name="play" size={14} />
              <span>Start</span>
            </button>
          )}

          {canPower && (isRunning || isStarting) && (
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
                  <Icon name="restart" size={15} />
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
                <Icon name="stop" size={15} />
              </button>
            </>
          )}

          {isStopping && (
            <span
              aria-label={`${s.name} is stopping`}
              className="inline-flex items-center gap-1.5 px-2 py-1 text-xs text-text-muted"
            >
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-border-default border-t-accent-primary" />
              <span>Stopping...</span>
            </span>
          )}
        </div>
      </div>
    </article>
  );
}
