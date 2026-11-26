import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { Skeleton } from "@/components/Skeleton";
import { Icon } from "@/components/ui/Icon";
import { AccessModeCard } from "@/server_manager/components/AccessModeCard";
import { PanelExposureSection } from "@/server_manager/components/PanelExposureSection";

export function AccessSection() {
  const api = useMemo(() => createAuthenticatedApi(), []);

  const { data: currentUser, isLoading: loadingUser, isError: userError } = useQuery({
    queryKey: ["currentUser"],
    queryFn: () => api.getMe(),
  });

  const isOwner = useMemo(() => {
    if (!currentUser) return false;
    return currentUser.roles?.includes("owner");
  }, [currentUser]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-text-primary">Remote &amp; Access</h2>
        <p className="text-sm text-text-muted mt-0.5">
          Expose the panel remotely and control user sign-up.
        </p>
      </div>

      {loadingUser ? (
        <div className="space-y-4">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : userError || !currentUser || !isOwner ? (
        <div className="rounded-xl border border-border-subtle bg-surface-card p-8 text-center space-y-2.5 shadow-2xs">
          <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-status-warning-bg text-status-warning">
            <Icon name="lock" size={20} />
          </div>
          <h3 className="text-sm font-semibold text-text-primary">Owner Access Required</h3>
          <p className="text-xs text-text-muted max-w-sm mx-auto">
            Only the instance Owner can view or modify Remote &amp; Access settings.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          <PanelExposureSection />
          <AccessModeCard />
        </div>
      )}
    </div>
  );
}
