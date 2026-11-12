import React, { useRef, useEffect } from "react";
import { NavLink, Link } from "react-router-dom";
import { useUIStore } from "@/stores/uiStore";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";
import { useBodyScrollLock } from "@/hooks/useBodyScrollLock";
import { useResizableWidth } from "@/hooks/useResizableWidth";
import { Icon, type IconName } from "@/components/ui/Icon";
import type { ServerMode } from "@/server_manager/types";
import { resolveServerMode } from "@/server_manager/utils/serverMode";

export interface ServerContext {
  serverId: string;
  serverName?: string;
  serverType?: string;
  supportsMods?: boolean;
  supportsPlugins?: boolean;
  mode?: ServerMode;
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
                <Icon name="server" size={16} className="text-accent-primary shrink-0" />
                <span className="truncate text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  Server Management
                </span>
              </div>
            </div>

            <nav aria-label="Server sections" className="flex-1 overflow-y-auto p-2 space-y-4">
              {/* Group 1: Core Workspace */}
              <div>
                <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Core Workspace
                </div>
                <div className="mt-1 flex flex-col gap-0.5">
                  <ServerNavLink
                    to={`/servers/${serverContext.serverId}/console`}
                    label="Console"
                    icon="dashboard"
                    onNavigate={handleNavigate}
                  />
                  <ServerNavLink
                    to={`/servers/${serverContext.serverId}/files`}
                    label="Files"
                    icon="folder"
                    onNavigate={handleNavigate}
                  />
                  <ServerNavLink
                    to={`/servers/${serverContext.serverId}/settings`}
                    label="Settings"
                    icon="settings"
                    onNavigate={handleNavigate}
                  />
                </div>
              </div>

              {/* Group 2: Add-ons & Content */}
              {(serverContext.supportsMods || serverContext.supportsPlugins) && (
                <div>
                  <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    Add-ons & Content
                  </div>
                  <div className="mt-1 flex flex-col gap-0.5">
                    {serverContext.supportsMods && (
                      <ServerNavLink
                        to={`/servers/${serverContext.serverId}/mods`}
                        label="Mods"
                        icon="plugin"
                        onNavigate={handleNavigate}
                      />
                    )}
                    {serverContext.supportsPlugins && (
                      <ServerNavLink
                        to={`/servers/${serverContext.serverId}/plugins`}
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
                  <ServerNavLink
                    to={`/servers/${serverContext.serverId}/network`}
                    label="Network & Exposure"
                    icon="activity"
                    onNavigate={handleNavigate}
                  />
                  {showVersioning && (
                    <ServerNavLink
                      to={`/servers/${serverContext.serverId}/versioning`}
                      label="Versions & Testing"
                      icon="backup"
                      onNavigate={handleNavigate}
                    />
                  )}
                  <ServerNavLink
                    to={`/servers/${serverContext.serverId}/activity`}
                    label="Change History"
                    icon="clock"
                    onNavigate={handleNavigate}
                  />
                </div>
              </div>
            </nav>
          </div>
        ) : (
          /* Global Navigation */
          <nav aria-label="Main" className="flex flex-col gap-1 p-2">
            {GLOBAL_NAV_ITEMS.map(({ to, label, icon, end }) => {
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
                        ? "bg-accent-primary/10 text-accent-primary font-semibold"
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
            ? "bg-accent-primary/10 text-accent-primary font-semibold"
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
