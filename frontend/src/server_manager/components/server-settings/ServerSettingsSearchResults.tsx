import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import type { HostResourceBudget } from "@/types";
import type { ServerDetailResponse } from "@/server_manager/types";
import {
  DistanceSliderControl,
  NumberStepper,
  SegmentedRadioGroup,
  ServerSwitchRow,
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
  MIN_RAM_FLOOR,
  PORT_MAX,
  PORT_MIN,
  RAM_PRESETS,
  SPAWN_PROTECTION_MAX,
  SPAWN_PROTECTION_MIN,
  STARTUP_TIMEOUT_MAX,
  STARTUP_TIMEOUT_MIN,
  filterSearchEntries,
  type NumericDraftKey,
  type SearchRowControlId,
  type ServerSettingsFormState,
  type ServerSettingsTabId,
  type ServerValidationErrors,
} from "./serverSettingsModel";

export interface ServerSettingsSearchResultsProps {
  query: string;
  serverId: string;
  server: ServerDetailResponse;
  form: ServerSettingsFormState;
  rawDrafts: Partial<Record<NumericDraftKey, string>>;
  errors: ServerValidationErrors;
  disabled: boolean;
  isWorkingBranch: boolean;
  gitBacked: boolean;
  activeBranch?: string;
  hostBudget?: HostResourceBudget | null;
  onClearSearch: () => void;
  onJumpToTab: (tab: ServerSettingsTabId) => void;
  onUpdateForm: (patch: Partial<ServerSettingsFormState>) => void;
  onNumericChange: (key: NumericDraftKey, raw: string) => void;
  onNumericBlur: (key: NumericDraftKey) => void;
  onNumericStep: (key: NumericDraftKey, delta: number) => void;
  onApplyRamPreset: (minMb: number, maxMb: number) => void;
}

