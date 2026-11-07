import { useState, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useSettings, useUpdateSettings } from "@/server_manager/hooks/useSettings";
import { Skeleton, ErrorState } from "@/components/ui/States";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon, type IconName } from "@/components/ui/Icon";
import { toast } from "@/stores/toastStore";
import type { SettingsResponse, SettingsUpdateRequest } from "@/types";
import { InvitationsSection } from "@/server_manager/components/InvitationsSection";
import { AccessSection } from "@/server_manager/components/AccessSection";
import { AppearanceSettingsSection } from "@/server_manager/components/AppearanceSettingsSection";
import { ApiKeysPage } from "@/server_manager/pages/ApiKeysPage";

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

type TabType = "system" | "appearance" | "invitations" | "access" | "api-keys";

interface TabDefinition {
  id: TabType;
  label: string;
  icon: IconName;
  description: string;
}

const TABS: TabDefinition[] = [
  { id: "system", label: "System Settings", icon: "settings", description: "Core engine, security, and sagas" },
  { id: "appearance", label: "Appearance & Themes", icon: "sun", description: "Skins, density, and colors" },
  { id: "invitations", label: "Invitations", icon: "users", description: "Invite tokens and access onboarding" },
  { id: "access", label: "Access Control", icon: "lock", description: "LAN vs global exposure posture" },
  { id: "api-keys", label: "API Keys", icon: "hard-drive", description: "Programmatic tokens and CI/CD auth" },
];

type CategoryId = "all" | "general" | "security" | "fault-tolerance" | "telemetry";

interface CategoryDefinition {
  id: CategoryId;
  label: string;
  sections: number[];
}

const CATEGORIES: CategoryDefinition[] = [
  { id: "all", label: "All Sections (6)", sections: [1, 2, 3, 4, 5, 6] },
  { id: "general", label: "General & Logging", sections: [1] },
  { id: "security", label: "Security & Throttling", sections: [2] },
  { id: "fault-tolerance", label: "Fault Tolerance & Sagas", sections: [3, 4] },
  { id: "telemetry", label: "Telemetry & Timeouts", sections: [5, 6] },
];

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;

function RestartBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium bg-status-warning-bg text-status-warning border border-status-warning-border shrink-0"
      title="Changes to this setting require a backend restart to take effect"
    >
      <Icon name="info" size={12} />
      Requires restart
    </span>
  );
}

interface SplitSettingRowProps {
  id: string;
  label: string;
  description: string;
  propertyKey: string;
  hasRestart?: boolean;
  children: React.ReactNode;
}

function SplitSettingRow({
  id,
  label,
  description,
  propertyKey,
  hasRestart,
  children,
}: SplitSettingRowProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_minmax(260px,360px)] items-center gap-4 px-5 py-4 border-b border-border-subtle last:border-b-0">
      <section className="space-y-1">
        <div className="flex items-center gap-2">
          <label htmlFor={id} className="text-sm font-bold text-text-primary cursor-pointer">
            {label}
          </label>
          {hasRestart && <RestartBadge />}
        </div>
        <p id={`${id}-help`} className="text-xs text-text-secondary mt-0.5 leading-relaxed">
          {description}
        </p>
        <div className="pt-0.5">
          <code className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-surface-elevated text-text-muted border border-border-subtle inline-block">
            {propertyKey}
          </code>
        </div>
      </section>

      <section className="w-full lg:max-w-[360px] lg:ml-auto flex flex-col items-start lg:items-end">
        {children}
      </section>
    </div>
  );
}

