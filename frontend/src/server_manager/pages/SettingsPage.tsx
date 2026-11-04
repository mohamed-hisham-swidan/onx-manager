import { useState, useMemo } from "react";
import { useSettings, useUpdateSettings } from "@/server_manager/hooks/useSettings";
import { Skeleton, ErrorState } from "@/components/ui/States";
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
  metrics_interval_seconds: number;
  server_startup_timeout_seconds: number;
  test_boot_timeout_seconds: number;
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
            <div key={i} className="rounded-xl border border-border-default bg-surface-panel p-6 space-y-4">
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
      <div className="flex border-b border-border-default">
        <button
          type="button"
          onClick={() => setActiveTab("system")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer ${
            activeTab === "system"
              ? "border-accent-primary text-accent-primary"
              : "border-transparent text-text-muted hover:text-text-primary"
          }`}
        >
          System Settings
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("invitations")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer ${
            activeTab === "invitations"
              ? "border-accent-primary text-accent-primary"
              : "border-transparent text-text-muted hover:text-text-primary"
          }`}
        >
          Invitations
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("access")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer ${
            activeTab === "access"
              ? "border-accent-primary text-accent-primary"
              : "border-transparent text-text-muted hover:text-text-primary"
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
    app_name: settings.app_name ?? "onx-manager",
    log_level: settings.log_level ?? "INFO",
    debug: Boolean(settings.debug),
    rate_limit_per_minute: settings.rate_limit_per_minute ?? 60,
    idempotency_ttl_hours: settings.idempotency_ttl_hours ?? 24,
    circuit_breaker_max_failures: settings.circuit_breaker_max_failures ?? 5,
    circuit_breaker_timeout_seconds: settings.circuit_breaker_timeout_seconds ?? 30,
    event_bus_retry_attempts: settings.event_bus_retry_attempts ?? 3,
    saga_timeout_seconds: settings.saga_timeout_seconds ?? 300,
    metrics_interval_seconds: settings.metrics_interval_seconds ?? 0.2,
    server_startup_timeout_seconds: settings.server_startup_timeout_seconds ?? 120,
    test_boot_timeout_seconds: settings.test_boot_timeout_seconds ?? 120,
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
      Number(formData.saga_timeout_seconds) !== settings.saga_timeout_seconds ||
      Number(formData.metrics_interval_seconds) !== (settings.metrics_interval_seconds ?? 0.2) ||
      Number(formData.server_startup_timeout_seconds) !== (settings.server_startup_timeout_seconds ?? 120) ||
      Number(formData.test_boot_timeout_seconds) !== (settings.test_boot_timeout_seconds ?? 120)
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
      app_name: settings.app_name ?? "onx-manager",
      log_level: settings.log_level ?? "INFO",
      debug: Boolean(settings.debug),
      rate_limit_per_minute: settings.rate_limit_per_minute ?? 60,
      idempotency_ttl_hours: settings.idempotency_ttl_hours ?? 24,
      circuit_breaker_max_failures: settings.circuit_breaker_max_failures ?? 5,
      circuit_breaker_timeout_seconds: settings.circuit_breaker_timeout_seconds ?? 30,
      event_bus_retry_attempts: settings.event_bus_retry_attempts ?? 3,
      saga_timeout_seconds: settings.saga_timeout_seconds ?? 300,
      metrics_interval_seconds: settings.metrics_interval_seconds ?? 0.2,
      server_startup_timeout_seconds: settings.server_startup_timeout_seconds ?? 120,
      test_boot_timeout_seconds: settings.test_boot_timeout_seconds ?? 120,
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
      metrics_interval_seconds: Number(formData.metrics_interval_seconds),
      server_startup_timeout_seconds: Number(formData.server_startup_timeout_seconds),
      test_boot_timeout_seconds: Number(formData.test_boot_timeout_seconds),
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
              className="px-4 py-2 rounded-lg border border-border-default bg-surface-panel text-sm font-medium text-text-secondary transition-colors hover:bg-surface-elevated disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Discard Changes
            </button>
            <button
              type="submit"
              disabled={updateSettings.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
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
      <div className="rounded-xl border border-border-default bg-surface-panel p-6 shadow-xs">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-text-primary">General</h3>
          <p className="text-xs text-text-muted">
            Core application identity and runtime logging configuration.
          </p>
          {settings.version ? (
            <p className="mt-2 inline-flex items-center gap-2 rounded-lg bg-surface-elevated border border-border-default px-3 py-1.5 text-xs text-text-secondary">
              <Icon name="info" size={14} className="text-text-muted" />
              {settings.app_name ?? "onx-manager"} {settings.version}
            </p>
          ) : null}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* App Name */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="app_name" className="block text-sm font-medium text-text-secondary">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="app_name-help" className="mt-1 text-xs text-text-muted">
              Display name for this onx-manager instance.
            </p>
          </div>

          {/* Log Level */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="log_level" className="block text-sm font-medium text-text-secondary">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            >
              <option value="DEBUG">DEBUG</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
            </select>
            <p id="log_level-help" className="mt-1 text-xs text-text-muted">
              Minimum severity level for application logs.
            </p>
          </div>

          {/* Debug Mode */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor="debug" className="block text-sm font-medium text-text-secondary">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            >
              <option value="true">Enabled</option>
              <option value="false">Disabled</option>
            </select>
            <p id="debug-help" className="mt-1 text-xs text-text-muted">
              Enables verbose logging and detailed error stack traces.
            </p>
          </div>
        </div>
      </div>

      {/* Section 2: Rate Limiting & Security */}
      <div className="rounded-xl border border-border-default bg-surface-panel p-6 shadow-xs">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-text-primary">Rate Limiting & Security</h3>
          <p className="text-xs text-text-muted">
            API request throttling and idempotency token retention policies.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Rate Limit per minute */}
          <div>
            <label htmlFor="rate_limit_per_minute" className="block text-sm font-medium text-text-secondary mb-1.5">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="rate_limit_per_minute-help" className="mt-1 text-xs text-text-muted">
              Max API requests per minute per IP address.
            </p>
          </div>

          {/* Idempotency TTL */}
          <div>
            <label htmlFor="idempotency_ttl_hours" className="block text-sm font-medium text-text-secondary mb-1.5">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="idempotency_ttl_hours-help" className="mt-1 text-xs text-text-muted">
              Retention period in hours for request idempotency execution keys.
            </p>
          </div>
        </div>
      </div>

      {/* Section 3: Circuit Breaker */}
      <div className="rounded-xl border border-border-default bg-surface-panel p-6 shadow-xs">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-text-primary">Circuit Breaker</h3>
          <p className="text-xs text-text-muted">
            Fault tolerance thresholds and automated service recovery timings.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Max Failures */}
          <div>
            <label htmlFor="circuit_breaker_max_failures" className="block text-sm font-medium text-text-secondary mb-1.5">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="circuit_breaker_max_failures-help" className="mt-1 text-xs text-text-muted">
              Consecutive errors before opening the circuit breaker.
            </p>
          </div>

          {/* Timeout seconds */}
          <div>
            <label htmlFor="circuit_breaker_timeout_seconds" className="block text-sm font-medium text-text-secondary mb-1.5">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="circuit_breaker_timeout_seconds-help" className="mt-1 text-xs text-text-muted">
              Cooldown duration in seconds before attempting half-open recovery.
            </p>
          </div>
        </div>
      </div>

      {/* Section 4: Event Bus & Sagas */}
      <div className="rounded-xl border border-border-default bg-surface-panel p-6 shadow-xs">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-text-primary">Event Bus & Sagas</h3>
          <p className="text-xs text-text-muted">
            Asynchronous event dispatch retry policies and multi-step saga execution timeouts.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Event bus retry attempts */}
          <div>
            <label htmlFor="event_bus_retry_attempts" className="block text-sm font-medium text-text-secondary mb-1.5">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="event_bus_retry_attempts-help" className="mt-1 text-xs text-text-muted">
              Max delivery retries for failing async domain event handlers.
            </p>
          </div>

          {/* Saga timeout seconds */}
          <div>
            <label htmlFor="saga_timeout_seconds" className="block text-sm font-medium text-text-secondary mb-1.5">
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
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="saga_timeout_seconds-help" className="mt-1 text-xs text-text-muted">
              Maximum execution duration before rolling back a distributed saga.
            </p>
          </div>
        </div>
      </div>

      {/* Section 5: Monitoring & Performance */}
      <div className="rounded-xl border border-border-default bg-surface-panel p-6 shadow-xs">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-text-primary">Monitoring & Performance</h3>
          <p className="text-xs text-text-muted">
            Real-time server metrics collection rate and CPU/RAM sampling interval.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Metrics interval seconds */}
          <div>
            <label htmlFor="metrics_interval_seconds" className="block text-sm font-medium text-text-secondary mb-1.5">
              CPU & Metrics Sampling Interval (seconds)
            </label>
            <input
              id="metrics_interval_seconds"
              name="metrics_interval_seconds"
              type="number"
              min={0.1}
              max={60}
              step={0.1}
              value={formData.metrics_interval_seconds}
              onChange={handleChange}
              aria-describedby="metrics_interval_seconds-help"
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="metrics_interval_seconds-help" className="mt-1 text-xs text-text-muted">
              Frequency in seconds for sampling CPU, RAM, and streaming real-time metrics (e.g. 0.2s for live real-time, 1.0s or 5.0s for reduced CPU overhead).
            </p>
          </div>
        </div>
      </div>

      {/* Section 6: Startup & Boot Timeouts */}
      <div className="rounded-xl border border-border-default bg-surface-panel p-6 shadow-xs">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-text-primary">Startup & Boot Timeouts</h3>
          <p className="text-xs text-text-muted">
            Default boot-gate timeouts for regular servers and isolated test containers (30–1800s). No server restart required.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label htmlFor="server_startup_timeout_seconds" className="block text-sm font-medium text-text-secondary mb-1.5">
              Server Startup Timeout (seconds)
            </label>
            <input
              id="server_startup_timeout_seconds"
              name="server_startup_timeout_seconds"
              type="number"
              min={30}
              max={1800}
              value={formData.server_startup_timeout_seconds}
              onChange={handleChange}
              aria-describedby="server_startup_timeout_seconds-help"
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="server_startup_timeout_seconds-help" className="mt-1 text-xs text-text-muted">
              Global timeout before starting monitor warns on slow server boot. Can be overridden per-server.
            </p>
          </div>

          <div>
            <label htmlFor="test_boot_timeout_seconds" className="block text-sm font-medium text-text-secondary mb-1.5">
              Test Boot Timeout (seconds)
            </label>
            <input
              id="test_boot_timeout_seconds"
              name="test_boot_timeout_seconds"
              type="number"
              min={30}
              max={1800}
              value={formData.test_boot_timeout_seconds}
              onChange={handleChange}
              aria-describedby="test_boot_timeout_seconds-help"
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-canvas text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            <p id="test_boot_timeout_seconds-help" className="mt-1 text-xs text-text-muted">
              Global timeout before isolated test containers fail boot verification.
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
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20"
      title="Changes to this setting require a backend restart to take effect"
    >
      <Icon name="info" size={12} />
      Requires restart
    </span>
  );
}

