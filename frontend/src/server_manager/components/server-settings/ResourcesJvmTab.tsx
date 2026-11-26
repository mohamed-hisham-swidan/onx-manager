import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { HostResourceBudgetBar } from "@/server_manager/components/HostResourceBudgetBar";
import type { HostResourceBudget } from "@/types";
import { NumberStepper, SettingsCard, SettingsRow } from "./ServerSettingsControls";
import {
  AIKARS_JVM_FLAGS,
  MIN_RAM_FLOOR,
  RAM_PRESETS,
  STARTUP_TIMEOUT_MAX,
  STARTUP_TIMEOUT_MIN,
  STARTUP_TIMEOUT_PRESETS,
  type NumericDraftKey,
  type ServerSettingsFormState,
  type ServerValidationErrors,
} from "./serverSettingsModel";

export interface ResourcesJvmTabProps {
  form: ServerSettingsFormState;
  rawDrafts: Partial<Record<NumericDraftKey, string>>;
  errors: ServerValidationErrors;
  disabled: boolean;
  gitBacked: boolean;
  hostBudget?: HostResourceBudget | null;
  onUpdateForm: (patch: Partial<ServerSettingsFormState>) => void;
  onNumericChange: (key: NumericDraftKey, raw: string) => void;
  onNumericBlur: (key: NumericDraftKey) => void;
  onNumericStep: (key: NumericDraftKey, delta: number) => void;
  onApplyRamPreset: (minMb: number, maxMb: number) => void;
}

