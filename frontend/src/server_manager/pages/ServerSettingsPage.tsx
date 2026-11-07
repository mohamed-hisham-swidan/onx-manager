import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useServerDetail, useDeleteServer } from "@/server_manager/hooks/useServers";
import { ServerSettingsSection } from "@/server_manager/components/ServerSettingsSection";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Skeleton } from "@/components/ui/States";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { toast } from "@/stores/toastStore";

export function ServerSettingsPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const { data: server, isLoading, error } = useServerDetail(serverId ?? "");
  const deleteServer = useDeleteServer();
  const [showDeleteModal, setShowDeleteModal] = useState(false);

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
      <div className="rounded-xl border border-status-danger-border bg-status-danger-bg p-6">
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

      {/* Danger Zone: Delete Server */}
      <section
        data-testid="server-danger-zone"
        className="rounded-2xl border border-status-danger-border bg-surface-card p-6 shadow-xs"
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-status-danger-bg text-status-danger">
                <Icon name="trash" size={16} />
              </span>
              <h3 className="text-base font-bold text-text-primary">
                Danger Zone: Delete Server
              </h3>
            </div>
            <p className="text-xs text-text-muted max-w-xl">
              Permanently delete this Minecraft server, including all worlds, configurations, installed add-ons, and local backups. This action cannot be undone.
            </p>
          </div>

          <Button
            variant="danger"
            size="md"
            icon="trash"
            onClick={() => setShowDeleteModal(true)}
            disabled={deleteServer.isPending}
          >
            {deleteServer.isPending ? "Deleting..." : "Delete Server"}
          </Button>
        </div>
      </section>

      <ConfirmDialog
        open={showDeleteModal}
        title={`Delete "${server.name}"?`}
        description="Are you sure you want to permanently delete this server? All player data, worlds, configurations, and installed files will be permanently erased. This action cannot be undone."
        confirmLabel="Delete Server"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={() => {
          deleteServer.mutate(serverId!, {
            onSuccess: () => {
              toast("success", "Server deleted", `"${server.name}" was permanently deleted.`);
              navigate("/servers");
            },
            onError: (err) => {
              toast("error", "Delete failed", err instanceof Error ? err.message : "Failed to delete server");
              setShowDeleteModal(false);
            },
          });
        }}
        onCancel={() => setShowDeleteModal(false)}
      />
    </div>
  );
}
