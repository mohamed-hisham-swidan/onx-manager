import {
  DistanceSliderControl,
  NumberStepper,
  SegmentedRadioGroup,
  SettingsCard,
  SettingsRow,
} from "./ServerSettingsControls";
import {
  DIFFICULTY_OPTIONS,
  DISTANCE_MAX,
  DISTANCE_MIN,
  GAMEMODE_OPTIONS,
  MAX_PLAYERS_MAX,
  MAX_PLAYERS_MIN,
  MAX_PLAYERS_PRESETS,
  SPAWN_PROTECTION_MAX,
  SPAWN_PROTECTION_MIN,
  type NumericDraftKey,
  type ServerSettingsFormState,
  type ServerValidationErrors,
} from "./serverSettingsModel";

function viewDistanceHint(chunks: number): string {
  if (chunks <= 8) return `${chunks} chunks · Light`;
  if (chunks <= 12) return `${chunks} chunks · Balanced`;
  if (chunks <= 16) return `${chunks} chunks · Heavy`;
  return `${chunks} chunks · High RAM/CPU`;
}

export interface GameplayWorldTabProps {
  form: ServerSettingsFormState;
  rawDrafts: Partial<Record<NumericDraftKey, string>>;
  errors: ServerValidationErrors;
  disabled: boolean;
  onUpdateForm: (patch: Partial<ServerSettingsFormState>) => void;
  onNumericChange: (key: NumericDraftKey, raw: string) => void;
  onNumericBlur: (key: NumericDraftKey) => void;
  onNumericStep: (key: NumericDraftKey, delta: number) => void;
}

export function GameplayWorldTab({
  form,
  rawDrafts,
  errors,
  disabled,
  onUpdateForm,
  onNumericChange,
  onNumericBlur,
  onNumericStep,
}: GameplayWorldTabProps) {
  return (
    <div className="space-y-6" data-testid="server-settings-tab-gameplay">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight text-text-primary">
          Gameplay &amp; World
        </h2>
        <p className="text-xs text-text-muted">
          Gamemode, difficulty, player cap, and world distances.
        </p>
      </header>

      <SettingsCard title="Core Gameplay">
        <SettingsRow
          id="srv-setting-gamemode"
          label="Default Gamemode"
          description="Initial game mode assigned to joining players."
        >
          <SegmentedRadioGroup
            id="srv-setting-gamemode"
            label="Default Gamemode"
            value={form.gamemode}
            options={GAMEMODE_OPTIONS}
            disabled={disabled}
            onChange={(gamemode) => onUpdateForm({ gamemode })}
          />
        </SettingsRow>

        <SettingsRow
          id="srv-setting-difficulty"
          label="Difficulty"
          description="World hazard severity and hostile mob damage."
        >
          <SegmentedRadioGroup
            id="srv-setting-difficulty"
            label="Difficulty"
            value={form.difficulty}
            options={DIFFICULTY_OPTIONS}
            disabled={disabled}
            onChange={(difficulty) => onUpdateForm({ difficulty })}
          />
        </SettingsRow>

        <SettingsRow
          id="srv-setting-max-players"
          label="Max Players"
          description="Maximum simultaneous players allowed online."
          alignTop
        >
          <div className="flex flex-col items-start sm:items-end gap-2 w-full">
            <NumberStepper
              id="srv-setting-max-players"
              name="max-players"
              label="Max Players"
              value={form.maxPlayers}
              draftValue={rawDrafts.maxPlayers}
              onChange={(v) => onNumericChange("maxPlayers", v)}
              onBlur={() => onNumericBlur("maxPlayers")}
              onStep={(d) => onNumericStep("maxPlayers", d)}
              min={MAX_PLAYERS_MIN}
              max={MAX_PLAYERS_MAX}
              step={1}
              disabled={disabled}
            />
            <div className="flex flex-wrap gap-1.5">
              {MAX_PLAYERS_PRESETS.map((cap) => (
                <button
                  key={cap}
                  type="button"
                  disabled={disabled}
                  onClick={() => onUpdateForm({ maxPlayers: cap })}
                  className={`rounded-md border px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer disabled:opacity-45 ${
                    form.maxPlayers === cap
                      ? "border-accent-primary bg-accent-primary/12 text-accent-primary"
                      : "border-border-subtle bg-surface-muted text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {cap}
                </button>
              ))}
            </div>
            {errors.maxPlayers && (
              <p className="text-xs font-medium text-status-danger">
                {errors.maxPlayers}
              </p>
            )}
          </div>
        </SettingsRow>
      </SettingsCard>

      <SettingsCard title="World & Chunk Distances">
        <SettingsRow
          id="srv-setting-view-distance"
          label="View Distance"
          description="Chunk radius streamed to each client."
        >
          <DistanceSliderControl
            id="srv-setting-view-distance"
            label="View Distance"
            value={form.viewDistance}
            draftValue={rawDrafts.viewDistance}
            onChange={(v) => onNumericChange("viewDistance", v)}
            onBlur={() => onNumericBlur("viewDistance")}
            onStep={(d) => onNumericStep("viewDistance", d)}
            min={DISTANCE_MIN}
            max={DISTANCE_MAX}
            unit="chunks"
            disabled={disabled}
            hint={viewDistanceHint(form.viewDistance)}
          />
        </SettingsRow>

        <SettingsRow
          id="srv-setting-sim-distance"
          label="Simulation Distance"
          description="Chunk radius where entities and redstone tick."
        >
          <DistanceSliderControl
            id="srv-setting-sim-distance"
            label="Simulation Distance"
            value={form.simulationDistance}
            draftValue={rawDrafts.simulationDistance}
            onChange={(v) => onNumericChange("simulationDistance", v)}
            onBlur={() => onNumericBlur("simulationDistance")}
            onStep={(d) => onNumericStep("simulationDistance", d)}
            min={DISTANCE_MIN}
            max={DISTANCE_MAX}
            unit="chunks"
            disabled={disabled}
          />
        </SettingsRow>

        <SettingsRow
          id="srv-setting-spawn-protection"
          label="Spawn Protection"
          description="Block radius around spawn locked for non-operators."
        >
          <DistanceSliderControl
            id="srv-setting-spawn-protection"
            label="Spawn Protection"
            value={form.spawnProtection}
            draftValue={rawDrafts.spawnProtection}
            onChange={(v) => onNumericChange("spawnProtection", v)}
            onBlur={() => onNumericBlur("spawnProtection")}
            onStep={(d) => onNumericStep("spawnProtection", d)}
            min={SPAWN_PROTECTION_MIN}
            max={SPAWN_PROTECTION_MAX}
            unit="blocks"
            disabled={disabled}
            hint={form.spawnProtection === 0 ? "0 = disabled" : null}
          />
        </SettingsRow>
      </SettingsCard>
    </div>
  );
}
