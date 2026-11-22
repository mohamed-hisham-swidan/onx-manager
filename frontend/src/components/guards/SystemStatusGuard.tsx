import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { createAuthenticatedApi } from "@/services/api";

export function SystemStatusGuard() {
  const location = useLocation();

  const { data: status, isLoading, isError, refetch } = useQuery({
    queryKey: ["systemStatus"],
    queryFn: () => createAuthenticatedApi().getSetupStatus(),
    staleTime: 1000 * 30, // 30s cache
  });

  if (isLoading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-surface-page text-text-primary">
        <div className="flex flex-col items-center gap-3">
          <div aria-hidden="true" className="h-8 w-8 animate-spin rounded-full border-4 border-accent-primary border-t-transparent" />
          <p className="text-sm text-text-muted">Checking system status...</p>
        </div>
      </div>
    );
  }

  if (isError || !status) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-surface-page p-4">
        <div role="alert" className="max-w-md w-full rounded-xl border border-status-danger-border bg-surface-card p-6 shadow-sm text-center space-y-4">
          <h3 className="text-base font-semibold text-status-danger">System Status Error</h3>
          <p className="text-xs text-text-secondary">
            Unable to connect to the server or retrieve system initialization status. Please verify server connectivity.
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="px-4 py-2 bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium rounded-lg transition-colors"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  const isSetupRoute = location.pathname === "/setup";
  const isLoginRoute = location.pathname === "/login";

  if (status.auth_mode === "local_zero_login") {
    if (isSetupRoute || isLoginRoute) {
      return <Navigate to="/" replace />;
    }
    return <Outlet />;
  }

  if (!status.initialized) {
    if (!isSetupRoute) {
      return <Navigate to="/setup" replace />;
    }
  } else {
    if (isSetupRoute) {
      return <Navigate to="/login" replace />;
    }
  }

  return <Outlet />;
}
