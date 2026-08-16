import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createApiClient } from "@/services/api";
import { Skeleton } from "@/components/Skeleton";
import { AccessModeCard } from "@/server_manager/components/AccessModeCard";
import { PanelExposureSection } from "@/server_manager/components/PanelExposureSection";

export function AccessSection() {
  const api = useMemo(() => createApiClient(window.location.origin, () => null), []);

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
      <div className="rounded-xl border border-red-200 bg-red-50 dark:border-red-900/40 dark:bg-red-900/20 p-6 text-center space-y-2">
        <h3 className="text-base font-semibold text-red-600 dark:text-red-400">
          Access Denied
        </h3>
        <p className="text-xs text-red-700 dark:text-red-300">
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
