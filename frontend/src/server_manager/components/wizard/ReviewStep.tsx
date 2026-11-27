import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { FORGE_EDITION_LABELS, forgeEditionForVersion } from "@/server_manager/utils/forgeEdition";
import { resolveJavaMajorForMcVersion } from "@/server_manager/utils/javaRuntime";
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

function CreatingStopwatch() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const startMs = Date.now();
    const timer = window.setInterval(() => {
      setSeconds(Math.max(0, Math.floor((Date.now() - startMs) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);
  const formatted = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(
    seconds % 60,
  ).padStart(2, "0")}`;
  return (
    <span className="font-mono text-[11px] font-semibold text-text-secondary tabular-nums shrink-0">
      {formatted}
    </span>
  );
}

function formatSoftwareDisplay(serverType: string): string {
  switch ((serverType || "").toLowerCase()) {
    case "paper":
      return "Paper";
    case "purpur":
      return "Purpur";
    case "fabric":
      return "Fabric";
    case "forge":
      return "Forge";
    case "neoforge":
      return "NeoForge";
    case "vanilla":
      return "Vanilla";
    case "quilt":
      return "Quilt";
    case "spigot":
      return "Spigot";
    default:
      return serverType ? serverType.charAt(0).toUpperCase() + serverType.slice(1) : "Server";
  }
}

function buildCreationSummaryNote(
  data: WizardData,
  installModpack: boolean,
): string {
  const software = formatSoftwareDisplay(data.serverType);
  const version = data.minecraftVersion || "selected";
  const lower = (data.serverType || "").toLowerCase();
  const usesInstaller = lower === "forge" || lower === "neoforge";
  const coreAction = usesInstaller
    ? `Downloads ${software} ${version} installer, runs loader setup & library verification`
    : `Downloads ${software} ${version}, verifies checksum`;

  const extras: string[] = ["writes server.properties & EULA"];
  if (data.mode === "advanced") {
    extras.push("initializes Git workspace on main");
  }
  if (data.selectedAddons.length > 0) {
    extras.push(`installs ${data.selectedAddons.length} selected add-on${data.selectedAddons.length > 1 ? "s" : ""}`);
  }
  if (installModpack) {
    extras.push("opens the modpack installer");
  }
  extras.push("and prepares the container.");
  return `${coreAction}, ${extras.join(", ")}`;
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
  const minMem = data.minMemoryMb || 1024;
  const maxMem = data.maxMemoryMb || 2048;
  const port = data.port || 25565;
  const javaMajor = resolveJavaMajorForMcVersion(data.minecraftVersion);
  const spawnProtection =
    data.spawnProtection === ""
      ? 16
      : Number.isFinite(Number(data.spawnProtection))
        ? Number(data.spawnProtection)
        : 16;
  const viewDistance = data.viewDistance === "" ? 10 : Number(data.viewDistance) || 10;
  const simulationDistance =
    data.simulationDistance === "" ? 10 : Number(data.simulationDistance) || 10;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold text-text-primary">Review &amp; Create</h3>
          <p className="text-xs text-text-muted">
            Review &amp; Confirm your server configuration before provisioning begins.
          </p>
        </div>
      </div>

      <div
        data-testid="review-confirm-card"
        className="rounded-xl border border-border-default bg-surface-card p-5 space-y-5 shadow-xs text-sm"
      >
        {/* 1. Identity & Mode */}
        <section className="space-y-2.5">
          <h4 className="border-b border-border-subtle pb-1.5 text-xs font-bold uppercase tracking-wider text-text-muted">
            Identity &amp; Mode
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-muted">Name</span>
              <span className="font-semibold text-text-primary text-right">{data.name}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-muted">Mode</span>
              <span className="inline-flex items-center gap-1.5 font-medium text-text-primary">
                <span>{serverModeLabel(data.mode)}</span>
                {data.mode === "advanced" && (
                  <span className="rounded-full border border-accent-primary/30 bg-accent-primary/10 px-2 py-0.5 text-[10px] font-semibold text-accent-primary">
                    Git Versioned
                  </span>
                )}
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-muted">Runtime Provider</span>
              <span className="font-medium text-text-primary">Docker Container</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-muted">Target Port</span>
              <span className="font-mono font-medium text-text-primary tabular-nums">{port}</span>
            </div>
          </div>
        </section>

        {/* 2. Software & Runtime */}
        <section className="space-y-2.5">
          <h4 className="border-b border-border-subtle pb-1.5 text-xs font-bold uppercase tracking-wider text-text-muted">
            Software &amp; Runtime
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-muted">Software</span>
              <LoaderBadge loader={data.serverType} />
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-muted">Minecraft Version</span>
              <span className="font-mono font-medium text-text-primary">
                {data.minecraftVersion}
              </span>
            </div>
            {data.serverType === "forge" && (
              <div className="flex items-center justify-between gap-2">
                <span className="text-text-muted">Forge Edition</span>
                <span className="font-medium text-text-primary">
                  {FORGE_EDITION_LABELS[forgeEditionForVersion(data.minecraftVersion)].label}
                </span>
              </div>
            )}
            <div className="flex items-center justify-between gap-2">
              <span className="text-text-muted">Java Runtime</span>
              <span className="font-mono font-medium text-text-primary">Java {javaMajor}</span>
            </div>
          </div>
        </section>

        {/* 3. Resources */}
        <section className="space-y-2.5">
          <h4 className="border-b border-border-subtle pb-1.5 text-xs font-bold uppercase tracking-wider text-text-muted">
            Resources
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                Memory (RAM)
              </div>
              <div className="mt-0.5 font-mono text-xs font-semibold text-text-primary tabular-nums">
                {minMem} - {maxMem} MB
              </div>
            </div>
            <div className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                CPU Limit
              </div>
              <div className="mt-0.5 font-mono text-xs font-semibold text-text-primary">
                Auto (Unrestricted)
              </div>
            </div>
            <div className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                Startup Timeout
              </div>
              <div className="mt-0.5 font-mono text-xs font-semibold text-text-primary tabular-nums">
                120s (Default)
              </div>
            </div>
          </div>
        </section>

        {/* 4. Gameplay & Properties Summary */}
        <section className="space-y-2.5">
          <h4 className="border-b border-border-subtle pb-1.5 text-xs font-bold uppercase tracking-wider text-text-muted">
            Gameplay &amp; Properties
          </h4>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-xs">
            <div>
              <div className="text-text-muted">Gamemode</div>
              <div className="font-medium capitalize text-text-primary">{data.gamemode}</div>
            </div>
            <div>
              <div className="text-text-muted">Difficulty</div>
              <div className="font-medium capitalize text-text-primary">{data.difficulty}</div>
            </div>
            <div>
              <div className="text-text-muted">Max Players</div>
              <div className="font-mono font-medium text-text-primary tabular-nums">
                {data.maxPlayers || 20}
              </div>
            </div>
            <div>
              <div className="text-text-muted">Online Mode</div>
              <div className="font-medium text-text-primary">
                {data.onlineMode ? "Yes" : "No"}
              </div>
            </div>
            <div>
              <div className="text-text-muted">View Distance</div>
              <div className="font-mono font-medium text-text-primary tabular-nums">
                {viewDistance} chunks
              </div>
            </div>
            <div>
              <div className="text-text-muted">Simulation</div>
              <div className="font-mono font-medium text-text-primary tabular-nums">
                {simulationDistance} chunks
              </div>
            </div>
            <div>
              <div className="text-text-muted">Spawn Protection</div>
              <div className="font-mono font-medium text-text-primary tabular-nums">
                {spawnProtection} blocks
              </div>
            </div>
            <div>
              <div className="text-text-muted">PVP / Whitelist</div>
              <div className="font-medium text-text-primary">
                {data.pvp ? "PVP On" : "PVP Off"} · {data.whitelist ? "Whitelist" : "Open"}
              </div>
            </div>
            {data.levelSeed && data.levelSeed.trim() && (
              <div className="col-span-2">
                <div className="text-text-muted">World Seed</div>
                <div className="font-mono font-medium text-text-primary truncate">
                  {data.levelSeed.trim()}
                </div>
              </div>
            )}
            <div className="col-span-2 sm:col-span-4">
              <div className="text-text-muted">MOTD</div>
              <div className="font-medium text-text-primary truncate">{data.motd}</div>
            </div>
          </div>
        </section>

        {/* 5. Add-ons / Modpack */}
        {((modded && installModpack) || data.selectedAddons.length > 0) && (
          <section className="space-y-2">
            <h4 className="border-b border-border-subtle pb-1.5 text-xs font-bold uppercase tracking-wider text-text-muted">
              {modded ? "Mods & Modpack" : "Plugins"}
            </h4>
            {modded && installModpack && (
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-text-muted">Modpack</span>
                <span className="font-medium text-text-primary">
                  Launch installer immediately after creation
                </span>
              </div>
            )}
            {data.selectedAddons.length > 0 && (
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-text-muted">{addonLabel}</span>
                <span className="font-medium text-text-primary text-right">
                  {data.selectedAddons.length} ({data.selectedAddons.map((a) => a.title).join(", ")})
                </span>
              </div>
            )}
          </section>
        )}

        {/* Clear note of what will happen */}
        <div
          data-testid="review-what-happens-note"
          className="flex items-start gap-2.5 rounded-lg border border-border-subtle bg-surface-muted p-3 text-xs text-text-secondary"
        >
          <Icon name="info" size={15} className="mt-0.5 shrink-0 text-accent-primary" />
          <p>{buildCreationSummaryNote(data, installModpack)}</p>
        </div>
      </div>

      {(statusMessage || creating) && (
        <div
          role="status"
          className="flex items-center justify-between gap-3 rounded-xl border border-accent-primary/30 bg-accent-primary/10 px-4 py-2.5 text-xs font-medium text-text-primary"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-accent-primary/30 border-t-accent-primary" />
            <span className="truncate">
              {statusMessage ||
                `Provisioning ${formatSoftwareDisplay(data.serverType)} ${data.minecraftVersion}...`}
            </span>
          </div>
          {creating && <CreatingStopwatch />}
        </div>
      )}

      <div className="flex justify-between pt-2">
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
          className="inline-flex items-center gap-2 px-6 py-2.5 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-semibold disabled:opacity-50 transition-colors shadow-xs cursor-pointer"
        >
          {creating ? (
            <>
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent-contrast-text/40 border-t-accent-contrast-text" />
              <span>{statusMessage || "Creating..."}</span>
            </>
          ) : (
            <span>Create Server</span>
          )}
        </button>
      </div>
    </div>
  );
}
