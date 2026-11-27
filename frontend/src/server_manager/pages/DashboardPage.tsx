import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  useRestartServer,
  useRetryProvisioningServer,
  useServersList,
  useStartServer,
  useStopServer,
} from "@/server_manager/hooks/useServers";
import { useHostResources } from "@/server_manager/hooks/useHostResources";
import { HostResourceBudgetBar } from "@/server_manager/components/HostResourceBudgetBar";
import { StartingMonitorBanner } from "@/server_manager/components/StartingMonitorBanner";
import { useFleetMetrics } from "@/server_manager/components/servers/useFleetMetrics";
import { useFleetPermissions } from "@/server_manager/components/servers/serversUtils";
import { DashboardHeader } from "@/server_manager/components/dashboard/DashboardHeader";
import { DashboardKpiStrip } from "@/server_manager/components/dashboard/DashboardKpiStrip";
import { DashboardFleetPanel } from "@/server_manager/components/dashboard/DashboardFleetPanel";
import { DashboardActivityPanel } from "@/server_manager/components/dashboard/DashboardActivityPanel";
import {
  computeServerCounts,
  getHostTelemetry,
} from "@/server_manager/utils/telemetryAdapter";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { Icon } from "@/components/ui/Icon";
import { useDeploymentProfile } from "@/hooks/useDeploymentProfile";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import type { ServerResponse } from "@/server_manager/types";

function extractErrorMessage(err: unknown): string {
  if (err && typeof err === "object") {
    const record = err as Record<string, unknown>;
    if (typeof record.message === "string" && record.message) return record.message;
    if (typeof record.error === "string" && record.error) return record.error;
  }
  return "Request failed. Please try again.";
}

