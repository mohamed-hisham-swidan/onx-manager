import { useSettings } from "@/server_manager/hooks/useSettings";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ErrorState";

export function SettingsPage() {
  const { data: settings, isLoading, error } = useSettings();

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState message={error instanceof Error ? error.message : "Failed to load settings"} />
    );
  }

  if (!settings) {
    return <p className="text-gray-500 dark:text-gray-400">Settings not available.</p>;
  }

  return (
    <div>
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Settings</h2>

      <div
        role="status"
        className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300"
      >
        Settings are <strong>read-only</strong> in this build — they are not persisted yet. Values
        below are loaded from the server's current configuration. Saving edits is not available until
        settings persistence is implemented.
      </div>

      <div className="space-y-6">
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">General</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">App Name</label>
              <input
                name="app_name"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                defaultValue={settings.app_name}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Log Level</label>
              <select
                name="log_level"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                defaultValue={settings.log_level}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Debug Mode</label>
              <select
                name="debug"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                defaultValue={settings.debug ? "true" : "false"}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="true">Enabled</option>
                <option value="false">Disabled</option>
              </select>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Rate Limiting & Security</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Rate Limit (per minute)</label>
              <input
                name="rate_limit_per_minute"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                type="number"
                defaultValue={settings.rate_limit_per_minute}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Idempotency TTL (hours)</label>
              <input
                name="idempotency_ttl_hours"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                type="number"
                defaultValue={settings.idempotency_ttl_hours}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Circuit Breaker</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Max Failures</label>
              <input
                name="circuit_breaker_max_failures"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                type="number"
                defaultValue={settings.circuit_breaker_max_failures}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Timeout (seconds)</label>
              <input
                name="circuit_breaker_timeout_seconds"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                type="number"
                defaultValue={settings.circuit_breaker_timeout_seconds}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-4">Event Bus & Sagas</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Event Bus Retry Attempts</label>
              <input
                name="event_bus_retry_attempts"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                type="number"
                defaultValue={settings.event_bus_retry_attempts}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Saga Timeout (seconds)</label>
              <input
                name="saga_timeout_seconds"
                disabled
                title="Read-only — settings persistence is not implemented in this build"
                type="number"
                defaultValue={settings.saga_timeout_seconds}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
