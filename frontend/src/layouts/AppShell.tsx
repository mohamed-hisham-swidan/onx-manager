import { useEffect, Suspense } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { TopBar } from "@/components/layout/TopBar";
import { Sidebar } from "@/components/layout/Sidebar";
import { LoadingBar } from "@/components/ui/LoadingBar";
import { Toaster } from "@/components/ui/Toaster";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { RouteFallback } from "@/components/ui/RouteFallback";
import { OperationDrawer } from "@/operations/components/OperationDrawer";
import { useOperationStore } from "@/operations/stores/operationStore";
import { useUIStore } from "@/stores/uiStore";

export function AppShell() {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);
  const activeDrawerId = useOperationStore((s) => s.activeDrawerId);
  const closeDrawer = useOperationStore((s) => s.closeDrawer);
  const location = useLocation();

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [location.pathname, setMobileSidebarOpen]);

  return (
    <div
      className="min-h-screen bg-surface-page text-text-primary transition-colors"
      style={{ "--sidebar-width": "var(--sidebar-width, 224px)" } as React.CSSProperties}
    >
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:inset-block-start-3 focus:inset-inline-start-3 focus:z-50 focus:rounded-lg focus:bg-surface-elevated focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-accent-primary focus:shadow-lg focus:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus"
        onClick={() => {
          const main = document.getElementById("main-content");
          if (main) main.focus();
        }}
      >
        Skip to content
      </a>
      <LoadingBar />
      <TopBar />
      <Sidebar />
      <main
        id="main-content"
        tabIndex={-1}
        className={`min-h-[calc(100vh-3.5rem)] pt-14 overflow-y-auto pb-16 transition-all duration-200 outline-hidden ${
          sidebarOpen ? "lg:pl-[var(--sidebar-width,14rem)]" : "lg:pl-0"
        }`}
      >
        <div className="mx-auto w-full max-w-[1880px] p-4 sm:p-6 lg:px-8 lg:py-6 pb-16">
          <ErrorBoundary>
            <Suspense fallback={<RouteFallback />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </div>
      </main>
      {activeDrawerId && <OperationDrawer operationId={activeDrawerId} onClose={closeDrawer} />}
      <Toaster />
    </div>
  );
}