export function ResourcesJvmTab({
  form,
  rawDrafts,
  errors,
  disabled,
  gitBacked,
  hostBudget,
  onUpdateForm,
  onNumericChange,
  onNumericBlur,
  onNumericStep,
  onApplyRamPreset,
}: ResourcesJvmTabProps) {
  const customizedAdvancedCount =
    (form.javaArgs.trim() ? 1 : 0) + (form.cpuAffinity.trim() ? 1 : 0);
  const [advancedOpen, setAdvancedOpen] = useState(customizedAdvancedCount > 0);

  const maxAllocRam = hostBudget?.allocatable_ram_mb ?? 262144;
  const maxAllocCpus = hostBudget?.allocatable_cpus
    ? Math.max(1, Math.floor(hostBudget.allocatable_cpus))
    : undefined;
  const heapRatio = Math.min(
    100,
    Math.max(4, Math.round((form.minRam / (form.maxRam || 1)) * 100)),
  );

  const cpuQuickChips = [
    { label: "Unlimited (0)", value: 0 },
    ...(maxAllocCpus === undefined || maxAllocCpus >= 2
      ? [{ label: "2 Cores", value: 2 }]
      : []),
    ...(maxAllocCpus === undefined || maxAllocCpus >= 4
      ? [{ label: "4 Cores", value: 4 }]
      : []),
  ];

  const handleApplyAikars = () => {
    onUpdateForm({ javaArgs: AIKARS_JVM_FLAGS.join("\n") });
  };

  return (
    <div className="space-y-6" data-testid="server-settings-tab-resources">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight text-text-primary">
          Resources &amp; JVM
        </h2>
        <p className="text-xs text-text-muted">
          Memory, CPU limits, boot timeout, and Java flags.
        </p>
      </header>

      {/* Memory & Host Budget */}
      <SettingsCard title="Memory & Host Budget">
        <div className="p-5 space-y-4">
          {hostBudget && (
            <HostResourceBudgetBar
              budget={hostBudget}
              requestedRamMb={form.maxRam}
              requestedCpuCores={form.cpuCores}
              compact
            />
          )}

          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="font-medium text-text-primary">
                Min {(form.minRam / 1024).toFixed(1)} GB / Max{" "}
                {(form.maxRam / 1024).toFixed(1)} GB
              </span>
              <span className="rounded-full bg-surface-muted px-2 py-0.5 font-mono text-[11px] font-medium text-text-secondary">
                {heapRatio}% Heap Ratio
              </span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-muted">
              <div
                className="h-full rounded-full bg-accent-primary transition-all duration-300"
                style={{ width: `${heapRatio}%` }}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {RAM_PRESETS.map((preset) => {
              const selected =
                form.minRam === preset.min && form.maxRam === preset.max;
              const overCeiling = Boolean(
                hostBudget && preset.max > hostBudget.allocatable_ram_mb,
              );
              return (
                <button
                  key={preset.label}
                  type="button"
                  disabled={disabled || overCeiling}
                  title={
                    overCeiling
                      ? `Exceeds host allocatable RAM (${hostBudget?.allocatable_ram_mb} MB)`
                      : undefined
                  }
                  onClick={() => onApplyRamPreset(preset.min, preset.max)}
                  className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                    selected
                      ? "border-accent-primary bg-accent-primary text-accent-contrast-text"
                      : "border-border-subtle bg-surface-muted text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2 border-t border-border-subtle">
            <div className="space-y-1.5">
              <label
                htmlFor="srv-setting-min-ram"
                className="block text-sm font-medium text-text-primary"
              >
                Minimum Memory (MB)
              </label>
              <p id="srv-setting-min-ram-help" className="text-xs text-text-muted">
                Initial Java heap allocated on startup.
              </p>
              <NumberStepper
                id="srv-setting-min-ram"
                name="min_memory_mb"
                label="Minimum Memory"
                value={form.minRam}
                draftValue={rawDrafts.minRam}
                onChange={(v) => onNumericChange("minRam", v)}
                onBlur={() => onNumericBlur("minRam")}
                onStep={(d) => onNumericStep("minRam", d)}
                min={MIN_RAM_FLOOR}
                max={maxAllocRam}
                step={128}
                unit="MB"
                disabled={disabled}
              />
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="srv-setting-max-ram"
                className="block text-sm font-medium text-text-primary"
              >
                Maximum Memory (MB)
              </label>
              <p id="srv-setting-max-ram-help" className="text-xs text-text-muted">
                Maximum Java heap ceiling for the server.
              </p>
              <NumberStepper
                id="srv-setting-max-ram"
                name="max_memory_mb"
                label="Maximum Memory"
                value={form.maxRam}
                draftValue={rawDrafts.maxRam}
                onChange={(v) => onNumericChange("maxRam", v)}
                onBlur={() => onNumericBlur("maxRam")}
                onStep={(d) => onNumericStep("maxRam", d)}
                min={MIN_RAM_FLOOR}
                max={maxAllocRam}
                step={128}
                unit="MB"
                disabled={disabled}
              />
            </div>
          </div>

          {errors.ram && (
            <p className="text-xs font-medium text-status-danger">{errors.ram}</p>
          )}
        </div>
      </SettingsCard>

      {/* CPU & Boot Limits */}
      <SettingsCard title="CPU & Boot Limits">
        <SettingsRow
          id="srv-setting-cpu-cores"
          label="CPU Core Limit"
          description="Maximum logical CPU cores (0 = unlimited)."
          alignTop
        >
          <div className="flex flex-col items-start sm:items-end gap-2 w-full">
            <NumberStepper
              id="srv-setting-cpu-cores"
              name="cpu_cores"
              label="CPU Core Limit"
              value={form.cpuCores}
              draftValue={rawDrafts.cpuCores}
              onChange={(v) => onNumericChange("cpuCores", v)}
              onBlur={() => onNumericBlur("cpuCores")}
              onStep={(d) => onNumericStep("cpuCores", d)}
              min={0}
              max={maxAllocCpus}
              step={1}
              disabled={disabled}
            />
            <div className="flex flex-wrap gap-1.5">
              {cpuQuickChips.map((chip) => {
                const active = form.cpuCores === chip.value;
                return (
                  <button
                    key={chip.label}
                    type="button"
                    disabled={disabled}
                    onClick={() => onUpdateForm({ cpuCores: chip.value })}
                    className={`rounded-md border px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer disabled:opacity-45 ${
                      active
                        ? "border-accent-primary bg-accent-primary/12 text-accent-primary"
                        : "border-border-subtle bg-surface-muted text-text-secondary hover:text-text-primary"
                    }`}
                  >
                    {chip.label}
                  </button>
                );
              })}
            </div>
          </div>
        </SettingsRow>

        <SettingsRow
          id="srv-setting-startup-timeout"
          label="Server Startup Timeout"
          description={
            gitBacked
              ? "Max seconds to wait before marking boot failed (server-wide)."
              : "Max seconds to wait before marking boot failed."
          }
          alignTop
        >
          <div className="flex flex-col items-start sm:items-end gap-2 w-full">
            <NumberStepper
              id="srv-setting-startup-timeout"
              name="startup_timeout_seconds"
              label="Server Startup Timeout"
              value={form.startupTimeout}
              draftValue={rawDrafts.startupTimeout}
              onChange={(v) => onNumericChange("startupTimeout", v)}
              onBlur={() => onNumericBlur("startupTimeout")}
              onStep={(d) => onNumericStep("startupTimeout", d)}
              min={STARTUP_TIMEOUT_MIN}
              max={STARTUP_TIMEOUT_MAX}
              step={15}
              unit="sec"
              disabled={disabled}
            />
            <div className="flex flex-wrap gap-1.5">
              {STARTUP_TIMEOUT_PRESETS.map((preset) => {
                const active = form.startupTimeout === preset.value;
                return (
                  <button
                    key={preset.label}
                    type="button"
                    disabled={disabled}
                    onClick={() => onUpdateForm({ startupTimeout: preset.value })}
                    className={`rounded-md border px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer disabled:opacity-45 ${
                      active
                        ? "border-accent-primary bg-accent-primary/12 text-accent-primary"
                        : "border-border-subtle bg-surface-muted text-text-secondary hover:text-text-primary"
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>
            {errors.startupTimeout && (
              <p className="text-xs font-medium text-status-danger">
                {errors.startupTimeout}
              </p>
            )}
          </div>
        </SettingsRow>
      </SettingsCard>

      {/* Collapsible Advanced JVM & CPU Pinning */}
      <section className="rounded-xl border border-border-subtle bg-surface-card overflow-hidden">
        <button
          type="button"
          aria-expanded={advancedOpen}
          data-testid="toggle-advanced-jvm"
          onClick={() => setAdvancedOpen((prev) => !prev)}
          className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left hover:bg-surface-hover/50 transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-2.5">
            <Icon
              name={advancedOpen ? "chevron-down" : "chevron-right"}
              size={15}
              className="text-text-muted"
            />
            <span className="text-sm font-semibold text-text-primary">
              Advanced JVM &amp; CPU Pinning
            </span>
            {customizedAdvancedCount > 0 && (
              <span className="rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-secondary">
                {customizedAdvancedCount} customized
              </span>
            )}
          </div>
          <span className="text-xs text-text-muted">
            {advancedOpen ? "Hide" : "Show"}
          </span>
        </button>

        {advancedOpen && (
          <div className="divide-y divide-border-subtle border-t border-border-subtle">
            <SettingsRow
              id="srv-setting-jvm-args"
              label="Custom JVM Arguments"
              description="Extra Java flags passed on startup, one per line."
              alignTop
            >
              <div className="w-full space-y-2">
                <div className="flex flex-wrap items-center justify-end gap-1.5">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={disabled}
                    onClick={handleApplyAikars}
                  >
                    Apply Aikar&apos;s Flags
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={disabled || !form.javaArgs}
                    onClick={() => onUpdateForm({ javaArgs: "" })}
                  >
                    Clear
                  </Button>
                </div>
                <textarea
                  id="srv-setting-jvm-args"
                  rows={4}
                  disabled={disabled}
                  value={form.javaArgs}
                  onChange={(e) => onUpdateForm({ javaArgs: e.target.value })}
                  placeholder="-XX:+UseG1GC&#10;-XX:+ParallelRefProcEnabled"
                  className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 font-mono text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
                />
                {errors.jvmArgs && (
                  <p className="text-xs font-medium text-status-danger">
                    {errors.jvmArgs}
                  </p>
                )}
              </div>
            </SettingsRow>

            <SettingsRow
              id="srv-setting-cpu-affinity"
              label="CPU Affinity Mask"
              description="Pin server threads to specific host CPU cores."
            >
              <div className="w-full space-y-1">
                <input
                  id="srv-setting-cpu-affinity"
                  type="text"
                  disabled={disabled}
                  value={form.cpuAffinity}
                  onChange={(e) => onUpdateForm({ cpuAffinity: e.target.value })}
                  placeholder="e.g. 0-3 or 0,2,4"
                  className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
                />
                {errors.cpuAffinity && (
                  <p className="text-xs font-medium text-status-danger">
                    {errors.cpuAffinity}
                  </p>
                )}
              </div>
            </SettingsRow>
          </div>
        )}
      </section>
    </div>
  );
}
