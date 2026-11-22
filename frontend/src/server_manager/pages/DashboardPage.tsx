import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useServersList } from "@/server_manager/hooks/useServers";
import { useHostResources } from "@/server_manager/hooks/useHostResources";
import { HostResourceBudgetBar } from "@/server_manager/components/HostResourceBudgetBar";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { Icon } from "@/components/ui/Icon";
import { CommandCenterKpiGrid } from "@/server_manager/components/CommandCenterKpiGrid";
import { CommandCenterFleetList } from "@/server_manager/components/CommandCenterFleetList";
import { CommandCenterDaemonStream } from "@/server_manager/components/CommandCenterDaemonStream";
import {
  getHostTelemetry,
  getInitialDaemonLogs,
} from "@/server_manager/utils/telemetryAdapter";
import { useDeploymentProfile } from "@/hooks/useDeploymentProfile";

export function DashboardPage() {
  const { data: servers, isLoading, error } = useServersList();
  const { data: hostBudget } = useHostResources();
  const { isLocal, showFullControls } = useDeploymentProfile();

  const serverList = useMemo(() => servers ?? [], [servers]);

  const counts = useMemo(() => {
    return serverList.reduce<Record<string, number>>((acc, s) => {
      const status = s.status || "unknown";
      acc[status] = (acc[status] || 0) + 1;
      return acc;
    }, {});
  }, [serverList]);

  const serverNames = useMemo(() => {
    return serverList.reduce<Record<string, string>>((acc, s) => {
      acc[s.server_id] = s.name;
      return acc;
    }, {});
  }, [serverList]);

  const onlineCount = counts.running || 0;
  const crashedServers = useMemo(() => {
    return serverList.filter(
      (s) => s.status === "crashed" || s.status === "broken",
    );
  }, [serverList]);
  const crashedCount = crashedServers.length;
  const totalCount = serverList.length;

  const telemetry = useMemo(() => getHostTelemetry(serverList), [serverList]);
  const initialLogs = useMemo(() => getInitialDaemonLogs(serverList), [serverList]);

  return (
    <div className="@container w-full max-w-[1920px] mx-auto space-y-5">
      {/* A. Top Header Bar & Honest Telemetry Strip */}
      <div className="flex flex-col gap-4 pb-1 border-b border-border-subtle @5xl:flex-row @5xl:items-center @5xl:justify-between">
        {/* Left Side: Breadcrumb & Title */}
        <div>
          <div className="flex items-center gap-1.5 font-mono text-xs text-text-muted">
            <span>ONX Manager</span>
            <span aria-hidden="true">/</span>
            <span className="text-text-primary font-medium">Dashboard</span>
          </div>
          <div className="mt-1 flex items-baseline gap-3">
            <h1
              aria-label="Dashboard"
              className="text-xl sm:text-2xl font-bold tracking-tight text-text-primary"
            >
              Command Center
            </h1>
            <p className="hidden sm:inline text-xs font-normal text-text-muted">
              {isLocal && !showFullControls
                ? "Local Minecraft servers & quick sharing"
                : "Real-time node telemetry & server orchestration"}
            </p>
          </div>
        </div>

        {/* Right Side: Honest Telemetry Pill & Quick Actions */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Honest Status Pill */}
          {crashedCount > 0 ? (
            <Link
              to={
                crashedCount === 1
                  ? `/servers/${crashedServers[0].server_id}`
                  : "/servers?status=crashed"
              }
              aria-label={
                crashedCount === 1
                  ? `Open crashed server ${crashedServers[0].name}`
                  : `View ${crashedCount} crashed servers`
              }
              className="flex items-center gap-2 rounded-lg border border-border-subtle bg-surface-card px-3 py-1.5 font-mono text-xs font-semibold shadow-2xs hover:bg-surface-hover hover:border-status-danger/40 transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-status-danger cursor-pointer"
            >
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-danger opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-status-danger" />
              </span>
              <span className="text-status-danger">
                DEGRADED ({crashedCount} CRASHED)
              </span>
            </Link>
          ) : (
            <div className="flex items-center gap-2 rounded-lg border border-border-subtle bg-surface-card px-3 py-1.5 font-mono text-xs font-semibold shadow-2xs">
              {onlineCount > 0 ? (
                <>
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-status-success opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-status-success" />
                  </span>
                  <span className="text-status-success">
                    NODE ACTIVE ({onlineCount}/{totalCount} ONLINE)
                  </span>
                </>
              ) : (
                <>
                  <span className="h-2 w-2 rounded-full bg-status-warning" />
                  <span className="text-status-warning">
                    DAEMON STANDBY (ALL OFFLINE)
                  </span>
                </>
              )}
            </div>
          )}

          {/* Quick Actions */}
          <Link
            to="/servers/import"
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3.5 text-xs font-semibold text-text-primary hover:bg-surface-hover hover:border-border-strong transition-colors"
          >
            <Icon name="upload" size={13} />
            <span>Import Server</span>
          </Link>

          <Link
            to="/servers/create"
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-accent-primary px-4 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover active:bg-accent-active shadow-xs transition-colors"
          >
            <Icon name="plus" size={13} />
            <span>Create Server</span>
          </Link>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-4 @lg:grid-cols-2 @4xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="h-[140px] rounded-xl border border-border-subtle bg-surface-card p-4.5 space-y-3"
              >
                <div className="flex justify-between items-center">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-7 w-7 rounded-lg" />
                </div>
                <Skeleton className="h-7 w-28" />
                <Skeleton className="h-2 w-full rounded-full" />
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-5 @5xl:grid-cols-12">
            <div className="h-[400px] rounded-xl border border-border-subtle bg-surface-card p-5 @5xl:col-span-8">
              <Skeleton className="h-5 w-32 mb-4" />
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full rounded-lg" />
                ))}
              </div>
            </div>
            <div className="h-[400px] rounded-xl border border-border-subtle bg-surface-card p-5 @5xl:col-span-4">
              <Skeleton className="h-5 w-40 mb-4" />
              <Skeleton className="h-[300px] w-full rounded-lg" />
            </div>
          </div>
        </div>
      ) : error ? (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load telemetry & servers"}
        />
      ) : serverList.length === 0 ? (
        <div className="py-8">
          <div className="mx-auto max-w-md text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-surface-elevated text-text-muted border border-border-subtle mb-4">
              <Icon name="server" size={24} />
            </div>
            <h2 className="text-base font-semibold text-text-primary">No servers yet</h2>
            <p className="mt-1 text-sm text-text-muted">
              Create your first Minecraft server to get started.
            </p>
            <div className="mt-5">
              <Link
                to="/servers/create"
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-accent-primary px-4 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover transition-colors shadow-xs"
              >
                <Icon name="plus" size={13} />
                <span>Create Server</span>
              </Link>
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* B. Row 1: The 4-Column Hardware & Fleet KPI Grid */}
          <CommandCenterKpiGrid
            counts={counts}
            totalServers={totalCount}
            telemetry={telemetry}
          />

          {hostBudget && <HostResourceBudgetBar budget={hostBudget} compact />}

          {/* C. Row 2: Main Split Workspace (12-Column Grid) */}
          <div className="grid grid-cols-1 items-stretch gap-5 @5xl:grid-cols-12">
            {/* Left Panel: Interactive Server Fleet Table/Cards (col-span-8) */}
            <section className="@5xl:col-span-8 @container min-w-0">
              <CommandCenterFleetList servers={serverList} />
            </section>

            {/* Right Panel: Real-Time Event Stream & Quick Diagnostics (col-span-4) */}
            <section className="@5xl:col-span-4 min-w-0 flex flex-col">
              <CommandCenterDaemonStream
                initialLogs={initialLogs}
                serverNames={serverNames}
              />
            </section>
          </div>
        </>
      )}
    </div>
  );
}
