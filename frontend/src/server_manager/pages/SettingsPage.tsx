import { useState, useMemo } from "react";
import { useSettings, useUpdateSettings } from "@/server_manager/hooks/useSettings";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { toast } from "@/stores/toastStore";
import type { SettingsResponse, SettingsUpdateRequest } from "@/types";
import { InvitationsSection } from "@/server_manager/components/InvitationsSection";
import { AccessSection } from "@/server_manager/components/AccessSection";

interface FormState {
  app_name: string;
  log_level: string;
  debug: boolean;
  rate_limit_per_minute: number;
  idempotency_ttl_hours: number;
  circuit_breaker_max_failures: number;
  circuit_breaker_timeout_seconds: number;
  event_bus_retry_attempts: number;
  saga_timeout_seconds: number;
}

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<"system" | "invitations" | "access">("system");
  const { data: settings, isLoading, error } = useSettings();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-48" />
        <div className="space-y-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800 space-y-4">
              <Skeleton className="h-6 w-36" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            </div>
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
    return <ErrorState message="Settings not available" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex border-b border-gray-200 dark:border-gray-700">
        <button
          type="button"
          onClick={() => setActiveTab("system")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
            activeTab === "system"
              ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400"
              : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          System Settings
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("invitations")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
            activeTab === "invitations"
              ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400"
              : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          Invitations
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("access")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
            activeTab === "access"
              ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400"
              : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          Access Control
        </button>
      </div>

      {activeTab === "system" ? (
        <SettingsForm settings={settings} />
      ) : activeTab === "invitations" ? (
        <InvitationsSection />
      ) : (
        <AccessSection />
      )}
    </div>
  );
}