export function DashboardPage() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const {
    data: servers,
    isLoading,
    error,
    refetch: refetchServers,
  } = useServersList();
  const { data: hostBudget, refetch: refetchHostBudget } = useHostResources();
  const { isLocal, showFullControls } = useDeploymentProfile();
  const permissions = useFleetPermissions();

  const startServer = useStartServer();
  const stopServer = useStopServer();
  const restartServer = useRestartServer();
  const retryProvisioning = useRetryProvisioningServer();

  const [busyServerIds, setBusyServerIds] = useState<Set<string>>(() => new Set());
  const [startCooldowns, setStartCooldowns] = useState<Record<string, number>>({});
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [copiedAddressId, setCopiedAddressId] = useState<string | null>(null);
  const [stopTarget, setStopTarget] = useState<ServerResponse | null>(null);
  const copyTimerRef = useRef<number | null>(null);

  const serverList = useMemo(() => servers ?? [], [servers]);

  const { metricsByServerId, snapshotsByServerId } = useFleetMetrics(
    serverList,
    hostBudget,
    { historyLimit: 60 },
  );

  // Cooldown ticker while any start cooldown is active
  useEffect(() => {
    const activeCooldowns = Object.values(startCooldowns).some((until) => until > Date.now());
    if (!activeCooldowns) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [startCooldowns]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) {
        window.clearTimeout(copyTimerRef.current);
      }
    };
  }, []);

  // Real daemon health (/health)
  const canFetchHealth = typeof api?.health === "function";
  const healthQuery = useQuery({
    queryKey: queryKeys.health.daemon(),
    queryFn: () => api.health(),
    enabled: canFetchHealth,
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: false,
  });

  // Shared setup status cache (version fallback)
  const canFetchSetup = typeof api?.getSetupStatus === "function";
  const setupStatusQuery = useQuery({
    queryKey: ["systemStatus"],
    queryFn: () => api.getSetupStatus(),
    enabled: canFetchSetup,
    staleTime: 30_000,
    retry: false,
  });

  // Fleet health summary (/api/v1/health/dashboard)
  const canFetchHealthDashboard = typeof api?.getHealthDashboard === "function";
  const healthDashboardQuery = useQuery({
    queryKey: queryKeys.health.dashboard(),
    queryFn: () => api.getHealthDashboard(),
    enabled: canFetchHealthDashboard,
    staleTime: 15_000,
    retry: false,
  });

  // Real backups & schedules
  const canFetchBackups = typeof api?.listBackups === "function";
  const backupsQuery = useQuery({
    queryKey: queryKeys.backups.list(),
    queryFn: () => api.listBackups(),
    enabled: canFetchBackups,
    staleTime: 30_000,
    retry: false,
  });

  const canFetchSchedules = typeof api?.listSchedules === "function";
  const schedulesQuery = useQuery({
    queryKey: queryKeys.schedules.list(),
    queryFn: () => api.listSchedules(),
    enabled: canFetchSchedules,
    staleTime: 30_000,
    retry: false,
  });

  const serverNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const s of serverList) {
      map[s.server_id] = s.name;
    }
    return map;
  }, [serverList]);

  const activeServerIds = useMemo(
    () => new Set(serverList.map((s) => s.server_id)),
    [serverList],
  );

  const counts = useMemo(() => computeServerCounts(serverList), [serverList]);

  const telemetry = useMemo(
    () =>
      getHostTelemetry({
        servers: serverList,
        snapshotsByServerId,
        metricsByServerId,
        hostBudget,
        backups: backupsQuery.data ?? null,
        schedules: schedulesQuery.data ?? null,
      }),
    [
      serverList,
      snapshotsByServerId,
      metricsByServerId,
      hostBudget,
      backupsQuery.data,
      schedulesQuery.data,
    ],
  );

  const startingServers = useMemo(
    () => serverList.filter((s) => s.status === "starting"),
    [serverList],
  );

  function markServerBusy(serverId: string, busy: boolean) {
    setBusyServerIds((prev) => {
      const next = new Set(prev);
      if (busy) {
        next.add(serverId);
      } else {
        next.delete(serverId);
      }
      return next;
    });
  }

  function handleStart(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    const now = Date.now();
    setNowMs(now);
    setStartCooldowns((prev) => ({ ...prev, [server.server_id]: now + 30_000 }));
    markServerBusy(server.server_id, true);

    startServer.mutate(server.server_id, {
      onSuccess: () =>
        toast("success", "Server starting", `"${server.name}" start command issued.`),
      onError: (err) => {
        setStartCooldowns((prev) => {
          const next = { ...prev };
          delete next[server.server_id];
          return next;
        });
        toast("error", "Start failed", extractErrorMessage(err));
      },
      onSettled: () => markServerBusy(server.server_id, false),
    });
  }

  function handleStartAll(targets: ServerResponse[]) {
    if (typeof startServer.mutateAsync !== "function") {
      for (const server of targets) {
        handleStart(server);
      }
      return;
    }
    const now = Date.now();
    setNowMs(now);
    for (const server of targets) {
      if ((startCooldowns[server.server_id] ?? 0) > now) continue;
      setStartCooldowns((prev) => ({
        ...prev,
        [server.server_id]: now + 30_000,
      }));
      markServerBusy(server.server_id, true);
      void startServer
        .mutateAsync(server.server_id)
        .then(() => {
          toast("success", "Server starting", `"${server.name}" start command issued.`);
        })
        .catch((err) => {
          setStartCooldowns((prev) => {
            const next = { ...prev };
            delete next[server.server_id];
            return next;
          });
          toast("error", "Start failed", extractErrorMessage(err));
        })
        .finally(() => {
          markServerBusy(server.server_id, false);
        });
    }
  }

  function handleStopRequest(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    setStopTarget(server);
  }

  function handleConfirmStop() {
    if (!stopTarget || stopServer.isPending) return;
    const target = stopTarget;
    markServerBusy(target.server_id, true);

    stopServer.mutate(target.server_id, {
      onSuccess: () => {
        setStopTarget(null);
        toast("info", "Server stopping", `"${target.name}" is stopping.`);
      },
      onError: (err) => {
        setStopTarget(null);
        toast("error", "Stop failed", extractErrorMessage(err));
      },
      onSettled: () => markServerBusy(target.server_id, false),
    });
  }

  function handleRestart(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    markServerBusy(server.server_id, true);

    restartServer.mutate(server.server_id, {
      onSuccess: () =>
        toast("info", "Server restarting", `"${server.name}" restart initiated.`),
      onError: (err) => toast("error", "Restart failed", extractErrorMessage(err)),
      onSettled: () => markServerBusy(server.server_id, false),
    });
  }

  function handleRetryProvisioning(server: ServerResponse, e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    markServerBusy(server.server_id, true);

    retryProvisioning.mutate(server.server_id, {
      onSuccess: () =>
        toast("success", "Retry started", `Provisioning retry started for "${server.name}".`),
      onError: (err) => toast("error", "Retry failed", extractErrorMessage(err)),
      onSettled: () => markServerBusy(server.server_id, false),
    });
  }

  function handleCopyAddress(address: string, serverId: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(address).catch(() => {});
    }
    setCopiedAddressId(serverId);
    toast("info", "Address copied", `Copied ${address}`);
    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current);
    }
    copyTimerRef.current = window.setTimeout(() => {
      setCopiedAddressId((prev) => (prev === serverId ? null : prev));
    }, 2000);
  }

  return (
    <div className="@container mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-6 space-y-6">
      <DashboardHeader
        isLocal={isLocal}
        showFullControls={showFullControls}
        health={healthQuery.data ?? null}
        setupVersion={setupStatusQuery.data?.version ?? null}
        healthDashboard={healthDashboardQuery.data ?? null}
        servers={serverList}
        permissions={{
          canCreate: permissions.canCreate,
          canImport: permissions.canImport,
        }}
      />

      {startingServers.map((s) => (
        <StartingMonitorBanner
          key={`starting-${s.server_id}`}
          targetName={s.name}
          startedAt={s.updated_at}
          timeoutSeconds={120}
          onCheckNow={async () => {
            await refetchServers();
          }}
        />
      ))}

      {isLoading ? (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-[140px] rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-5 w-16 rounded-full" />
                </div>
                <Skeleton className="h-7 w-28" />
                <Skeleton className="h-2 w-full rounded-full" />
                <Skeleton className="h-3 w-36" />
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-12 @5xl:grid-cols-12">
            <div className="h-[360px] rounded-xl border border-border-subtle bg-surface-card p-5 xl:col-span-8 @5xl:col-span-8 space-y-3">
              <Skeleton className="h-5 w-32" />
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))}
            </div>
            <div className="h-[360px] rounded-xl border border-border-subtle bg-surface-card p-5 xl:col-span-4 @5xl:col-span-4 space-y-3">
              <Skeleton className="h-5 w-36" />
              <Skeleton className="h-[280px] w-full rounded-lg" />
            </div>
          </div>
        </div>
      ) : error ? (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load dashboard telemetry"}
          onRetry={() => {
            void refetchServers?.();
            void refetchHostBudget?.();
          }}
        />
      ) : serverList.length === 0 ? (
        <EmptyState
          icon="server"
          title="Launch your first Minecraft server"
          description="Create a managed instance or import an existing server directory."
          action={
            permissions.canCreate || permissions.canImport ? (
              <div className="flex flex-wrap items-center justify-center gap-2.5">
                {permissions.canCreate && (
                  <Link
                    to="/servers/create"
                    className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-accent-primary px-4 text-xs font-semibold text-accent-contrast-text shadow-xs transition-colors hover:bg-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                  >
                    <Icon name="plus" size={14} />
                    <span>Create Server</span>
                  </Link>
                )}
                {permissions.canImport && (
                  <Link
                    to="/servers/import"
                    className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-4 text-xs font-semibold text-text-primary transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-focus"
                  >
                    <Icon name="upload" size={14} />
                    <span>Import Existing Server</span>
                  </Link>
                )}
              </div>
            ) : undefined
          }
        />
      ) : (
        <>
          <DashboardKpiStrip
            counts={counts}
            totalServers={serverList.length}
            telemetry={telemetry}
            healthDashboard={healthDashboardQuery.data ?? null}
            activeServerIds={activeServerIds}
          />

          {hostBudget && <HostResourceBudgetBar budget={hostBudget} compact />}

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-12 @5xl:grid-cols-12 items-start">
            <section className="xl:col-span-8 @5xl:col-span-8 @container min-w-0">
              <DashboardFleetPanel
                servers={serverList}
                metricsByServerId={metricsByServerId}
                hostBudget={hostBudget}
                busyServerIds={busyServerIds}
                startCooldowns={startCooldowns}
                nowMs={nowMs}
                copiedAddressId={copiedAddressId}
                canPower={permissions.canPower}
                onStart={handleStart}
                onStartAll={handleStartAll}
                onStop={handleStopRequest}
                onRestart={handleRestart}
                onRetryProvisioning={handleRetryProvisioning}
                onCopyAddress={handleCopyAddress}
              />
            </section>

            <section className="xl:col-span-4 @5xl:col-span-4 min-w-0 flex flex-col">
              <DashboardActivityPanel servers={serverList} serverNames={serverNames} />
            </section>
          </div>
        </>
      )}

      <ConfirmDialog
        open={stopTarget !== null}
        title="Stop server?"
        description={
          stopTarget
            ? `Are you sure you want to stop "${stopTarget.name}"? Active players will be disconnected cleanly.`
            : undefined
        }
        confirmLabel={stopServer.isPending ? "Stopping..." : "Stop Server"}
        cancelLabel="Cancel"
        variant="danger"
        isPending={stopServer.isPending}
        onConfirm={handleConfirmStop}
        onCancel={() => {
          if (stopServer.isPending) return;
          setStopTarget(null);
        }}
      />
    </div>
  );
}
