import { useServersList } from "@/server_manager/hooks/useServers";
import { STATUS_MAP } from "@/server_manager/types";
import { Link } from "react-router-dom";

export function DashboardPage() {
  const { data: servers, isLoading } = useServersList();

  const counts = (servers ?? []).reduce<Record<string, number>>((acc, s) => {
    const status = s.status || "unknown";
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Dashboard</h2>

      {isLoading ? (
        <p className="text-gray-500 dark:text-gray-400">Loading...</p>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            {Object.entries(STATUS_MAP).map(([status, { label }]) => (
              <div
                key={status}
                className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4"
              >
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">{label}</p>
                <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {counts[status] ?? 0}
                </p>
              </div>
            ))}
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100">Servers</h3>
              <Link
                to="/servers"
                className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
              >
                View all
              </Link>
            </div>
            {servers && servers.length > 0 ? (
              <div className="space-y-2">
                {servers.slice(0, 5).map((s) => (
                  <div
                    key={s.server_id}
                    className="flex items-center justify-between py-1.5"
                  >
                    <span className="text-sm text-gray-700 dark:text-gray-300">{s.name}</span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        STATUS_MAP[s.status]?.color ?? "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {STATUS_MAP[s.status]?.label ?? s.status}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400">No servers yet.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}