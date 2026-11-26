import React, { useMemo, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import { Banner } from "@/components/ui/Banner";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useUpdateSettings } from "@/server_manager/hooks/useSettings";
import { toast } from "@/stores/toastStore";
import type { SettingsResponse } from "@/types";
import { AdvancedEngineSettingsDrawer } from "./AdvancedEngineSettingsDrawer";
import {
  ENGINE_SETTING_KEYS,
  GENERAL_SETTING_KEYS,
  SETTINGS_BOUNDS,
  clampNumericValue,
  computeDirtyPatch,
  formStateFromSettings,
  normalizeFormWithDrafts,
  resolveCanonicalDefaults,
  useSettingsPermissions,
  type NumericSettingKey,
  type SystemFormState,
} from "./settingsModel";
import { NumberStepper, SettingRow } from "./settingsUtils";

const RAM_PRESETS = [
  { label: "Auto (0)", value: 0 },
  { label: "2 GB (2048)", value: 2048 },
  { label: "4 GB (4096)", value: 4096 },
  { label: "8 GB (8192)", value: 8192 },
];

const CPU_PRESETS = [
  { label: "Auto (0)", value: 0 },
  { label: "1 Core", value: 1 },
  { label: "2 Cores", value: 2 },
  { label: "4 Cores", value: 4 },
];

const STARTUP_TIMEOUT_PRESETS = [
  { label: "60s", value: 60 },
  { label: "120s (Default)", value: 120 },
  { label: "300s (Heavy Modpacks)", value: 300 },
];

export interface GeneralSettingsTabProps {
  settings: SettingsResponse;
}

