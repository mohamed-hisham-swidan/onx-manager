import { Link } from "react-router-dom";
import { useServersList } from "@/server_manager/hooks/useServers";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { StatusOverviewCards } from "@/server_manager/components/StatusOverviewCards";
import { DashboardServerList } from "@/server_manager/components/DashboardServerList";
import { RecentActivity } from "@/server_manager/components/RecentActivity";
import { useActivityStore } from "@/stores/activityStore";

export function DashboardPage() {
  const { data: servers, isLoading, error } = useServersList();
  const activityCount = useActivityStore((s) => s.events.length);

  const counts = (servers ?? []).reduce<Record<string, number>>((acc, s) => {
    const status = s.status || "unknown";
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});

  const serverNames = (servers ?? []).reduce<Record<string, string>>((acc, s) => {
    acc[s.server_id] = s.name;
    return acc;
  }, {});

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Overview of your Minecraft servers"
        icon="dashboard"
        actions={
          <Link
            to="/servers/create"
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            + New Server
          </Link>
        }
      />

      {isLoading ? (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800"
              >
                <Skeleton className="h-9 w-9 mb-3" />
                <Skeleton className="h-7 w-10 mb-2" />
                <Skeleton className="h-3 w-14" />
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
            <Skeleton className="h-5 w-32 mb-4" />
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full mb-2" />
            ))}
          </div>
        </div>
      ) : error ? (
        <ErrorState message={error instanceof Error ? error.message : "Failed to load servers"} />
      ) : servers && servers.length > 0 ? (
        <>
          <StatusOverviewCards counts={counts} />

          <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-5">
            <section className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800 lg:col-span-3">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Servers</h2>
                <Link
                  to="/servers"
                  className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  View all
                </Link>
              </div>
              <DashboardServerList servers={servers.slice(0, 5)} />
            </section>

            <section className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800 lg:col-span-2">
              <h2 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">Recent Activity</h2>
              {activityCount > 0 ? (
                <RecentActivity serverNames={serverNames} />
              ) : (
                <EmptyState
                  icon="activity"
                  title="No activity yet"
                  description="Server events will appear here as they happen."
                />
              )}
            </section>
          </div>
        </>
      ) : (
        <EmptyState
          icon="server"
          title="No servers yet"
          description="Create your first Minecraft server to get started."
          action={
            <Link
              to="/servers/create"
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              + New Server
            </Link>
          }
        />
      )}
    </div>
  );
}
