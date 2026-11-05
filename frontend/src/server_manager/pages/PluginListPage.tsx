import { useState, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useServersList } from "@/server_manager/hooks/useServers";
import {
  usePluginsList,
  useEnablePlugin,
  useDisablePlugin,
  useUninstallPlugin,
} from "@/server_manager/hooks/usePlugins";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Pagination } from "@/components/ui/Pagination";
import { TableSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import type { PluginResponse } from "@/types";

const PAGE_SIZE = 15;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function SourceBadge({ plugin }: { plugin: PluginResponse }) {
  if (plugin.source === "modrinth") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-accent-primary/20 px-2 py-0.5 text-xs font-medium text-accent-primary border border-accent-primary/30">
        <Icon name="external" size={12} />
        Marketplace
      </span>
    );
  }
  if (plugin.source === "detected") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-surface-page px-2 py-0.5 text-xs font-medium text-text-secondary border border-border-default">
        Detected on disk
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-status-warning-bg px-2 py-0.5 text-xs font-medium text-status-warning border border-status-warning/30">
      Manual
    </span>
  );
}

export function PluginListPage() {
  const { serverId: routeServerId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const { data: servers } = useServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);
  const [touched, setTouched] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState("");
  const [uninstallTarget, setUninstallTarget] = useState<PluginResponse | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  const effectiveServerId = routeServerId
    ? routeServerId
    : touched
      ? selectedServerId
      : lastUsedServerId && servers?.some((s) => s.server_id === lastUsedServerId)
        ? lastUsedServerId
        : selectedServerId;

  const { data: plugins, isLoading, error } = usePluginsList(effectiveServerId);
  const enablePlugin = useEnablePlugin(effectiveServerId);
  const disablePlugin = useDisablePlugin(effectiveServerId);
  const uninstallPlugin = useUninstallPlugin(effectiveServerId);

  const paginatedPlugins = useMemo(() => {
    if (!plugins || plugins.length <= PAGE_SIZE) return plugins ?? [];
    const startIdx = (currentPage - 1) * PAGE_SIZE;
    return plugins.slice(startIdx, startIdx + PAGE_SIZE);
  }, [plugins, currentPage]);

  function handleServerChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setTouched(true);
    setSelectedServerId(e.target.value);
    setCurrentPage(1);
  }

  function handleInstall() {
    navigate(`/marketplace?server=${encodeURIComponent(effectiveServerId)}`);
  }

  function handleConfirmUninstall() {
    if (!uninstallTarget) return;
    uninstallPlugin.mutate(uninstallTarget.plugin_id, {
      onSuccess: () =>
        toast(
          "success",
          "Removal requested",
          `"${uninstallTarget.name}" will be removed on the next server restart.`,
        ),
      onError: (err) => toast("error", "Remove failed", errorMessage(err)),
      onSettled: () => setUninstallTarget(null),
    });
  }

  return (
    <div>
      <PageHeader
        title="Plugins"
        description="Manage plugins for your servers"
        icon="plugin"
        actions={
          effectiveServerId ? (
            <button
              type="button"
              onClick={handleInstall}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover cursor-pointer shadow-xs"
            >
              <Icon name="plus" size={16} />
              Install Plugin
            </button>
          ) : undefined
        }
      />

      {!routeServerId && (
        <div className="mb-4 max-w-xs">
          <label className="sr-only" htmlFor="plugin-server-select">
            Choose a server
          </label>
          <select
            id="plugin-server-select"
            value={effectiveServerId}
            onChange={handleServerChange}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
          >
            <option value="">Select a server...</option>
            {servers?.map((s) => (
              <option key={s.server_id} value={s.server_id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {!effectiveServerId ? (
        <EmptyState
          icon="plugin"
          title="Select a server"
          description="Choose a server above to view its plugins."
        />
      ) : isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : error ? (
        <ErrorState message={error instanceof Error ? error.message : "Failed to load plugins"} />
      ) : plugins && plugins.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-border-default bg-surface-card shadow-xs">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle bg-surface-page/50">
                <th className="px-4 py-3 text-left font-medium text-text-muted">Name</th>
                <th className="hidden px-4 py-3 text-left font-medium text-text-muted sm:table-cell">Version</th>
                <th className="hidden px-4 py-3 text-left font-medium text-text-muted md:table-cell">Author</th>
                <th className="px-4 py-3 text-left font-medium text-text-muted">Status</th>
                <th className="px-4 py-3 text-right font-medium text-text-muted">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {paginatedPlugins.map((p) => (
                <tr
                  key={p.plugin_id}
                  className="hover:bg-surface-hover/50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-start gap-3">
                      {p.icon_url ? (
                        <img
                          src={p.icon_url}
                          alt={`${p.name} icon`}
                          className="h-10 w-10 shrink-0 rounded-lg bg-surface-page object-cover border border-border-subtle"
                        />
                      ) : (
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-page text-text-muted border border-border-subtle">
                          <Icon name="plugin" size={24} />
                        </div>
                      )}
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="font-medium text-text-primary">{p.name}</p>
                          <SourceBadge plugin={p} />
                        </div>
                        {p.description && (
                          <p className="mt-0.5 truncate text-xs text-text-muted" title={p.description}>
                            {p.description}
                          </p>
                        )}
                        {p.filename && (
                          <p className="mt-0.5 truncate font-mono text-xs text-text-muted opacity-80" title={p.filename}>
                            {p.filename}
                          </p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="hidden px-4 py-3 text-text-muted sm:table-cell">
                    {p.version === "unknown" ? (
                      <span className="text-text-muted opacity-50">{p.version}</span>
                    ) : (
                      p.version
                    )}
                  </td>
                  <td className="hidden px-4 py-3 text-text-muted md:table-cell">{p.author}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium border ${
                        p.status === "enabled"
                          ? "bg-status-success-bg text-status-success border-status-success/30"
                          : "bg-surface-page text-text-muted border-border-default"
                      }`}
                    >
                      <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      {p.status === "enabled" ? (
                        <button
                          type="button"
                          onClick={() =>
                            disablePlugin.mutate(p.plugin_id, {
                              onSuccess: () => toast("success", "Plugin disabled", `"${p.name}" is disabled.`),
                              onError: (err) => toast("error", "Disable failed", errorMessage(err)),
                            })
                          }
                          disabled={disablePlugin.isPending}
                          aria-label={`Disable ${p.name}`}
                          title="Disable"
                          className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                        >
                          <Icon name="stop" size={16} />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() =>
                            enablePlugin.mutate(p.plugin_id, {
                              onSuccess: () => toast("success", "Plugin enabled", `"${p.name}" is enabled.`),
                              onError: (err) => toast("error", "Enable failed", errorMessage(err)),
                            })
                          }
                          disabled={enablePlugin.isPending}
                          aria-label={`Enable ${p.name}`}
                          title="Enable"
                          className="rounded-lg p-1.5 text-status-success transition-colors hover:bg-status-success-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                        >
                          <Icon name="play" size={16} />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setUninstallTarget(p)}
                        disabled={uninstallPlugin.isPending}
                        aria-label={`Uninstall ${p.name}`}
                        title="Uninstall"
                        className="rounded-lg p-1.5 text-status-danger transition-colors hover:bg-status-danger-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                      >
                        <Icon name="trash" size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {plugins.length > PAGE_SIZE && (
            <div className="border-t border-border-subtle p-3">
              <Pagination
                totalItems={plugins.length}
                pageSize={PAGE_SIZE}
                page={currentPage}
                onPageChange={setCurrentPage}
              />
            </div>
          )}
        </div>
      ) : (
        <EmptyState
          icon="plugin"
          title="No plugins installed"
          description="Install a plugin from the marketplace, or drop a .jar file directly into the server's plugins/ folder — it will appear here automatically."
          action={
            <button
              type="button"
              onClick={handleInstall}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover cursor-pointer shadow-xs"
            >
              <Icon name="plus" size={16} />
              Install Plugin
            </button>
          }
        />
      )}

      <ConfirmDialog
        open={uninstallTarget !== null}
        title="Uninstall plugin?"
        description={
          uninstallTarget
            ? `This removes "${uninstallTarget.name}" from the list now. The ${uninstallTarget.filename ? `file ${uninstallTarget.filename} ` : "file "}will be deleted from disk the next time this server restarts.`
            : undefined
        }
        confirmLabel="Uninstall"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmUninstall}
        onCancel={() => setUninstallTarget(null)}
      />
    </div>
  );
}

