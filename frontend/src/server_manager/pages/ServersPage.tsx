import { Link } from "react-router-dom";
import { useServersList, useDeleteServer, useStartServer, useStopServer } from "@/server_manager/hooks/useServers";
import { STATUS_MAP } from "@/server_manager/types";

export function ServersPage() {
  const { data: servers, isLoading, error } = useServersList();
  const deleteServer = useDeleteServer();
  const startServer = useStartServer();
  const stopServer = useStopServer();

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Servers</h2>
        <Link
          to="/servers/create"
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
        >
          + New Server
        </Link>
        <Link
          to="/servers/import"
          className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          Import
        </Link>
      </div>

      {isLoading ? (
        <p className="text-gray-500 dark:text-gray-400">Loading...</p>
      ) : error ? (
        <p className="text-red-600 dark:text-red-400">
          {error instanceof Error ? error.message : "Failed to load servers"}
        </p>
      ) : servers && servers.length > 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Name</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Version</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Port</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Status</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Actions</th>
              </tr>
            </thead>
            <tbody>
              {servers.map((s) => (
                <tr
                  key={s.server_id}
                  className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30"
                >
                  <td className="px-4 py-3">
                    <Link to={`/servers/${s.server_id}`} className="text-blue-600 dark:text-blue-400 hover:underline font-medium">
                      {s.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{s.minecraft_version}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{s.port}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        STATUS_MAP[s.status]?.color ?? "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {STATUS_MAP[s.status]?.label ?? s.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right space-x-1">
                    {["stopped", "created"].includes(s.status) ? (
                      <button
                        onClick={() => startServer.mutate(s.server_id)}
                        disabled={startServer.isPending}
                        className="px-2 py-1 text-xs rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50 disabled:opacity-50"
                      >
                        Start
                      </button>
                    ) : s.status === "running" ? (
                      <button
                        onClick={() => stopServer.mutate(s.server_id)}
                        disabled={stopServer.isPending}
                        className="px-2 py-1 text-xs rounded bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400 hover:bg-orange-200 dark:hover:bg-orange-900/50 disabled:opacity-50"
                      >
                        Stop
                      </button>
                    ) : null}
                    <button
                      onClick={() => {
                        if (confirm(`Delete ${s.name}?`)) deleteServer.mutate(s.server_id);
                      }}
                      disabled={deleteServer.isPending}
                      className="px-2 py-1 text-xs rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-gray-500 dark:text-gray-400">No servers found. Create one to get started.</p>
      )}
    </div>
  );
}