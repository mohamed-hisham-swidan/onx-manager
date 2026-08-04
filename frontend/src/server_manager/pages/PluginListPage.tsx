import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useServersList } from "@/server_manager/hooks/useServers";
import { usePluginsList, useEnablePlugin, useDisablePlugin, useUninstallPlugin } from "@/server_manager/hooks/usePlugins";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/EmptyState";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import type { PluginResponse } from "@/types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

export function PluginListPage() {
  const navigate = useNavigate();
  const { data: servers } = useServersList();
  const [selectedServerId, setSelectedServerId] = useState("");
  const [uninstallTarget, setUninstallTarget] = useState<PluginResponse | null>(null);

  const { data: plugins, isLoading, error } = usePluginsList(selectedServerId);
  const enablePlugin = useEnablePlugin(selectedServerId);
  const disablePlugin = useDisablePlugin(selectedServerId);
  const uninstallPlugin = useUninstallPlugin(selectedServerId);

  function handleInstall() {
    navigate(`/plugins/marketplace?server=${encodeURIComponent(selectedServerId)}`);
  }

  function handleConfirmUninstall() {
    if (!uninstallTarget) return;
    uninstallPlugin.mutate(uninstallTarget.plugin_id, {
      onSuccess: () => toast("success", "Plugin uninstalled", `"${uninstallTarget.name}" was removed.`),
      onError: (err) => toast("error", "Uninstall failed", errorMessage(err)),
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
          selectedServerId ? (
            <button
              onClick={handleInstall}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              <Icon name="plus" size={16} />
              Install Plugin
            </button>
          ) : undefined
        }
      />

      <div className="mb-4 max-w-xs">
        <label className="sr-only" htmlFor="plugin-server-select">
          Choose a server
        </label>
        <select
          id="plugin-server-select"
          value={selectedServerId}
          onChange={(e) => setSelectedServerId(e.target.value)}
          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
        >
          <option value="">Select a server...</option>
          {servers?.map((s) => (
            <option key={s.server_id} value={s.server_id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>

      {!selectedServerId ? (
        <EmptyState
          icon="plugin"
          title="Select a server"
          description="Choose a server above to view its plugins."
        />
      ) : isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400">
          {error instanceof Error ? error.message : "Failed to load plugins"}
        </div>
      ) : plugins && plugins.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">Name</th>
                <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 sm:table-cell">Version</th>
                <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 md:table-cell">Author</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">Status</th>
                <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-400">Actions</th>
              </tr>
            </thead>
            <tbody>
              {plugins.map((p) => (
                <tr
                  key={p.plugin_id}
                  className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                >
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900 dark:text-gray-100">{p.name}</p>
                    {p.description && (
                      <p className="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400" title={p.description}>
                        {p.description}
                      </p>
                    )}
                  </td>
                  <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 sm:table-cell">{p.version}</td>
                  <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 md:table-cell">{p.author}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        p.status === "enabled"
                          ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                          : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400"
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
                          onClick={() =>
                            disablePlugin.mutate(p.plugin_id, {
                              onSuccess: () => toast("success", "Plugin disabled", `"${p.name}" is disabled.`),
                              onError: (err) => toast("error", "Disable failed", errorMessage(err)),
                            })
                          }
                          disabled={disablePlugin.isPending}
                          aria-label={`Disable ${p.name}`}
                          title="Disable"
                          className="rounded-lg p-1.5 text-orange-600 transition-colors hover:bg-orange-100 hover:text-orange-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-orange-400 dark:hover:bg-orange-900/30 dark:hover:text-orange-300"
                        >
                          <Icon name="stop" size={16} />
                        </button>
                      ) : (
                        <button
                          onClick={() =>
                            enablePlugin.mutate(p.plugin_id, {
                              onSuccess: () => toast("success", "Plugin enabled", `"${p.name}" is enabled.`),
                              onError: (err) => toast("error", "Enable failed", errorMessage(err)),
                            })
                          }
                          disabled={enablePlugin.isPending}
                          aria-label={`Enable ${p.name}`}
                          title="Enable"
                          className="rounded-lg p-1.5 text-green-600 transition-colors hover:bg-green-100 hover:text-green-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-green-400 dark:hover:bg-green-900/30 dark:hover:text-green-300"
                        >
                          <Icon name="play" size={16} />
                        </button>
                      )}
                      <button
                        onClick={() => setUninstallTarget(p)}
                        disabled={uninstallPlugin.isPending}
                        aria-label={`Uninstall ${p.name}`}
                        title="Uninstall"
                        className="rounded-lg p-1.5 text-red-600 transition-colors hover:bg-red-100 hover:text-red-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-red-400 dark:hover:bg-red-900/30 dark:hover:text-red-300"
                      >
                        <Icon name="trash" size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          icon="plugin"
          title="No plugins installed"
          description="Install a plugin to add functionality to your server."
          action={
            <button
              onClick={handleInstall}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
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
          uninstallTarget ? `This removes "${uninstallTarget.name}" from the server.` : undefined
        }
        confirmLabel="Uninstall"
        cancelLabel="Cancel"
        onConfirm={handleConfirmUninstall}
        onCancel={() => setUninstallTarget(null)}
      />
    </div>
  );
}
