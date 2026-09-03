import { useState, useEffect } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export function AuthGuard() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const refreshAuth = useAuthStore((s) => s.refreshAuth);

  const canAttemptRefresh = !isAuthenticated && !!refreshToken;
  const [isRefreshing, setIsRefreshing] = useState(() => canAttemptRefresh);

  useEffect(() => {
    let mounted = true;
    if (canAttemptRefresh && refreshAuth) {
      refreshAuth().finally(() => {
        if (mounted) {
          setIsRefreshing(false);
        }
      });
    }
    return () => {
      mounted = false;
    };
  }, [canAttemptRefresh, refreshAuth]);

  if (canAttemptRefresh && isRefreshing) {
    return null;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