export function ServerSettingsSearchResults({
  query,
  serverId,
  form,
  rawDrafts,
  errors,
  disabled,
  isWorkingBranch,
  gitBacked,
  activeBranch,
  hostBudget,
  onClearSearch,
  onJumpToTab,
  onUpdateForm,
  onNumericChange,
  onNumericBlur,
  onNumericStep,
  onApplyRamPreset,
}: ServerSettingsSearchResultsProps) {
  const matches = filterSearchEntries(query);
  const maxAllocRam = hostBudget?.allocatable_ram_mb ?? 262144;
  const maxAllocCpus = hostBudget?.allocatable_cpus
    ? Math.max(1, Math.floor(hostBudget.allocatable_cpus))
    : undefined;

  if (matches.length === 0) {
    return (
      <div
        data-testid="search-empty-state"
        className="rounded-xl border border-border-subtle bg-surface-card py-12 px-6 text-center space-y-3"
      >
        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-surface-muted text-text-muted">
          <Icon name="search" size={20} />
        </div>
        <h3 className="text-sm font-semibold text-text-primary">
          No settings match &lsquo;{query.trim()}&rsquo;.
        </h3>
        <p className="text-xs text-text-muted">
          Try another term like port, ram, pvp, or timeout.
        </p>
        <Button type="button" variant="secondary" size="sm" onClick={onClearSearch}>
          Clear Search
        </Button>
      </div>
    );
  }

  const renderSectionBadge = (tabId: ServerSettingsTabId, tabLabel: string) => (
    <button
      type="button"
      onClick={() => {
        onClearSearch();
        onJumpToTab(tabId);
      }}
      className="rounded-md bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-secondary hover:text-accent-primary transition-colors cursor-pointer"
    >
      {tabLabel}
    </button>
  );

  const renderControl = (id: SearchRowControlId, tabId: ServerSettingsTabId, tabLabel: string) => {
    switch (id) {
      case "server-icon": {
        const iconUrl =
          gitBacked && activeBranch && activeBranch !== "main"
            ? `/servers/${serverId}/files?file=server-icon.png&branch=${encodeURIComponent(activeBranch)}`
            : `/servers/${serverId}/files?file=server-icon.png`;
        return (
          <SettingsRow
            id="search-server-icon"
            label="Server Icon"
            description="64×64 PNG shown in multiplayer server lists."
          >
            <div className="flex items-center gap-2">
              {renderSectionBadge(tabId, tabLabel)}
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  onClearSearch();
                  onJumpToTab("general");
                }}
              >
                Manage Icon →
              </Button>
              <Link to={iconUrl} className="sr-only">
                Open server-icon.png
              </Link>
            </div>
          </SettingsRow>
        );
      }
      case "server-name":
        return (
          <SettingsRow
            id="search-server-name"
            label="Server Name"
            description="Display name shown across the panel."
          >
            <div className="w-full space-y-1.5">
              <div className="flex justify-end">
                {renderSectionBadge(tabId, tabLabel)}
              </div>
              <input
                id="search-server-name"
                type="text"
                maxLength={128}
                disabled={disabled}
                value={form.name}
                onChange={(e) => onUpdateForm({ name: e.target.value })}
                className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-1.5 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
              />
              {errors.name && (
                <p className="text-xs font-medium text-status-danger">{errors.name}</p>
              )}
            </div>
          </SettingsRow>
        );
      case "motd":
        return (
          <SettingsRow
            id="search-motd"
            label="MOTD"
            description="Tagline shown in the Minecraft multiplayer list."
          >
            <div className="w-full space-y-1.5">
              <div className="flex justify-end">
                {renderSectionBadge(tabId, tabLabel)}
              </div>
              <input
                id="search-motd"
                type="text"
                disabled={disabled}
                value={form.motd}
                onChange={(e) => onUpdateForm({ motd: e.target.value })}
                className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-1.5 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
              />
            </div>
          </SettingsRow>
        );
      case "server-port":
        return (
          <SettingsRow
            id="search-server-port"
            label="Game Port"
            description="Host TCP/UDP port players connect to."
          >
            <div className="flex flex-col items-end gap-1.5">
              {renderSectionBadge(tabId, tabLabel)}
              <NumberStepper
                id="search-server-port"
                label="Game Port"
                value={form.port}
                draftValue={rawDrafts.port}
                onChange={(v) => onNumericChange("port", v)}
                onBlur={() => onNumericBlur("port")}
                onStep={(d) => onNumericStep("port", d)}
                min={PORT_MIN}
                max={PORT_MAX}
                disabled={disabled || isWorkingBranch}
              />
            </div>
          </SettingsRow>
        );
      case "ram-allocation":
        return (
          <div className="px-5 py-4 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium text-text-primary">
                  Memory Allocation (RAM)
                </p>
                <p className="text-xs text-text-muted">
                  Minimum (-Xms) and maximum (-Xmx) Java heap.
                </p>
              </div>
              {renderSectionBadge(tabId, tabLabel)}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {RAM_PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  disabled={
                    disabled ||
                    Boolean(hostBudget && preset.max > hostBudget.allocatable_ram_mb)
                  }
                  onClick={() => onApplyRamPreset(preset.min, preset.max)}
                  className={`rounded-lg border px-2.5 py-1 text-xs font-semibold cursor-pointer ${
                    form.minRam === preset.min && form.maxRam === preset.max
                      ? "border-accent-primary bg-accent-primary text-accent-contrast-text"
                      : "border-border-subtle bg-surface-muted text-text-secondary"
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-4">
              <NumberStepper
                id="search-min-ram"
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
              <NumberStepper
                id="search-max-ram"
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
            {errors.ram && (
              <p className="text-xs font-medium text-status-danger">{errors.ram}</p>
            )}
          </div>
        );
      case "cpu-cores":
        return (
          <SettingsRow
            id="search-cpu-cores"
            label="CPU Core Limit"
            description="Maximum logical CPU cores (0 = unlimited)."
          >
            <div className="flex flex-col items-end gap-1.5">
              {renderSectionBadge(tabId, tabLabel)}
              <NumberStepper
                id="search-cpu-cores"
                label="CPU Core Limit"
                value={form.cpuCores}
                draftValue={rawDrafts.cpuCores}
                onChange={(v) => onNumericChange("cpuCores", v)}
                onBlur={() => onNumericBlur("cpuCores")}
                onStep={(d) => onNumericStep("cpuCores", d)}
                min={0}
                max={maxAllocCpus}
                disabled={disabled}
              />
            </div>
          </SettingsRow>
        );
      case "startup-timeout":
        return (
          <SettingsRow
            id="search-startup-timeout"
            label="Server Startup Timeout"
            description="Max seconds to wait before marking boot failed."
          >
            <div className="flex flex-col items-end gap-1.5">
              {renderSectionBadge(tabId, tabLabel)}
              <NumberStepper
                id="search-startup-timeout"
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
            </div>
          </SettingsRow>
        );
      case "jvm-args":
        return (
          <SettingsRow
            id="search-jvm-args"
            label="Custom JVM Arguments"
            description="Extra Java flags passed on startup."
            alignTop
          >
            <div className="w-full space-y-1.5">
              <div className="flex justify-end">
                {renderSectionBadge(tabId, tabLabel)}
              </div>
              <textarea
                id="search-jvm-args"
                rows={3}
                disabled={disabled}
                value={form.javaArgs}
                onChange={(e) => onUpdateForm({ javaArgs: e.target.value })}
                className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-1.5 font-mono text-xs text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
              />
              {errors.jvmArgs && (
                <p className="text-xs font-medium text-status-danger">
                  {errors.jvmArgs}
                </p>
              )}
            </div>
          </SettingsRow>
        );
      case "cpu-affinity":
        return (
          <SettingsRow
            id="search-cpu-affinity"
            label="CPU Affinity Mask"
            description="Pin server threads to specific host CPU cores."
          >
            <div className="w-full space-y-1.5">
              <div className="flex justify-end">
                {renderSectionBadge(tabId, tabLabel)}
              </div>
              <input
                id="search-cpu-affinity"
                type="text"
                disabled={disabled}
                value={form.cpuAffinity}
                onChange={(e) => onUpdateForm({ cpuAffinity: e.target.value })}
                placeholder="e.g. 0-3 or 0,2,4"
                className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-1.5 font-mono text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
              />
            </div>
          </SettingsRow>
        );
      case "gamemode":
        return (
          <SettingsRow
            id="search-gamemode"
            label="Default Gamemode"
            description="Initial game mode assigned to joining players."
          >
            <div className="flex flex-col items-end gap-1.5">
              {renderSectionBadge(tabId, tabLabel)}
              <SegmentedRadioGroup
                id="search-gamemode"
                label="Default Gamemode"
                value={form.gamemode}
                options={GAMEMODE_OPTIONS}
                disabled={disabled}
                onChange={(gamemode) => onUpdateForm({ gamemode })}
              />
            </div>
          </SettingsRow>
        );
      case "difficulty":
        return (
          <SettingsRow
            id="search-difficulty"
            label="Difficulty"
            description="World hazard severity and hostile mob damage."
          >
            <div className="flex flex-col items-end gap-1.5">
              {renderSectionBadge(tabId, tabLabel)}
              <SegmentedRadioGroup
                id="search-difficulty"
                label="Difficulty"
                value={form.difficulty}
                options={DIFFICULTY_OPTIONS}
                disabled={disabled}
                onChange={(difficulty) => onUpdateForm({ difficulty })}
              />
            </div>
          </SettingsRow>
        );
      case "max-players":
        return (
          <SettingsRow
            id="search-max-players"
            label="Max Players"
            description="Maximum simultaneous players allowed online."
          >
            <div className="flex flex-col items-end gap-1.5">
              {renderSectionBadge(tabId, tabLabel)}
              <NumberStepper
                id="search-max-players"
                label="Max Players"
                value={form.maxPlayers}
                draftValue={rawDrafts.maxPlayers}
                onChange={(v) => onNumericChange("maxPlayers", v)}
                onBlur={() => onNumericBlur("maxPlayers")}
                onStep={(d) => onNumericStep("maxPlayers", d)}
                min={MAX_PLAYERS_MIN}
                max={MAX_PLAYERS_MAX}
                disabled={disabled}
              />
            </div>
          </SettingsRow>
        );
      case "view-distance":
        return (
          <SettingsRow
            id="search-view-distance"
            label="View Distance"
            description="Chunk radius streamed to each client."
          >
            <div className="flex flex-col items-end gap-1.5 w-full">
              {renderSectionBadge(tabId, tabLabel)}
              <DistanceSliderControl
                id="search-view-distance"
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
              />
            </div>
          </SettingsRow>
        );
      case "simulation-distance":
        return (
          <SettingsRow
            id="search-sim-distance"
            label="Simulation Distance"
            description="Chunk radius where entities and redstone tick."
          >
            <div className="flex flex-col items-end gap-1.5 w-full">
              {renderSectionBadge(tabId, tabLabel)}
              <DistanceSliderControl
                id="search-sim-distance"
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
            </div>
          </SettingsRow>
        );
      case "spawn-protection":
        return (
          <SettingsRow
            id="search-spawn-protection"
            label="Spawn Protection"
            description="Block radius around spawn locked for non-operators."
          >
            <div className="flex flex-col items-end gap-1.5 w-full">
              {renderSectionBadge(tabId, tabLabel)}
              <DistanceSliderControl
                id="search-spawn-protection"
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
              />
            </div>
          </SettingsRow>
        );
      case "online-mode":
      case "whitelist":
      case "enforce-secure-profile":
      case "force-gamemode":
      case "pvp":
      case "hardcore":
      case "enable-command-block":
      case "allow-flight":
      case "allow-nether":
      case "spawn-monsters":
      case "spawn-animals":
      case "spawn-npcs":
      case "generate-structures":
      case "sync-chunk-writes": {
        const switchMeta: Record<
          string,
          { label: string; description: string; key: keyof ServerSettingsFormState }
        > = {
          "online-mode": {
            label: "Online Mode",
            description: "Verify players with Mojang authentication.",
            key: "onlineMode",
          },
          whitelist: {
            label: "Whitelist",
            description: "Allow only players listed in whitelist.json.",
            key: "whitelist",
          },
          "enforce-secure-profile": {
            label: "Enforce Secure Profile",
            description: "Require Mojang-signed keys for player chat.",
            key: "enforceSecureProfile",
          },
          "force-gamemode": {
            label: "Force Gamemode",
            description: "Reset reconnecting players to the default gamemode.",
            key: "forceGamemode",
          },
          pvp: {
            label: "PvP",
            description: "Allow combat damage between players.",
            key: "pvp",
          },
          hardcore: {
            label: "Hardcore Mode",
            description: "Lock or ban players permanently on death.",
            key: "hardcore",
          },
          "enable-command-block": {
            label: "Command Blocks",
            description: "Allow redstone command blocks to execute commands.",
            key: "enableCommandBlock",
          },
          "allow-flight": {
            label: "Allow Flight",
            description: "Prevent automated survival flight kicks.",
            key: "allowFlight",
          },
          "allow-nether": {
            label: "Allow Nether",
            description: "Enable Nether portals and dimension.",
            key: "allowNether",
          },
          "spawn-monsters": {
            label: "Spawn Monsters",
            description: "Spawn hostile mobs in the world.",
            key: "spawnMonsters",
          },
          "spawn-animals": {
            label: "Spawn Animals",
            description: "Spawn passive wildlife across chunks.",
            key: "spawnAnimals",
          },
          "spawn-npcs": {
            label: "Spawn NPCs",
            description: "Spawn villagers and wandering traders.",
            key: "spawnNpcs",
          },
          "generate-structures": {
            label: "Generate Structures",
            description: "Applies to newly generated chunks only.",
            key: "generateStructures",
          },
          "sync-chunk-writes": {
            label: "Sync Chunk Writes",
            description: "Flush chunk saves synchronously to prevent corruption.",
            key: "syncChunkWrites",
          },
        };
        const meta = switchMeta[id];
        return (
          <div className="space-y-0">
            <div className="flex justify-end px-5 pt-2.5">
              {renderSectionBadge(tabId, tabLabel)}
            </div>
            <ServerSwitchRow
              id={`search-${id}`}
              label={meta.label}
              description={meta.description}
              checked={Boolean(form[meta.key])}
              disabled={disabled}
              onChange={(checked) => onUpdateForm({ [meta.key]: checked })}
            />
          </div>
        );
      }
      default: {
        const entry = matches.find((m) => m.id === id)!;
        return (
          <SettingsRow
            id={`search-${id}`}
            label={entry.label}
            description={entry.description}
          >
            <div className="flex items-center gap-2">
              {renderSectionBadge(tabId, tabLabel)}
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  onClearSearch();
                  onJumpToTab(tabId);
                }}
              >
                Open in {tabLabel} →
              </Button>
            </div>
          </SettingsRow>
        );
      }
    }
  };

  return (
    <div className="space-y-4" data-testid="server-settings-search-results">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-text-primary">
          Search Results ({matches.length})
        </h2>
        <button
          type="button"
          onClick={onClearSearch}
          className="text-xs font-medium text-text-secondary hover:text-text-primary cursor-pointer"
        >
          Clear Search
        </button>
      </div>

      <SettingsCard>
        {matches.map((entry) => (
          <div key={entry.id} data-testid={`search-result-${entry.id}`}>
            {renderControl(entry.id, entry.tabId, entry.tabLabel)}
          </div>
        ))}
      </SettingsCard>
    </div>
  );
}
