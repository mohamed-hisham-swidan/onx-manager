import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useStartServer, useStopServer, useRestartServer, useRetryProvisioningServer } from "@/server_manager/hooks/useServers";
import { STATUS_MAP } from "@/server_manager/types";
import { toast } from "@/stores/toastStore";
import { useEffectiveConnectionState, useIsChannelDegraded } from "@/stores/wsStore";
import { ProvisioningProgress } from "@/server_manager/components/ProvisioningProgress";
import type { ServerResponse } from "@/server_manager/types";

interface DashboardServerListProps {
  servers: ServerResponse[];
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

export function DashboardServerList({ servers }: DashboardServerListProps) {
  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();
  const retryProvisioning = useRetryProvisioningServer();
  const connectionState = useEffectiveConnectionState();
  const serverChannelDegraded = useIsChannelDegraded("server:*");

  const staleNote =
    connectionState === "reconnecting"
      ? { text: "Status not live — reconnecting...", color: "text-status-warning" }
      : connectionState === "connecting"
        ? { text: "Connecting to live status…", color: "text-text-muted" }
        : connectionState === "disconnected"
          ? { text: "Status not live — showing last known", color: "text-status-danger" }
          : serverChannelDegraded
            ? { text: "Status not live — subscription rejected", color: "text-status-warning" }
            : null;

  const isBusy = startServer.isPending || stopServer.isPending || restartServer.isPending || retryProvisioning.isPending;
  const [stopTarget, setStopTarget] = useState<{ id: string; name: string } | null>(null);
  const [startCooldowns, setStartCooldowns] = useState<Record<string, number>>({});
  const [now, setNow] = useState<number>(() => Date.now());

  const hasActiveCooldown = useMemo(
    () => Object.values(startCooldowns).some((until) => until > now),
    [startCooldowns, now]
  );

  useEffect(() => {
    if (!hasActiveCooldown) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [hasActiveCooldown]);

  function handleStart(serverId: string, name: string) {
    // eslint-disable-next-line react-hooks/purity
    const currentTime = Date.now();
    setNow(currentTime);
    setStartCooldowns((prev) => ({ ...prev, [serverId]: currentTime + 3000 }));
    startServer.mutate(serverId, {
      onSuccess: () => toast("success", "Server started", `"${name}" is starting.`),
      onError: (err) => toast("error", "Start failed", errorMessage(err)),
    });
  }

  function handleStop(serverId: string, name: string) {
    setStopTarget({ id: serverId, name });
  }

  function handleConfirmStop() {
    if (!stopTarget) return;
    const { id, name } = stopTarget;
    setStopTarget(null);
    stopServer.mutate(id, {
      onSuccess: () => toast("success", "Server stopped", `"${name}" is stopping.`),
      onError: (err) => toast("error", "Stop failed", errorMessage(err)),
    });
  }

  function handleRestart(serverId: string, name: string) {
    restartServer.mutate(serverId, {
      onSuccess: () => toast("success", "Server restarting", `"${name}" is restarting.`),
      onError: (err) => toast("error", "Restart failed", errorMessage(err)),
    });
  }

  function handleRetryProvisioning(serverId: string, name: string) {
    retryProvisioning.mutate(serverId, {
      onSuccess: () => toast("success", "Retry started", `Provisioning retry started for "${name}".`),
      onError: (err) => toast("error", "Retry failed", errorMessage(err)),
    });
  }

  return (
    <>
      {staleNote && (
        <p role="status" className={`mb-2 px-1 text-xs font-medium ${staleNote.color}`}>
          {staleNote.text}
        </p>
      )}
      <ul className="divide-y divide-border-subtle">
        {servers.map((server) => {
        const status = server.status || "unknown";
        const actionColor =
          STATUS_MAP[status]?.color ?? "bg-surface-muted text-text-muted";
        const isServerStartingCooldown = startCooldowns[server.server_id] !== undefined && now < startCooldowns[server.server_id];

        return (
          <li key={server.server_id} className="flex items-center gap-3 py-3">
            <div
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${actionColor}`}
            >
              <Icon name="server" size={16} />
            </div>

            <div className="min-w-0 flex-1">
              <Link
                to={`/servers/${server.server_id}/console`}
                className="block truncate text-sm font-medium text-text-primary hover:underline"
              >
                {server.name}
              </Link>
              <div className="flex items-center gap-1.5 truncate text-xs text-text-muted">
                <LoaderBadge loader={server.server_type} />
                <span>{server.minecraft_version} · port {server.port}</span>
              </div>
            </div>

            <StatusBadge status={status} />

            <div className="flex shrink-0 items-center gap-1">
              {["stopped", "created", "crashed", "provisioning"].includes(status) && (
                <button
                  onClick={() => handleStart(server.server_id, server.name)}
                  disabled={isBusy || isServerStartingCooldown || status === "starting" || status === "provisioning"}
                  aria-label={`Start ${server.name}`}
                  title="Start"
                  className="rounded-lg p-1.5 text-status-success transition-colors hover:bg-status-success-bg hover:text-status-success disabled:opacity-40 disabled:hover:bg-transparent"
                >
                  <Icon name="play" size={16} />
                </button>
              )}
              {status === "provisioning_failed" && server.provisioning_retryable === false && (
                <button
                  onClick={() => handleRetryProvisioning(server.server_id, server.name)}
                  disabled={isBusy}
                  aria-label={`Retry Provisioning ${server.name}`}
                  title="Retry Provisioning"
                  className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg hover:text-status-warning disabled:opacity-40 disabled:hover:bg-transparent"
                >
                  <Icon name="restart" size={16} />
                </button>
              )}
              {["running", "starting"].includes(status) && (
                <>
                  <button
                    onClick={() => handleStop(server.server_id, server.name)}
                    disabled={isBusy}
                    aria-label={`Stop ${server.name}`}
                    title="Stop"
                    className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg hover:text-status-warning disabled:opacity-40 disabled:hover:bg-transparent"
                  >
                    <Icon name="stop" size={16} />
                  </button>
                  {status === "running" && (
                    <button
                      onClick={() => handleRestart(server.server_id, server.name)}
                      disabled={isBusy}
                      aria-label={`Restart ${server.name}`}
                      title="Restart"
                      className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg hover:text-status-warning disabled:opacity-40 disabled:hover:bg-transparent"
                    >
                      <Icon name="restart" size={16} />
                    </button>
                  )}
                </>
              )}
              {status === "stopping" && (
                <span
                  aria-label={`${server.name} is ${STATUS_MAP[status]?.label.toLowerCase()}`}
                  className="inline-flex h-7 w-7 items-center justify-center text-text-muted"
                >
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-border-default border-t-text-primary" />
                </span>
              )}
              {status === "provisioning" && (
                <ProvisioningProgress serverId={server.server_id} />
              )}
            </div>
          </li>
        );
      })}
      </ul>
      <ConfirmDialog
        open={stopTarget !== null}
        title="Stop server?"
        description={
          stopTarget
            ? `Are you sure you want to stop "${stopTarget.name}"? ` +
              "Active players will be disconnected."
            : undefined
        }
        confirmLabel="Stop Server"
        cancelLabel="Cancel"
        onConfirm={handleConfirmStop}
        onCancel={() => setStopTarget(null)}
      />
    </>
  );
}
