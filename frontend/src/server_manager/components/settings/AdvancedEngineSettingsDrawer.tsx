import React, { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import { Banner } from "@/components/ui/Banner";
import { Modal } from "@/components/ui/Modal";
import { useUpdateSettings } from "@/server_manager/hooks/useSettings";
import { toast } from "@/stores/toastStore";
import type { SettingsResponse } from "@/types";
import {
  ENGINE_SETTING_KEYS,
  SETTINGS_BOUNDS,
  clampNumericValue,
  computeDirtyPatch,
  formStateFromSettings,
  normalizeFormWithDrafts,
  resolveCanonicalDefaults,
  type NumericSettingKey,
  type SystemFormState,
} from "./settingsModel";
import { NumberStepper, SettingRow } from "./settingsUtils";

type EngineSubTab = "all" | "monitoring" | "security" | "resilience";

const SUB_TABS: { id: EngineSubTab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "monitoring", label: "Monitoring & Logs" },
  { id: "security", label: "Security" },
  { id: "resilience", label: "Resilience" },
];

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;

export interface AdvancedEngineSettingsDrawerProps {
  open: boolean;
  onClose: () => void;
  settings: SettingsResponse;
  canWrite: boolean;
}

export function AdvancedEngineSettingsDrawer({
  open,
  onClose,
  settings,
  canWrite,
}: AdvancedEngineSettingsDrawerProps) {
  const updateSettings = useUpdateSettings();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const baseline = useMemo(() => formStateFromSettings(settings), [settings]);
  const defaults = useMemo(() => resolveCanonicalDefaults(settings), [settings]);
  const restartSet = useMemo(
    () => new Set(settings.requires_restart ?? ["log_level", "debug"]),
    [settings.requires_restart],
  );

  const [syncedSettings, setSyncedSettings] = useState(settings);
  const [wasOpen, setWasOpen] = useState(open);
  const [formData, setFormData] = useState<SystemFormState>(baseline);
  const [rawDrafts, setRawDrafts] = useState<Record<string, string>>({});
  const [subTab, setSubTab] = useState<EngineSubTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDiscardOpen, setConfirmDiscardOpen] = useState(false);
  const [confirmResetOpen, setConfirmResetOpen] = useState(false);

  if (syncedSettings !== settings) {
    setSyncedSettings(settings);
    setFormData(baseline);
    setRawDrafts({});
    setSaveError(null);
  }

  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) {
      setFormData(baseline);
      setRawDrafts({});
      setConfirmDiscardOpen(false);
      setConfirmResetOpen(false);
      setSaveError(null);
    }
  }

  const normalizedCurrent = useMemo(
    () => normalizeFormWithDrafts(formData, rawDrafts, ENGINE_SETTING_KEYS),
    [formData, rawDrafts],
  );

  const dirtyPatch = useMemo(
    () => computeDirtyPatch(normalizedCurrent, baseline, ENGINE_SETTING_KEYS),
    [normalizedCurrent, baseline],
  );

  const dirtyCount = Object.keys(dirtyPatch).length;
  const isDirty = dirtyCount > 0;

  const requestClose = () => {
    if (updateSettings.isPending) return;
    if (isDirty) {
      setConfirmDiscardOpen(true);
      return;
    }
    onClose();
  };

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        if (confirmDiscardOpen) {
          setConfirmDiscardOpen(false);
        } else if (confirmResetOpen) {
          setConfirmResetOpen(false);
        } else if (isDirty) {
          setConfirmDiscardOpen(true);
        } else if (!updateSettings.isPending) {
          onClose();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, isDirty, confirmDiscardOpen, confirmResetOpen, updateSettings.isPending, onClose]);

  const handleNumberChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setSaveError(null);
    setRawDrafts((prev) => ({ ...prev, [name]: value }));
    if (value.trim() !== "") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        setFormData((prev) => ({ ...prev, [name]: parsed }));
      }
    }
  };

  const handleNumberBlur = (key: NumericSettingKey) => {
    const draft = rawDrafts[key];
    if (draft === undefined) return;
    const clamped = clampNumericValue(key, draft.trim() === "" ? formData[key] : draft);
    if (clamped !== null) {
      setFormData((prev) => ({ ...prev, [key]: clamped }));
    }
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleNumberStep = (key: NumericSettingKey, delta: number) => {
    setSaveError(null);
    const current = Number(rawDrafts[key] !== undefined && rawDrafts[key] !== "" ? rawDrafts[key] : formData[key]);
    const clamped = clampNumericValue(key, (Number.isFinite(current) ? current : SETTINGS_BOUNDS[key].min) + delta);
    if (clamped !== null) {
      setFormData((prev) => ({ ...prev, [key]: clamped }));
    }
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canWrite) return;
    setSaveError(null);

    const clamped = normalizeFormWithDrafts(formData, rawDrafts, ENGINE_SETTING_KEYS);
    setFormData(clamped);
    setRawDrafts({});

    const patch = computeDirtyPatch(clamped, baseline, ENGINE_SETTING_KEYS);
    if (Object.keys(patch).length === 0) return;

    try {
      const res = await updateSettings.mutateAsync(patch);
      if (res.settings) {
        setFormData(formStateFromSettings(res.settings));
      }
      const restartNote =
        res.requires_restart && res.requires_restart.length > 0
          ? `Restart required for: ${res.requires_restart.join(", ")}.`
          : "Changes applied immediately.";
      toast("success", "Engine settings saved", restartNote);
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save engine settings";
      setSaveError(msg);
      toast("error", "Failed to save engine settings", msg);
    }
  };

  const handleResetDefaults = async () => {
    if (!canWrite) return;
    setSaveError(null);
    const patch = computeDirtyPatch(defaults, baseline, ENGINE_SETTING_KEYS);
    if (Object.keys(patch).length === 0) {
      setFormData(defaults);
      setRawDrafts({});
      setConfirmResetOpen(false);
      toast("info", "Already at defaults", "All engine settings match factory defaults.");
      return;
    }
    try {
      const res = await updateSettings.mutateAsync(patch);
      if (res.settings) {
        setFormData(formStateFromSettings(res.settings));
      } else {
        setFormData(defaults);
      }
      setRawDrafts({});
      setConfirmResetOpen(false);
      toast("success", "Engine defaults restored", "Engine settings were reset to factory defaults.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to reset engine defaults";
      setSaveError(msg);
      toast("error", "Reset failed", msg);
    }
  };

  const q = searchQuery.trim().toLowerCase();
  const matchesQuery = (text: string) => !q || text.toLowerCase().includes(q);
  const showGroup = (group: Exclude<EngineSubTab, "all">, keywords: string) => {
    if (q) return matchesQuery(keywords);
    return subTab === "all" || subTab === group;
  };

  const showMonitoring = showGroup(
    "monitoring",
    "monitoring diagnostics metrics polling interval test sandbox boot timeout log level debug verbose",
  );
  const showSecurity = showGroup(
    "security",
    "security throttling api rate limit requests minute duplicate action window idempotency ttl",
  );
  const showResilience = showGroup(
    "resilience",
    "resilience background jobs circuit breaker failure limit recovery cooldown task retry event bus timeout saga",
  );

  return (
    <Modal
      open={open}
      onClose={requestClose}
      variant="drawer"
      size="xl"
      padded={false}
      showCloseButton={false}
      closeOnBackdrop={true}
      closeOnEscape={false}
      ariaLabel="Advanced Engine Settings"
      initialFocusRef={searchInputRef}
      className="h-[92dvh] self-end md:self-stretch md:h-full rounded-t-2xl md:rounded-none border-t md:border-t-0 md:border-l overflow-hidden"
    >
      {/* Header */}
        <div className="px-6 py-4 border-b border-border-subtle space-y-3 shrink-0">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-text-primary">
                Advanced Engine Settings
              </h2>
              <p className="text-xs text-text-muted mt-0.5">
                Tune polling, throttling, resilience, and backend logs.
              </p>
            </div>
            <button
              type="button"
              onClick={requestClose}
              aria-label="Close engine settings"
              className="rounded-lg p-1.5 text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
            >
              <Icon name="x" size={18} />
            </button>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center gap-2.5">
            <div className="relative flex-1">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-text-muted">
                <Icon name="search" size={14} />
              </div>
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Filter engine settings..."
                className="w-full pl-9 pr-8 py-1.5 rounded-lg border border-border-subtle bg-surface-page text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  aria-label="Clear filter"
                  className="absolute inset-y-0 right-0 pr-2.5 flex items-center text-text-muted hover:text-text-primary cursor-pointer"
                >
                  <Icon name="x" size={13} />
                </button>
              )}
            </div>

            <div className="flex items-center gap-1 overflow-x-auto pb-0.5">
              {SUB_TABS.map((tab) => {
                const selected = !q && subTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => {
                      setSubTab(tab.id);
                      setSearchQuery("");
                    }}
                    className={`px-2.5 py-1.5 rounded-lg text-xs whitespace-nowrap transition-colors cursor-pointer ${
                      selected
                        ? "bg-accent-primary/14 text-text-primary font-semibold"
                        : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                    }`}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Body + Sticky Footer inside form so Enter & Save submit reliably */}
        <form id="advanced-engine-form" noValidate onSubmit={handleSubmit} className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          <div className="rounded-lg bg-surface-muted/70 border border-border-subtle px-3.5 py-2 text-xs text-text-secondary flex items-center gap-2">
            <Icon name="info" size={14} className="text-text-muted shrink-0" />
            <span>Defaults are tuned for stability. Change only if troubleshooting or scaling.</span>
          </div>

          {saveError && (
            <Banner variant="danger" title="Save failed" description={saveError} />
          )}

          {confirmDiscardOpen && (
            <div
              role="alert"
              className="rounded-xl border border-status-warning-border bg-status-warning-bg p-3.5 flex flex-wrap items-center justify-between gap-3"
            >
              <span className="text-xs font-medium text-text-primary">
                Discard {dirtyCount} unsaved engine change{dirtyCount === 1 ? "" : "s"}?
              </span>
              <div className="flex items-center gap-2">
                <Button type="button" size="xs" variant="ghost" onClick={() => setConfirmDiscardOpen(false)}>
                  Keep Editing
                </Button>
                <Button
                  type="button"
                  size="xs"
                  variant="danger"
                  onClick={() => {
                    setFormData(baseline);
                    setRawDrafts({});
                    setConfirmDiscardOpen(false);
                    onClose();
                  }}
                >
                  Discard &amp; Close
                </Button>
              </div>
            </div>
          )}

          {confirmResetOpen && (
            <div
              role="alert"
              className="rounded-xl border border-status-warning-border bg-status-warning-bg p-3.5 flex flex-wrap items-center justify-between gap-3"
            >
              <span className="text-xs font-medium text-text-primary">
                Reset all 10 engine settings to factory defaults?
              </span>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="xs"
                  variant="ghost"
                  disabled={updateSettings.isPending}
                  onClick={() => setConfirmResetOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  size="xs"
                  variant="primary"
                  loading={updateSettings.isPending}
                  onClick={handleResetDefaults}
                >
                  Confirm Reset
                </Button>
              </div>
            </div>
          )}

          {!showMonitoring && !showSecurity && !showResilience && (
            <div className="rounded-xl border border-border-subtle bg-surface-page/50 p-8 text-center space-y-2">
              <p className="text-sm font-medium text-text-primary">No matching engine settings</p>
              <p className="text-xs text-text-muted">Try a different keyword or clear the filter.</p>
            </div>
          )}

          {showMonitoring && (
            <section className="rounded-xl border border-border-subtle bg-surface-page/50 overflow-hidden">
              <div className="px-4 py-2.5 border-b border-border-subtle bg-surface-muted/40">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  Monitoring &amp; Diagnostics
                </h3>
              </div>
              <div>
                <SettingRow
                  id="metrics_interval_seconds"
                  label="Metrics Polling Interval"
                  description="How often CPU and RAM stats refresh."
                  propertyKey="metrics_interval_seconds"
                >
                  <NumberStepper
                    id="metrics_interval_seconds"
                    name="metrics_interval_seconds"
                    label="Metrics Polling Interval"
                    value={formData.metrics_interval_seconds}
                    draftValue={rawDrafts["metrics_interval_seconds"]}
                    onChange={handleNumberChange}
                    onBlur={() => handleNumberBlur("metrics_interval_seconds")}
                    onStep={(delta) => handleNumberStep("metrics_interval_seconds", delta)}
                    min={SETTINGS_BOUNDS.metrics_interval_seconds.min}
                    max={SETTINGS_BOUNDS.metrics_interval_seconds.max}
                    step={0.1}
                    unit="sec"
                    disabled={!canWrite}
                  />
                </SettingRow>

                <SettingRow
                  id="test_boot_timeout_seconds"
                  label="Test Sandbox Boot Timeout"
                  description="Max wait for isolated test containers."
                  propertyKey="test_boot_timeout_seconds"
                >
                  <NumberStepper
                    id="test_boot_timeout_seconds"
                    name="test_boot_timeout_seconds"
                    label="Test Sandbox Boot Timeout"
                    value={formData.test_boot_timeout_seconds}
                    draftValue={rawDrafts["test_boot_timeout_seconds"]}
                    onChange={handleNumberChange}
                    onBlur={() => handleNumberBlur("test_boot_timeout_seconds")}
                    onStep={(delta) => handleNumberStep("test_boot_timeout_seconds", delta)}
                    min={SETTINGS_BOUNDS.test_boot_timeout_seconds.min}
                    max={SETTINGS_BOUNDS.test_boot_timeout_seconds.max}
                    step={15}
                    unit="sec"
                    disabled={!canWrite}
                  />
                </SettingRow>

                <SettingRow
                  id="log_level"
                  label="Log Level"
                  description="Minimum backend log severity."
                  propertyKey="log_level"
                  hasRestart={restartSet.has("log_level")}
                >
                  <div className="inline-flex items-center gap-1 rounded-lg bg-surface-card border border-border-subtle p-1">
                    {LOG_LEVELS.map((lvl) => {
                      const active = formData.log_level === lvl;
                      return (
                        <button
                          key={lvl}
                          type="button"
                          disabled={!canWrite}
                          onClick={() => {
                            setSaveError(null);
                            setFormData((prev) => ({ ...prev, log_level: lvl }));
                          }}
                          className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer disabled:opacity-50 ${
                            active
                              ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                              : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                          }`}
                        >
                          {lvl}
                        </button>
                      );
                    })}
                    <select
                      id="log_level"
                      name="log_level"
                      aria-label="Log Level"
                      value={formData.log_level}
                      disabled={!canWrite}
                      onChange={(e) => {
                        setSaveError(null);
                        setFormData((prev) => ({ ...prev, log_level: e.target.value }));
                      }}
                      className="sr-only"
                    >
                      {LOG_LEVELS.map((lvl) => (
                        <option key={lvl} value={lvl}>
                          {lvl}
                        </option>
                      ))}
                    </select>
                  </div>
                </SettingRow>

                <SettingRow
                  id="debug"
                  label="Verbose Debug Mode"
                  description="Enable verbose backend diagnostic logs."
                  propertyKey="debug"
                  hasRestart={restartSet.has("debug")}
                >
                  <button
                    id="debug"
                    type="button"
                    role="switch"
                    aria-checked={formData.debug}
                    aria-label="Verbose Debug Mode"
                    disabled={!canWrite}
                    onClick={() => {
                      setSaveError(null);
                      setFormData((prev) => ({ ...prev, debug: !prev.debug }));
                    }}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors disabled:opacity-50 ${
                      formData.debug ? "bg-accent-primary" : "bg-border-default"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-accent-contrast-text shadow-xs transition-transform ${
                        formData.debug ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </SettingRow>
              </div>
            </section>
          )}

          {showSecurity && (
            <section className="rounded-xl border border-border-subtle bg-surface-page/50 overflow-hidden">
              <div className="px-4 py-2.5 border-b border-border-subtle bg-surface-muted/40">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  API Security &amp; Throttling
                </h3>
              </div>
              <div>
                <SettingRow
                  id="rate_limit_per_minute"
                  label="API Rate Limit"
                  description="Max API requests per IP per minute."
                  propertyKey="rate_limit_per_minute"
                >
                  <NumberStepper
                    id="rate_limit_per_minute"
                    name="rate_limit_per_minute"
                    label="API Rate Limit"
                    value={formData.rate_limit_per_minute}
                    draftValue={rawDrafts["rate_limit_per_minute"]}
                    onChange={handleNumberChange}
                    onBlur={() => handleNumberBlur("rate_limit_per_minute")}
                    onStep={(delta) => handleNumberStep("rate_limit_per_minute", delta)}
                    min={SETTINGS_BOUNDS.rate_limit_per_minute.min}
                    max={SETTINGS_BOUNDS.rate_limit_per_minute.max}
                    step={10}
                    unit="req/min"
                    disabled={!canWrite}
                  />
                </SettingRow>

                <SettingRow
                  id="idempotency_ttl_hours"
                  label="Duplicate Action Window"
                  description="Prevents accidental double-click repeats."
                  propertyKey="idempotency_ttl_hours"
                >
                  <NumberStepper
                    id="idempotency_ttl_hours"
                    name="idempotency_ttl_hours"
                    label="Duplicate Action Window"
                    value={formData.idempotency_ttl_hours}
                    draftValue={rawDrafts["idempotency_ttl_hours"]}
                    onChange={handleNumberChange}
                    onBlur={() => handleNumberBlur("idempotency_ttl_hours")}
                    onStep={(delta) => handleNumberStep("idempotency_ttl_hours", delta)}
                    min={SETTINGS_BOUNDS.idempotency_ttl_hours.min}
                    max={SETTINGS_BOUNDS.idempotency_ttl_hours.max}
                    step={1}
                    unit="hrs"
                    disabled={!canWrite}
                  />
                </SettingRow>
              </div>
            </section>
          )}

          {showResilience && (
            <section className="rounded-xl border border-border-subtle bg-surface-page/50 overflow-hidden">
              <div className="px-4 py-2.5 border-b border-border-subtle bg-surface-muted/40">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  Resilience &amp; Background Jobs
                </h3>
              </div>
              <div>
                <SettingRow
                  id="circuit_breaker_max_failures"
                  label="Failure Limit"
                  description="Consecutive failures before pausing retries."
                  propertyKey="circuit_breaker_max_failures"
                >
                  <NumberStepper
                    id="circuit_breaker_max_failures"
                    name="circuit_breaker_max_failures"
                    label="Failure Limit"
                    value={formData.circuit_breaker_max_failures}
                    draftValue={rawDrafts["circuit_breaker_max_failures"]}
                    onChange={handleNumberChange}
                    onBlur={() => handleNumberBlur("circuit_breaker_max_failures")}
                    onStep={(delta) => handleNumberStep("circuit_breaker_max_failures", delta)}
                    min={SETTINGS_BOUNDS.circuit_breaker_max_failures.min}
                    max={SETTINGS_BOUNDS.circuit_breaker_max_failures.max}
                    step={1}
                    disabled={!canWrite}
                  />
                </SettingRow>

                <SettingRow
                  id="circuit_breaker_timeout_seconds"
                  label="Recovery Cooldown"
                  description="Wait time before retrying a failed service."
                  propertyKey="circuit_breaker_timeout_seconds"
                >
                  <NumberStepper
                    id="circuit_breaker_timeout_seconds"
                    name="circuit_breaker_timeout_seconds"
                    label="Recovery Cooldown"
                    value={formData.circuit_breaker_timeout_seconds}
                    draftValue={rawDrafts["circuit_breaker_timeout_seconds"]}
                    onChange={handleNumberChange}
                    onBlur={() => handleNumberBlur("circuit_breaker_timeout_seconds")}
                    onStep={(delta) => handleNumberStep("circuit_breaker_timeout_seconds", delta)}
                    min={SETTINGS_BOUNDS.circuit_breaker_timeout_seconds.min}
                    max={SETTINGS_BOUNDS.circuit_breaker_timeout_seconds.max}
                    step={5}
                    unit="sec"
                    disabled={!canWrite}
                  />
                </SettingRow>

                <SettingRow
                  id="event_bus_retry_attempts"
                  label="Task Retry Count"
                  description="Automatic retries for failed background tasks."
                  propertyKey="event_bus_retry_attempts"
                >
                  <NumberStepper
                    id="event_bus_retry_attempts"
                    name="event_bus_retry_attempts"
                    label="Task Retry Count"
                    value={formData.event_bus_retry_attempts}
                    draftValue={rawDrafts["event_bus_retry_attempts"]}
                    onChange={handleNumberChange}
                    onBlur={() => handleNumberBlur("event_bus_retry_attempts")}
                    onStep={(delta) => handleNumberStep("event_bus_retry_attempts", delta)}
                    min={SETTINGS_BOUNDS.event_bus_retry_attempts.min}
                    max={SETTINGS_BOUNDS.event_bus_retry_attempts.max}
                    step={1}
                    disabled={!canWrite}
                  />
                </SettingRow>

                <SettingRow
                  id="saga_timeout_seconds"
                  label="Background Job Timeout"
                  description="Max runtime for long multi-step operations."
                  propertyKey="saga_timeout_seconds"
                >
                  <NumberStepper
                    id="saga_timeout_seconds"
                    name="saga_timeout_seconds"
                    label="Background Job Timeout"
                    value={formData.saga_timeout_seconds}
                    draftValue={rawDrafts["saga_timeout_seconds"]}
                    onChange={handleNumberChange}
                    onBlur={() => handleNumberBlur("saga_timeout_seconds")}
                    onStep={(delta) => handleNumberStep("saga_timeout_seconds", delta)}
                    min={SETTINGS_BOUNDS.saga_timeout_seconds.min}
                    max={SETTINGS_BOUNDS.saga_timeout_seconds.max}
                    step={15}
                    unit="sec"
                    disabled={!canWrite}
                  />
                </SettingRow>
              </div>
            </section>
          )}
        </div>

        {/* Sticky Footer */}
        <div className="px-6 py-3.5 border-t border-border-subtle bg-surface-elevated/80 flex flex-wrap items-center justify-between gap-3 shrink-0">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            icon="restart"
            disabled={!canWrite || updateSettings.isPending}
            onClick={() => setConfirmResetOpen(true)}
          >
            Reset Engine Defaults
          </Button>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={updateSettings.isPending}
              onClick={requestClose}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={updateSettings.isPending}
              disabled={!canWrite || !isDirty || updateSettings.isPending}
            >
              Save Engine Settings
            </Button>
          </div>
        </div>
        </form>
    </Modal>
  );
}