export function GeneralSettingsTab({ settings }: GeneralSettingsTabProps) {
  const updateSettings = useUpdateSettings();
  const { canWriteSettings } = useSettingsPermissions();

  const baseline = useMemo(() => formStateFromSettings(settings), [settings]);
  const defaults = useMemo(() => resolveCanonicalDefaults(settings), [settings]);

  const [syncedSettings, setSyncedSettings] = useState(settings);
  const [savedSnapshot, setSavedSnapshot] = useState<SystemFormState | null>(null);
  const effectiveBaseline = savedSnapshot ?? baseline;
  const [formData, setFormData] = useState<SystemFormState>(effectiveBaseline);
  const [rawDrafts, setRawDrafts] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [resetDialogOpen, setResetDialogOpen] = useState(false);

  if (syncedSettings !== settings) {
    setSyncedSettings(settings);
    setSavedSnapshot(null);
    setFormData(baseline);
    setRawDrafts({});
    setSaveError(null);
  }

  const normalizedCurrent = useMemo(
    () => normalizeFormWithDrafts(formData, rawDrafts, GENERAL_SETTING_KEYS),
    [formData, rawDrafts],
  );

  const dirtyPatch = useMemo(
    () => computeDirtyPatch(normalizedCurrent, effectiveBaseline, GENERAL_SETTING_KEYS),
    [normalizedCurrent, effectiveBaseline],
  );

  const dirtyCount = Object.keys(dirtyPatch).length;
  const isDirty = dirtyCount > 0;

  const customizedEngineCount = useMemo(() => {
    let count = 0;
    for (const key of ENGINE_SETTING_KEYS) {
      if (baseline[key] !== defaults[key]) count += 1;
    }
    return count;
  }, [baseline, defaults]);

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
    const current = Number(
      rawDrafts[key] !== undefined && rawDrafts[key] !== "" ? rawDrafts[key] : formData[key],
    );
    const clamped = clampNumericValue(
      key,
      (Number.isFinite(current) ? current : SETTINGS_BOUNDS[key].min) + delta,
    );
    if (clamped !== null) {
      setFormData((prev) => ({ ...prev, [key]: clamped }));
    }
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const applyPreset = (key: NumericSettingKey, value: number) => {
    setSaveError(null);
    setFormData((prev) => ({ ...prev, [key]: value }));
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleDiscard = () => {
    setFormData(effectiveBaseline);
    setRawDrafts({});
    setSaveError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canWriteSettings) return;
    setSaveError(null);

    const clamped = normalizeFormWithDrafts(formData, rawDrafts, GENERAL_SETTING_KEYS);
    setFormData(clamped);
    setRawDrafts({});

    const patch = computeDirtyPatch(clamped, effectiveBaseline, GENERAL_SETTING_KEYS);
    if (Object.keys(patch).length === 0) return;

    try {
      const res = await updateSettings.mutateAsync(patch);
      const nextState = res.settings ? formStateFromSettings(res.settings) : clamped;
      setSavedSnapshot(nextState);
      setFormData(nextState);
      toast("success", "Settings saved", "Your changes have been saved.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save settings";
      setSaveError(msg);
      toast("error", "Failed to save settings", msg);
    }
  };

  const handleConfirmResetDefaults = async () => {
    if (!canWriteSettings) return;
    setResetDialogOpen(false);
    setSaveError(null);
    const patch = computeDirtyPatch(defaults, effectiveBaseline, GENERAL_SETTING_KEYS);
    if (Object.keys(patch).length === 0) {
      setFormData(defaults);
      setRawDrafts({});
      toast("info", "Already at defaults", "General settings already match factory defaults.");
      return;
    }
    try {
      const res = await updateSettings.mutateAsync(patch);
      const nextState = res.settings ? formStateFromSettings(res.settings) : defaults;
      setSavedSnapshot(nextState);
      setFormData(nextState);
      setRawDrafts({});
      toast("success", "Defaults restored", "General settings were reset to factory defaults.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to restore defaults";
      setSaveError(msg);
      toast("error", "Failed to restore defaults", msg);
    }
  };

  return (
    <div className="space-y-6 pb-8">
      {/* Unified Tab Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">General</h2>
          <p className="text-sm text-text-muted mt-0.5">
            Host resource limits and server boot behavior.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!canWriteSettings && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border-subtle bg-surface-muted px-3 py-1 text-xs font-medium text-text-muted">
              <Icon name="lock" size={12} />
              Read-only access
            </span>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            icon="restart"
            disabled={!canWriteSettings || updateSettings.isPending}
            onClick={() => setResetDialogOpen(true)}
          >
            Reset Defaults
          </Button>
        </div>
      </div>

      {saveError && (
        <Banner variant="danger" title="Failed to save settings" description={saveError} />
      )}

      <form noValidate onSubmit={handleSubmit} className="space-y-6">
        {/* Section A: Host Resource Reserve */}
        <section className="rounded-xl border border-border-subtle bg-surface-card shadow-2xs overflow-hidden">
          <div className="px-5 py-3.5 border-b border-border-subtle bg-surface-muted/40">
            <h3 className="text-sm font-semibold text-text-primary">Host Resource Reserve</h3>
            <p className="text-xs text-text-muted mt-0.5">
              Memory and CPU kept free for your OS.
            </p>
          </div>

          <div>
            <SettingRow
              id="host_ram_reserve_mb"
              label="Host RAM Reserve"
              description="Leave at 0 for automatic host protection."
              propertyKey="host_ram_reserve_mb"
            >
              <NumberStepper
                id="host_ram_reserve_mb"
                name="host_ram_reserve_mb"
                label="Host RAM Reserve"
                value={formData.host_ram_reserve_mb}
                draftValue={rawDrafts["host_ram_reserve_mb"]}
                onChange={handleNumberChange}
                onBlur={() => handleNumberBlur("host_ram_reserve_mb")}
                onStep={(delta) => handleNumberStep("host_ram_reserve_mb", delta)}
                min={SETTINGS_BOUNDS.host_ram_reserve_mb.min}
                max={SETTINGS_BOUNDS.host_ram_reserve_mb.max}
                step={512}
                unit="MB"
                disabled={!canWriteSettings}
              />
              <div className="flex flex-wrap gap-1.5 justify-start sm:justify-end">
                {RAM_PRESETS.map((preset) => {
                  const active = normalizedCurrent.host_ram_reserve_mb === preset.value;
                  return (
                    <button
                      key={preset.value}
                      type="button"
                      disabled={!canWriteSettings}
                      onClick={() => applyPreset("host_ram_reserve_mb", preset.value)}
                      className={`px-2 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer disabled:opacity-50 ${
                        active
                          ? "bg-accent-primary/14 text-text-accent"
                          : "bg-surface-page text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                      }`}
                    >
                      {preset.label}
                    </button>
                  );
                })}
              </div>
            </SettingRow>

            <SettingRow
              id="host_cpu_reserve"
              label="Host CPU Reserve"
              description="CPU cores reserved for the OS. 0 = automatic."
              propertyKey="host_cpu_reserve"
            >
              <NumberStepper
                id="host_cpu_reserve"
                name="host_cpu_reserve"
                label="Host CPU Reserve"
                value={formData.host_cpu_reserve}
                draftValue={rawDrafts["host_cpu_reserve"]}
                onChange={handleNumberChange}
                onBlur={() => handleNumberBlur("host_cpu_reserve")}
                onStep={(delta) => handleNumberStep("host_cpu_reserve", delta)}
                min={SETTINGS_BOUNDS.host_cpu_reserve.min}
                max={SETTINGS_BOUNDS.host_cpu_reserve.max}
                step={0.5}
                unit="cores"
                disabled={!canWriteSettings}
              />
              <div className="flex flex-wrap gap-1.5 justify-start sm:justify-end">
                {CPU_PRESETS.map((preset) => {
                  const active = normalizedCurrent.host_cpu_reserve === preset.value;
                  return (
                    <button
                      key={preset.value}
                      type="button"
                      disabled={!canWriteSettings}
                      onClick={() => applyPreset("host_cpu_reserve", preset.value)}
                      className={`px-2 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer disabled:opacity-50 ${
                        active
                          ? "bg-accent-primary/14 text-text-accent"
                          : "bg-surface-page text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                      }`}
                    >
                      {preset.label}
                    </button>
                  );
                })}
              </div>
            </SettingRow>
          </div>
        </section>

        {/* Section B: Server Lifecycle */}
        <section className="rounded-xl border border-border-subtle bg-surface-card shadow-2xs overflow-hidden">
          <div className="px-5 py-3.5 border-b border-border-subtle bg-surface-muted/40">
            <h3 className="text-sm font-semibold text-text-primary">Server Lifecycle</h3>
            <p className="text-xs text-text-muted mt-0.5">
              Default boot wait limits for servers.
            </p>
          </div>

          <div>
            <SettingRow
              id="server_startup_timeout_seconds"
              label="Server Startup Timeout"
              description="Max seconds to wait before marking a boot failed."
              propertyKey="server_startup_timeout_seconds"
            >
              <NumberStepper
                id="server_startup_timeout_seconds"
                name="server_startup_timeout_seconds"
                label="Server Startup Timeout"
                value={formData.server_startup_timeout_seconds}
                draftValue={rawDrafts["server_startup_timeout_seconds"]}
                onChange={handleNumberChange}
                onBlur={() => handleNumberBlur("server_startup_timeout_seconds")}
                onStep={(delta) => handleNumberStep("server_startup_timeout_seconds", delta)}
                min={SETTINGS_BOUNDS.server_startup_timeout_seconds.min}
                max={SETTINGS_BOUNDS.server_startup_timeout_seconds.max}
                step={15}
                unit="sec"
                disabled={!canWriteSettings}
              />
              <div className="flex flex-wrap gap-1.5 justify-start sm:justify-end">
                {STARTUP_TIMEOUT_PRESETS.map((preset) => {
                  const active = normalizedCurrent.server_startup_timeout_seconds === preset.value;
                  return (
                    <button
                      key={preset.value}
                      type="button"
                      disabled={!canWriteSettings}
                      onClick={() => applyPreset("server_startup_timeout_seconds", preset.value)}
                      className={`px-2 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer disabled:opacity-50 ${
                        active
                          ? "bg-accent-primary/14 text-text-accent"
                          : "bg-surface-page text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                      }`}
                    >
                      {preset.label}
                    </button>
                  );
                })}
              </div>
            </SettingRow>
          </div>
        </section>

        {/* Section C: Advanced Engine Settings Gateway Card */}
        <section className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5 min-w-0">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-surface-muted text-text-secondary">
              <Icon name="cpu" size={18} />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-text-primary">Advanced Engine Settings</h3>
              <p className="text-xs text-text-muted mt-0.5">
                Rate limits, timeouts, retries, monitoring, and logging.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {customizedEngineCount > 0 && (
              <span className="inline-flex items-center rounded-full bg-accent-primary/12 px-2.5 py-1 text-xs font-medium text-text-accent">
                {customizedEngineCount} customized
              </span>
            )}
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setDrawerOpen(true)}
            >
              Configure Engine →
            </Button>
          </div>
        </section>

        {/* Floating Sticky Unsaved Changes Bar */}
        {isDirty && (
          <div className="sticky bottom-4 z-30 flex justify-center">
            <div
              role="region"
              aria-label="Unsaved changes"
              className="w-full max-w-xl rounded-xl border border-border-subtle bg-surface-elevated/95 backdrop-blur-md px-4 py-3 shadow-lg flex items-center justify-between gap-4"
            >
              <div className="flex items-center gap-2 text-xs font-medium text-text-primary">
                <span className="h-2 w-2 rounded-full bg-status-warning shrink-0" />
                <span>
                  {dirtyCount} unsaved {dirtyCount === 1 ? "change" : "changes"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={updateSettings.isPending}
                  onClick={handleDiscard}
                >
                  Discard
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  icon="check"
                  loading={updateSettings.isPending}
                  disabled={!canWriteSettings || updateSettings.isPending}
                >
                  {updateSettings.isPending ? "Saving..." : "Save Changes"}
                </Button>
              </div>
            </div>
          </div>
        )}
      </form>

      <AdvancedEngineSettingsDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        settings={settings}
        canWrite={canWriteSettings}
      />

      <ConfirmDialog
        open={resetDialogOpen}
        title="Reset General settings?"
        description="Restore Host RAM Reserve, Host CPU Reserve, and Server Startup Timeout to factory defaults."
        confirmLabel="Reset Defaults"
        onConfirm={handleConfirmResetDefaults}
        onCancel={() => setResetDialogOpen(false)}
      />
    </div>
  );
}