interface NumberStepperProps {
  id: string;
  name: string;
  label: string;
  value: number;
  draftValue?: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onBlur: () => void;
  onStep: (delta: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
}

function NumberStepper({
  id,
  name,
  label,
  value,
  draftValue,
  onChange,
  onBlur,
  onStep,
  min,
  max,
  step,
  unit,
}: NumberStepperProps) {
  const displayVal = draftValue !== undefined ? draftValue : String(value);

  return (
    <span className="inline-flex items-center gap-1.5 w-full justify-end">
      <button
        type="button"
        aria-label={`Decrease ${label}`}
        onClick={() => onStep(-(step || 1))}
        disabled={min !== undefined && value <= min}
        className="h-9 w-9 flex items-center justify-center rounded-lg border border-border-default bg-surface-elevated text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-30 disabled:pointer-events-none transition-all cursor-pointer font-bold text-base select-none shrink-0"
      >
        −
      </button>

      <span className="relative inline-flex items-center">
        <input
          id={id}
          name={name}
          type="number"
          min={min}
          max={max}
          step={step || "any"}
          value={displayVal}
          onChange={onChange}
          onBlur={onBlur}
          aria-describedby={`${id}-help`}
          className={`w-32 text-center px-2 py-1.5 font-mono text-sm rounded-lg border border-border-default bg-surface-page text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow ${
            unit ? "pr-8" : ""
          }`}
        />
        {unit && (
          <span className="absolute right-2.5 pointer-events-none text-[11px] font-mono text-text-muted">
            {unit}
          </span>
        )}
      </span>

      <button
        type="button"
        aria-label={`Increase ${label}`}
        onClick={() => onStep(step || 1)}
        disabled={max !== undefined && value >= max}
        className="h-9 w-9 flex items-center justify-center rounded-lg border border-border-default bg-surface-elevated text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-30 disabled:pointer-events-none transition-all cursor-pointer font-bold text-base select-none shrink-0"
      >
        +
      </button>
    </span>
  );
}

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeTab: TabType =
    rawTab && TABS.some((t) => t.id === rawTab) ? (rawTab as TabType) : "system";

