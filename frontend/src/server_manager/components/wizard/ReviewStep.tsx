import { FORGE_EDITION_LABELS, forgeEditionForVersion } from "@/server_manager/utils/forgeEdition";
import { serverModeLabel } from "@/server_manager/utils/serverMode";
import { isModpackSupportedLoader } from "@/server_manager/utils/loaderCapabilities";
import type { WizardData } from "./types";

interface ReviewStepProps {
  data: WizardData;
  creating: boolean;
  installModpack?: boolean;
  statusMessage?: string | null;
  onCreate: () => void;
  onBack: () => void;
}

export function ReviewStep({
  data,
  creating,
  installModpack = false,
  statusMessage = null,
  onCreate,
  onBack,
}: ReviewStepProps) {
  const modded = isModpackSupportedLoader(data.serverType);
  const addonLabel = modded ? "Selected Mods" : "Selected Plugins";
  const rows: [string, string][] = [
    ["Name", data.name],
    ["Mode", serverModeLabel(data.mode)],
    ["Runtime Provider", "Docker Container"],
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
    ...(modded && installModpack
      ? [["Modpack", "Launch installer immediately after creation"] as [string, string]]
      : []),
    ...(data.selectedAddons.length > 0
      ? [
          [
            addonLabel,
            `${data.selectedAddons.length} (${data.selectedAddons.map((a) => a.title).join(", ")})`,
          ] as [string, string],
        ]
      : []),
  ];

  return (
    <div>
      <h3 className="text-lg font-semibold text-text-primary mb-4">Review &amp; Create</h3>
      <div className="bg-surface-card rounded-xl border border-border-default p-4 space-y-2 text-sm shadow-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4 py-1 border-b border-border-subtle last:border-none">
            <span className="shrink-0 text-text-muted">{label}</span>
            <span className="text-text-primary font-medium text-right">{value}</span>
          </div>
        ))}
      </div>
      {statusMessage && (
        <div
          role="status"
          className="mt-4 rounded-xl border border-accent-primary/30 bg-accent-primary/10 px-4 py-2.5 text-xs font-medium text-text-primary"
        >
          {statusMessage}
        </div>
      )}
      <div className="flex justify-between mt-6">
        <button
          type="button"
          onClick={onBack}
          disabled={creating}
          className="text-sm text-accent-primary hover:underline cursor-pointer disabled:opacity-50"
        >
          Back
        </button>
        <button
          type="button"
          onClick={onCreate}
          disabled={creating}
          className="px-6 py-2 rounded-lg bg-status-success hover:bg-status-success/90 text-white text-sm font-semibold disabled:opacity-50 transition-colors shadow-xs cursor-pointer"
        >
          {creating ? (statusMessage || "Creating...") : "Create Server"}
        </button>
      </div>
    </div>
  );
}
