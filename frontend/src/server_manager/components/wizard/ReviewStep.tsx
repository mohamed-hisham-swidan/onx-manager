import { FORGE_EDITION_LABELS, forgeEditionForVersion } from "@/server_manager/utils/forgeEdition";
import { serverModeLabel } from "@/server_manager/utils/serverMode";
import type { WizardData } from "./types";

interface ReviewStepProps {
  data: WizardData;
  creating: boolean;
  onCreate: () => void;
  onBack: () => void;
}

export function ReviewStep({ data, creating, onCreate, onBack }: ReviewStepProps) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-text-primary mb-4">Review &amp; Create</h3>
      <div className="bg-surface-card rounded-xl border border-border-default p-4 space-y-2 text-sm shadow-xs">
        {[
          ["Name", data.name],
          ["Mode", serverModeLabel(data.mode)],
          ["Runtime Provider", data.provider === "docker" ? "Docker Container" : "Host Process"],
          ["Software", data.serverType],
          ...(data.serverType === "forge"
            ? [
                [
                  "Forge Edition",
                  FORGE_EDITION_LABELS[forgeEditionForVersion(data.minecraftVersion)].label,
                ] as [string, string],
              ]
            : []),
          ["Version", data.minecraftVersion],
          ["Port", String(data.port || 25565)],
          ["Max Players", String(data.maxPlayers || 20)],
          ["RAM", `${data.minMemoryMb || 1024} - ${data.maxMemoryMb || 2048} MB`],
          ["MOTD", data.motd],
          ["Gamemode", data.gamemode],
          ["Difficulty", data.difficulty],
          ["PVP", data.pvp ? "Yes" : "No"],
          ["Online Mode", data.onlineMode ? "Yes" : "No"],
          ["Whitelist", data.whitelist ? "Yes" : "No"],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between py-1 border-b border-border-subtle last:border-none">
            <span className="text-text-muted">{label}</span>
            <span className="text-text-primary font-medium">{value}</span>
          </div>
        ))}
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
          onClick={onCreate}
          disabled={creating}
          className="px-6 py-2 rounded-lg bg-status-success hover:bg-status-success/90 text-white text-sm font-semibold disabled:opacity-50 transition-colors shadow-xs cursor-pointer"
        >
          {creating ? "Creating..." : "Create Server"}
        </button>
      </div>
    </div>
  );
}