function SettingsForm({ settings }: { settings: SettingsResponse }) {
  const updateSettings = useUpdateSettings();

  const [formData, setFormData] = useState<FormState>({
    app_name: settings.app_name ?? "MCS Manager",
    log_level: settings.log_level ?? "INFO",
    debug: Boolean(settings.debug),
    rate_limit_per_minute: settings.rate_limit_per_minute ?? 60,
    idempotency_ttl_hours: settings.idempotency_ttl_hours ?? 24,
    circuit_breaker_max_failures: settings.circuit_breaker_max_failures ?? 5,
    circuit_breaker_timeout_seconds: settings.circuit_breaker_timeout_seconds ?? 30,
    event_bus_retry_attempts: settings.event_bus_retry_attempts ?? 3,
    saga_timeout_seconds: settings.saga_timeout_seconds ?? 300,
  });

  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccessNotice, setSaveSuccessNotice] = useState<{
    message: string;
    restartFields: string[];
  } | null>(null);

  // Set of fields that require backend service restart
  const restartRequiredSet = useMemo(() => {
    return new Set(settings.requires_restart || ["app_name", "log_level", "debug"]);
  }, [settings.requires_restart]);

  // Compute dirty state
  const isDirty = useMemo(() => {
    return (
      formData.app_name !== settings.app_name ||
      formData.log_level !== settings.log_level ||
      formData.debug !== settings.debug ||
      Number(formData.rate_limit_per_minute) !== settings.rate_limit_per_minute ||
      Number(formData.idempotency_ttl_hours) !== settings.idempotency_ttl_hours ||
      Number(formData.circuit_breaker_max_failures) !== settings.circuit_breaker_max_failures ||
      Number(formData.circuit_breaker_timeout_seconds) !== settings.circuit_breaker_timeout_seconds ||
      Number(formData.event_bus_retry_attempts) !== settings.event_bus_retry_attempts ||
      Number(formData.saga_timeout_seconds) !== settings.saga_timeout_seconds
    );
  }, [formData, settings]);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const { name, value, type } = e.target;
    let newValue: string | number | boolean = value;

    if (type === "number") {
      newValue = value === "" ? 0 : Number(value);
    } else if (name === "debug") {
      newValue = value === "true";
    }

    setFormData((prev) => ({
      ...prev,
      [name]: newValue,
    }));
  };

  const handleReset = () => {
    setFormData({
      app_name: settings.app_name ?? "MCS Manager",
      log_level: settings.log_level ?? "INFO",
      debug: Boolean(settings.debug),
      rate_limit_per_minute: settings.rate_limit_per_minute ?? 60,
      idempotency_ttl_hours: settings.idempotency_ttl_hours ?? 24,
      circuit_breaker_max_failures: settings.circuit_breaker_max_failures ?? 5,
      circuit_breaker_timeout_seconds: settings.circuit_breaker_timeout_seconds ?? 30,
      event_bus_retry_attempts: settings.event_bus_retry_attempts ?? 3,
      saga_timeout_seconds: settings.saga_timeout_seconds ?? 300,
    });
    setSaveError(null);
    setSaveSuccessNotice(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    setSaveSuccessNotice(null);

    const payload: SettingsUpdateRequest = {
      app_name: formData.app_name,
      log_level: formData.log_level,
      debug: formData.debug,
      rate_limit_per_minute: Number(formData.rate_limit_per_minute),
      idempotency_ttl_hours: Number(formData.idempotency_ttl_hours),
      circuit_breaker_max_failures: Number(formData.circuit_breaker_max_failures),
      circuit_breaker_timeout_seconds: Number(formData.circuit_breaker_timeout_seconds),
      event_bus_retry_attempts: Number(formData.event_bus_retry_attempts),
      saga_timeout_seconds: Number(formData.saga_timeout_seconds),
    };

    try {
      const res = await updateSettings.mutateAsync(payload);
      toast("success", "Settings saved", "Your changes have been saved successfully.");
      setSaveSuccessNotice({
        message: res.message || "Settings updated successfully.",
        restartFields: res.requires_restart || [],
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to update settings";
      setSaveError(msg);
      toast("error", "Failed to save settings", msg);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <PageHeader
        title="Settings"
        description="System parameters, rate limits, security thresholds, and saga execution settings"
        icon="settings"
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleReset}
              disabled={!isDirty || updateSettings.isPending}
              className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm font-medium text-gray-700 dark:text-gray-200 transition-colors hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Discard Changes
            </button>
            <button
              type="submit"
              disabled={updateSettings.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {updateSettings.isPending ? (
                <>
                  <Icon name="restart" size={16} className="animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Icon name="check" size={16} />
                  Save Settings
                </>
              )}
            </button>
          </div>
        }
      />

      {saveError && (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 flex items-start gap-3"
        >
          <Icon name="alert" size={18} className="mt-0.5 shrink-0 text-red-600 dark:text-red-400" />
          <div className="flex-1 min-w-0">
            <p className="font-medium">Failed to save settings</p>
            <p className="mt-0.5 text-xs text-red-700 dark:text-red-300">{saveError}</p>
          </div>
        </div>
      )}

      {saveSuccessNotice && (
        <div
          role="status"
          className="rounded-xl border border-green-200 bg-green-50 p-4 text-sm text-green-800 dark:border-green-900/40 dark:bg-green-900/20 dark:text-green-300 flex items-start gap-3"
        >
          <Icon name="check" size={18} className="mt-0.5 shrink-0 text-green-600 dark:text-green-400" />
          <div className="flex-1 min-w-0">
            <p className="font-medium">{saveSuccessNotice.message}</p>
            {saveSuccessNotice.restartFields.length > 0 && (
              <p className="mt-1 text-xs text-green-700 dark:text-green-300">
                Note: Changes to <strong>{saveSuccessNotice.restartFields.join(", ")}</strong> require a backend restart to take effect.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Section 1: General */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">General</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Core application identity and runtime logging configuration.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* App Name */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="app_name" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                App Name
              </label>
              {restartRequiredSet.has("app_name") && <RestartBadge />}
            </div>
            <input
              id="app_name"
              name="app_name"
              type="text"
              value={formData.app_name}
              onChange={handleChange}
              aria-describedby="app_name-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p id="app_name-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Display name for this MCS Manager instance.
            </p>
          </div>

          {/* Log Level */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="log_level" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Log Level
              </label>
              {restartRequiredSet.has("log_level") && <RestartBadge />}
            </div>
            <select
              id="log_level"
              name="log_level"
              value={formData.log_level}
              onChange={handleChange}
              aria-describedby="log_level-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="DEBUG">DEBUG</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
            </select>
            <p id="log_level-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Minimum severity level for application logs.
            </p>
          </div>

          {/* Debug Mode */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="debug" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                Debug Mode
              </label>
              {restartRequiredSet.has("debug") && <RestartBadge />}
            </div>
            <select
              id="debug"
              name="debug"
              value={formData.debug ? "true" : "false"}
              onChange={handleChange}
              aria-describedby="debug-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="true">Enabled</option>
              <option value="false">Disabled</option>
            </select>
            <p id="debug-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Enables verbose logging and detailed error stack traces.
            </p>
          </div>
        </div>
      </div>

      {/* Section 2: Rate Limiting & Security */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Rate Limiting & Security</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            API request throttling and idempotency token retention policies.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Rate Limit per minute */}
          <div>
            <label htmlFor="rate_limit_per_minute" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Rate Limit (per minute)
            </label>
            <input
              id="rate_limit_per_minute"
              name="rate_limit_per_minute"
              type="number"
              min={1}
              max={10000}
              value={formData.rate_limit_per_minute}
              onChange={handleChange}
              aria-describedby="rate_limit_per_minute-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p id="rate_limit_per_minute-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Max API requests per minute per IP address.
            </p>
          </div>

          {/* Idempotency TTL */}
          <div>
            <label htmlFor="idempotency_ttl_hours" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Idempotency TTL (hours)
            </label>
            <input
              id="idempotency_ttl_hours"
              name="idempotency_ttl_hours"
              type="number"
              min={1}
              max={720}
              value={formData.idempotency_ttl_hours}
              onChange={handleChange}
              aria-describedby="idempotency_ttl_hours-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p id="idempotency_ttl_hours-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Retention period in hours for request idempotency execution keys.
            </p>
          </div>
        </div>
      </div>

      {/* Section 3: Circuit Breaker */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Circuit Breaker</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Fault tolerance thresholds and automated service recovery timings.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Max Failures */}
          <div>
            <label htmlFor="circuit_breaker_max_failures" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Max Failures
            </label>
            <input
              id="circuit_breaker_max_failures"
              name="circuit_breaker_max_failures"
              type="number"
              min={1}
              max={100}
              value={formData.circuit_breaker_max_failures}
              onChange={handleChange}
              aria-describedby="circuit_breaker_max_failures-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p id="circuit_breaker_max_failures-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Consecutive errors before opening the circuit breaker.
            </p>
          </div>

          {/* Timeout seconds */}
          <div>
            <label htmlFor="circuit_breaker_timeout_seconds" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Timeout (seconds)
            </label>
            <input
              id="circuit_breaker_timeout_seconds"
              name="circuit_breaker_timeout_seconds"
              type="number"
              min={1}
              max={3600}
              value={formData.circuit_breaker_timeout_seconds}
              onChange={handleChange}
              aria-describedby="circuit_breaker_timeout_seconds-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p id="circuit_breaker_timeout_seconds-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Cooldown duration in seconds before attempting half-open recovery.
            </p>
          </div>
        </div>
      </div>

      {/* Section 4: Event Bus & Sagas */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Event Bus & Sagas</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Asynchronous event dispatch retry policies and multi-step saga execution timeouts.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Event bus retry attempts */}
          <div>
            <label htmlFor="event_bus_retry_attempts" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Event Bus Retry Attempts
            </label>
            <input
              id="event_bus_retry_attempts"
              name="event_bus_retry_attempts"
              type="number"
              min={0}
              max={10}
              value={formData.event_bus_retry_attempts}
              onChange={handleChange}
              aria-describedby="event_bus_retry_attempts-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p id="event_bus_retry_attempts-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Max delivery retries for failing async domain event handlers.
            </p>
          </div>

          {/* Saga timeout seconds */}
          <div>
            <label htmlFor="saga_timeout_seconds" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Saga Timeout (seconds)
            </label>
            <input
              id="saga_timeout_seconds"
              name="saga_timeout_seconds"
              type="number"
              min={1}
              max={3600}
              value={formData.saga_timeout_seconds}
              onChange={handleChange}
              aria-describedby="saga_timeout_seconds-help"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p id="saga_timeout_seconds-help" className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              Maximum execution duration before rolling back a distributed saga.
            </p>
          </div>
        </div>
      </div>
    </form>
  );
}

function RestartBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800/50"
      title="Changes to this setting require a backend restart to take effect"
    >
      <Icon name="info" size={12} />
      Requires restart
    </span>
  );
}

