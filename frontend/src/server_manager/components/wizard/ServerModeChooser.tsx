import type { ServerMode } from "@/server_manager/types";

interface ServerModeChooserProps {
  value: ServerMode;
  onChange: (mode: ServerMode) => void;
  disabled?: boolean;
  advancedEnabled?: boolean;
}

export function ServerModeChooser({
  value,
  onChange,
  disabled = false,
  advancedEnabled = false,
}: ServerModeChooserProps) {
  const isSimple = value === "simple";
  const isAdvanced = value === "advanced";

  return (
    <div>
      <label className="block text-sm font-medium text-text-secondary mb-1">
        Server Mode
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <button
          type="button"
          data-testid="server-mode-simple"
          onClick={() => onChange("simple")}
          disabled={disabled}
          className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
            isSimple
              ? "border-accent-primary bg-accent-primary/15 shadow-xs"
              : "border-border-default hover:border-accent-primary bg-surface-card"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold text-sm text-text-primary">
              Simple
            </span>
            {isSimple && (
              <span className="text-[10px] bg-status-success-bg text-status-success px-1.5 py-0.5 rounded font-medium border border-status-success/30">
                Active
              </span>
            )}
          </div>
          <div className="text-xs text-text-muted mt-0.5">
            Git-free server. Recommended for most servers.
          </div>
        </button>

        {advancedEnabled && (
          <button
            type="button"
            data-testid="server-mode-advanced"
            onClick={() => onChange("advanced")}
            disabled={disabled}
            className={`p-3.5 rounded-xl border text-left transition-all cursor-pointer ${
              isAdvanced
                ? "border-accent-primary bg-accent-primary/15 shadow-xs"
                : "border-border-default hover:border-accent-primary bg-surface-card"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-semibold text-sm text-text-primary">
                Advanced
              </span>
              <span className="text-[10px] bg-accent-primary/15 text-accent-primary px-1.5 py-0.5 rounded font-medium border border-accent-primary/30">
                POSIX Advanced
              </span>
            </div>
            <div className="text-xs text-text-muted mt-0.5">
              Git-backed server with branches, safe upgrades, and commit history.
            </div>
          </button>
        )}
      </div>
    </div>
  );
}
