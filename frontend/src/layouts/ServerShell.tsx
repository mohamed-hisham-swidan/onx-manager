import { useEffect, useState, Suspense } from "react";
import { Outlet, useLocation, useParams, Link } from "react-router-dom";
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
import {
  useServerDetail,
  useStartServer,
  useStopServer,
  useRestartServer,
} from "@/server_manager/hooks/useServers";
import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";

export function ServerShell() {
  const { serverId } = useParams<{ serverId: string }>();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);
  const activeDrawerId = useOperationStore((s) => s.activeDrawerId);
  const closeDrawer = useOperationStore((s) => s.closeDrawer);
  const location = useLocation();

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

  const serverAddress = server ? `127.0.0.1:${server.port}` : "";

  const handleCopyAddress = () => {
    if (!serverAddress) return;
    navigator.clipboard?.writeText(serverAddress);
    setCopiedAddress(true);
    setTimeout(() => setCopiedAddress(false), 2000);
  };

  const isRunning = server?.status === "running";
  const isStarting = server?.status === "starting";
  const canStop = isRunning || isStarting;
  const isStopping = server?.status === "stopping";
  const isTransitioning =
    isStarting ||
    isStopping ||
    server?.status === "provisioning" ||
    startMutation.isPending ||
    stopMutation.isPending ||
    restartMutation.isPending;

  return (
    <div className="min-h-screen bg-surface-page text-text-primary transition-colors">
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
        className={`pt-14 transition-all duration-200 ${
          sidebarOpen ? "lg:pl-56" : "lg:pl-0"
        }`}
      >
        <div className="mx-auto max-w-7xl p-3.5 sm:p-5 lg:px-6 lg:py-5 space-y-4">
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

          {/* Server Identity Strip (D4) */}
          {server && (
            <div className="flex flex-col gap-3 rounded-2xl border border-border-subtle bg-surface-card p-4 shadow-2xs sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3 min-w-0">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-primary/10 text-accent-primary border border-accent-primary/20 shadow-2xs">
                  <Icon name="server" size={22} />
                </div>

                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-lg font-bold text-text-primary">
                      {server.name}
                    </h1>
                    <StatusBadge status={server.status} />
                    <LoaderBadge loader={server.server_type} />
                    {server.provider && (
                      <span
                        data-testid="server-provider-badge"
                        className={
                          "inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium " +
                          (server.provider === "docker"
                            ? "bg-status-info/10 text-status-info border border-status-info/20"
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

                  <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-text-muted">
                    <span>
                      <strong className="text-text-secondary">MC:</strong> {server.minecraft_version}
                    </span>
                    <span>•</span>
                    <span>
                      <strong className="text-text-secondary">Port:</strong> {server.port}
                    </span>
                    <span>•</span>
                    <span className="inline-flex items-center gap-1">
                      <strong className="text-text-secondary">Address:</strong>
                      <Chip
                        label={copiedAddress ? "Copied!" : serverAddress}
                        size="xs"
                        variant="outline"
                        onClick={handleCopyAddress}
                        className="font-mono text-[11px]"
                      />
                    </span>
                  </div>
                </div>
              </div>

              {/* Server Power Controls */}
              <div className="flex items-center gap-2 shrink-0 pt-2 sm:pt-0 border-t border-border-subtle sm:border-t-0">
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
                    disabled={isTransitioning}
                    onClick={() => startMutation.mutate(serverId!)}
                  >
                    Start
                  </Button>
                )}
              </div>
            </div>
          )}

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
