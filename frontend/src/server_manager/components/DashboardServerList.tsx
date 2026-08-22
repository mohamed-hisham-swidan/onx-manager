import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
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
      ? { text: "Status not live — reconnecting...", color: "text-amber-700 dark:text-amber-400" }
      : connectionState === "connecting"
        ? { text: "Connecting to live status…", color: "text-gray-500 dark:text-gray-400" }
        : connectionState === "disconnected"
          ? { text: "Status not live — showing last known", color: "text-red-600 dark:text-red-400" }
          : serverChannelDegraded
            ? { text: "Status not live — subscription rejected", color: "text-amber-700 dark:text-amber-400" }
            : null;

  const isBusy = startServer.isPending || stopServer.isPending || restartServer.isPending || retryProvisioning.isPending;
  const [startCooldowns, setStartCooldowns] = useState<Record<string, number>>({});
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const hasActive = Object.values(startCooldowns).some((t) => t > Date.now());
    if (!hasActive) return;
    const timer = setInterval(() => {
      const current = Date.now();
      setNow(current);
    }, 200);
    return () => clearInterval(timer);
  }, [startCooldowns]);

  function handleStart(serverId: string, name: string) {
    setStartCooldowns((prev) => ({ ...prev, [serverId]: Date.now() + 3000 }));
    setNow(Date.now());
    startServer.mutate(serverId, {
      onSuccess: () => toast("success", "Server started", `"${name}" is starting.`),
      onError: (err) => toast("error", "Start failed", errorMessage(err)),
    });
  }

  function handleStop(serverId: string, name: string) {
    stopServer.mutate(serverId, {
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
      <ul className="divide-y divide-gray-100 dark:divide-gray-700/50">
        {servers.map((server) => {
        const status = server.status || "unknown";
        const actionColor =
          STATUS_MAP[status]?.color ?? "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400";
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
                className="block truncate text-sm font-medium text-gray-900 hover:underline dark:text-gray-100"
              >
                {server.name}
              </Link>
              <p className="truncate text-xs text-gray-500 dark:text-gray-400">
                {server.minecraft_version} · port {server.port}
              </p>
            </div>

            <StatusBadge status={status} />

            <div className="flex shrink-0 items-center gap-1">
              {["stopped", "created", "crashed", "provisioning"].includes(status) && (
                <button
                  onClick={() => handleStart(server.server_id, server.name)}
                  disabled={isBusy || isServerStartingCooldown || status === "starting" || status === "provisioning"}
                  aria-label={`Start ${server.name}`}
                  title="Start"
                  className="rounded-lg p-1.5 text-green-600 transition-colors hover:bg-green-100 hover:text-green-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-green-400 dark:hover:bg-green-900/30 dark:hover:text-green-300"
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
                  className="rounded-lg p-1.5 text-amber-600 transition-colors hover:bg-amber-100 hover:text-amber-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-amber-400 dark:hover:bg-amber-900/30 dark:hover:text-amber-300"
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
                    className="rounded-lg p-1.5 text-orange-600 transition-colors hover:bg-orange-100 hover:text-orange-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-orange-400 dark:hover:bg-orange-900/30 dark:hover:text-orange-300"
                  >
                    <Icon name="stop" size={16} />
                  </button>
                  {status === "running" && (
                    <button
                      onClick={() => handleRestart(server.server_id, server.name)}
                      disabled={isBusy}
                      aria-label={`Restart ${server.name}`}
                      title="Restart"
                      className="rounded-lg p-1.5 text-yellow-600 transition-colors hover:bg-yellow-100 hover:text-yellow-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-yellow-400 dark:hover:bg-yellow-900/30 dark:hover:text-yellow-300"
                    >
                      <Icon name="restart" size={16} />
                    </button>
                  )}
                </>
              )}
              {status === "stopping" && (
                <span
                  aria-label={`${server.name} is ${STATUS_MAP[status]?.label.toLowerCase()}`}
                  className="inline-flex h-7 w-7 items-center justify-center text-gray-400 dark:text-gray-500"
                >
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600 dark:border-gray-600 dark:border-t-gray-300" />
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
    </>
  );
}
