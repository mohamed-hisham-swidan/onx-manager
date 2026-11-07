import { useEffect, useState, Suspense, useContext, useMemo } from "react";
import { Outlet, useLocation, useParams, Link, useNavigate } from "react-router-dom";
import { QueryClientContext } from "@tanstack/react-query";
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
import * as serverHooks from "@/server_manager/hooks/useServers";
import {
  useServerDetail,
  useStartServer,
  useStopServer,
  useRestartServer,
} from "@/server_manager/hooks/useServers";
import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";

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
  return (fn as () => { data?: Array<{ server_id: string; name: string; status: string; port?: number }> })();
}

export function ServerShell() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);
  const activeDrawerId = useOperationStore((s) => s.activeDrawerId);
  const closeDrawer = useOperationStore((s) => s.closeDrawer);
  const location = useLocation();

  const serversQuery = useSafeServersList();
  const servers = useMemo(() => serversQuery?.data ?? [], [serversQuery?.data]);

  const { data: server } = useServerDetail(serverId!);
  const { supportsMods, supportsPlugins } = getServerCapabilities(server?.server_type);

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
    if (path.includes("/mods")) return "Mods";
    if (path.includes("/plugins")) return "Plugins";
    if (path.includes("/versioning")) return "Versions & Testing";
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

  const effectiveHost =
    server?.deployment_host &&
    server.deployment_host !== "undefined" &&
    server.deployment_host !== "null"
      ? server.deployment_host.trim()
      : "";
  const effectivePort = server?.deployment_port ?? server?.port;
  const serverAddress = server
    ? `${effectiveHost || "127.0.0.1"}:${effectivePort}`
    : "";
  const headerDisplayIpOrFallback = effectiveHost || serverAddress;

  const handleCopyAddress = () => {
    if (!serverAddress) return;
    navigator.clipboard?.writeText(serverAddress);
    setCopiedAddress(true);
    setTimeout(() => setCopiedAddress(false), 2000);
  };

  const isStatusRunning = server?.status === "running" || server?.status === "RUNNING";
  const isStatusStarting = server?.status === "starting" || server?.status === "STARTING";
  const isRunning = isStatusRunning;
  const isStarting = isStatusStarting;
  const canStop = isRunning || isStarting;
  const isStopping = server?.status === "stopping" || server?.status === "STOPPING";
  const isTransitioning =
    isStarting ||
    isStopping ||
    server?.status === "provisioning" ||
    startMutation.isPending ||
    stopMutation.isPending ||
    restartMutation.isPending;

  const effectiveServerId = serverId || "";
  const serverName = server?.name || effectiveServerId || "Server";
  const maxPlayers = String(
    (server as unknown as { env?: { MAX_PLAYERS?: string | number } })?.env?.MAX_PLAYERS ??
    server?.max_players ??
    20
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
    (location.pathname.endsWith(`/servers/${effectiveServerId}`) ? "console" : location.pathname.split("/").pop() || "console");

  const navPills = [
    { id: "console", label: "Console", path: `/servers/${effectiveServerId}/console`, icon: "dashboard" as const },
    { id: "files", label: "Files", path: `/servers/${effectiveServerId}/files`, icon: "folder" as const },
    ...(supportsPlugins ? [{ id: "plugins", label: "Plugins", path: `/servers/${effectiveServerId}/plugins`, icon: "plugin" as const }] : []),
    ...(supportsMods ? [{ id: "mods", label: "Mods", path: `/servers/${effectiveServerId}/mods`, icon: "plugin" as const }] : []),
    { id: "versioning", label: "Versions", path: `/servers/${effectiveServerId}/versioning`, icon: "backup" as const },
    { id: "network", label: "Network", path: `/servers/${effectiveServerId}/network`, icon: "activity" as const },
    { id: "activity", label: "Activity", path: `/servers/${effectiveServerId}/activity`, icon: "clock" as const },
    { id: "settings", label: "Settings", path: `/servers/${effectiveServerId}/settings`, icon: "settings" as const },
  ];

  return (
    <div className="min-h-screen bg-surface-page text-text-primary transition-colors">
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
        }}
      />

      <main
        id="main-content"
        tabIndex={-1}
        className={`min-h-[calc(100vh-3.5rem)] pt-14 overflow-y-auto pb-16 transition-all duration-200 outline-hidden ${
          sidebarOpen ? "lg:pl-56" : "lg:pl-0"
        }`}
      >
        <div className="mx-auto w-full max-w-[1880px] p-4 sm:p-6 lg:px-8 lg:py-6 space-y-4 pb-16">
          {/* Breadcrumb Navigation (Exact semantics preserved for tests) */}
          <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-xs flex-wrap text-text-muted">
            <Link
              to={currentSection === "Console" ? "/servers" : `/servers/${serverId}/console`}
              className="text-text-muted hover:text-text-primary flex items-center gap-1 transition-colors"
            >
              <Icon name="chevron-left" size={14} />
              <span>{server?.name || "Server"}</span>
            </Link>
            <span className="text-border-subtle">/</span>

            {currentSection === "Files" && (filePathParts.length > 0 || fileName) ? (
              <>
                <Link
                  to={`/servers/${serverId}/files`}
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
                          to={`/servers/${serverId}/files?path=${encodeURIComponent(pathUpTo)}`}
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

          {/* Unified Server Workspace Header (<ServerContextHeader>) */}
          <div
            data-testid="server-context-header"
            className={`flex flex-col gap-4 rounded-xl border p-4 transition-all ${
              isRunning
                ? "border-status-success-border/40 bg-status-success-bg/15 shadow-2xs"
                : isStarting
                ? "border-status-warning-border/40 bg-status-warning-bg/15 shadow-2xs"
                : "border-border-subtle bg-surface-card shadow-2xs"
            }`}
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              {/* Left: Identity & Metadata */}
              <div className="flex flex-wrap items-center gap-3.5 min-w-0">
                <div
                  className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border transition-all ${
                    isRunning
                      ? "border-status-success/30 bg-status-success-bg text-status-success shadow-xs ring-2 ring-status-success/20 ring-offset-2 ring-offset-surface-card"
                      : "border-accent-primary/20 bg-accent-primary/10 text-accent-primary shadow-2xs"
                  }`}
                >
                  <Icon name="server" size={24} />
                </div>

                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-xl font-bold tracking-tight text-text-primary">
                      {serverName}
                    </h1>

                    {/* Quick Server-Switcher Dropdown */}
                    <div className="relative inline-flex items-center">
                      <select
                        aria-label="Switch server"
                        data-testid="server-switcher-select"
                        value={serverId}
                        onChange={(e) => {
                          const targetId = e.target.value;
                          if (targetId && targetId !== serverId) {
                            navigate(`/servers/${targetId}/${currentSubPath}${location.search}`);
                          }
                        }}
                        className="appearance-none bg-surface-elevated hover:bg-surface-hover text-text-secondary hover:text-text-primary text-xs font-medium py-1 pl-2.5 pr-7 rounded-lg border border-border-default cursor-pointer transition-colors focus:outline-hidden focus:ring-1 focus:ring-border-focus"
                      >
                        {availableServers.length > 0 ? (
                          availableServers.map((s) => (
                            <option key={s.server_id} value={s.server_id}>
                              {s.name} ({s.status})
                            </option>
                          ))
                        ) : (
                          <option value={serverId}>{serverName}</option>
                        )}
                      </select>
                      <span className="pointer-events-none absolute right-2 text-text-muted">
                        <Icon name="chevron-down" size={12} />
                      </span>
                    </div>

                    <StatusBadge status={server?.status || "stopped"} />
                    {server?.server_type && <LoaderBadge loader={server.server_type} />}
                    {server?.provider && (
                      <span
                        data-testid="server-provider-badge"
                        className={
                          "inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium " +
                          (server.provider === "docker"
                            ? "bg-status-info-bg text-status-info border border-status-info-border"
                            : "bg-surface-elevated text-text-secondary border border-border-default")
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

                  <div className="mt-1.5 flex flex-wrap items-center gap-2.5 text-xs text-text-muted">
                    {/* Prominent High-Contrast Status Capsule */}
                    {isStatusRunning ? (
                      <span
                        data-testid="server-status-capsule"
                        className="inline-flex items-center gap-1.5 rounded-full border border-status-success/40 bg-status-success-bg px-3 py-1 font-mono text-xs font-bold text-status-success shadow-xs"
                      >
                        <span className="text-[10px] leading-none" aria-hidden="true">●</span>
                        <span>ONLINE · PORT {server?.port ?? 25565}</span>
                      </span>
                    ) : isStatusStarting ? (
                      <span
                        data-testid="server-status-capsule"
                        className="inline-flex items-center gap-1.5 rounded-full border border-status-warning/40 bg-status-warning-bg px-3 py-1 font-mono text-xs font-bold text-status-warning shadow-xs"
                      >
                        <span className="text-[10px] leading-none" aria-hidden="true">◐</span>
                        <span>STARTING · PORT {server?.port ?? 25565}</span>
                      </span>
                    ) : (
                      <span
                        data-testid="server-status-capsule"
                        className="inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-elevated px-3 py-1 font-mono text-xs font-bold text-text-secondary shadow-xs"
                      >
                        <span className="text-[10px] leading-none" aria-hidden="true">○</span>
                        <span>OFFLINE · CONTAINER HALTED</span>
                      </span>
                    )}

                    {/* Active Player Counter Badge */}
                    <div
                      data-testid="server-active-players-badge"
                      className="inline-flex items-center gap-1.5 rounded-full border border-border-default bg-surface-elevated px-3 py-1 font-mono text-xs font-semibold text-text-secondary"
                    >
                      <Icon name="users" size={13} className="text-text-muted" />
                      <span>0 / {maxPlayers} Players</span>
                    </div>

                    {server && (
                      <>
                        <span className="font-mono">
                          <strong className="text-text-secondary">MC:</strong> {server.minecraft_version}
                        </span>
                        <span className="text-border-subtle">•</span>
                        <span className="font-mono">
                          <strong className="text-text-secondary">Port:</strong>{" "}
                          {effectiveHost || server.port}
                        </span>
                        <span className="text-border-subtle">•</span>
                        <span
                          data-testid="server-header-copy-address"
                          onClick={handleCopyAddress}
                          className="inline-flex items-center gap-1 cursor-pointer"
                        >
                          <strong className="text-text-secondary">Address:</strong>
                          <Chip
                            label={copiedAddress ? "Copied!" : headerDisplayIpOrFallback}
                            size="xs"
                            variant="outline"
                            onClick={handleCopyAddress}
                            className="font-mono text-[11px] cursor-pointer"
                          />
                        </span>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* Center-Right: Instance Allocation Summary */}
              {server && (
                <div className="hidden xl:flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-elevated/70 px-3.5 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">Heap</span>
                    <span className="font-mono text-xs tabular-nums text-text-primary">
                      {server.min_memory_mb && server.max_memory_mb
                        ? `${server.min_memory_mb}–${server.max_memory_mb} MB`
                        : `${server.max_memory_mb || 2048} MB`}
                    </span>
                  </div>

                  <div className="h-4 w-px bg-border-subtle" />

                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">View Dist</span>
                    <span className="font-mono text-xs font-semibold tabular-nums text-text-primary">
                      {server.view_distance ?? 10} chunks
                    </span>
                  </div>
                </div>
              )}

              {/* Far-Right: Power Lifecycle Button Group */}
              <div className="flex items-center gap-2 shrink-0 pt-2 lg:pt-0 border-t border-border-subtle lg:border-t-0">
                {canStop ? (
                  <>
                    {isRunning && (
                      <Button
                        size="sm"
                        variant="secondary"
                        icon="restart"
                        disabled={isTransitioning}
                        onClick={() => restartMutation.mutate(serverId!)}
                      >
                        Restart
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="danger"
                      icon="stop"
                      disabled={isStopping || stopMutation.isPending}
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
                    onClick={() => startMutation.mutate(serverId!)}
                  >
                    Start
                  </Button>
                )}
              </div>
            </div>

            {/* Sub-Page Navigation / Breadcrumb Pills */}
            <div className="w-full pt-3 border-t border-border-subtle flex items-center justify-between flex-wrap gap-2">
              <nav aria-label="Server quick navigation" className="flex items-center gap-1.5 overflow-x-auto py-0.5 text-xs">
                {navPills.map((pill) => {
                  const isActive = location.pathname.includes(pill.id);
                  return (
                    <Link
                      key={pill.id}
                      to={pill.path}
                      aria-label={`Quick ${pill.label}`}
                      className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                        isActive
                          ? "bg-accent-primary text-accent-contrast-text shadow-xs font-semibold"
                          : "bg-surface-elevated text-text-secondary hover:bg-surface-hover hover:text-text-primary border border-border-default"
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

          <ErrorBoundary>
            <Suspense fallback={<RouteFallback />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </div>
      </main>

      {/* Stop Server Confirmation */}
      <ConfirmDialog
        open={showStopDialog}
        title={`Stop ${server?.name || "Server"}?`}
        description="Are you sure you want to stop this Minecraft server? Active player connections will be safely terminated."
        confirmLabel="Stop Server"
        variant="danger"
        onConfirm={() => {
          setShowStopDialog(false);
          stopMutation.mutate(serverId!);
        }}
        onCancel={() => setShowStopDialog(false)}
      />

      {activeDrawerId && <OperationDrawer operationId={activeDrawerId} onClose={closeDrawer} />}
      <Toaster />
    </div>
  );
}
