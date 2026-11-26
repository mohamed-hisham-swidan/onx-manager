import { ServerSwitchRow, SettingsCard } from "./ServerSettingsControls";
import type { ServerSettingsFormState } from "./serverSettingsModel";

export interface RulesSecurityTabProps {
  form: ServerSettingsFormState;
  disabled: boolean;
  onUpdateForm: (patch: Partial<ServerSettingsFormState>) => void;
}

export function RulesSecurityTab({
  form,
  disabled,
  onUpdateForm,
}: RulesSecurityTabProps) {
  return (
    <div className="space-y-6" data-testid="server-settings-tab-rules">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight text-text-primary">
          Rules &amp; Security
        </h2>
        <p className="text-xs text-text-muted">
          Access rules, combat settings, and entity spawning.
        </p>
      </header>

      <SettingsCard title="Access & Security">
        <ServerSwitchRow
          id="srv-setting-online-mode"
          label="Online Mode"
          description="Verify players with Mojang authentication."
          badge={!form.onlineMode ? "Critical" : undefined}
          hint={!form.onlineMode ? "Cracked / offline launchers allowed" : null}
          icon="globe"
          checked={form.onlineMode}
          disabled={disabled}
          onChange={(onlineMode) => onUpdateForm({ onlineMode })}
        />
        <ServerSwitchRow
          id="srv-setting-whitelist"
          label="Whitelist"
          description="Allow only players listed in whitelist.json."
          icon="users"
          checked={form.whitelist}
          disabled={disabled}
          onChange={(whitelist) => onUpdateForm({ whitelist })}
        />
        <ServerSwitchRow
          id="srv-setting-enforce-secure-profile"
          label="Enforce Secure Profile"
          description="Require Mojang-signed keys for player chat."
          icon="shield"
          checked={form.enforceSecureProfile}
          disabled={disabled}
          onChange={(enforceSecureProfile) =>
            onUpdateForm({ enforceSecureProfile })
          }
        />
        <ServerSwitchRow
          id="srv-setting-force-gamemode"
          label="Force Gamemode"
          description="Reset reconnecting players to the default gamemode."
          icon="sliders"
          checked={form.forceGamemode}
          disabled={disabled}
          onChange={(forceGamemode) => onUpdateForm({ forceGamemode })}
        />
      </SettingsCard>

      <SettingsCard title="Combat & Players">
        <ServerSwitchRow
          id="srv-setting-pvp"
          label="PvP"
          description="Allow combat damage between players."
          icon="activity"
          checked={form.pvp}
          disabled={disabled}
          onChange={(pvp) => onUpdateForm({ pvp })}
        />
        <ServerSwitchRow
          id="srv-setting-hardcore"
          label="Hardcore Mode"
          description="Lock or ban players permanently on death."
          icon="alert"
          checked={form.hardcore}
          disabled={disabled}
          onChange={(hardcore) => onUpdateForm({ hardcore })}
        />
        <ServerSwitchRow
          id="srv-setting-command-block"
          label="Command Blocks"
          description="Allow redstone command blocks to execute commands."
          icon="terminal"
          checked={form.enableCommandBlock}
          disabled={disabled}
          onChange={(enableCommandBlock) =>
            onUpdateForm({ enableCommandBlock })
          }
        />
        <ServerSwitchRow
          id="srv-setting-allow-flight"
          label="Allow Flight"
          description="Prevent automated survival flight kicks."
          icon="paper"
          checked={form.allowFlight}
          disabled={disabled}
          onChange={(allowFlight) => onUpdateForm({ allowFlight })}
        />
      </SettingsCard>

      <SettingsCard title="Dimensions & Entities">
        <ServerSwitchRow
          id="srv-setting-allow-nether"
          label="Allow Nether"
          description="Enable Nether portals and dimension."
          icon="globe"
          checked={form.allowNether}
          disabled={disabled}
          onChange={(allowNether) => onUpdateForm({ allowNether })}
        />
        <ServerSwitchRow
          id="srv-setting-spawn-monsters"
          label="Spawn Monsters"
          description="Spawn hostile mobs in the world."
          icon="alert"
          checked={form.spawnMonsters}
          disabled={disabled}
          onChange={(spawnMonsters) => onUpdateForm({ spawnMonsters })}
        />
        <ServerSwitchRow
          id="srv-setting-spawn-animals"
          label="Spawn Animals"
          description="Spawn passive wildlife across chunks."
          icon="heart"
          checked={form.spawnAnimals}
          disabled={disabled}
          onChange={(spawnAnimals) => onUpdateForm({ spawnAnimals })}
        />
        <ServerSwitchRow
          id="srv-setting-spawn-npcs"
          label="Spawn NPCs"
          description="Spawn villagers and wandering traders."
          icon="users"
          checked={form.spawnNpcs}
          disabled={disabled}
          onChange={(spawnNpcs) => onUpdateForm({ spawnNpcs })}
        />
      </SettingsCard>

      <SettingsCard title="World Mechanics">
        <ServerSwitchRow
          id="srv-setting-generate-structures"
          label="Generate Structures"
          description="Applies to newly generated chunks only."
          icon="world"
          checked={form.generateStructures}
          disabled={disabled}
          onChange={(generateStructures) =>
            onUpdateForm({ generateStructures })
          }
        />
        <ServerSwitchRow
          id="srv-setting-sync-chunk-writes"
          label="Sync Chunk Writes"
          description="Flush chunk saves synchronously to prevent corruption."
          icon="file"
          checked={form.syncChunkWrites}
          disabled={disabled}
          onChange={(syncChunkWrites) => onUpdateForm({ syncChunkWrites })}
        />
      </SettingsCard>
    </div>
  );
}
