import { type WizardData, RAM_PRESETS } from "./types";
import { ServerModeChooser } from "./ServerModeChooser";

interface RamStepperFieldProps {
  label: string;
  value: number | "";
  placeholder: string;
  onChange: (val: number | "") => void;
}

export function RamStepperField({
  label,
  value,
  placeholder,
  onChange,
}: RamStepperFieldProps) {
  const gbDisplay =
    typeof value === "number" && value > 0
      ? value >= 1024
        ? `${(value / 1024).toFixed(value % 1024 === 0 ? 0 : 1)} GB`
        : `${value} MB`
      : "";

  const stepBy = (delta: number) => {
    const base = typeof value === "number" && value > 0 ? value : Number(placeholder) || 1024;
    const next = Math.max(512, base + delta);
    onChange(next);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="block text-xs font-semibold text-text-secondary uppercase tracking-wider">
          {label}
        </label>
        {gbDisplay && (
          <span className="text-[11px] font-bold text-accent-primary bg-accent-primary/20 px-2 py-0.5 rounded-full border border-accent-primary/40">
            {gbDisplay}
          </span>
        )}
      </div>
      <div className="relative flex items-stretch rounded-lg border border-border-default bg-surface-page focus-within:ring-2 focus-within:ring-accent-primary focus-within:border-accent-primary shadow-xs overflow-hidden">
        <button
          type="button"
          onClick={() => stepBy(-512)}
          aria-label={`Decrease ${label} by 512 MB`}
          className="flex items-center justify-center px-3 text-xs font-bold text-text-secondary bg-surface-card hover:bg-surface-hover active:opacity-75 border-r border-border-default transition-colors select-none cursor-pointer"
        >
          <span className="text-text-muted mr-0.5">▼</span> -512
        </button>
        <div className="relative flex-1 flex items-center">
          <input
            type="number"
            step={512}
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
            className="w-full h-10 px-3 text-sm text-center font-semibold text-text-primary bg-transparent focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
          />
          <span className="absolute right-3 text-xs text-text-muted pointer-events-none font-medium">
            MB
          </span>
        </div>
        <button
          type="button"
          onClick={() => stepBy(512)}
          aria-label={`Increase ${label} by 512 MB`}
          className="flex items-center justify-center px-3 text-xs font-bold text-text-secondary bg-surface-card hover:bg-surface-hover active:opacity-75 border-l border-border-default transition-colors select-none cursor-pointer"
        >
          +512 <span className="text-text-muted ml-0.5">▲</span>
        </button>
      </div>
    </div>
  );
}

interface ConfigStepProps {
  data: WizardData;
  dockerAvailable?: boolean | null;
  onChange: (d: Partial<WizardData>) => void;
  onNext: () => void;
  onBack: () => void;
}

export function ConfigStep({
  data,
  dockerAvailable,
  onChange,
  onNext,
  onBack,
}: ConfigStepProps) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-text-primary mb-4">Server Configuration</h3>
      <div className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">Server Name</label>
          <input
            value={data.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="My Awesome Server"
            required
            className="w-full px-3.5 py-2.5 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary shadow-xs"
          />
        </div>

        <ServerModeChooser
          value={data.mode}
          onChange={(mode) => onChange({ mode })}
        />

        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">
            Runtime Provider
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => onChange({ provider: "" })}
              className={`text-left p-3.5 rounded-xl border-2 transition-all cursor-pointer ${
                !data.provider
                  ? "border-accent-primary bg-accent-primary/15 shadow-xs"
                  : "border-border-default hover:border-accent-primary bg-surface-card"
              }`}
              title="Runs natively on the host via tmux/Win32"
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-text-primary">
                  Host Process
                </span>
                <span className="text-[10px] bg-surface-hover text-text-secondary px-1.5 py-0.5 rounded font-medium">
                  Default
                </span>
              </div>
              <div className="text-xs text-text-muted mt-0.5">
                Runs natively on the host via tmux / Win32
              </div>
            </button>

            <button
              type="button"
              disabled={dockerAvailable === false}
              onClick={() => onChange({ provider: "docker" })}
              className={`text-left p-3.5 rounded-xl border-2 transition-all cursor-pointer ${
                dockerAvailable === false
                  ? "opacity-50 cursor-not-allowed border-border-subtle bg-surface-page/50"
                  : data.provider === "docker"
                    ? "border-accent-primary bg-accent-primary/15 shadow-xs"
                    : "border-border-default hover:border-accent-primary bg-surface-card"
              }`}
              title="Runs isolated in a Docker container"
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sm text-text-primary">
                  Docker Container
                </span>
                {dockerAvailable === false && (
                  <span className="text-[10px] bg-status-warning-bg text-status-warning px-1.5 py-0.5 rounded font-medium border border-status-warning/30">
                    Docker daemon not detected
                  </span>
                )}
                {dockerAvailable === true && (
                  <span className="text-[10px] bg-status-success-bg text-status-success px-1.5 py-0.5 rounded font-medium border border-status-success/30">
                    Daemon ready
                  </span>
                )}
              </div>
              <div className="text-xs text-text-muted mt-0.5">
                Runs isolated in a Docker container
              </div>
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">Port</label>
            <input
              type="number"
              value={data.port}
              placeholder="25565"
              onChange={(e) => onChange({ port: e.target.value === "" ? "" : Number(e.target.value) })}
              className="w-full px-3.5 py-2.5 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary shadow-xs"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">Max Players</label>
            <input
              type="number"
              value={data.maxPlayers}
              placeholder="20"
              onChange={(e) => onChange({ maxPlayers: e.target.value === "" ? "" : Number(e.target.value) })}
              className="w-full px-3.5 py-2.5 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary shadow-xs"
            />
          </div>
        </div>

        <div className="rounded-xl border border-border-default bg-surface-card p-4 space-y-3.5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <RamStepperField
              label="Min RAM"
              value={data.minMemoryMb}
              placeholder="1024"
              onChange={(v) => onChange({ minMemoryMb: v })}
            />
            <RamStepperField
              label="Max RAM"
              value={data.maxMemoryMb}
              placeholder="2048"
              onChange={(v) => onChange({ maxMemoryMb: v })}
            />
          </div>
          <div>
            <div className="text-xs font-semibold text-text-muted mb-2 uppercase tracking-wider">
              Quick Memory Presets
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-9 gap-1.5">
              {RAM_PRESETS.map((preset) => {
                const isActive = data.minMemoryMb === preset.min && data.maxMemoryMb === preset.max;
                return (
                  <button
                    type="button"
                    key={preset.label}
                    onClick={() => onChange({ minMemoryMb: preset.min, maxMemoryMb: preset.max })}
                    className={`py-1.5 px-2 text-xs font-semibold rounded-lg border transition-all text-center cursor-pointer ${
                      isActive
                        ? "bg-accent-primary text-white border-accent-primary shadow-xs ring-2 ring-accent-primary/30"
                        : "bg-surface-page border-border-default text-text-primary hover:border-accent-primary hover:bg-surface-hover"
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-text-secondary mb-1">MOTD</label>
          <input
            value={data.motd}
            onChange={(e) => onChange({ motd: e.target.value })}
            className="w-full px-3.5 py-2.5 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary shadow-xs"
          />
        </div>
      </div>

      <div className="flex justify-between mt-6">
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-accent-primary hover:underline cursor-pointer"
        >
          Back
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!data.name.trim()}
          className="px-5 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-white text-sm font-medium disabled:opacity-50 transition-colors shadow-xs cursor-pointer"
        >
          Next
        </button>
      </div>
    </div>
  );
}
