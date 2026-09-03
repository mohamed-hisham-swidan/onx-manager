import { useState, useEffect } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export function AuthGuard() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const refreshAuth = useAuthStore((s) => s.refreshAuth);

  const [isChecking, setIsChecking] = useState(() => !isAuthenticated && !!refreshToken);

  useEffect(() => {
    let mounted = true;
    if (!isAuthenticated && refreshToken && refreshAuth) {
      refreshAuth().finally(() => {
        if (mounted) {
          setIsChecking(false);
        }
      });
    } else {
      setIsChecking(false);
    }
    return () => {
      mounted = false;
    };
  }, [isAuthenticated, refreshToken, refreshAuth]);

  if (isChecking) {
    return null;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
