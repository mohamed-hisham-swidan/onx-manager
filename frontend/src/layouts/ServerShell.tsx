import { useEffect, useState, Suspense, useContext, useMemo, useCallback } from "react";
import { Outlet, useLocation, useParams, Link, useNavigate } from "react-router-dom";
import { QueryClientContext, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { TopBar } from "@/components/layout/TopBar";
import { Sidebar } from "@/components/layout/Sidebar";
import { LoadingBar } from "@/components/ui/LoadingBar";
import { Toaster } from "@/components/ui/Toaster";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { RouteFallback } from "@/components/ui/RouteFallback";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { Chip } from "@/components/ui/Chip";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { OperationDrawer } from "@/operations/components/OperationDrawer";
import { useOperationStore } from "@/operations/stores/operationStore";
import { useUIStore } from "@/stores/uiStore";
import { useClipboard } from "@/hooks/useClipboard";
import { subscribeChannels, unsubscribeChannels } from "@/hooks/useWebSocket";
import * as serverHooks from "@/server_manager/hooks/useServers";
import {
  useServerDetail,
  useStartServer,
  useStopServer,
  useRestartServer,
} from "@/server_manager/hooks/useServers";
import { ServerIcon } from "@/server_manager/components/ServerIcon";
import {
  resolveJoinAddress,
  useFleetPermissions,
} from "@/server_manager/components/servers/serversUtils";
import { resolveAccessAddress } from "@/server_manager/utils/accessAddress";
import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";
import { resolveServerMode } from "@/server_manager/utils/serverMode";
import { STATUS_MAP, type ServerMode } from "@/server_manager/types";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { ServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { UpgradePinnedBanner } from "@/server_manager/components/p55/UpgradePinnedBanner";
import { useServerExposure } from "@/server_manager/hooks/useServerExposure";
import { toast } from "@/stores/toastStore";

function useSafeServersList() {
  const queryClient = useContext(QueryClientContext);
  let fn: unknown;
  try {
    fn = (serverHooks as Record<string, unknown>).useServersList;
  } catch {
    fn = undefined;
  }
  if (typeof fn !== "function") {
    return { data: undefined };
  }
  if (!queryClient && !(fn as { _isMockFunction?: boolean })._isMockFunction) {
    return { data: undefined };
  }
  return (fn as () => {
    data?: Array<{
      server_id: string;
      name: string;
      status: string;
      port?: number;
      server_type?: string;
      mode?: ServerMode;
    }>;
  })();
}

export function ServerShell() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const changeVersionOpen = useUIStore((s) => s.changeVersionOpen);
  const syncRightPanelSidebarCollapse = useUIStore((s) => s.syncRightPanelSidebarCollapse);
  const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);
  const activeDrawerId = useOperationStore((s) => s.activeDrawerId);
  const closeDrawer = useOperationStore((s) => s.closeDrawer);
  const rightPanelOpen = Boolean(activeDrawerId) || changeVersionOpen;

  useEffect(() => {
    syncRightPanelSidebarCollapse(rightPanelOpen);
  }, [rightPanelOpen, syncRightPanelSidebarCollapse]);
  const location = useLocation();
  const { copy } = useClipboard();
  const permissions = useFleetPermissions();

  const serversQuery = useSafeServersList();
  const servers = useMemo(() => serversQuery?.data ?? [], [serversQuery?.data]);

  const urlBranch = new URLSearchParams(location.search).get("branch");
  const persistedBranch =
    typeof window !== "undefined" && serverId
      ? window.localStorage.getItem(`onx.selectedBranch.${serverId}`)
      : null;
  const candidateBranch = urlBranch || persistedBranch || "main";

  const { data: server } = useServerDetail(
    serverId!,
    candidateBranch !== "main" ? candidateBranch : undefined,
  );
  const { supportsMods, supportsPlugins } = getServerCapabilities(server?.server_type);
  const serverMode = resolveServerMode(server?.mode);

  const api = useMemo(() => createAuthenticatedApi(), []);
  const branchesQuery = useQuery({
    queryKey: queryKeys.versioning.branches(serverId ?? ""),
    queryFn: () => api.getServerBranches(serverId!),
    enabled: !!serverId && serverMode === "advanced",
  });
  const branches = useMemo(() => branchesQuery.data ?? [], [branchesQuery.data]);
  const gitBacked = branches.some((branch) => branch.worktree_path != null);

  const selectedBranch = gitBacked
    ? branches.length > 0 && !branches.some((branch) => branch.name === candidateBranch)
      ? "main"
      : candidateBranch
    : "main";
  const isNonMainBranch = gitBacked && selectedBranch !== "main";

  const queryClient = useQueryClient();
  const branchRuntimeQuery = useQuery({
    queryKey: queryKeys.versioning.branchRuntime(serverId ?? "", selectedBranch),
    queryFn: () =>
      typeof api.getBranchRuntime === "function"
        ? api.getBranchRuntime(serverId!, selectedBranch)
        : Promise.resolve(null),
    enabled: !!serverId && isNonMainBranch,
    refetchInterval: 5000,
  });
  const branchRuntime = branchRuntimeQuery.data ?? null;

  // Subscribe to per-server status channel so Viewer/Console roles get live state updates
  useEffect(() => {
    if (!serverId) return;
    const channel = `server:${serverId}`;
    subscribeChannels([channel]);
    return () => unsubscribeChannels([channel]);
  }, [serverId]);

  const branchStartMutation = useMutation({
    mutationFn: () => api.startBranchRun(serverId!, selectedBranch),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.versioning.branchRuntime(serverId!, selectedBranch),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.versioning.branches(serverId!),
      });
    },
    onError: (err) => {
      toast(
        "error",
        "Branch start failed",
        err instanceof Error ? err.message : "Failed to start branch container.",
      );
    },
  });

  const branchStopMutation = useMutation({
    mutationFn: () => api.stopBranchRun(serverId!, selectedBranch),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.versioning.branchRuntime(serverId!, selectedBranch),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.versioning.branches(serverId!),
      });
    },
    onError: (err) => {
      toast(
        "error",
        "Branch stop failed",
        err instanceof Error ? err.message : "Failed to stop branch container.",
      );
    },
  });

  const branchRestartMutation = useMutation({
    mutationFn: async () => {
      await api.stopBranchRun(serverId!, selectedBranch);
      return api.startBranchRun(serverId!, selectedBranch);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.versioning.branchRuntime(serverId!, selectedBranch),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.versioning.branches(serverId!),
      });
    },
    onError: (err) => {
      toast(
        "error",
        "Branch restart failed",
        err instanceof Error ? err.message : "Failed to restart branch container.",
      );
    },
  });

  const selectBranch = useCallback(
    (nextBranch: string) => {
      if (typeof window !== "undefined" && serverId) {
        try {
          window.localStorage.setItem(
            `onx.selectedBranch.${serverId}`,
            nextBranch,
          );
        } catch {
          // Storage can be unavailable in privacy-restricted contexts.
        }
      }
      const params = new URLSearchParams(location.search);
      if (nextBranch === "main") {
        params.delete("branch");
      } else {
        params.set("branch", nextBranch);
      }
      const search = params.toString();
      navigate(
        { pathname: location.pathname, search: search ? `?${search}` : "" },
        { replace: true },
      );
    },
    [location.pathname, location.search, navigate, serverId],
  );

  const branchContextValue = useMemo(
    () => ({
      branch: selectedBranch,
      setBranch: selectBranch,
      gitBacked,
      serverMode,
    }),
    [selectedBranch, selectBranch, gitBacked, serverMode],
  );

  const startMutation = useStartServer();
  const stopMutation = useStopServer();
  const restartMutation = useRestartServer();

  const [showStopDialog, setShowStopDialog] = useState(false);
  const [copiedAddress, setCopiedAddress] = useState(false);

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [location.pathname, setMobileSidebarOpen]);

  const getSectionTitle = () => {
    const path = location.pathname;
    if (path.includes("/files")) return "Files";
    if (path.includes("/network")) return "Network & Exposure";
    if (path.includes("/backups")) return "Backups";
    if (path.includes("/mods/marketplace")) return "Mod Marketplace";
    if (path.includes("/plugins/marketplace")) return "Plugin Marketplace";
    if (path.includes("/mods")) return "Mods";
    if (path.includes("/plugins")) return "Plugins";
    if (path.includes("/versioning")) return "Versions & Sandboxes";
    if (path.includes("/activity")) return "Change History";
    if (path.includes("/settings")) return "Settings";
    return "Console";
  };
  const currentSection = getSectionTitle();

  const searchPath = new URLSearchParams(location.search).get("path") || "";
  const searchFile =
    new URLSearchParams(location.search).get("file") ||
    new URLSearchParams(location.search).get("edit") ||
    "";
  const resolvedPath =
    searchPath ||
    (searchFile.includes("/")
      ? searchFile.substring(0, searchFile.lastIndexOf("/"))
      : "");
  const filePathParts =
    currentSection === "Files" ? resolvedPath.split("/").filter(Boolean) : [];
  const fileName = searchFile ? searchFile.split("/").pop() : "";

  const effectiveServerId = serverId || "";
  const serverName = server?.name || effectiveServerId || "Server";
  const canPowerServer = permissions.canPower(effectiveServerId);
  const canAccessFiles = permissions.canFiles(effectiveServerId);
  const canViewExposure = permissions.canViewExposure(effectiveServerId);
  const { exposure } = useServerExposure(
    effectiveServerId,
    isNonMainBranch ? selectedBranch : undefined,
    {
      includeAgentAndPorts: false,
      enabled: Boolean(effectiveServerId) && canViewExposure,
    },
  );

  // Canonical playable join address (filters Docker 172.16-31.x.x & 0.0.0.0; honors public_address)
  const branchGamePort = branchRuntime?.port_set?.game_port;
  const resolvedHeaderAccess = server
    ? resolveAccessAddress(server, exposure ?? null)
    : { address: null, kind: null };
  const fallbackHeaderJoin = server ? resolveJoinAddress(server) : { address: "", isPublic: false };
  const serverAddress = server
    ? isNonMainBranch
      ? exposure?.targets?.[0]?.public_address ||
        (branchGamePort ? `localhost:${branchGamePort}` : "")
      : resolvedHeaderAccess.address ?? fallbackHeaderJoin.address
    : "";
  const isHeaderAddressPublic = isNonMainBranch
    ? Boolean(exposure?.targets?.[0]?.public_address)
    : resolvedHeaderAccess.kind === "playit" ||
      resolvedHeaderAccess.kind === "cloudflare" ||
      fallbackHeaderJoin.isPublic;

  const handleCopyAddress = () => {
    if (!serverAddress) return;
    void copy(serverAddress, "Join address copied to clipboard");
    setCopiedAddress(true);
    setTimeout(() => setCopiedAddress(false), 2000);
  };

  const activeStatus = isNonMainBranch
    ? (branchRuntime?.runtime_status || "stopped")
    : (server?.status || "stopped");
  const isStatusRunning = activeStatus === "running" || activeStatus === "RUNNING";
  const isStatusStarting = activeStatus === "starting" || activeStatus === "STARTING";
  const isRunning = isStatusRunning;
  const isStarting = isStatusStarting;
  const canStop = isRunning || isStarting;
  const isStopping = activeStatus === "stopping" || activeStatus === "STOPPING";
  const isTransitioning = isNonMainBranch
    ? isStarting ||
      isStopping ||
      branchStartMutation.isPending ||
      branchStopMutation.isPending ||
      branchRestartMutation.isPending
    : isStarting ||
      isStopping ||
      server?.status === "provisioning" ||
      startMutation.isPending ||
      stopMutation.isPending ||
      restartMutation.isPending;

  const withBranch = useCallback(
    (path: string) =>
      isNonMainBranch ? `${path}?branch=${encodeURIComponent(selectedBranch)}` : path,
    [isNonMainBranch, selectedBranch],
  );

  const buildFilesPathUrl = useCallback(
    (dirPath?: string) => {
      const params = new URLSearchParams();
      if (dirPath) params.set("path", dirPath);
      if (isNonMainBranch) {
        params.set("branch", selectedBranch);
      } else if (urlBranch) {
        params.set("branch", urlBranch);
      }
      const currentParams = new URLSearchParams(location.search);
      const view = currentParams.get("view") || currentParams.get("mode");
      if (view === "live-state" || view === "live_state") {
        params.set("view", "live-state");
      }
      const qs = params.toString();
      return `/servers/${serverId}/files${qs ? `?${qs}` : ""}`;
    },
    [isNonMainBranch, location.search, selectedBranch, serverId, urlBranch],
  );

  const availableServers = useMemo(() => {
    const list = [...servers];
    if (server && !list.some((s) => s.server_id === server.server_id)) {
      list.unshift(server);
    }
    return list;
  }, [servers, server]);

  const currentSubPath =
    location.pathname.split(`/servers/${effectiveServerId}/`)[1] ||
    (location.pathname.endsWith(`/servers/${effectiveServerId}`)
      ? "console"
      : location.pathname.split("/").pop() || "console");

  const navPills = [
    { id: "console", label: "Console", path: withBranch(`/servers/${effectiveServerId}/console`), icon: "dashboard" as const },
    ...(canAccessFiles ? [{ id: "files", label: "Files", path: withBranch(`/servers/${effectiveServerId}/files`), icon: "folder" as const }] : []),
    ...(supportsPlugins ? [{ id: "plugins", label: "Plugins", path: withBranch(`/servers/${effectiveServerId}/plugins`), icon: "plugin" as const }] : []),
    ...(supportsMods ? [{ id: "mods", label: "Mods", path: withBranch(`/servers/${effectiveServerId}/mods`), icon: "plugin" as const }] : []),
    ...(serverMode === "advanced"
      ? [{ id: "versioning", label: "Versions", path: withBranch(`/servers/${effectiveServerId}/versioning`), icon: "backup" as const }]
      : []),
    { id: "network", label: "Network & Exposure", path: withBranch(`/servers/${effectiveServerId}/network`), icon: "activity" as const },
    { id: "backups", label: "Backups", path: `/servers/${effectiveServerId}/backups`, icon: "backup" as const },
    { id: "activity", label: "Change History", path: withBranch(`/servers/${effectiveServerId}/activity`), icon: "clock" as const },
    { id: "settings", label: "Settings", path: withBranch(`/servers/${effectiveServerId}/settings`), icon: "settings" as const },
  ];

  const pendingSettings = server?.pending_settings_branch;
  const hasPendingSettings =
    !isNonMainBranch &&
    Boolean(pendingSettings && pendingSettings.status === "pending");

  return (
    <div className="min-h-screen bg-surface-page text-text-primary transition-colors flex flex-col">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:inset-block-start-3 focus:inset-inline-start-3 focus:z-50 focus:rounded-lg focus:bg-surface-elevated focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-accent-primary focus:shadow-lg focus:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus"
        onClick={() => {
          const main = document.getElementById("main-content");
          if (main) main.focus();
        }}
      >
        Skip to content
      </a>
      <LoadingBar />
      <TopBar />

      {/* Shared Unified Sidebar */}
      <Sidebar
        serverContext={{
          serverId: serverId!,
          serverName: server?.name,
          serverType: server?.server_type,
          supportsMods,
          supportsPlugins,
          canFiles: canAccessFiles,
          mode: serverMode,
          branch: isNonMainBranch ? selectedBranch : undefined,
        }}
      />

      <main
        id="main-content"
        tabIndex={-1}
        className={`min-h-[calc(100vh-3.5rem)] pt-14 overflow-y-auto pb-12 transition-all duration-200 outline-hidden flex flex-col flex-1 min-h-0 ${
          sidebarOpen ? "lg:pl-56" : "lg:pl-0"
        } ${rightPanelOpen ? "lg:pr-[488px] xl:pr-[528px]" : ""}`}
      >
        <div className="mx-auto w-full max-w-[1880px] p-4 sm:p-5 lg:px-7 lg:py-5 space-y-3.5 pb-12 flex flex-col flex-1 min-h-0">
          {/* Breadcrumb Navigation */}
          <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-xs flex-wrap text-text-muted">
            <Link
              to={currentSection === "Console" ? "/servers" : withBranch(`/servers/${serverId}/console`)}
              className="text-text-muted hover:text-text-primary flex items-center gap-1 transition-colors"
            >
              <Icon name="chevron-left" size={14} />
              <span>{server?.name || "Server"}</span>
            </Link>
            <span className="text-border-subtle">/</span>

            {currentSection === "Files" && (filePathParts.length > 0 || fileName) ? (
              <>
                <Link
                  to={buildFilesPathUrl()}
                  className="text-text-muted hover:text-text-primary transition-colors"
                >
                  Files
                </Link>
                {filePathParts.map((part, index) => {
                  const pathUpTo = filePathParts.slice(0, index + 1).join("/");
                  const isLast = index === filePathParts.length - 1 && !fileName;
                  return (
                    <span key={pathUpTo} className="flex items-center gap-2">
                      <span className="text-border-subtle">/</span>
                      {isLast ? (
                        <span className="font-semibold text-text-primary">
                          {part}
                        </span>
                      ) : (
                        <Link
                          to={buildFilesPathUrl(pathUpTo)}
                          className="text-text-muted hover:text-text-primary transition-colors"
                        >
                          {part}
                        </Link>
                      )}
                    </span>
                  );
                })}
                {fileName && (
                  <span className="flex items-center gap-2">
                    <span className="text-border-subtle">/</span>
                    <span className="font-semibold text-text-primary">
                      {fileName}
                    </span>
                  </span>
                )}
              </>
            ) : (
              <span className="font-semibold text-text-primary">
                {currentSection}
              </span>
            )}
          </nav>

          {/* Unified Server Workspace Header */}
          <div
            data-testid="server-context-header"
            className={`flex flex-col gap-3 rounded-xl border px-4 py-3.5 transition-all ${
              isRunning
                ? "border-status-success-border/40 bg-status-success-bg/10 shadow-2xs"
                : isStarting
                  ? "border-status-warning-border/40 bg-status-warning-bg/10 shadow-2xs"
                  : "border-border-subtle bg-surface-card shadow-2xs"
            }`}
          >
            <div
              data-testid="server-header-primary-row"
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3"
            >
              {/* Left: Identity & Metadata */}
              <div className="flex items-center gap-3 min-w-0 max-w-full">
                <ServerIcon
                  serverId={effectiveServerId}
                  serverName={serverName}
                  serverType={server?.server_type}
                  status={activeStatus}
                  iconDataUrl={server?.icon_data_url ?? null}
                  size={44}
                  className={
                    isRunning
                      ? "rounded-xl ring-2 ring-status-success/25 ring-offset-2 ring-offset-surface-card"
                      : ""
                  }
                />

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-lg sm:text-xl font-bold tracking-tight text-text-primary">
                      {serverName}
                    </h1>

                    {/* Quick Server-Switcher Dropdown (strips ?branch= when changing server) */}
                    <div className="relative inline-flex items-center">
                      <select
                        aria-label="Switch server"
                        data-testid="server-switcher-select"
                        value={serverId}
                        onChange={(e) => {
                          const targetId = e.target.value;
                          if (targetId && targetId !== serverId) {
                            const targetServer = availableServers.find(
                              (s) => s.server_id === targetId,
                            );
                            const targetCaps = targetServer?.server_type
                              ? getServerCapabilities(targetServer.server_type)
                              : null;
                            const targetMode = targetServer
                              ? resolveServerMode(targetServer.mode)
                              : null;
                            const baseSegment = currentSubPath.split("/")[0];
                            const restSegment = currentSubPath.includes("/")
                              ? currentSubPath.slice(currentSubPath.indexOf("/"))
                              : "";
                            let nextSubPath = currentSubPath;
                            if (baseSegment === "mods" && targetCaps && !targetCaps.supportsMods) {
                              nextSubPath = targetCaps.supportsPlugins
                                ? `plugins${restSegment}`
                                : "console";
                            } else if (
                              baseSegment === "plugins" &&
                              targetCaps &&
                              !targetCaps.supportsPlugins
                            ) {
                              nextSubPath = targetCaps.supportsMods
                                ? `mods${restSegment}`
                                : "console";
                            } else if (baseSegment === "versioning" && targetMode === "simple") {
                              nextSubPath = "console";
                            }

                            const nextParams = new URLSearchParams(location.search);
                            nextParams.delete("branch");
                            const nextSearch = nextParams.toString();
                            navigate(
                              `/servers/${targetId}/${nextSubPath}${
                                nextSearch ? `?${nextSearch}` : ""
                              }`,
                            );
                          }
                        }}
                        className="appearance-none bg-surface-muted hover:bg-surface-hover text-text-secondary hover:text-text-primary text-xs font-medium py-1 pl-2.5 pr-7 rounded-lg border border-border-subtle hover:border-border-hover cursor-pointer transition-colors focus:outline-hidden focus:ring-1 focus:ring-border-focus"
                      >
                        {availableServers.length > 0 ? (
                          availableServers.map((s) => {
                            const statusLabel = STATUS_MAP[s.status]?.label ?? s.status;
                            return (
                              <option key={s.server_id} value={s.server_id}>
                                {s.name} ({statusLabel})
                              </option>
                            );
                          })
                        ) : (
                          <option value={serverId}>{serverName}</option>
                        )}
                      </select>
                      <span className="pointer-events-none absolute right-2 text-text-muted">
                        <Icon name="chevron-down" size={12} />
                      </span>
                    </div>

                    {gitBacked && (
                      <div
                        className="relative inline-flex items-center gap-1.5"
                        data-testid="branch-selector"
                      >
                        <Icon name="backup" size={12} className="text-text-muted" />
                        <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                          Branch
                        </span>
                        <select
                          aria-label="Switch branch"
                          data-testid="branch-switcher-select"
                          value={selectedBranch}
                          onChange={(e) => selectBranch(e.target.value)}
                          className="appearance-none bg-surface-muted hover:bg-surface-hover text-text-secondary hover:text-text-primary text-xs font-medium py-1 pl-2.5 pr-7 rounded-lg border border-border-subtle hover:border-border-hover cursor-pointer transition-colors focus:outline-hidden focus:ring-1 focus:ring-border-focus"
                        >
                          {branches.map((branch) => (
                            <option key={branch.name} value={branch.name}>
                              {branch.name}
                            </option>
                          ))}
                        </select>
                        <span className="pointer-events-none absolute right-2 text-text-muted">
                          <Icon name="chevron-down" size={12} />
                        </span>
                      </div>
                    )}

                    <StatusBadge status={activeStatus} />
                    {isNonMainBranch && branchRuntime && !branchRuntime.container_provisioned && (
                      <span
                        data-testid="branch-unprovisioned-badge"
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-surface-muted text-text-muted border border-border-subtle"
                      >
                        No Container
                      </span>
                    )}
                    {server?.server_type && <LoaderBadge loader={server.server_type} />}
                    {server?.provider && (
                      <span
                        data-testid="server-provider-badge"
                        className={
                          "inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium " +
                          (server.provider === "docker"
                            ? "bg-status-info-bg text-status-info"
                            : "bg-surface-muted text-text-secondary")
                        }
                        title={
                          server.provider === "docker"
                            ? "Running in a Docker Container"
                            : "Running directly on Host Filesystem / Process"
                        }
                      >
                        <Icon name={server.provider === "docker" ? "server" : "folder"} size={12} />
                        {server.provider === "docker" ? "Container" : "File / Host"}
                      </span>
                    )}
                  </div>

                  {server && (
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-muted">
                      <span className="font-mono">
                        <strong className="text-text-secondary">MC:</strong> {server.minecraft_version}
                      </span>
                      {serverAddress && (
                        <>
                          <span className="text-border-subtle">•</span>
                          <span
                            data-testid="server-header-copy-address"
                            onClick={handleCopyAddress}
                            className="inline-flex items-center gap-1 cursor-pointer"
                            title={
                              isHeaderAddressPublic
                                ? "Public exposure address — click to copy"
                                : "Join address — click to copy"
                            }
                          >
                            {isHeaderAddressPublic && (
                              <Icon name="globe" size={12} className="text-status-success" />
                            )}
                            <strong className="text-text-secondary">Address:</strong>
                            <Chip
                              label={copiedAddress ? "Copied!" : serverAddress}
                              size="xs"
                              variant="inset"
                              className="font-mono text-[11px] cursor-pointer"
                            />
                          </span>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Far-Right: Power Lifecycle Button Group (gated by canPower) */}
              {canPowerServer && (
                <div
                  data-testid="server-header-power-actions"
                  className="flex items-center gap-2 shrink-0"
                >
                  {canStop ? (
                    <>
                      {isRunning && (
                        <Button
                          size="sm"
                          variant="secondary"
                          icon="restart"
                          disabled={isTransitioning}
                          onClick={() =>
                            isNonMainBranch
                              ? branchRestartMutation.mutate()
                              : restartMutation.mutate(serverId!)
                          }
                        >
                          Restart
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="danger"
                        icon="stop"
                        disabled={
                          isStopping ||
                          (isNonMainBranch
                            ? branchStopMutation.isPending
                            : stopMutation.isPending)
                        }
                        onClick={() => setShowStopDialog(true)}
                      >
                        Stop
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant="primary"
                      icon="play"
                      disabled={isTransitioning || !server}
                      onClick={() =>
                        isNonMainBranch
                          ? branchStartMutation.mutate()
                          : startMutation.mutate(serverId!)
                      }
                    >
                      Start
                    </Button>
                  )}
                </div>
              )}
            </div>

            {/* Sub-Page Navigation Pills (Mobile/Tablet only) */}
            <div className="w-full pt-2.5 border-t border-border-subtle flex items-center justify-between flex-wrap gap-2 lg:hidden">
              <nav aria-label="Server quick navigation" className="flex items-center gap-1.5 overflow-x-auto py-0.5 text-xs">
                {navPills.map((pill) => {
                  const isActive =
                    pill.id === "console"
                      ? currentSubPath === "console"
                      : currentSubPath === pill.id || currentSubPath.startsWith(`${pill.id}/`);
                  return (
                    <Link
                      key={pill.id}
                      to={pill.path}
                      aria-label={`Quick ${pill.label}`}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                        isActive
                          ? "bg-accent-primary text-accent-contrast-text shadow-xs font-semibold"
                          : "bg-surface-muted text-text-secondary hover:bg-surface-hover hover:text-text-primary border border-border-subtle hover:border-border-hover"
                      }`}
                    >
                      <Icon name={pill.icon} size={13} />
                      <span>{pill.label}</span>
                    </Link>
                  );
                })}
              </nav>
            </div>
          </div>

          {/* Pending Settings Restart Notice Banner */}
          {hasPendingSettings && (
            <div
              data-testid="pending-settings-banner"
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-warning-border bg-status-warning-bg px-4 py-2.5 text-xs"
            >
              <div className="flex items-center gap-2 text-text-primary">
                <Icon name="alert" size={15} className="text-status-warning shrink-0" />
                <span>
                  <strong className="font-semibold">Settings changes pending restart.</strong>{" "}
                  Restart the server to apply queued configuration updates.
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Link
                  to={`/servers/${effectiveServerId}/settings`}
                  className="px-2.5 py-1 rounded-lg border border-border-default bg-surface-card text-text-primary font-medium hover:bg-surface-hover transition-colors"
                >
                  View Settings
                </Link>
                {canPowerServer && isRunning && (
                  <button
                    type="button"
                    data-testid="pending-settings-restart-btn"
                    disabled={isTransitioning}
                    onClick={() => restartMutation.mutate(effectiveServerId)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-accent-primary text-accent-contrast-text font-semibold hover:bg-accent-hover disabled:opacity-50 transition-colors cursor-pointer"
                  >
                    <Icon name="restart" size={12} />
                    <span>Restart &amp; Apply</span>
                  </button>
                )}
              </div>
            </div>
          )}

          <ServerBranchContext.Provider value={branchContextValue}>
            <UpgradePinnedBanner key={effectiveServerId} serverId={effectiveServerId} />

            <ErrorBoundary>
              <Suspense fallback={<RouteFallback />}>
                <Outlet />
              </Suspense>
            </ErrorBoundary>
          </ServerBranchContext.Provider>
        </div>
      </main>

      {/* Stop Server Confirmation */}
      <ConfirmDialog
        open={showStopDialog}
        title={
          isNonMainBranch
            ? `Stop branch ${selectedBranch}?`
            : `Stop ${server?.name || "Server"}?`
        }
        description={
          isNonMainBranch
            ? `Are you sure you want to stop the isolated container for branch "${selectedBranch}"?`
            : "Are you sure you want to stop this Minecraft server? Active player connections will be safely terminated."
        }
        confirmLabel={isNonMainBranch ? "Stop Branch Container" : "Stop Server"}
        variant="danger"
        onConfirm={() => {
          setShowStopDialog(false);
          if (isNonMainBranch) {
            branchStopMutation.mutate();
          } else {
            stopMutation.mutate(serverId!);
          }
        }}
        onCancel={() => setShowStopDialog(false)}
      />

      {activeDrawerId && <OperationDrawer operationId={activeDrawerId} onClose={closeDrawer} />}
      <Toaster />
    </div>
  );
}
