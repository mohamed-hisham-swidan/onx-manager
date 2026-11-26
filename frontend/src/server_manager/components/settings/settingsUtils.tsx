import React from "react";
import { Icon } from "@/components/ui/Icon";

export function RestartBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium bg-status-warning-bg text-status-warning border border-status-warning-border shrink-0"
      title="Requires a backend restart to take effect"
    >
      <Icon name="info" size={11} />
      Restart required
    </span>
  );
}

export interface SettingRowProps {
  id: string;
  label: string;
  description: string;
  propertyKey: string;
  hasRestart?: boolean;
  children: React.ReactNode;
}

export function SettingRow({
  id,
  label,
  description,
  propertyKey,
  hasRestart,
  children,
}: SettingRowProps) {
  return (
    <div
      data-property-key={propertyKey}
      className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 px-5 py-4 border-b border-border-subtle last:border-b-0"
    >
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={id} className="text-sm font-medium text-text-primary cursor-pointer">
            {label}
          </label>
          {hasRestart && <RestartBadge />}
        </div>
        <p id={`${id}-help`} className="text-xs text-text-muted leading-relaxed">
          {description}
        </p>
      </div>
      <div className="w-full sm:w-auto sm:min-w-[220px] flex flex-col items-start sm:items-end gap-2">
        {children}
      </div>
    </div>
  );
}

export interface NumberStepperProps {
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
  disabled?: boolean;
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
}: NumberStepperProps) {
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
          onChange={onChange}
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
