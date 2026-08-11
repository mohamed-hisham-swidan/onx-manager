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
      <div className="flex h-screen w-screen items-center justify-center bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          <p className="text-sm text-gray-500 dark:text-gray-400">Checking system status...</p>
        </div>
      </div>
    );
  }

  if (isError || !status) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
        <div role="alert" className="max-w-md w-full rounded-xl border border-red-200 dark:border-red-900/50 bg-white dark:bg-gray-800 p-6 shadow-sm text-center space-y-4">
          <h3 className="text-base font-semibold text-red-600 dark:text-red-400">System Status Error</h3>
          <p className="text-xs text-gray-600 dark:text-gray-400">
            Unable to connect to the server or retrieve system initialization status. Please verify server connectivity.
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium rounded-lg transition-colors"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  const isSetupRoute = location.pathname === "/setup";

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
