import { NavLink, useLocation } from "react-router-dom";
import { useUIStore } from "@/stores/uiStore";
import { useMarketplaceSourceStore, type MarketplaceSource } from "@/stores/marketplaceSourceStore";
import { Icon, type IconName } from "@/components/ui/Icon";

const NAV_ITEMS: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/servers", label: "Servers", icon: "server" },
  { to: "/backups", label: "Backups", icon: "backup" },
  { to: "/marketplace", label: "Marketplace", icon: "store" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

export function Sidebar() {
  const location = useLocation();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
  const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);
  const source = useMarketplaceSourceStore((s) => s.source);
  const setSource = useMarketplaceSourceStore((s) => s.setSource);

  const handleNavigate = () => {
    if (mobileSidebarOpen) setMobileSidebarOpen(false);
  };

  const handleSelectSource = (newSource: MarketplaceSource) => {
    setSource(newSource);
    handleNavigate();
  };

  const isMarketplaceActive = location.pathname.startsWith("/marketplace");

  return (
    <>
      {/* Mobile backdrop */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-gray-900/50 lg:hidden"
          onClick={() => setMobileSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed left-0 top-14 z-40 flex h-[calc(100vh-3.5rem)] flex-col border-r border-gray-200 bg-white transition-all duration-200 dark:border-gray-700 dark:bg-gray-800 ${
          mobileSidebarOpen ? "w-64 translate-x-0" : "w-64 -translate-x-full"
        } lg:w-56 ${sidebarOpen ? "lg:translate-x-0" : "lg:-translate-x-full"}`}
      >
        <nav className="flex flex-col gap-1 p-2">
          {NAV_ITEMS.map(({ to, label, icon, end }) => {
            const isMarketplace = to === "/marketplace";
            return (
              <div key={to} className="flex flex-col gap-1">
                <NavLink
                  to={to}
                  end={end}
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

                {isMarketplace && (
                  <div className="ml-4 flex flex-col gap-0.5 border-l border-gray-200 pl-3 dark:border-gray-700">
                    <NavLink
                      to="/marketplace"
                      onClick={() => handleSelectSource("modrinth")}
                      className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                        isMarketplaceActive && source === "modrinth"
                          ? "bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
                          : "text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-700/50 dark:hover:text-gray-200"
                      }`}
                    >
                      <Icon name="modrinth" size={14} className="shrink-0" />
                      <span className="truncate">Modrinth</span>
                    </NavLink>
                    <NavLink
                      to="/marketplace"
                      onClick={() => handleSelectSource("curseforge")}
                      className={`flex items-center justify-between rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                        isMarketplaceActive && source === "curseforge"
                          ? "bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
                          : "text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-700/50 dark:hover:text-gray-200"
                      }`}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <Icon name="curseforge" size={14} className="shrink-0" />
                        <span className="truncate">CurseForge</span>
                      </div>
                      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                        Soon
                      </span>
                    </NavLink>
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-gray-200 p-3 dark:border-gray-700">
          <div className="flex items-center gap-2 px-1 text-xs text-gray-400 dark:text-gray-500">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
            </span>
            System Online
          </div>
        </div>
      </aside>
    </>
  );
}
