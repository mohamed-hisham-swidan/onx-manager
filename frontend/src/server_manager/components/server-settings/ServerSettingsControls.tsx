import React from "react";
import { Icon, type IconName } from "@/components/ui/Icon";

export function SettingsCard({
  title,
  description,
  children,
  headerRight,
}: {
  title?: string;
  description?: string;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border-subtle bg-surface-card overflow-hidden">
      {title && (
        <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-border-subtle bg-surface-muted/40">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
            {description && (
              <p className="text-xs text-text-muted mt-0.5">{description}</p>
            )}
          </div>
          {headerRight}
        </div>
      )}
      <div className="divide-y divide-border-subtle">{children}</div>
    </section>
  );
}

export function SettingsRow({
  id,
  label,
  description,
  badge,
  badgeVariant = "warning",
  children,
  alignTop = false,
}: {
  id: string;
  label: string;
  description?: string;
  badge?: string;
  badgeVariant?: "warning" | "neutral";
  children: React.ReactNode;
  alignTop?: boolean;
}) {
  return (
    <div
      className={`flex flex-col sm:flex-row ${
        alignTop ? "sm:items-start" : "sm:items-center"
      } justify-between gap-4 px-5 py-4`}
    >
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor={id}
            className="text-sm font-medium text-text-primary cursor-pointer"
          >
            {label}
          </label>
          {badge && (
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide border shrink-0 ${
                badgeVariant === "warning"
                  ? "bg-status-warning-bg text-status-warning border-status-warning-border"
                  : "bg-surface-muted text-text-muted border-border-subtle"
              }`}
            >
              {badge}
            </span>
          )}
        </div>
        {description && (
          <p id={`${id}-help`} className="text-xs text-text-muted leading-relaxed">
            {description}
          </p>
        )}
      </div>
      <div className="w-full sm:w-auto sm:min-w-[240px] sm:max-w-[360px] flex flex-col items-start sm:items-end gap-1.5 shrink-0">
        {children}
      </div>
    </div>
  );
}

export function ServerSwitchRow({
  id,
  label,
  description,
  icon,
  badge,
  hint,
  checked,
  disabled = false,
  onChange,
}: {
  id: string;
  label: string;
  description?: string;
  icon?: IconName;
  badge?: string;
  hint?: string | null;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-3.5">
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex flex-wrap items-center gap-2">
          {icon && (
            <Icon name={icon} size={14} className="text-text-muted shrink-0" />
          )}
          <label
            htmlFor={id}
            className={`text-sm font-medium text-text-primary ${
              disabled ? "opacity-70" : "cursor-pointer"
            }`}
          >
            {label}
          </label>
          {badge && (
            <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-status-warning-bg text-status-warning border border-status-warning-border shrink-0">
              {badge}
            </span>
          )}
        </div>
        {description && (
          <p className="text-xs text-text-muted leading-relaxed">{description}</p>
        )}
        {hint && (
          <p className="text-xs font-medium text-status-warning pt-0.5">{hint}</p>
        )}
      </div>

      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus disabled:opacity-45 disabled:cursor-not-allowed cursor-pointer ${
          checked ? "bg-accent-primary" : "bg-border-default"
        }`}
      >
        <span
          aria-hidden="true"
          className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-accent-contrast-text shadow-xs transition-transform ${
            checked ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </button>
    </div>
  );
}

const BLOCKED_NON_NEGATIVE_KEYS = new Set(["e", "E", "+", "-"]);

export function NumberStepper({
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
  step = 1,
  unit,
  disabled = false,
}: {
  id: string;
  name?: string;
  label: string;
  value: number;
  draftValue?: string;
  onChange: (val: string) => void;
  onBlur: () => void;
  onStep: (delta: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  disabled?: boolean;
}) {
  const displayVal = draftValue !== undefined ? draftValue : String(value);
  const isInteger = Number.isInteger(step);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (min !== undefined && min >= 0 && BLOCKED_NON_NEGATIVE_KEYS.has(e.key)) {
      e.preventDefault();
      return;
    }
    if (isInteger && e.key === ".") {
      e.preventDefault();
    }
  };

  return (
    <div className="inline-flex items-center gap-1.5 w-full sm:w-auto justify-start sm:justify-end">
      <button
        type="button"
        aria-label={`Decrease ${label}`}
        onClick={() => onStep(-step)}
        disabled={disabled || (min !== undefined && value <= min)}
        className="h-9 w-9 flex items-center justify-center rounded-lg border border-border-subtle bg-surface-page text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-35 disabled:pointer-events-none transition-all cursor-pointer font-semibold text-base select-none shrink-0"
      >
        −
      </button>

      <div className="relative inline-flex items-center flex-1 sm:flex-initial">
        <input
          id={id}
          name={name}
          type="number"
          min={min}
          max={max}
          step="any"
          value={displayVal}
          disabled={disabled}
          onKeyDown={handleKeyDown}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          aria-describedby={`${id}-help`}
          className={`w-full sm:w-32 text-center px-2.5 py-1.5 font-mono text-sm rounded-lg border border-border-subtle bg-surface-page text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-hidden disabled:opacity-50 transition-shadow ${
            unit ? "pr-11" : ""
          }`}
        />
        {unit && (
          <span className="absolute right-2.5 pointer-events-none text-[11px] font-mono text-text-muted">
            {unit}
          </span>
        )}
      </div>

      <button
        type="button"
        aria-label={`Increase ${label}`}
        onClick={() => onStep(step)}
        disabled={disabled || (max !== undefined && value >= max)}
        className="h-9 w-9 flex items-center justify-center rounded-lg border border-border-subtle bg-surface-page text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-35 disabled:pointer-events-none transition-all cursor-pointer font-semibold text-base select-none shrink-0"
      >
        +
      </button>
    </div>
  );
}

export function DistanceSliderControl({
  id,
  label,
  value,
  draftValue,
  onChange,
  onBlur,
  onStep,
  min,
  max,
  unit,
  disabled = false,
  hint,
}: {
  id: string;
  label: string;
  value: number;
  draftValue?: string;
  onChange: (val: string) => void;
  onBlur: () => void;
  onStep: (delta: number) => void;
  min: number;
  max: number;
  unit: string;
  disabled?: boolean;
  hint?: string | null;
}) {
  const displayVal = draftValue !== undefined ? draftValue : String(value);

  return (
    <div className="flex flex-col items-start sm:items-end gap-1.5 w-full">
      <div className="inline-flex flex-col sm:flex-row items-start sm:items-center gap-2.5 w-full sm:justify-end">
        <input
          type="range"
          min={min}
          max={max}
          step={1}
          value={Math.min(max, Math.max(min, value))}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          aria-label={`${label} slider`}
          className="w-full sm:w-32 accent-accent-primary cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed shrink-0"
        />

        <div className="inline-flex items-center gap-1.5">
          <button
            type="button"
            aria-label={`Decrease ${label}`}
            onClick={() => onStep(-1)}
            disabled={disabled || value <= min}
            className="h-8 w-8 flex items-center justify-center rounded-lg border border-border-subtle bg-surface-page text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-35 disabled:pointer-events-none transition-all cursor-pointer font-semibold text-sm select-none shrink-0"
          >
            −
          </button>

          <div className="inline-flex items-center gap-1.5">
            <input
              id={id}
              type="number"
              min={min}
              max={max}
              step={1}
              value={displayVal}
              disabled={disabled}
              onChange={(e) => onChange(e.target.value)}
              onBlur={onBlur}
              aria-describedby={`${id}-help`}
              className="w-20 text-center px-1.5 py-1 font-mono text-sm rounded-lg border border-border-subtle bg-surface-page text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-hidden disabled:opacity-50"
            />
            <span className="text-xs font-mono text-text-muted shrink-0">
              {unit}
            </span>
          </div>

          <button
            type="button"
            aria-label={`Increase ${label}`}
            onClick={() => onStep(1)}
            disabled={disabled || value >= max}
            className="h-8 w-8 flex items-center justify-center rounded-lg border border-border-subtle bg-surface-page text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-35 disabled:pointer-events-none transition-all cursor-pointer font-semibold text-sm select-none shrink-0"
          >
            +
          </button>
        </div>
      </div>
      {hint && <span className="text-[11px] text-text-muted">{hint}</span>}
    </div>
  );
}

export function SegmentedRadioGroup({
  id,
  label,
  value,
  options,
  disabled = false,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: readonly { value: string; label: string }[];
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div
      id={id}
      role="radiogroup"
      aria-label={label}
      className="inline-flex flex-wrap p-1 rounded-xl bg-surface-muted border border-border-subtle gap-1"
    >
      {options.map((opt) => {
        const selected = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
              selected
                ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
