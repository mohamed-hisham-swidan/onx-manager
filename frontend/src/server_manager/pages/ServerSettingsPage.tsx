import { useParams } from "react-router-dom";
import { useServerDetail } from "@/server_manager/hooks/useServers";
import { ServerSettingsSection } from "@/server_manager/components/ServerSettingsSection";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Skeleton } from "@/components/ui/States";

export function ServerSettingsPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const { data: server, isLoading, error } = useServerDetail(serverId ?? "");

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !server) {
    return (
      <div className="rounded-xl border border-status-danger/30 bg-status-danger/10 p-6">
        <p className="text-sm text-status-danger">
          {error instanceof Error ? error.message : "Failed to load server details"}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border-default pb-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-xl font-bold text-text-primary">
              Server Settings & Configuration
            </h2>
            <StatusBadge status={server.status} />
          </div>
        </div>
      </div>

      {/* Settings Form */}
      <ServerSettingsSection serverId={serverId!} server={server} />
    </div>
  );
}
