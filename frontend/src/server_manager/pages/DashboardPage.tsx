import { Link } from "react-router-dom";
import { useServersList } from "@/server_manager/hooks/useServers";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { StatusOverviewCards } from "@/server_manager/components/StatusOverviewCards";
import { DashboardServerList } from "@/server_manager/components/DashboardServerList";
import { RecentActivity } from "@/server_manager/components/RecentActivity";
import { useActivityStore } from "@/stores/activityStore";
import { VoxelBanner } from "@/components/brand/VoxelBanner";

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
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Overview of your Minecraft servers"
        icon="dashboard"
        actions={
          <Link to="/servers/create">
            <Button variant="primary" size="md" icon="plus">
              New Server
            </Button>
          </Link>
        }
      />

      {isLoading ? (
        <div className="space-y-6">
          <div className="rounded-2xl border border-border-subtle bg-surface-card p-4">
            <Skeleton className="h-6 w-32 mb-4" />
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
              {Array.from({ length: 7 }).map((_, i) => (
                <Skeleton key={i} className="h-14 rounded-xl" />
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
            <div className="rounded-2xl border border-border-subtle bg-surface-card p-5 lg:col-span-3">
              <Skeleton className="h-5 w-24 mb-4" />
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full rounded-xl" />
                ))}
              </div>
            </div>
            <div className="rounded-2xl border border-border-subtle bg-surface-card p-5 lg:col-span-2">
              <Skeleton className="h-5 w-32 mb-4" />
              <Skeleton className="h-40 w-full rounded-xl" />
            </div>
          </div>
        </div>
      ) : error ? (
        <ErrorState message={error instanceof Error ? error.message : "Failed to load servers"} />
      ) : servers && servers.length > 0 ? (
        <>
          <VoxelBanner variant="dashboard" className="mb-2" />
          <StatusOverviewCards counts={counts} />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
            <section className="rounded-2xl border border-border-subtle bg-surface-card p-5 shadow-2xs lg:col-span-3">
              <div className="mb-4 flex items-center justify-between pb-2 border-b border-border-subtle">
                <h2 className="text-sm font-bold text-text-primary">Servers</h2>
                <Link
                  to="/servers"
                  className="text-xs font-semibold text-accent-primary hover:underline"
                >
                  View all
                </Link>
              </div>
              <DashboardServerList servers={servers.slice(0, 5)} />
            </section>

            <section className="rounded-2xl border border-border-subtle bg-surface-card p-5 shadow-2xs lg:col-span-2">
              <div className="mb-4 pb-2 border-b border-border-subtle">
                <h2 className="text-sm font-bold text-text-primary">Recent Activity</h2>
              </div>
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
          action={{
            label: "+ New Server",
            onClick: () => {
              window.location.href = "/servers/create";
            },
          }}
        />
      )}
    </div>
  );
}
