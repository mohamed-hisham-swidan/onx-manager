import { useEffect, useMemo, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  useServerDetail,
  useServerRuntime,
  useRetryProvisioningServer,
} from "@/server_manager/hooks/useServers";
import { useServerExposure } from "@/server_manager/hooks/useServerExposure";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { subscribeChannels, unsubscribeChannels } from "@/hooks/useWebSocket";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ui/States";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Icon } from "@/components/ui/Icon";
import { isModpackSupportedLoader } from "@/server_manager/utils/loaderCapabilities";
import { useFleetPermissions } from "@/server_manager/components/servers/serversUtils";
import { ServerConsole } from "@/server_manager/components/ServerConsole";
import { StartingMonitorBanner } from "@/server_manager/components/StartingMonitorBanner";
import { ProvisioningProgress } from "@/server_manager/components/ProvisioningProgress";
import { ServerVitalsRail } from "@/server_manager/components/console/ServerVitalsRail";
import { ServerDiagnosticsDrawer } from "@/server_manager/components/console/ServerDiagnosticsDrawer";
import { useServerMetrics } from "@/server_manager/hooks/useServerMetrics";
import { ApiError, createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import { ModpackInstallWizardModal } from "@/server_manager/components/p55";

export function ServerDetailPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const branchCtx = useServerBranchContext();
  const activeBranch = branchCtx?.gitBacked ? branchCtx.branch : undefined;
  const isBranchView = Boolean(branchCtx?.gitBacked && branchCtx.branch !== "main");
  const permissions = useFleetPermissions();

  const effectiveServerId = serverId ?? "";
  const canViewExposure = permissions.canViewExposure(effectiveServerId);
  const canConsole = permissions.canConsole(effectiveServerId);
  const canPower = permissions.canPower(effectiveServerId);
  const canWrite = permissions.canWrite(effectiveServerId);

  const { data: server, isLoading, error, refetch: refetchServer } = useServerDetail(
    effectiveServerId,
    activeBranch,
  );
  const { data: runtime } = useServerRuntime(isBranchView ? "" : effectiveServerId);
  const { data: metrics } = useServerMetrics(isBranchView ? "" : effectiveServerId);
  const { exposure } = useServerExposure(effectiveServerId, activeBranch, {
    includeAgentAndPorts: false,
    enabled: canViewExposure,
  });
  const retryProvisioning = useRetryProvisioningServer();

  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();

  const healthStatusQuery = useQuery({
    queryKey: queryKeys.health.serverStatus(effectiveServerId),
    queryFn: () => api.getServerHealthStatus(effectiveServerId),
    enabled:
      Boolean(effectiveServerId) &&
      !isBranchView &&
      typeof api.getServerHealthStatus === "function",
    staleTime: 30_000,
    retry: false,
  });

  const branchRuntimeQuery = useQuery({
    queryKey: queryKeys.versioning.branchRuntime(effectiveServerId, branchCtx?.branch ?? "main"),
    queryFn: () => api.getBranchRuntime(serverId!, branchCtx!.branch),
    enabled: Boolean(serverId && isBranchView),
    refetchInterval: 5000,
  });
  const branchRuntime = branchRuntimeQuery.data ?? null;

  const templatesQuery = useQuery({
    queryKey: queryKeys.versioning.dataTemplates(effectiveServerId),
    queryFn: () => api.listDataTemplates(serverId!),
    enabled: Boolean(serverId && isBranchView),
  });

  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [showDestroyConfirm, setShowDestroyConfirm] = useState(false);
  const [isDiagnosticsOpen, setIsDiagnosticsOpen] = useState(false);
  const [isModpackWizardOpen, setIsModpackWizardOpen] = useState(false);

  const invalidateBranchQueries = () => {
    if (!serverId || !branchCtx?.branch) return;
    queryClient.invalidateQueries({
      queryKey: queryKeys.versioning.branchRuntime(serverId, branchCtx.branch),
    });
    queryClient.invalidateQueries({
      queryKey: queryKeys.versioning.branches(serverId),
    });
    queryClient.invalidateQueries({
      queryKey: queryKeys.console.history(serverId, branchCtx.branch),
    });
  };

  const branchStartMutation = useMutation({
    mutationFn: () =>
      api.startBranchRun(
        serverId!,
        branchCtx!.branch,
        selectedTemplateId ? { data_template_id: selectedTemplateId } : undefined,
      ),
    onSuccess: () => {
      invalidateBranchQueries();
      toast("success", "Branch container started", `Branch "${branchCtx!.branch}" is starting.`);
    },
    onError: (err) => {
      toast("error", "Start failed", err instanceof Error ? err.message : "Failed to start branch container.");
    },
  });

  const branchDestroyMutation = useMutation({
    mutationFn: () => api.destroyBranchRun(serverId!, branchCtx!.branch),
    onSuccess: () => {
      setShowDestroyConfirm(false);
      invalidateBranchQueries();
      toast("success", "Branch container destroyed", `Container and export for "${branchCtx!.branch}" removed.`);
    },
    onError: (err) => {
      setShowDestroyConfirm(false);
      toast("error", "Destroy failed", err instanceof Error ? err.message : "Failed to destroy branch container.");
    },
  });

  useEffect(() => {
    if (!serverId || isBranchView) return;
    const channel = `metrics:${serverId}`;
    subscribeChannels([channel]);
    return () => unsubscribeChannels([channel]);
  }, [serverId, isBranchView]);

  if (!serverId) {
    return (
      <div className="rounded-xl border border-status-danger-border bg-status-danger-bg p-6 text-sm text-status-danger">
        No server ID specified.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-96" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-surface-card rounded-xl border border-border-subtle p-4">
              <Skeleton className="h-4 w-16 mb-2" />
              <Skeleton className="h-6 w-24" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  const isNotFound = error instanceof ApiError && error.status === 404;

  if (error && !isNotFound) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load server details"}
        onRetry={() => {
          if (typeof refetchServer === "function") {
            void refetchServer();
          }
        }}
      />
    );
  }

  if (isNotFound || !server) {
    return (
      <div className="rounded-xl border border-border-subtle bg-surface-card p-6 text-center">
        <h2 className="text-lg font-semibold text-text-primary">Server not found</h2>
        <p className="mt-2 text-sm text-text-muted">
          This server does not exist or may have been deleted.
        </p>
        <Link
          to="/servers"
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text hover:bg-accent-hover transition-colors"
        >
          Back to Servers
        </Link>
      </div>
    );
  }

  const isBranchProvisioned = Boolean(branchRuntime?.container_provisioned);
  const branchStatus = branchRuntime?.runtime_status ?? "stopped";
  const isRunning = isBranchView ? branchStatus === "running" : server.status === "running";

  const currentMetric =
    !isBranchView && isRunning && metrics?.length
      ? metrics.reduce((latest, m) => (m.timestamp > latest.timestamp ? m : latest))
      : undefined;

  const branchGamePort = branchRuntime?.port_set?.game_port;
  const supportsModpacks = isModpackSupportedLoader(server.server_type);
  const isBranchBusy = branchStartMutation.isPending || branchDestroyMutation.isPending;
  const canRetryProvisioning = server.provisioning_retryable !== false;

  return (
    <div className="flex flex-col flex-1 min-h-0 gap-4">
      {server.status === "starting" && (
        <StartingMonitorBanner
          targetName={server.name}
          startedAt={server.updated_at}
          timeoutSeconds={server.startup_timeout_seconds ?? 120}
          onCheckNow={async () => {
            if (typeof refetchServer === "function") {
              await refetchServer();
            }
          }}
        />
      )}

      {server.status === "provisioning" && (
        <ProvisioningProgress
          serverId={effectiveServerId}
          serverName={server.name}
          serverType={server.server_type}
          minecraftVersion={server.minecraft_version}
          mode={server.mode}
          port={server.port}
          initialSnapshot={server.provisioning_progress ?? null}
          enablePollingFallback
          onOpenConsole={() => {
            void refetchServer();
          }}
        />
      )}

      {server.status === "provisioning_failed" && (
        <div className="space-y-3">
          <div
            data-testid="provisioning-failed-banner"
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-danger-border bg-status-danger-bg px-4 py-3 text-sm"
          >
            <div className="flex items-start gap-2.5 min-w-0">
              <Icon name="alert" size={18} className="mt-0.5 shrink-0 text-status-danger" />
              <div className="min-w-0">
                <p className="font-semibold text-status-danger">Server Installation Failed</p>
                <p className="text-xs text-text-secondary break-words">
                  {server.provisioning_error ||
                    "The server installer did not finish cleanly. Retry provisioning to resume setup."}
                </p>
              </div>
            </div>
            {canRetryProvisioning && (
              <button
                type="button"
                data-testid="detail-retry-provisioning-btn"
                disabled={retryProvisioning.isPending}
                onClick={() => retryProvisioning.mutate(serverId)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-status-danger px-3.5 py-1.5 text-xs font-semibold text-accent-contrast-text hover:opacity-90 disabled:opacity-50 transition-opacity cursor-pointer shrink-0"
              >
                <Icon name="restart" size={14} />
                {retryProvisioning.isPending ? "Retrying..." : "Retry Provisioning"}
              </button>
            )}
          </div>
          {server.provisioning_progress && (
            <ProvisioningProgress
              serverId={effectiveServerId}
              serverName={server.name}
              serverType={server.server_type}
              minecraftVersion={server.minecraft_version}
              mode={server.mode}
              port={server.port}
              initialSnapshot={server.provisioning_progress}
              retryable={canRetryProvisioning}
              retrying={retryProvisioning.isPending}
              onRetryProvisioning={() => retryProvisioning.mutate(serverId)}
            />
          )}
        </div>
      )}

      {/* 12-Column Terminal Cockpit Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 min-h-0 lg:items-start">
        {/* Left (col-span-8 or 9): IDE-Grade Console Terminal */}
        <div className="lg:col-span-8 xl:col-span-9 flex flex-col min-h-0 gap-3.5">
          {isBranchView && (
            <div
              data-testid="branch-console-lifecycle-card"
              className="rounded-xl border border-border-subtle bg-surface-card px-3.5 py-2.5 shadow-2xs flex flex-wrap items-center justify-between gap-3"
            >
              <div className="flex flex-wrap items-center gap-2.5 text-xs">
                <span className="inline-flex items-center gap-1 rounded-md border border-accent-primary/30 bg-accent-primary/10 px-2 py-0.5 font-mono font-semibold text-accent-primary">
                  Branch: {branchCtx!.branch}
                </span>
                <StatusBadge status={isBranchProvisioned ? branchStatus : "stopped"} />
                <span className="font-medium text-text-secondary">
                  {!isBranchProvisioned
                    ? "Unprovisioned"
                    : branchStatus === "running"
                      ? "Isolated Container Running"
                      : "Isolated Container Stopped (Data Preserved)"}
                </span>
                {branchRuntime?.port_set && (
                  <span className="font-mono text-[11px] text-text-muted">
                    Ports: Game {branchRuntime.port_set.game_port} · RCON{" "}
                    {branchRuntime.port_set.rcon_port} · Query{" "}
                    {branchRuntime.port_set.query_port}
                  </span>
                )}
              </div>

              {isBranchProvisioned && canWrite && (
                <button
                  type="button"
                  data-testid="branch-console-destroy-btn"
                  disabled={isBranchBusy || branchStatus === "running"}
                  title={
                    branchStatus === "running"
                      ? "Stop the branch container before destroying it"
                      : "Remove container, export directory, and release ports"
                  }
                  onClick={() => setShowDestroyConfirm(true)}
                  className="inline-flex items-center gap-1 rounded-lg border border-status-danger-border bg-status-danger-bg px-2.5 py-1 text-xs font-medium text-status-danger hover:opacity-90 disabled:opacity-50 cursor-pointer"
                >
                  <Icon name="trash" size={12} />
                  Destroy Container
                </button>
              )}
            </div>
          )}

          <div className="rounded-xl border border-border-subtle bg-surface-card p-3 sm:p-4 shadow-2xs min-h-0 flex flex-col">
            {isBranchView && !isBranchProvisioned ? (
              <div
                data-testid="branch-container-unprovisioned-state"
                className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-border-default bg-surface-muted/40 p-8 text-center min-h-[360px]"
              >
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-accent-primary/10 text-accent-primary">
                  <Icon name="server" size={24} />
                </div>
                <h3 className="text-base font-semibold text-text-primary">
                  No container created for branch &ldquo;{branchCtx!.branch}&rdquo; yet
                </h3>
                <p className="mt-1.5 max-w-md text-xs text-text-muted">
                  Branch containers run in full isolation from main using this branch&apos;s own
                  worktree configuration and plugins. Choose optional world data and provision a
                  container when ready to test.
                </p>

                <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
                  <label className="flex items-center gap-2 text-xs text-text-secondary">
                    <span>Data Template</span>
                    <select
                      aria-label="Data template"
                      data-testid="branch-console-template-select"
                      value={selectedTemplateId}
                      onChange={(e) => setSelectedTemplateId(e.target.value)}
                      className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary focus:border-accent-primary focus:outline-none"
                    >
                      <option value="">Fresh World</option>
                      {(templatesQuery.data ?? []).map((tpl) => (
                        <option key={tpl.id} value={tpl.id}>
                          {tpl.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  {canPower && (
                    <button
                      type="button"
                      data-testid="branch-console-create-start-btn"
                      disabled={isBranchBusy}
                      onClick={() => branchStartMutation.mutate()}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer shadow-xs"
                    >
                      <Icon name="play" size={14} />
                      {branchStartMutation.isPending
                        ? "Creating & Starting..."
                        : "Create & Start Branch Container"}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <ServerConsole
                serverId={serverId}
                serverName={server.name}
                branch={activeBranch}
                serverStatus={isBranchView ? branchStatus : server.status}
                tps={isBranchView ? null : currentMetric?.tps}
                players={isBranchView ? undefined : currentMetric?.players}
                maxPlayers={server.max_players}
                provider={isBranchView ? "docker" : server.provider}
                host={
                  isBranchView
                    ? branchGamePort
                      ? "localhost"
                      : undefined
                    : server.deployment_host
                }
                port={
                  isBranchView
                    ? branchGamePort ?? undefined
                    : server.deployment_port ?? server.port
                }
                compactHeader
                canConsole={canConsole}
                uptimeSeconds={runtime?.uptime_seconds ?? server.uptime_seconds}
              />
            )}
          </div>
        </div>

        {/* Right (col-span-4 or 3): Consolidated 4-Card Operational Vitals Rail */}
        <div className="lg:col-span-4 xl:col-span-3">
          <ServerVitalsRail
            server={server}
            serverId={serverId}
            branch={activeBranch}
            isBranchView={isBranchView}
            branchGamePort={branchGamePort}
            isRunning={isRunning}
            runtime={runtime}
            metrics={metrics}
            exposure={exposure}
            healthStatus={healthStatusQuery.data}
            supportsModpacks={supportsModpacks}
            canConsole={canConsole}
            canWrite={canWrite}
            onOpenDiagnostics={() => setIsDiagnosticsOpen(true)}
            onOpenModpackWizard={() => setIsModpackWizardOpen(true)}
            onOpenSafeUpgradeWizard={() =>
              navigate(
                `/servers/${effectiveServerId}/settings?tab=lifecycle&action=change-version`,
              )
            }
          />
        </div>
      </div>

      <ServerDiagnosticsDrawer
        open={isDiagnosticsOpen}
        onClose={() => setIsDiagnosticsOpen(false)}
        server={server}
        runtime={runtime}
        exposure={exposure}
      />

      {supportsModpacks && (
        <ModpackInstallWizardModal
          serverId={serverId}
          isOpen={isModpackWizardOpen}
          onClose={() => setIsModpackWizardOpen(false)}
        />
      )}

      <ConfirmDialog
        open={showDestroyConfirm}
        title={`Destroy container for branch "${branchCtx?.branch ?? ""}"?`}
        description="This permanently removes the branch container, its exported server files, and its allocated port set. Git commits and branches are not affected."
        confirmLabel="Destroy Container"
        variant="danger"
        onConfirm={() => branchDestroyMutation.mutate()}
        onCancel={() => setShowDestroyConfirm(false)}
      />
    </div>
  );
}
