import { useState } from "react";
import { useServersList } from "@/server_manager/hooks/useServers";
import { usePluginsList, useEnablePlugin, useDisablePlugin, useUninstallPlugin } from "@/server_manager/hooks/usePlugins";
import { TableSkeleton } from "@/components/Skeleton";
import { EmptyState } from "@/components/EmptyState";
import { InstallPluginDialog } from "@/server_manager/components/InstallPluginDialog";

export function PluginListPage() {
  const { data: servers } = useServersList();
  const [selectedServerId, setSelectedServerId] = useState("");
  const [showInstall, setShowInstall] = useState(false);

  const { data: plugins, isLoading, error } = usePluginsList(selectedServerId);
  const enablePlugin = useEnablePlugin(selectedServerId);
  const disablePlugin = useDisablePlugin(selectedServerId);
  const uninstallPlugin = useUninstallPlugin(selectedServerId);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Plugins</h2>
        {selectedServerId && (
          <button
            onClick={() => setShowInstall(!showInstall)}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
          >
            {showInstall ? "Cancel" : "+ Install Plugin"}
          </button>
        )}
      </div>

      <div className="mb-4">
        <select
          value={selectedServerId}
          onChange={(e) => { setSelectedServerId(e.target.value); setShowInstall(false); }}
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 w-full max-w-xs"
        >
          <option value="">Select a server...</option>
          {servers?.map((s) => (
            <option key={s.server_id} value={s.server_id}>{s.name}</option>
          ))}
        </select>
      </div>

      {showInstall && selectedServerId && (
        <div className="mb-6">
          <InstallPluginDialog serverId={selectedServerId} onDone={() => setShowInstall(false)} />
        </div>
      )}

      {!selectedServerId ? (
        <EmptyState icon="⌘" title="Select a server" description="Choose a server above to view its plugins." />
      ) : isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : error ? (
        <p className="text-red-600 dark:text-red-400">
          {error instanceof Error ? error.message : "Failed to load plugins"}
        </p>
      ) : plugins && plugins.length > 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Name</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Version</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Author</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Status</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Actions</th>
              </tr>
            </thead>
            <tbody>
              {plugins.map((p) => (
                <tr key={p.plugin_id} className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  <td className="px-4 py-3">
                    <div className="text-gray-900 dark:text-gray-100 font-medium">{p.name}</div>
                    {p.description && <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{p.description}</div>}
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{p.version}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{p.author}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      p.status === "enabled"
                        ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                        : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400"
                    }`}>
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right space-x-1">
                    {p.status === "enabled" ? (
                      <button
                        onClick={() => disablePlugin.mutate(p.plugin_id)}
                        disabled={disablePlugin.isPending}
                        className="px-2 py-1 text-xs rounded bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400 hover:bg-orange-200 dark:hover:bg-orange-900/50 disabled:opacity-50"
                      >
                        Disable
                      </button>
                    ) : (
                      <button
                        onClick={() => enablePlugin.mutate(p.plugin_id)}
                        disabled={enablePlugin.isPending}
                        className="px-2 py-1 text-xs rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50 disabled:opacity-50"
                      >
                        Enable
                      </button>
                    )}
                    <button
                      onClick={() => {
                        if (confirm(`Uninstall ${p.name}?`)) uninstallPlugin.mutate(p.plugin_id);
                      }}
                      disabled={uninstallPlugin.isPending}
                      className="px-2 py-1 text-xs rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50"
                    >
                      Uninstall
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          icon="⌘"
          title="No plugins installed"
          description="Install a plugin to add functionality to your server."
          action={
            <button
              onClick={() => setShowInstall(true)}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
            >
              + Install Plugin
            </button>
          }
        />
      )}
    </div>
  );
}
