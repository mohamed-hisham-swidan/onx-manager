import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import { createAuthenticatedApi } from "@/services/api";

export function TopNav() {
  const logout = useAuthStore((s) => s.logout);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const navigate = useNavigate();

  const handleLogout = useCallback(() => {
    const api = createAuthenticatedApi();
    if (refreshToken) {
      api.logout({ refresh_token: refreshToken }).catch(() => {});
    } else {
      api.logout().catch(() => {});
    }
    logout();
    navigate("/login");
  }, [refreshToken, logout, navigate]);

  return (
    <header className="fixed top-0 left-0 right-0 h-14 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 z-40">
      <div className="flex items-center justify-between h-full px-4">
        <div className="flex items-center gap-3">
          {isAuthenticated && (
            <button
              onClick={toggleSidebar}
              className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400"
              aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          )}
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            MC Server Manager
          </h1>
        </div>

        {isAuthenticated && (
          <button
            onClick={handleLogout}
            className="px-3 py-1.5 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 transition-colors"
          >
            Logout
          </button>
        )}
      </div>
    </header>
  );
}
