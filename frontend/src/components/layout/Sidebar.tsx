import React, { useContext, useRef, useEffect } from "react";
import { NavLink, Link } from "react-router-dom";
import { QueryClientContext } from "@tanstack/react-query";
import { useUIStore } from "@/stores/uiStore";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";
import { useResizableWidth } from "@/hooks/useResizableWidth";
import { useAuthPermissions } from "@/hooks/useAuthPermissions";
import { Icon, type IconName } from "@/components/ui/Icon";
import type { ServerMode } from "@/server_manager/types";
import { resolveServerMode } from "@/server_manager/utils/serverMode";

export interface ServerContext {
  serverId: string;
  serverName?: string;
  serverType?: string;
  supportsMods?: boolean;
  supportsPlugins?: boolean;
  canConsoleView?: boolean;
  canFiles?: boolean;
  canSettings?: boolean;
  canPluginsView?: boolean;
  canExposureView?: boolean;
  canBackupsView?: boolean;
  canVersioningView?: boolean;
  mode?: ServerMode;
  branch?: string;
}

export interface SidebarProps {
  serverContext?: ServerContext;
}

const GLOBAL_NAV_ITEMS: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/servers", label: "Servers", icon: "server" },
  { to: "/backups", label: "Backups", icon: "backup" },
  { to: "/marketplace", label: "Marketplace", icon: "store" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

export const Sidebar: React.FC<SidebarProps> = ({ serverContext }) => {
  const hasQueryClient = Boolean(useContext(QueryClientContext));
  const isServerContext = Boolean(serverContext);
  const showVersioning = resolveServerMode(serverContext?.mode) === "advanced";
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);
  const setSource = useMarketplaceSourceStore((s) => s.setSource);

  const { width, isDragging, handleProps } = useResizableWidth({
    disabled: isServerContext,
  });

  const asideRef = useRef<HTMLElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useBodyScrollLock(mobileSidebarOpen);

  useEffect(() => {
    if (!mobileSidebarOpen) return;

    openerRef.current = (document.activeElement as HTMLElement) ?? null;

    const timer = setTimeout(() => {
      if (asideRef.current) {
        const focusable = asideRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length > 0) {
          focusable[0].focus();
        } else {
          asideRef.current.focus();
        }
      }
    }, 0);

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setMobileSidebarOpen(false);
      }
    };

    window.addEventListener("keydown", onKeyDown);

    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", onKeyDown);
      openerRef.current?.focus();
    };
  }, [mobileSidebarOpen, setMobileSidebarOpen]);

  const handleNavigate = () => {
    if (mobileSidebarOpen) setMobileSidebarOpen(false);
  };

  const handleGlobalNavigate = (isMarketplace: boolean) => {
    if (isMarketplace) {
      setSource("modrinth");
    }
    handleNavigate();
  };

  const withBranch = (path: string) =>
    serverContext?.branch && serverContext.branch !== "main"
      ? `${path}?branch=${encodeURIComponent(serverContext.branch)}`
      : path;

  return (
    <>
      {/* Mobile backdrop */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-xs lg:hidden"
          onClick={() => setMobileSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        ref={asideRef}
        tabIndex={-1}
        style={
          !isServerContext
            ? ({
                "--sidebar-width": `${width}px`,
                width: "var(--sidebar-width)",
              } as React.CSSProperties)
            : undefined
        }
        className={`fixed left-0 top-14 z-40 flex h-[calc(100vh-3.5rem)] flex-col border-r border-border-subtle bg-surface-card outline-hidden ${
          isDragging ? "transition-none select-none" : "transition-all duration-200"
        } ${
          mobileSidebarOpen ? "w-64 translate-x-0" : "w-64 -translate-x-full"
        } ${isServerContext ? "lg:w-56" : "lg:w-[var(--sidebar-width,14rem)]"} ${
          sidebarOpen ? "lg:translate-x-0" : "lg:-translate-x-full"
        }`}
      >
        {serverContext ? (
          /* Contextual Server Navigation (D5) */
          <div className="flex h-full flex-col">
            <div className="border-b border-border-subtle p-3">
              <Link
                to="/servers"
                onClick={handleNavigate}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-text-muted hover:text-text-primary transition-colors"
              >
                <Icon name="chevron-left" size={14} />
                Back to Servers
              </Link>
              <div className="mt-2 flex items-center gap-2">
                <Icon name="server" size={16} className="text-text-muted shrink-0" />
                <span className="truncate text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  Server Management
                </span>
              </div>
            </div>

            <nav aria-label="Server sections" className="flex-1 overflow-y-auto p-2 space-y-4">
              {/* Group 1: Core Workspace */}
              {(serverContext.canConsoleView !== false ||
                serverContext.canFiles !== false ||
                serverContext.canSettings !== false) && (
                <div>
                  <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    Core Workspace
                  </div>
                  <div className="mt-1 flex flex-col gap-0.5">
                    {serverContext.canConsoleView !== false && (
                      <ServerNavLink
                        to={withBranch(`/servers/${serverContext.serverId}/console`)}
                        label="Console"
                        icon="dashboard"
                        onNavigate={handleNavigate}
                      />
                    )}
                    {serverContext.canFiles !== false && (
                      <ServerNavLink
                        to={withBranch(`/servers/${serverContext.serverId}/files`)}
                        label="Files"
                        icon="folder"
                        onNavigate={handleNavigate}
                      />
                    )}
                    {serverContext.canSettings !== false && (
                      <ServerNavLink
                        to={withBranch(`/servers/${serverContext.serverId}/settings`)}
                        label="Settings"
                        icon="settings"
                        onNavigate={handleNavigate}
                      />
                    )}
                  </div>
                </div>
              )}

              {/* Group 2: Add-ons & Content */}
              {serverContext.canPluginsView !== false &&
                (serverContext.supportsMods || serverContext.supportsPlugins) && (
                  <div>
                    <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                      Add-ons & Content
                    </div>
                    <div className="mt-1 flex flex-col gap-0.5">
                      {serverContext.supportsMods && (
                        <ServerNavLink
                          to={withBranch(`/servers/${serverContext.serverId}/mods`)}
                          label="Mods"
                          icon="plugin"
                          onNavigate={handleNavigate}
                        />
                      )}
                      {serverContext.supportsPlugins && (
                        <ServerNavLink
                          to={withBranch(`/servers/${serverContext.serverId}/plugins`)}
                          label="Plugins"
                          icon="plugin"
                          onNavigate={handleNavigate}
                        />
                      )}
                    </div>
                  </div>
                )}

              {/* Group 3: Operations & DevOps */}
              <div>
                <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Operations & DevOps
                </div>
                <div className="mt-1 flex flex-col gap-0.5">
                  {serverContext.canExposureView !== false && (
                    <ServerNavLink
                      to={withBranch(`/servers/${serverContext.serverId}/network`)}
                      label="Network & Exposure"
                      icon="activity"
                      onNavigate={handleNavigate}
                    />
                  )}
                  {serverContext.canBackupsView !== false && (
                    <ServerNavLink
                      to={`/servers/${serverContext.serverId}/backups`}
                      label="Backups"
                      icon="backup"
                      onNavigate={handleNavigate}
                    />
                  )}
                  {showVersioning && serverContext.canVersioningView !== false && (
                    <ServerNavLink
                      to={withBranch(`/servers/${serverContext.serverId}/versioning`)}
                      label="Versions & Sandboxes"
                      icon="backup"
                      onNavigate={handleNavigate}
                    />
                  )}
                  <ServerNavLink
                    to={withBranch(`/servers/${serverContext.serverId}/activity`)}
                    label="Change History"
                    icon="clock"
                    onNavigate={handleNavigate}
                  />
                </div>
              </div>
            </nav>
          </div>
        ) : hasQueryClient ? (
          <GlobalSidebarNav handleGlobalNavigate={handleGlobalNavigate} />
        ) : (
          <GlobalNavList items={GLOBAL_NAV_ITEMS} handleGlobalNavigate={handleGlobalNavigate} />
        )}

        {/* Legal Disclaimer Footer */}
        <div className="mt-auto border-t border-border-subtle p-3 text-[10px] leading-tight text-text-muted">
          <p>Unofficial. Not affiliated with or endorsed by Mojang or Microsoft.</p>
        </div>

        {/* Resizable drag handle (desktop global navigation only) */}
        {!isServerContext && sidebarOpen && !mobileSidebarOpen && (
          <div
            {...handleProps}
            className={`group absolute top-0 right-0 z-50 h-full w-[6px] cursor-col-resize select-none touch-none hidden lg:flex items-center justify-center transition-colors ${
              isDragging ? "bg-accent-primary" : "hover:bg-accent-primary/60"
            }`}
          >
            <div
              className={`h-8 w-[2px] rounded-full transition-opacity ${
                isDragging
                  ? "bg-white opacity-100"
                  : "bg-text-muted/40 opacity-0 group-hover:opacity-100"
              }`}
            />
          </div>
        )}
      </aside>
    </>
  );
};

function ServerNavLink({
  to,
  label,
  icon,
  onNavigate,
}: {
  to: string;
  label: string;
  icon: IconName;
  onNavigate: () => void;
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        `group relative flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition-colors ${
          isActive
            ? "bg-accent-primary/10 text-text-accent font-semibold"
            : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
        }`
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-accent-primary" />
          )}
          <Icon name={icon} size={18} className="shrink-0" />
          <span className="truncate">{label}</span>
        </>
      )}
    </NavLink>
  );
}

