import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { Skeleton } from "@/components/Skeleton";
import { AccessModeCard } from "@/server_manager/components/AccessModeCard";
import { PanelExposureSection } from "@/server_manager/components/PanelExposureSection";

export function AccessSection() {
  const api = useMemo(() => createAuthenticatedApi(), []);

  // Current user identity check for single Owner permission gate
  const { data: currentUser, isLoading: loadingUser, isError: userError } = useQuery({
    queryKey: ["currentUser"],
    queryFn: () => api.getMe(),
  });

  const isOwner = useMemo(() => {
    if (!currentUser) return false;
    return currentUser.roles?.includes("owner");
  }, [currentUser]);

  if (loadingUser) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (userError || !currentUser || !isOwner) {
    return (
      <div className="rounded-xl border border-status-danger-border bg-status-danger-bg p-6 text-center space-y-2">
        <h3 className="text-base font-semibold text-status-danger">
          Access Denied
        </h3>
        <p className="text-xs text-status-danger opacity-90">
          Only the instance Owner can view or modify Access Mode settings.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AccessModeCard />
      <PanelExposureSection />
    </div>
  );
}
