import { useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useServerDetail, useDeleteServer } from "@/server_manager/hooks/useServers";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { ServerSettingsSection } from "@/server_manager/components/ServerSettingsSection";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Skeleton } from "@/components/ui/States";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ServerP55SettingsCard } from "@/server_manager/components/p55/ServerP55SettingsCard";
import { ServerModeConversionCard } from "@/server_manager/components/ServerModeConversionCard";
import { toast } from "@/stores/toastStore";

export function ServerSettingsPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const branchCtx = useServerBranchContext();
  const gitBacked = Boolean(branchCtx?.gitBacked);
  const activeBranch = gitBacked ? branchCtx?.branch : undefined;
  const isMainBranch = Boolean(gitBacked && activeBranch === "main");

  const { data: server, isLoading, error } = useServerDetail(
    serverId ?? "",
    activeBranch,
  );
  const deleteServer = useDeleteServer();
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const deletingRef = useRef(false);

  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();

  const restartAndApplyMutation = useMutation({
    mutationFn: () => api.restartServer(serverId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.servers.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId!, "main") });
      queryClient.invalidateQueries({ queryKey: queryKeys.versioning.branches(serverId!) });
      toast("success", "Server restarting", "Pending settings branch will auto-merge during restart.");
    },
    onError: (err) =>
      toast("error", "Restart failed", err instanceof Error ? err.message : "Failed to restart server"),
  });

  const discardPendingMutation = useMutation({
    mutationFn: () => api.discardPendingSettings(serverId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.servers.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId!, "main") });
      queryClient.invalidateQueries({ queryKey: queryKeys.versioning.branches(serverId!) });
      toast("success", "Pending settings discarded", "Cleared unmerged settings branch.");
    },
    onError: (err) =>
      toast("error", "Discard failed", err instanceof Error ? err.message : "Failed to discard pending settings"),
  });

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
            {gitBacked && activeBranch && (
              <span
                data-testid="settings-branch-badge"
                className="inline-flex items-center gap-1 rounded-md border border-accent-primary/30 bg-accent-primary/10 px-2.5 py-0.5 font-mono text-xs font-semibold text-accent-primary"
              >
                Branch: {activeBranch}
              </span>
            )}
          </div>
        </div>
      </div>

      {isMainBranch && server.pending_settings_branch && (
        <div
          data-testid="pending-settings-banner"
          role="region"
          aria-label="Pending Settings Branch"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-warning-border bg-status-warning-bg px-4 py-3 text-xs text-text-primary shadow-2xs"
        >
          <div className="space-y-0.5 min-w-0">
            <p className="font-semibold text-status-warning">
              Pending main settings queued in{" "}
              <code className="font-mono">{server.pending_settings_branch.branch_name}</code>{" "}
              ({server.pending_settings_branch.status || "pending"})
            </p>
            <p className="text-text-secondary">
              {server.pending_settings_branch.error_message
                ? `Auto-merge issue: ${server.pending_settings_branch.error_message}`
                : "Changes will automatically merge into main on next server restart."}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <Link
              to={`/servers/${serverId}/versioning?branch=${encodeURIComponent(server.pending_settings_branch.branch_name)}`}
              className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 font-medium text-text-primary hover:bg-surface-hover"
            >
              View Diff
            </Link>
            <button
              type="button"
              data-testid="pending-settings-restart-btn"
              disabled={restartAndApplyMutation.isPending}
              onClick={() => restartAndApplyMutation.mutate()}
              className="inline-flex items-center gap-1 rounded-lg bg-accent-primary px-3 py-1.5 font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer"
            >
              {restartAndApplyMutation.isPending ? "Restarting..." : "Restart & Apply Now"}
            </button>
            <button
              type="button"
              data-testid="pending-settings-discard-btn"
              disabled={discardPendingMutation.isPending}
              onClick={() => discardPendingMutation.mutate()}
              className="inline-flex items-center gap-1 rounded-lg border border-status-danger-border bg-surface-card px-3 py-1.5 font-medium text-status-danger hover:bg-status-danger-bg disabled:opacity-50 cursor-pointer"
            >
              {discardPendingMutation.isPending ? "Discarding..." : "Discard Pending Changes"}
            </button>
          </div>
        </div>
      )}

      {/* Section 1: Branch-Scoped Settings */}
      <section data-testid="branch-scoped-settings-section" className="space-y-4">
        {gitBacked && activeBranch && (
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-bold uppercase tracking-wider text-text-secondary">
              Branch-Scoped Settings (Branch: {activeBranch})
            </h3>
          </div>
        )}
        <ServerSettingsSection
          key={`${serverId}-${activeBranch ?? "main"}`}
          serverId={serverId!}
          server={server}
          branch={activeBranch}
          gitBacked={gitBacked}
        />
      </section>

      {/* Section 2: Server-Wide Settings */}
      <section data-testid="server-wide-settings-section" className="space-y-4 pt-2 border-t border-border-default">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-wider text-text-secondary">
            Server-Wide Settings
          </h3>
          <p className="text-xs text-text-muted">
            Applies to the entire server (all branches)
          </p>
        </div>

        <ServerP55SettingsCard serverId={serverId!} serverType={server.server_type} />

        <ServerModeConversionCard serverId={serverId!} server={server} />

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
      </section>

      <ConfirmDialog
        open={showDeleteModal}
        title={`Delete "${server.name}"?`}
        description="Are you sure you want to permanently delete this server? All player data, worlds, configurations, and installed files will be permanently erased. This action cannot be undone."
        confirmLabel={deleteServer.isPending ? "Deleting..." : "Delete Server"}
        cancelLabel="Cancel"
        variant="danger"
        isPending={deleteServer.isPending}
        onConfirm={() => {
          if (deleteServer.isPending || deletingRef.current) return;
          deletingRef.current = true;
          deleteServer.mutate(serverId!, {
            onSuccess: () => {
              deletingRef.current = false;
              setShowDeleteModal(false);
              toast("success", "Server deleted", `"${server.name}" was permanently deleted.`);
              navigate("/servers", { replace: true });
            },
            onError: (err) => {
              deletingRef.current = false;
              toast("error", "Delete failed", err instanceof Error ? err.message : "Failed to delete server");
              setShowDeleteModal(false);
            },
          });
        }}
        onCancel={() => {
          if (deleteServer.isPending) return;
          setShowDeleteModal(false);
        }}
      />
    </div>
  );
}