  const handleTabChange = (tabId: TabType) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (tabId === "system") {
          next.delete("tab");
        } else {
          next.set("tab", tabId);
        }
        return next;
      },
      { replace: true }
    );
  };

  const { data: settings, isLoading, error } = useSettings();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-48" />
        <div className="space-y-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-2xl border border-border-default bg-surface-card p-6 space-y-4">
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
      {/* Top-Level Modern Icon-Enhanced Tab Navigation */}
      <div className="flex flex-wrap items-center gap-1 border-b border-border-default pb-px">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleTabChange(tab.id)}
              className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors cursor-pointer rounded-t-lg ${
                isActive
                  ? "border-accent-primary text-accent-primary bg-surface-card"
                  : "border-transparent text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              <Icon
                name={tab.icon}
                size={16}
                className={isActive ? "text-accent-primary" : "text-text-muted"}
              />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {activeTab === "system" ? (
        <SettingsForm settings={settings} />
      ) : activeTab === "appearance" ? (
        <AppearanceSettingsSection />
      ) : activeTab === "invitations" ? (
        <InvitationsSection />
      ) : activeTab === "access" ? (
        <AccessSection />
      ) : (
        <ApiKeysPage />
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

  // Local string drafts for numeric editing ergonomics (unblocks typing & backspace)
  const [rawDrafts, setRawDrafts] = useState<Record<string, string>>({});

  const [activeCategory, setActiveCategory] = useState<CategoryId>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccessNotice, setSaveSuccessNotice] = useState<{
    message: string;
    restartFields: string[];
  } | null>(null);

  // Set of fields that require backend service restart
  const restartRequiredSet = useMemo(() => {
    return new Set(settings.requires_restart || ["app_name", "log_level", "debug"]);
  }, [settings.requires_restart]);

  // Compute dirty count and state
  const dirtyCount = useMemo(() => {
    let count = 0;
    if (formData.app_name !== (settings.app_name ?? "onx-manager")) count++;
    if (formData.log_level !== (settings.log_level ?? "INFO")) count++;
    if (formData.debug !== Boolean(settings.debug)) count++;
    if (Number(formData.rate_limit_per_minute) !== (settings.rate_limit_per_minute ?? 60)) count++;
    if (Number(formData.idempotency_ttl_hours) !== (settings.idempotency_ttl_hours ?? 24)) count++;
    if (Number(formData.circuit_breaker_max_failures) !== (settings.circuit_breaker_max_failures ?? 5)) count++;
    if (Number(formData.circuit_breaker_timeout_seconds) !== (settings.circuit_breaker_timeout_seconds ?? 30)) count++;
    if (Number(formData.event_bus_retry_attempts) !== (settings.event_bus_retry_attempts ?? 3)) count++;
    if (Number(formData.saga_timeout_seconds) !== (settings.saga_timeout_seconds ?? 300)) count++;
    if (Number(formData.metrics_interval_seconds) !== (settings.metrics_interval_seconds ?? 0.2)) count++;
    if (Number(formData.server_startup_timeout_seconds) !== (settings.server_startup_timeout_seconds ?? 120)) count++;
    if (Number(formData.test_boot_timeout_seconds) !== (settings.test_boot_timeout_seconds ?? 120)) count++;
    return count;
  }, [formData, settings]);

  const isDirty = dirtyCount > 0;

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const { name, value, type } = e.target;
    if (type === "number") {
      setRawDrafts((prev) => ({ ...prev, [name]: value }));
      if (value.trim() !== "") {
        const num = Number(value);
        if (!isNaN(num)) {
          setFormData((prev) => ({ ...prev, [name]: num }));
        }
      }
      return;
    }

    let newValue: string | number | boolean = value;
    if (name === "debug") {
      newValue = value === "true";
    }

    setFormData((prev) => ({
      ...prev,
      [name]: newValue,
    }));
  };

  const handleNumberBlur = (name: string, min?: number, max?: number) => {
    const draft = rawDrafts[name];
    if (draft === undefined) return;
    const current = formData[name as keyof FormState] as number;
    if (draft.trim() === "" || isNaN(Number(draft))) {
      const fallback = min !== undefined ? Math.max(min, current) : current;
      setFormData((prev) => ({ ...prev, [name]: fallback }));
    } else {
      let parsed = Number(draft);
      if (min !== undefined && parsed < min) parsed = min;
      if (max !== undefined && parsed > max) parsed = max;
      setFormData((prev) => ({ ...prev, [name]: parsed }));
    }
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
  };

  const handleNumberStep = (name: string, delta: number, min?: number, max?: number) => {
    const current = (formData[name as keyof FormState] as number) ?? 0;
    let nextVal = current + delta;
    if (min !== undefined && nextVal < min) nextVal = min;
    if (max !== undefined && nextVal > max) nextVal = max;
    nextVal = Math.round(nextVal * 10) / 10;
    setFormData((prev) => ({ ...prev, [name]: nextVal }));
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
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
    setRawDrafts({});
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
      rate_limit_per_minute: Number(rawDrafts["rate_limit_per_minute"] !== undefined && rawDrafts["rate_limit_per_minute"] !== "" ? rawDrafts["rate_limit_per_minute"] : formData.rate_limit_per_minute),
      idempotency_ttl_hours: Number(rawDrafts["idempotency_ttl_hours"] !== undefined && rawDrafts["idempotency_ttl_hours"] !== "" ? rawDrafts["idempotency_ttl_hours"] : formData.idempotency_ttl_hours),
      circuit_breaker_max_failures: Number(rawDrafts["circuit_breaker_max_failures"] !== undefined && rawDrafts["circuit_breaker_max_failures"] !== "" ? rawDrafts["circuit_breaker_max_failures"] : formData.circuit_breaker_max_failures),
      circuit_breaker_timeout_seconds: Number(rawDrafts["circuit_breaker_timeout_seconds"] !== undefined && rawDrafts["circuit_breaker_timeout_seconds"] !== "" ? rawDrafts["circuit_breaker_timeout_seconds"] : formData.circuit_breaker_timeout_seconds),
      event_bus_retry_attempts: Number(rawDrafts["event_bus_retry_attempts"] !== undefined && rawDrafts["event_bus_retry_attempts"] !== "" ? rawDrafts["event_bus_retry_attempts"] : formData.event_bus_retry_attempts),
      saga_timeout_seconds: Number(rawDrafts["saga_timeout_seconds"] !== undefined && rawDrafts["saga_timeout_seconds"] !== "" ? rawDrafts["saga_timeout_seconds"] : formData.saga_timeout_seconds),
      metrics_interval_seconds: Number(rawDrafts["metrics_interval_seconds"] !== undefined && rawDrafts["metrics_interval_seconds"] !== "" ? rawDrafts["metrics_interval_seconds"] : formData.metrics_interval_seconds),
      server_startup_timeout_seconds: Number(rawDrafts["server_startup_timeout_seconds"] !== undefined && rawDrafts["server_startup_timeout_seconds"] !== "" ? rawDrafts["server_startup_timeout_seconds"] : formData.server_startup_timeout_seconds),
      test_boot_timeout_seconds: Number(rawDrafts["test_boot_timeout_seconds"] !== undefined && rawDrafts["test_boot_timeout_seconds"] !== "" ? rawDrafts["test_boot_timeout_seconds"] : formData.test_boot_timeout_seconds),
    };

    try {
      const res = await updateSettings.mutateAsync(payload);
      setRawDrafts({});
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

  // Section keyword mapping for search filtering
  const sectionMatches = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const matches: Record<number, boolean> = {
      1: true,
      2: true,
      3: true,
      4: true,
      5: true,
      6: true,
    };

    if (q) {
      matches[1] =
        "general app name log level debug info warning error version onx-manager".includes(q) ||
        formData.app_name.toLowerCase().includes(q);
      matches[2] =
        "rate limiting & security throttling idempotency ttl hours per minute request ip".includes(q);
      matches[3] =
        "circuit breaker fault tolerance max failures timeout cooldown consecutive errors recovery".includes(q);
      matches[4] =
        "event bus & sagas retry attempts timeout distributed rollback async domain".includes(q);
      matches[5] =
        "monitoring & performance cpu ram sampling interval real-time metrics frequency overhead".includes(q);
      matches[6] =
        "startup & boot timeouts server startup timeout test boot timeout containers verification".includes(q);
    }

    return matches;
  }, [searchQuery, formData.app_name]);

  const isSectionVisible = (sectionNumber: number) => {
    if (searchQuery.trim()) {
      return Boolean(sectionMatches[sectionNumber]);
    }
    const cat = CATEGORIES.find((c) => c.id === activeCategory);
    if (!cat) return true;
    return cat.sections.includes(sectionNumber);
  };

  const hasAnyVisibleSection = [1, 2, 3, 4, 5, 6].some(isSectionVisible);

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <PageHeader
        title="Settings"
        description="System parameters, rate limits, security thresholds, and saga execution settings"
        icon="settings"
        actions={
          <div className="flex items-center gap-2">
            {isDirty && (
              <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-status-warning-bg text-status-warning border border-status-warning-border">
                <span className="w-1.5 h-1.5 rounded-full bg-status-warning" />
                Unsaved changes ({dirtyCount})
              </span>
            )}
            <button
              type="button"
              onClick={handleReset}
              disabled={!isDirty || updateSettings.isPending}
              className="px-4 py-2 rounded-lg border border-border-default bg-surface-card text-sm font-medium text-text-secondary transition-colors hover:bg-surface-elevated disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              Discard Changes
            </button>
            <button
              type="submit"
              disabled={updateSettings.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
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

      {/* Category Filter & Search Bar */}
      <div className="rounded-2xl border border-border-default bg-surface-card p-4 space-y-3 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          {/* Category Filter Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            {CATEGORIES.map((cat) => {
              const isSelected = activeCategory === cat.id && !searchQuery.trim();
              return (
                <button
                  key={cat.id}
                  type="button"
                  onClick={() => {
                    setActiveCategory(cat.id);
                    setSearchQuery("");
                  }}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                    isSelected
                      ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                      : "bg-surface-page border border-border-default text-text-secondary hover:text-text-primary hover:bg-surface-elevated"
                  }`}
                >
                  {cat.label}
                </button>
              );
            })}
          </div>

          {/* Search Input */}
          <div className="relative min-w-[240px]">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-text-muted">
              <Icon name="search" size={14} />
            </div>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter system settings..."
              className="w-full pl-9 pr-8 py-1.5 rounded-lg border border-border-default bg-surface-page text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent-primary"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute inset-y-0 right-0 pr-2.5 flex items-center text-text-muted hover:text-text-primary cursor-pointer"
                title="Clear filter"
              >
                <Icon name="x" size={14} />
              </button>
            )}
          </div>
        </div>

        {isDirty && (
          <div className="sm:hidden pt-2 border-t border-border-subtle flex items-center justify-between">
            <span className="text-xs text-text-muted">Form State:</span>
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-status-warning-bg text-status-warning border border-status-warning-border">
              Unsaved changes ({dirtyCount})
            </span>
          </div>
        )}
      </div>

      {saveError && (
        <div
          role="alert"
          className="rounded-xl border border-status-danger-border bg-status-danger-bg p-4 text-sm text-status-danger flex items-start gap-3"
        >
          <Icon name="alert" size={18} className="mt-0.5 shrink-0 text-status-danger" />
          <div className="flex-1 min-w-0">
            <p className="font-medium">Failed to save settings</p>
            <p className="mt-0.5 text-xs text-status-danger opacity-90">{saveError}</p>
          </div>
        </div>
      )}

      {saveSuccessNotice && (
        <div
          role="status"
          className="rounded-xl border border-status-success-border bg-status-success-bg p-4 text-sm text-status-success flex items-start gap-3"
        >
          <Icon name="check" size={18} className="mt-0.5 shrink-0 text-status-success" />
          <div className="flex-1 min-w-0">
            <p className="font-medium">{saveSuccessNotice.message}</p>
            {saveSuccessNotice.restartFields.length > 0 && (
              <p className="mt-1 text-xs text-status-success opacity-90">
                Note: Changes to <strong>{saveSuccessNotice.restartFields.join(", ")}</strong> require a backend restart to take effect.
              </p>
            )}
          </div>
        </div>
      )}

      {!hasAnyVisibleSection && (
        <div className="rounded-2xl border border-border-default bg-surface-card p-12 text-center space-y-3">
          <Icon name="search" size={24} className="mx-auto text-text-muted" />
          <p className="text-sm font-medium text-text-primary">No settings match "{searchQuery}"</p>
          <p className="text-xs text-text-muted">Try adjusting your keyword filter or browse all sections.</p>
          <button
            type="button"
            onClick={() => {
              setSearchQuery("");
              setActiveCategory("all");
            }}
            className="px-3 py-1.5 rounded-lg border border-border-default bg-surface-elevated text-xs font-medium text-text-secondary hover:text-text-primary cursor-pointer"
          >
            Clear Filter
          </button>
        </div>
      )}

      {/* Section 1: General (Split-Row Card) */}
      {isSectionVisible(1) && (
        <div className="rounded-2xl border border-border-default bg-surface-card shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-surface-elevated border border-border-subtle text-text-secondary">
              <Icon name="settings" size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-text-primary">General</h3>
              <p className="text-xs text-text-muted mt-0.5">
                Core application identity and runtime logging configuration.
              </p>
              {settings.version ? (
                <p className="mt-2 inline-flex items-center gap-2 rounded-lg bg-surface-elevated border border-border-default px-3 py-1.5 text-xs text-text-secondary">
                  <Icon name="info" size={14} className="text-text-muted" />
                  {settings.app_name ?? "onx-manager"} {settings.version}
                </p>
              ) : null}
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* App Name */}
            <SplitSettingRow
              id="app_name"
              label="App Name"
              description="Display name for this onx-manager instance."
              propertyKey="app_name"
              hasRestart={restartRequiredSet.has("app_name")}
            >
              <input
                id="app_name"
                name="app_name"
                type="text"
                value={formData.app_name}
                onChange={handleChange}
                aria-describedby="app_name-help"
                className="w-full px-3.5 py-2 rounded-xl border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
              />
            </SplitSettingRow>

            {/* Log Level */}
            <SplitSettingRow
              id="log_level"
              label="Log Level"
              description="Minimum severity level for application logs."
              propertyKey="log_level"
              hasRestart={restartRequiredSet.has("log_level")}
            >
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-flex p-1 rounded-xl bg-surface-elevated border border-border-default gap-1">
                  {LOG_LEVELS.map((lvl) => {
                    const isSelected = formData.log_level === lvl;
                    return (
                      <button
                        key={lvl}
                        type="button"
                        onClick={() => setFormData((prev) => ({ ...prev, log_level: lvl }))}
                        className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                          isSelected
                            ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                            : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                        }`}
                      >
                        {lvl}
                      </button>
                    );
                  })}
                </span>
                <select
                  id="log_level"
                  name="log_level"
                  value={formData.log_level}
                  onChange={handleChange}
                  aria-describedby="log_level-help"
                  className="sr-only"
                >
                  {LOG_LEVELS.map((lvl) => (
                    <option key={lvl} value={lvl}>
                      {lvl}
                    </option>
                  ))}
                </select>
              </span>
            </SplitSettingRow>

            {/* Debug Mode */}
            <SplitSettingRow
              id="debug"
              label="Debug Mode"
              description="Enables verbose logging and detailed error stack traces."
              propertyKey="debug"
              hasRestart={restartRequiredSet.has("debug")}
            >
              <span className="inline-flex items-center justify-end gap-3 w-full">
                <span
                  className={`text-[10px] font-bold font-mono uppercase tracking-wider px-2 py-0.5 rounded-full border transition-colors ${
                    formData.debug
                      ? "bg-status-success-bg text-status-success border-status-success-border"
                      : "bg-surface-elevated text-text-muted border-border-subtle"
                  }`}
                >
                  {formData.debug ? "ENABLED" : "DISABLED"}
                </span>

                <label className="relative inline-flex items-center cursor-pointer select-none">
                  <input
                    type="checkbox"
                    role="switch"
                    aria-label="Debug Mode Toggle"
                    checked={formData.debug}
                    onChange={(e) => setFormData((prev) => ({ ...prev, debug: e.target.checked }))}
                    className="sr-only peer"
                  />
                  <div
                    className={`w-11 h-6 rounded-full transition-colors duration-200 ease-in-out ${
                      formData.debug ? "bg-accent-primary" : "bg-border-strong"
                    }`}
                  >
                    <div
                      className={`w-5 h-5 bg-accent-contrast-text rounded-full shadow-md transform transition-transform duration-200 ease-in-out mt-0.5 ${
                        formData.debug ? "translate-x-5.5 ml-0.5" : "translate-x-0.5"
                      }`}
                    />
                  </div>
                </label>

                {/* Synchronized accessible select for test compatibility */}
                <select
                  id="debug"
                  name="debug"
                  value={formData.debug ? "true" : "false"}
                  onChange={handleChange}
                  aria-describedby="debug-help"
                  className="sr-only"
                >
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              </span>
            </SplitSettingRow>
          </div>
        </div>
      )}

      {/* Section 2: Rate Limiting & Security (Split-Row Card) */}
      {isSectionVisible(2) && (
        <div className="rounded-2xl border border-border-default bg-surface-card shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-surface-elevated border border-border-subtle text-text-secondary">
              <Icon name="lock" size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-text-primary">Rate Limiting & Security</h3>
              <p className="text-xs text-text-muted mt-0.5">
                API request throttling and idempotency token retention policies.
              </p>
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* Rate Limit per minute */}
            <SplitSettingRow
              id="rate_limit_per_minute"
              label="Rate Limit (per minute)"
              description="Max API requests per minute per IP address."
              propertyKey="rate_limit_per_minute"
            >
              <NumberStepper
                id="rate_limit_per_minute"
                name="rate_limit_per_minute"
                label="Rate Limit (per minute)"
                value={formData.rate_limit_per_minute}
                draftValue={rawDrafts["rate_limit_per_minute"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("rate_limit_per_minute", 1, 10000)}
                onStep={(delta) => handleNumberStep("rate_limit_per_minute", delta, 1, 10000)}
                min={1}
                max={10000}
              />
            </SplitSettingRow>

            {/* Idempotency TTL */}
            <SplitSettingRow
              id="idempotency_ttl_hours"
              label="Idempotency TTL (hours)"
              description="Retention period in hours for request idempotency execution keys."
              propertyKey="idempotency_ttl_hours"
            >
              <NumberStepper
                id="idempotency_ttl_hours"
                name="idempotency_ttl_hours"
                label="Idempotency TTL (hours)"
                value={formData.idempotency_ttl_hours}
                draftValue={rawDrafts["idempotency_ttl_hours"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("idempotency_ttl_hours", 1, 720)}
                onStep={(delta) => handleNumberStep("idempotency_ttl_hours", delta, 1, 720)}
                min={1}
                max={720}
                unit="hrs"
              />
            </SplitSettingRow>
          </div>
        </div>
      )}

      {/* Section 3: Circuit Breaker (Split-Row Card) */}
      {isSectionVisible(3) && (
        <div className="rounded-2xl border border-border-default bg-surface-card shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-surface-elevated border border-border-subtle text-text-secondary">
              <Icon name="alert" size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-text-primary">Circuit Breaker</h3>
              <p className="text-xs text-text-muted mt-0.5">
                Fault tolerance thresholds and automated service recovery timings.
              </p>
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* Max Failures */}
            <SplitSettingRow
              id="circuit_breaker_max_failures"
              label="Max Failures"
              description="Consecutive errors before opening the circuit breaker."
              propertyKey="circuit_breaker_max_failures"
            >
              <NumberStepper
                id="circuit_breaker_max_failures"
                name="circuit_breaker_max_failures"
                label="Max Failures"
                value={formData.circuit_breaker_max_failures}
                draftValue={rawDrafts["circuit_breaker_max_failures"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("circuit_breaker_max_failures", 1, 100)}
                onStep={(delta) => handleNumberStep("circuit_breaker_max_failures", delta, 1, 100)}
                min={1}
                max={100}
              />
            </SplitSettingRow>

            {/* Timeout seconds */}
            <SplitSettingRow
              id="circuit_breaker_timeout_seconds"
              label="Timeout (seconds)"
              description="Cooldown duration in seconds before attempting half-open recovery."
              propertyKey="circuit_breaker_timeout_seconds"
            >
              <NumberStepper
                id="circuit_breaker_timeout_seconds"
                name="circuit_breaker_timeout_seconds"
                label="Timeout (seconds)"
                value={formData.circuit_breaker_timeout_seconds}
                draftValue={rawDrafts["circuit_breaker_timeout_seconds"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("circuit_breaker_timeout_seconds", 1, 3600)}
                onStep={(delta) => handleNumberStep("circuit_breaker_timeout_seconds", delta, 1, 3600)}
                min={1}
                max={3600}
                unit="sec"
              />
            </SplitSettingRow>
          </div>
        </div>
      )}

      {/* Section 4: Event Bus & Sagas (Split-Row Card) */}
      {isSectionVisible(4) && (
        <div className="rounded-2xl border border-border-default bg-surface-card shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-surface-elevated border border-border-subtle text-text-secondary">
              <Icon name="version-branch" size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-text-primary">Event Bus & Sagas</h3>
              <p className="text-xs text-text-muted mt-0.5">
                Asynchronous event dispatch retry policies and multi-step saga execution timeouts.
              </p>
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* Event bus retry attempts */}
            <SplitSettingRow
              id="event_bus_retry_attempts"
              label="Event Bus Retry Attempts"
              description="Max delivery retries for failing async domain event handlers."
              propertyKey="event_bus_retry_attempts"
            >
              <NumberStepper
                id="event_bus_retry_attempts"
                name="event_bus_retry_attempts"
                label="Event Bus Retry Attempts"
                value={formData.event_bus_retry_attempts}
                draftValue={rawDrafts["event_bus_retry_attempts"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("event_bus_retry_attempts", 0, 10)}
                onStep={(delta) => handleNumberStep("event_bus_retry_attempts", delta, 0, 10)}
                min={0}
                max={10}
              />
            </SplitSettingRow>

            {/* Saga timeout seconds */}
            <SplitSettingRow
              id="saga_timeout_seconds"
              label="Saga Timeout (seconds)"
              description="Maximum execution duration before rolling back a distributed saga."
              propertyKey="saga_timeout_seconds"
            >
              <NumberStepper
                id="saga_timeout_seconds"
                name="saga_timeout_seconds"
                label="Saga Timeout (seconds)"
                value={formData.saga_timeout_seconds}
                draftValue={rawDrafts["saga_timeout_seconds"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("saga_timeout_seconds", 1, 3600)}
                onStep={(delta) => handleNumberStep("saga_timeout_seconds", delta, 1, 3600)}
                min={1}
                max={3600}
                unit="sec"
              />
            </SplitSettingRow>
          </div>
        </div>
      )}

      {/* Section 5: Monitoring & Performance (Split-Row Card) */}
      {isSectionVisible(5) && (
        <div className="rounded-2xl border border-border-default bg-surface-card shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-surface-elevated border border-border-subtle text-text-secondary">
              <Icon name="activity" size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-text-primary">Monitoring & Performance</h3>
              <p className="text-xs text-text-muted mt-0.5">
                Real-time server metrics collection rate and CPU/RAM sampling interval.
              </p>
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* Metrics interval seconds */}
            <SplitSettingRow
              id="metrics_interval_seconds"
              label="CPU & Metrics Sampling Interval (seconds)"
              description="Frequency in seconds for sampling CPU, RAM, and streaming real-time metrics (e.g. 0.2s for live real-time, 1.0s or 5.0s for reduced CPU overhead)."
              propertyKey="metrics_interval_seconds"
            >
              <NumberStepper
                id="metrics_interval_seconds"
                name="metrics_interval_seconds"
                label="CPU & Metrics Sampling Interval (seconds)"
                value={formData.metrics_interval_seconds}
                draftValue={rawDrafts["metrics_interval_seconds"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("metrics_interval_seconds", 0.1, 60)}
                onStep={(delta) => handleNumberStep("metrics_interval_seconds", delta, 0.1, 60)}
                min={0.1}
                max={60}
                step={0.1}
                unit="sec"
              />
            </SplitSettingRow>
          </div>
        </div>
      )}

      {/* Section 6: Startup & Boot Timeouts (Split-Row Card) */}
      {isSectionVisible(6) && (
        <div className="rounded-2xl border border-border-default bg-surface-card shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-surface-elevated border border-border-subtle text-text-secondary">
              <Icon name="clock" size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-text-primary">Startup & Boot Timeouts</h3>
              <p className="text-xs text-text-muted mt-0.5">
                Default boot-gate timeouts for regular servers and isolated test containers (30–1800s). No server restart required.
              </p>
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* Server Startup Timeout */}
            <SplitSettingRow
              id="server_startup_timeout_seconds"
              label="Server Startup Timeout (seconds)"
              description="Global timeout before starting monitor warns on slow server boot. Can be overridden per-server."
              propertyKey="server_startup_timeout_seconds"
            >
              <NumberStepper
                id="server_startup_timeout_seconds"
                name="server_startup_timeout_seconds"
                label="Server Startup Timeout (seconds)"
                value={formData.server_startup_timeout_seconds}
                draftValue={rawDrafts["server_startup_timeout_seconds"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("server_startup_timeout_seconds", 30, 1800)}
                onStep={(delta) => handleNumberStep("server_startup_timeout_seconds", delta, 30, 1800)}
                min={30}
                max={1800}
                unit="sec"
              />
            </SplitSettingRow>

            {/* Test Boot Timeout */}
            <SplitSettingRow
              id="test_boot_timeout_seconds"
              label="Test Boot Timeout (seconds)"
              description="Global timeout before isolated test containers fail boot verification."
              propertyKey="test_boot_timeout_seconds"
            >
              <NumberStepper
                id="test_boot_timeout_seconds"
                name="test_boot_timeout_seconds"
                label="Test Boot Timeout (seconds)"
                value={formData.test_boot_timeout_seconds}
                draftValue={rawDrafts["test_boot_timeout_seconds"]}
                onChange={handleChange}
                onBlur={() => handleNumberBlur("test_boot_timeout_seconds", 30, 1800)}
                onStep={(delta) => handleNumberStep("test_boot_timeout_seconds", delta, 30, 1800)}
                min={30}
                max={1800}
                unit="sec"
              />
            </SplitSettingRow>
          </div>
        </div>
      )}
    </form>
  );
}
