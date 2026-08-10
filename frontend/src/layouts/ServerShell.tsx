import { useEffect } from "react";
import { Outlet, useLocation, useParams, NavLink, Link } from "react-router-dom";
import { TopBar } from "@/components/layout/TopBar";
import { LoadingBar } from "@/components/ui/LoadingBar";
import { Toaster } from "@/components/ui/Toaster";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Icon } from "@/components/ui/Icon";
import { useUIStore } from "@/stores/uiStore";
import { useServerDetail } from "@/server_manager/hooks/useServers";
import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";

export function ServerShell() {
  const { serverId } = useParams<{ serverId: string }>();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);
  const location = useLocation();

  const { data: server } = useServerDetail(serverId!);
  const { supportsMods, supportsPlugins } = getServerCapabilities(server?.server_type);

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [location.pathname, setMobileSidebarOpen]);

  const handleNavigate = () => {
    if (mobileSidebarOpen) setMobileSidebarOpen(false);
  };

  const navItems = [
    { to: `/servers/${serverId}/console`, label: "Console", icon: "dashboard" as const },
    { to: `/servers/${serverId}/files`, label: "Files", icon: "folder" as const },
    ...(supportsMods ? [{ to: `/servers/${serverId}/mods`, label: "Mods", icon: "plugin" as const }] : []),
    ...(supportsPlugins ? [{ to: `/servers/${serverId}/plugins`, label: "Plugins", icon: "plugin" as const }] : []),
  ];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <LoadingBar />
      <TopBar />

      {/* Mobile backdrop */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-gray-900/50 lg:hidden"
          onClick={() => setMobileSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Contextual Server Sidebar */}
      <aside
        className={`fixed left-0 top-14 z-40 flex h-[calc(100vh-3.5rem)] flex-col border-r border-gray-200 bg-white transition-all duration-200 dark:border-gray-700 dark:bg-gray-800 ${
          mobileSidebarOpen ? "w-64 translate-x-0" : "w-64 -translate-x-full"
        } lg:w-56 lg:translate-x-0`}
      >
        <div className="border-b border-gray-200 p-3 dark:border-gray-700">
          <Link
            to="/servers"
            onClick={handleNavigate}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100 transition-colors"
          >
            <Icon name="chevron-left" size={14} />
            Back to Servers
          </Link>
          <div className="mt-2 flex items-center gap-2">
            <Icon name="server" size={16} className="text-blue-600 dark:text-blue-400 shrink-0" />
            <span className="truncate text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Server Management
            </span>
          </div>
        </div>

        <nav className="flex flex-col gap-1 p-2">
          {navItems.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={handleNavigate}
              className={({ isActive }) =>
                `group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-100"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-blue-600 dark:bg-blue-400" />
                  )}
                  <Icon name={icon} size={20} className="shrink-0" />
                  <span className="truncate">{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main
        className={`pt-14 transition-all duration-200 ${
          sidebarOpen ? "lg:pl-56" : "lg:pl-0"
        }`}
      >
        <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </div>
      </main>
      <Toaster />
    </div>
  );
}
