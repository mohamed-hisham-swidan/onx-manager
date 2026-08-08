import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import { useWSStore } from "@/stores/wsStore";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import type { ConnectionState } from "@/websocket/types";

const WS_DOT: Record<ConnectionState, { dot: string; text: string; label: string; present: boolean }> = {
  connected: { dot: "bg-green-500", text: "text-green-600 dark:text-green-400", label: "Live", present: true },
  connecting: { dot: "bg-gray-400", text: "text-gray-500 dark:text-gray-400", label: "Connecting…", present: true },
  reconnecting: { dot: "bg-amber-500", text: "text-amber-700 dark:text-amber-400", label: "Reconnecting…", present: true },
  disconnected: { dot: "bg-red-500", text: "text-red-600 dark:text-red-400", label: "Offline", present: true },
  degraded: { dot: "bg-amber-500", text: "text-amber-700 dark:text-amber-400", label: "Degraded", present: true },
};

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
  const connectionState = useWSStore((s) => s.connectionState);
  const navigate = useNavigate();

  const ws = WS_DOT[connectionState];

  const handleLogout = useCallback(() => {
    const api = createAuthenticatedApi();
    if (refreshToken) {
      api.logout({ refresh_token: refreshToken }).catch(() => {});
    }
    logout();
    navigate("/login");
  }, [refreshToken, logout, navigate]);

  const handleToggleSidebar = () => {
    if (window.matchMedia("(min-width: 1024px)").matches) {
      toggleSidebar();
    } else {
      toggleMobileSidebar();
    }
  };

  return (
    <header className="fixed left-0 right-0 top-0 z-40 flex h-14 items-center justify-between border-b border-gray-200 bg-white px-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-center gap-3">
        {isAuthenticated && (
          <button
            onClick={handleToggleSidebar}
            className="rounded-lg p-1.5 text-gray-600 transition-colors hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
            aria-label={sidebarOpen || mobileSidebarOpen ? "Close sidebar" : "Open sidebar"}
          >
            <Icon name="menu" size={22} />
          </button>
        )}
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white">
            <Icon name="server" size={18} />
          </div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">MC Server Manager</h1>
        </div>
      </div>

      {isAuthenticated && (
        <div className="flex items-center gap-1">
          <div
            className="flex items-center gap-1.5 rounded-lg px-2 py-1"
            role="status"
            aria-label={`Socket ${connectionState}`}
            title={`Live updates: ${connectionState === "connected" ? "connected" : connectionState}`}
          >
            <span className={`h-2 w-2 rounded-full ${ws.dot}`} />
            <span className={`text-xs font-medium ${ws.text}`}>{ws.label}</span>
          </div>
          <button
            onClick={toggleTheme}
            className="rounded-lg p-2 text-gray-600 transition-colors hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700"
            aria-label="Toggle theme"
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={18} />
          </button>
          <button
            onClick={handleLogout}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400"
          >
            Logout
          </button>
        </div>
      )}
    </header>
  );
}
