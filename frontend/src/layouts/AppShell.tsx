import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { TopBar } from "@/components/layout/TopBar";
import { Sidebar } from "@/components/layout/Sidebar";
import { LoadingBar } from "@/components/ui/LoadingBar";
import { Toaster } from "@/components/ui/Toaster";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { useUIStore } from "@/stores/uiStore";

export function AppShell() {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);
  const location = useLocation();

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [location.pathname, setMobileSidebarOpen]);

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <LoadingBar />
      <TopBar />
      <Sidebar />
      <main
        className={`pt-14 transition-all duration-200 ${
          sidebarOpen ? "lg:pl-56" : "lg:pl-0"
        }`}
      >
        <div className="mx-auto max-w-7xl p-3.5 sm:p-5 lg:px-6 lg:py-4">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </div>
      </main>
      <Toaster />
    </div>
  );
}
