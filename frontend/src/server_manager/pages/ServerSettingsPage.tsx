import { useParams } from "react-router-dom";
import { useServerDetail } from "@/server_manager/hooks/useServers";
import { ServerSettingsSection } from "@/server_manager/components/ServerSettingsSection";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { PageSkeleton } from "@/components/Skeleton";

export function ServerSettingsPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const { data: server, isLoading, error } = useServerDetail(serverId ?? "");

  if (isLoading) {
    return <PageSkeleton />;
  }

  if (error || !server) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 dark:border-red-900/50 dark:bg-red-950/20">
        <p className="text-sm text-red-600 dark:text-red-400">
          {error instanceof Error ? error.message : "Failed to load server details"}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-gray-200 pb-4 dark:border-gray-700">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">
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