function GlobalSidebarNav({
  handleGlobalNavigate,
}: {
  handleGlobalNavigate: (isMarketplace: boolean) => void;
}) {
  const auth = useAuthPermissions();
  const visibleItems = GLOBAL_NAV_ITEMS.filter((item) => {
    if (item.to === "/settings") return auth.canAccessGlobalSettings;
    if (item.to === "/marketplace") {
      return auth.isAdmin || (!auth.isViewer && auth.canViewPlugins());
    }
    if (item.to === "/backups") {
      return auth.isAdmin || auth.canViewBackups();
    }
    return true;
  });
  return <GlobalNavList items={visibleItems} handleGlobalNavigate={handleGlobalNavigate} />;
}

function GlobalNavList({
  items,
  handleGlobalNavigate,
}: {
  items: { to: string; label: string; icon: IconName; end?: boolean }[];
  handleGlobalNavigate: (isMarketplace: boolean) => void;
}) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-1 p-2">
      {items.map(({ to, label, icon, end }) => {
        const isMarketplace = to === "/marketplace";
        return (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={() => handleGlobalNavigate(isMarketplace)}
            className={({ isActive }) =>
              `group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-accent-primary/10 text-text-accent font-semibold"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-accent-primary" />
                )}
                <Icon name={icon} size={20} className="shrink-0" />
                <span className="truncate">{label}</span>
              </>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}
