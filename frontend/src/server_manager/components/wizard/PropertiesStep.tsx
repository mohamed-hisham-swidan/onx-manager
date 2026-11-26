import { useState } from "react";
import { Icon } from "@/components/ui/Icon";
import type { WizardData } from "./types";

interface PropertiesStepProps {
  data: WizardData;
  onChange: (d: Partial<WizardData>) => void;
  onNext: () => void;
  onBack: () => void;
}

export function PropertiesStep({ data, onChange, onNext, onBack }: PropertiesStepProps) {
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);

  return (
    <div>
      <h3 className="text-lg font-semibold text-text-primary mb-4">Game Properties</h3>
      <div className="space-y-4">
        {/* Core Properties */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">Gamemode</label>
            <select
              value={data.gamemode}
              onChange={(e) => onChange({ gamemode: e.target.value })}
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            >
              <option value="survival">Survival</option>
              <option value="creative">Creative</option>
              <option value="adventure">Adventure</option>
              <option value="spectator">Spectator</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">Difficulty</label>
            <select
              value={data.difficulty}
              onChange={(e) => onChange({ difficulty: e.target.value })}
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
            >
              <option value="peaceful">Peaceful</option>
              <option value="easy">Easy</option>
              <option value="normal">Normal</option>
              <option value="hard">Hard</option>
            </select>
          </div>
        </div>

        {/* Collapsible Advanced Properties (collapsed by default per D8 / PART_2) */}
        <div className="rounded-xl border border-border-default bg-surface-card overflow-hidden">
          <button
            type="button"
            onClick={() => setIsAdvancedOpen(!isAdvancedOpen)}
            className="w-full flex items-center justify-between p-3.5 text-left text-sm font-medium text-text-primary hover:bg-surface-hover/50 transition-colors cursor-pointer"
          >
            <span className="flex items-center gap-2">
              <Icon name="settings" size={16} className="text-text-muted" />
              <span>Advanced Server Properties</span>
            </span>
            <Icon
              name={isAdvancedOpen ? "chevron-up" : "chevron-down"}
              size={16}
              className="text-text-muted"
            />
          </button>

          {isAdvancedOpen && (
            <div className="p-4 pt-2 border-t border-border-subtle space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1">View Distance</label>
                  <input
                    type="number"
                    value={data.viewDistance}
                    placeholder="10"
                    onChange={(e) =>
                      onChange({ viewDistance: e.target.value === "" ? "" : Number(e.target.value) })
                    }
                    className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-text-secondary mb-1">
                    Simulation Distance
                  </label>
                  <input
                    type="number"
                    value={data.simulationDistance}
                    placeholder="10"
                    onChange={(e) =>
                      onChange({
                        simulationDistance: e.target.value === "" ? "" : Number(e.target.value),
                      })
                    }
                    className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="wizard-spawn-protection"
                    className="block text-sm font-medium text-text-secondary mb-1"
                  >
                    Spawn Protection Radius
                  </label>
                  <input
                    id="wizard-spawn-protection"
                    type="number"
                    value={data.spawnProtection}
                    placeholder="16"
                    onChange={(e) =>
                      onChange({
                        spawnProtection: e.target.value === "" ? "" : Number(e.target.value),
                      })
                    }
                    className="w-full px-3 py-2 rounded-lg border border-border-default bg-surface-page text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
                  />
                </div>
              </div>

              <div className="space-y-3 pt-2 border-t border-border-subtle">
                {([
                  ["PVP", "pvp"],
                  ["Enable Command Blocks", "enableCommandBlock"],
                  ["Online Mode", "onlineMode"],
                  ["Whitelist", "whitelist"],
                ] as const).map(([label, key]) => (
                  <label key={key} className="flex items-center space-x-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={data[key]}
                      onChange={(e) =>
                        onChange({ [key]: e.target.checked } as Partial<WizardData>)
                      }
                      className="rounded border-border-default text-accent-primary focus:ring-accent-primary"
                    />
                    <span className="text-sm text-text-secondary">{label}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
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
          className="px-5 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors shadow-xs cursor-pointer"
        >
          Next
        </button>
      </div>
    </div>
  );
}
