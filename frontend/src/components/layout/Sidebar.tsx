import { NavLink } from "react-router-dom";
import { useUIStore } from "@/stores/uiStore";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: "◆" },
  { to: "/servers", label: "Servers", icon: "⚡" },
  { to: "/backups", label: "Backups", icon: "◈" },
  { to: "/plugins", label: "Plugins", icon: "⌘" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

export function Sidebar() {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);

  return (
    <aside
      className={`fixed top-14 left-0 h-full bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 transition-all duration-200 z-30 ${
        sidebarOpen ? "w-56" : "w-0 overflow-hidden"
      }`}
    >
      <nav className="flex flex-col gap-1 p-2">
        {NAV_ITEMS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? "bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
                  : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
              }`
            }
          >
            <span className="w-5 text-center">{icon}</span>
            {sidebarOpen && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
