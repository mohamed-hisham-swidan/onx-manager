import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { BrandLogo } from "@/components/brand/BrandLogo";
import { ConfigureCredentialsModal } from "@/components/auth/ConfigureCredentialsModal";
import { useDeploymentProfile } from "@/hooks/useDeploymentProfile";

export function TopBar() {
  const logout = useAuthStore((s) => s.logout);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const theme = useUIStore((s) => s.theme);
  const toggleTheme = useUIStore((s) => s.toggleTheme);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const toggleMobileSidebar = useUIStore((s) => s.toggleMobileSidebar);

  const operations = useOperationStore((s) => s.operations);
  const activeDrawerId = useOperationStore((s) => s.activeDrawerId);
  const openDrawer = useOperationStore((s) => s.openDrawer);
  const closeDrawer = useOperationStore((s) => s.closeDrawer);

  const navigate = useNavigate();
  const { isLocalZeroLogin } = useDeploymentProfile();
  const hasSessionAccess = isAuthenticated || isLocalZeroLogin;

  const [showCredentialsModal, setShowCredentialsModal] = useState(false);

  const activeOpList = Object.values(operations).filter(
    (op) => op.status === "RUNNING" || op.status === "PREPARING" || op.status === "QUEUED",
  );
  const hasActiveOps = activeOpList.length > 0;

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
    }
  };

  return (
    <header className="fixed left-0 right-0 top-0 z-40 flex h-14 items-center justify-between border-b border-border-subtle bg-surface-card px-4 text-text-primary shadow-2xs">
      <div className="flex items-center gap-3">
        {hasSessionAccess && (
          <button
            onClick={handleToggleSidebar}
            className="rounded-lg p-1.5 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus cursor-pointer"
            aria-label={sidebarOpen || mobileSidebarOpen ? "Close sidebar" : "Open sidebar"}
          >
            <Icon name="menu" size={22} />
          </button>
        )}
        <BrandLogo variant="full" size="sm" />
      </div>

      {hasSessionAccess && (
        <div className="flex items-center gap-2">
          {hasActiveOps && (
            <button
              type="button"
              onClick={handleToggleOpsDrawer}
              aria-label="Background Operations"
              className="inline-flex items-center gap-1.5 rounded-lg border border-accent-primary/40 bg-accent-primary/10 px-2.5 py-1 text-xs font-semibold text-text-accent hover:bg-accent-primary/20 transition-colors cursor-pointer"
            >
              <span className="h-2 w-2 rounded-full bg-accent-primary animate-pulse" />
              <span>Running ({activeOpList.length})</span>
            </button>
          )}

          {/* Theme Toggle (Dark / Light) */}
          <button
            onClick={toggleTheme}
            className="rounded-lg p-2 text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer"
            aria-label="Toggle theme"
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
          </button>

          {/* Logout / Set Password */}
          {isLocalZeroLogin && !isAuthenticated ? (
            <button
              type="button"
              onClick={() => setShowCredentialsModal(true)}
              className="rounded-lg border border-border-subtle bg-surface-elevated px-3 py-1.5 text-xs font-medium text-text-primary transition-colors hover:border-border-hover hover:bg-surface-hover cursor-pointer"
            >
              Set Password
            </button>
          ) : (
            <button
              onClick={handleLogout}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-text-secondary transition-colors hover:bg-status-danger-bg hover:text-status-danger cursor-pointer"
            >
              Logout
            </button>
          )}
        </div>
      )}
      {showCredentialsModal && (
        <ConfigureCredentialsModal
          open={showCredentialsModal}
          onClose={() => setShowCredentialsModal(false)}
          reason="Configure an administrator username and password to secure this local instance."
        />
      )}
    </header>
  );
}
