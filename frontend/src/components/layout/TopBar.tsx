import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import { useEffectiveConnectionState } from "@/stores/wsStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { ConnectionState } from "@/websocket/types";

const WS_DOT: Record<ConnectionState, { dot: string; text: string; label: string; present: boolean }> = {
  connected: { dot: "bg-status-success", text: "text-status-success", label: "Live", present: true },
  connecting: { dot: "bg-text-muted", text: "text-text-muted", label: "Connecting…", present: true },
  reconnecting: { dot: "bg-status-warning", text: "text-status-warning", label: "Reconnecting…", present: true },
  disconnected: { dot: "bg-status-danger", text: "text-status-danger", label: "Offline", present: true },
  degraded: { dot: "bg-status-warning", text: "text-status-warning", label: "Degraded", present: true },
};

export function TopBar() {
  const logout = useAuthStore((s) => s.logout);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const theme = useUIStore((s) => s.theme);
  const toggleTheme = useUIStore((s) => s.toggleTheme);
  const skin = useUIStore((s) => s.skin);
  const setSkin = useUIStore((s) => s.setSkin);
  const density = useUIStore((s) => s.density);
  const toggleDensity = useUIStore((s) => s.toggleDensity);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const toggleMobileSidebar = useUIStore((s) => s.toggleMobileSidebar);

  const operations = useOperationStore((s) => s.operations);
  const activeDrawerId = useOperationStore((s) => s.activeDrawerId);
  const openDrawer = useOperationStore((s) => s.openDrawer);
  const closeDrawer = useOperationStore((s) => s.closeDrawer);

  const connectionState = useEffectiveConnectionState();
  const navigate = useNavigate();

  const [showWsDiagnostics, setShowWsDiagnostics] = useState(false);

  const activeOpList = Object.values(operations).filter(
    (op) => op.status === "RUNNING" || op.status === "PREPARING" || op.status === "QUEUED"
  );
  const hasActiveOps = activeOpList.length > 0;

  const ws = WS_DOT[connectionState] || WS_DOT.disconnected;

  const handleLogout = useCallback(() => {
    const api = createAuthenticatedApi();
    if (refreshToken) {
      api.logout({ refresh_token: refreshToken }).catch(() => {});
    }
    logout();
    navigate("/login");
  }, [refreshToken, logout, navigate]);

  const handleToggleSidebar = () => {
    if (typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches) {
      toggleSidebar();
    } else {
      toggleMobileSidebar();
    }
  };

  const handleToggleOpsDrawer = () => {
    if (activeDrawerId) {
      closeDrawer();
    } else if (hasActiveOps) {
      openDrawer(activeOpList[0].id);
    } else {
      const allOps = Object.values(operations);
      if (allOps.length > 0) {
        openDrawer(allOps[allOps.length - 1].id);
      }
    }
  };

  return (
    <header className="fixed left-0 right-0 top-0 z-40 flex h-14 items-center justify-between border-b border-border-subtle bg-surface-card px-4 text-text-primary shadow-2xs">
      <div className="flex items-center gap-3">
        {isAuthenticated && (
          <button
            onClick={handleToggleSidebar}
            className="rounded-lg p-1.5 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus cursor-pointer"
            aria-label={sidebarOpen || mobileSidebarOpen ? "Close sidebar" : "Open sidebar"}
          >
            <Icon name="menu" size={22} />
          </button>
        )}
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-primary text-accent-contrast-text shadow-2xs">
            {/* Minimalist voxel swirl brand mark */}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <rect x="3" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" />
            </svg>
          </div>
          <span className="text-base font-bold tracking-tight text-text-primary">
            onx-manager
          </span>
        </div>
      </div>

      {isAuthenticated && (
        <div className="flex items-center gap-2">
          {/* Operations Drawer Trigger */}
          <button
            type="button"
            onClick={handleToggleOpsDrawer}
            aria-label="Background Operations"
            title={hasActiveOps ? `${activeOpList.length} operation(s) in progress` : "Background Operations"}
            className={`relative rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer ${
              hasActiveOps ? "text-accent-primary" : ""
            }`}
          >
            <Icon name="activity" size={18} />
            {hasActiveOps && (
              <span className="absolute right-1.5 top-1.5 flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-primary opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-accent-primary" />
              </span>
            )}
          </button>

          {/* WebSocket Pill & Diagnostic Popover */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowWsDiagnostics((v) => !v)}
              className="flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-muted/50 px-2.5 py-1 transition-colors hover:bg-surface-hover cursor-pointer"
              role="status"
              aria-label={`Socket ${connectionState}`}
              title={
                connectionState === ConnectionState.DEGRADED
                  ? "WebSocket connected, but 1 or more subscriptions were rejected"
                  : `Live updates: ${connectionState === "connected" ? "connected" : connectionState}`
              }
            >
              <span className={`h-2 w-2 rounded-full ${ws.dot}`} />
              <span className={`text-xs font-semibold ${ws.text}`}>{ws.label}</span>
            </button>

            {showWsDiagnostics && (
              <div className="absolute right-0 top-full mt-2 w-64 rounded-xl border border-border-subtle bg-surface-card p-3 shadow-xl z-50 text-xs">
                <div className="flex items-center justify-between pb-2 border-b border-border-subtle font-semibold">
                  <span>Connection Diagnostics</span>
                  <button
                    onClick={() => setShowWsDiagnostics(false)}
                    className="text-text-muted hover:text-text-primary"
                  >
                    <Icon name="x" size={14} />
                  </button>
                </div>
                <div className="mt-2 space-y-1.5 text-text-secondary">
                  <div className="flex justify-between">
                    <span>Status:</span>
                    <span className="font-medium text-text-primary capitalize">{connectionState}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Skin:</span>
                    <span className="font-medium text-text-primary capitalize">{skin}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Density:</span>
                    <span className="font-medium text-text-primary capitalize">{density}</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Skin Toggle (Graphite / Azure) */}
          <button
            type="button"
            onClick={() => setSkin(skin === "graphite" ? "azure" : "graphite")}
            className="hidden sm:inline-flex items-center gap-1 rounded-lg border border-border-subtle px-2 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
            aria-label="Toggle skin"
            title={`Current skin: ${skin}. Click to toggle.`}
          >
            <span className="h-2 w-2 rounded-full bg-accent-primary" />
            <span className="capitalize">{skin}</span>
          </button>

          {/* Density Toggle (Comfortable / Compact) */}
          <button
            type="button"
            onClick={toggleDensity}
            className="hidden sm:inline-flex items-center rounded-lg border border-border-subtle px-2 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
            aria-label="Toggle density"
            title={`Density: ${density}. Click to switch.`}
          >
            <span className="capitalize">{density}</span>
          </button>

          {/* Theme Toggle (Dark / Light) */}
          <button
            onClick={toggleTheme}
            className="rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer"
            aria-label="Toggle theme"
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
          </button>

          {/* Logout */}
          <button
            onClick={handleLogout}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:bg-status-danger-bg hover:text-status-danger cursor-pointer"
          >
            Logout
          </button>
        </div>
      )}
    </header>
  );
}
