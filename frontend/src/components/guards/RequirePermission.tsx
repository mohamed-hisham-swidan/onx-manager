import React from "react";
import { Navigate, useParams } from "react-router-dom";
import { useAuthPermissions, type AuthPermissionsState } from "@/hooks/useAuthPermissions";

export interface RequirePermissionProps {
  check: (perms: AuthPermissionsState, serverId?: string) => boolean;
  redirectTo?: string;
  children: React.ReactNode;
}

export function RequirePermission({
  check,
  redirectTo,
  children,
}: RequirePermissionProps) {
  const { serverId } = useParams<{ serverId: string }>();
  const perms = useAuthPermissions();

  // Wait for /api/v1/auth/me before kicking out on initial direct navigation
  if (perms.isLoading && !perms.user) {
    return null;
  }

  if (!check(perms, serverId)) {
    const fallback = redirectTo ?? (serverId ? `/servers/${encodeURIComponent(serverId)}` : "/");
    return <Navigate to={fallback} replace />;
  }

  return <>{children}</>;
}
