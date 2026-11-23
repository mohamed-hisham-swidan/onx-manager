import { useState, useMemo, useId } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "@/components/ui/Icon";
import { useUpdateServer } from "@/server_manager/hooks/useServers";
import { useHostResources } from "@/server_manager/hooks/useHostResources";
import { HostResourceBudgetBar } from "@/server_manager/components/HostResourceBudgetBar";
import { toast } from "@/stores/toastStore";
import type { ServerDetailResponse, ServerUpdateRequest } from "@/server_manager/types";

interface ServerSettingsSectionProps {
  serverId: string;
  server: ServerDetailResponse;
  branch?: string;
  gitBacked?: boolean;
}

type SettingsCategory = "all" | "identity" | "resources" | "gameplay" | "rules" | "advanced";

interface CategoryTab {
  id: SettingsCategory;
  label: string;
  icon: IconName;
}

const CATEGORY_TABS: CategoryTab[] = [
  { id: "all", label: "All Settings", icon: "settings" },
  { id: "identity", label: "Identity & Network", icon: "server" },
  { id: "resources", label: "Resources & JVM", icon: "cpu" },
  { id: "gameplay", label: "Gameplay & World", icon: "activity" },
  { id: "rules", label: "Rules & Security", icon: "check" },
  { id: "advanced", label: "Advanced & Files", icon: "file" },
];

const KNOWN_KEY_LABELS: Record<string, string> = {
  "server-name": "Server Name",
  "server_name": "Server Name",
  "name": "Server Name",
  "server-port": "Server Port",
  "server_port": "Server Port",
  "port": "Server Port",
  "motd": "MOTD",
  "gamemode": "Gamemode",
  "difficulty": "Difficulty",
  "max-players": "Player Capacity",
  "max_players": "Player Capacity",
  "spawn-protection": "Spawn Protection",
  "spawn_protection": "Spawn Protection",
  "view-distance": "View Distance",
  "view_distance": "View Distance",
  "simulation-distance": "Simulation Distance",
  "simulation_distance": "Simulation Distance",
  "pvp": "PvP toggle",
  "online-mode": "Online Mode toggle",
  "online_mode": "Online Mode toggle",
  "white-list": "Whitelist Enforcement toggle",
  "whitelist": "Whitelist Enforcement toggle",
  "enable-command-block": "Command Blocks toggle",
  "enable_command_block": "Command Blocks toggle",
  "allow-flight": "Allow Flight toggle",
  "allow_flight": "Allow Flight toggle",
  "spawn-monsters": "Spawn Monsters toggle",
  "spawn_monsters": "Spawn Monsters toggle",
  "spawn-animals": "Spawn Animals toggle",
  "spawn_animals": "Spawn Animals toggle",
  "spawn-npcs": "Spawn NPCs toggle",
  "spawn_npcs": "Spawn NPCs toggle",
  "allow-nether": "Allow Nether toggle",
  "allow_nether": "Allow Nether toggle",
  "hardcore": "Hardcore Mode toggle",
  "force-gamemode": "Force Gamemode toggle",
  "force_gamemode": "Force Gamemode toggle",
  "enforce-secure-profile": "Enforce Secure Profile toggle",
  "enforce_secure_profile": "Enforce Secure Profile toggle",
  "generate-structures": "Generate Structures toggle",
  "generate_structures": "Generate Structures toggle",
  "sync-chunk-writes": "Sync Chunk Writes toggle",
  "sync_chunk_writes": "Sync Chunk Writes toggle",
};

const KNOWN_PROPERTY_KEYS = new Set(Object.keys(KNOWN_KEY_LABELS));

function parseBool(val: unknown, defaultVal = false): boolean {
  if (typeof val === "boolean") return val;
  if (typeof val === "string") {
    const s = val.toLowerCase().trim();
    if (s === "true" || s === "1" || s === "yes" || s === "on") return true;
    if (s === "false" || s === "0" || s === "no" || s === "off") return false;
  }
  return defaultVal;
}

function parseAffinity(affinity: string): boolean {
  if (!affinity) return true;
  const regex = /^[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*$/;
  if (!regex.test(affinity)) return false;
  const parts = affinity.replace(/,/g, " ").split(/\s+/);
  for (const part of parts) {
    if (part.includes("-")) {
      const [start, end] = part.split("-").map(Number);
      if (isNaN(start) || isNaN(end) || start < 0 || end < 0 || start > end) {
        return false;
      }
    } else {
      const num = Number(part);
      if (isNaN(num) || num < 0) return false;
    }
  }
  return true;
}

const RAM_PRESETS = [
  { label: "1 GB", min: 512, max: 1024 },
  { label: "2 GB", min: 1024, max: 2048 },
  { label: "4 GB", min: 2048, max: 4096 },
  { label: "6 GB", min: 3072, max: 6144 },
  { label: "8 GB", min: 4096, max: 8192 },
  { label: "16 GB", min: 8192, max: 16384 },
];

const GAMEMODE_OPTIONS = [
  { value: "survival", label: "Survival" },
  { value: "creative", label: "Creative" },
  { value: "adventure", label: "Adventure" },
  { value: "spectator", label: "Spectator" },
];

const DIFFICULTY_OPTIONS = [
  { value: "peaceful", label: "Peaceful" },
  { value: "easy", label: "Easy" },
  { value: "normal", label: "Normal" },
  { value: "hard", label: "Hard" },
];

interface SplitRowProps {
  id: string;
  title: string;
  description?: string;
  propertyKey?: string;
  badge?: string;
  children: React.ReactNode;
}

function SplitRow({ id, title, description, propertyKey, badge, children }: SplitRowProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_minmax(260px,360px)] items-center gap-4 px-5 py-4 border-b border-border-subtle last:border-b-0">
      <section className="space-y-1">
        <div className="flex items-center gap-2">
          <label htmlFor={id} className="text-sm font-bold text-text-primary cursor-pointer">
            {title}
          </label>
          {badge && (
            <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-medium uppercase bg-status-warning-bg text-status-warning border border-status-warning-border shrink-0">
              {badge}
            </span>
          )}
        </div>
        {description && (
          <p className="text-xs text-text-secondary mt-0.5 leading-relaxed">
            {description}
          </p>
        )}
        {propertyKey && (
          <div className="pt-0.5">
            <code className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-surface-elevated text-text-muted border border-border-subtle inline-block">
              {propertyKey}
            </code>
          </div>
        )}
      </section>

      <section className="w-full lg:max-w-[360px] lg:ml-auto flex flex-col items-start lg:items-end">
        {children}
      </section>
    </div>
  );
}

interface StepperNumberInputProps {
  id: string;
  name?: string;
  label: string;
  value: number;
  draftValue?: string;
  onChange: (val: string) => void;
  onBlur?: () => void;
  onStep: (delta: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  placeholder?: string;
  required?: boolean;
}

function StepperNumberInput({
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
  placeholder,
  required,
}: StepperNumberInputProps) {
  const displayVal = draftValue !== undefined ? draftValue : String(value);

  return (
    <span className="inline-flex items-center gap-1.5 w-full justify-end">
      <button
        type="button"
        aria-label={`Decrease ${label}`}
        onClick={() => onStep(-step)}
        disabled={min !== undefined && value <= min}
        className="h-9 w-9 flex items-center justify-center rounded-lg border border-border-default bg-surface-elevated text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-30 disabled:pointer-events-none transition-all cursor-pointer font-bold text-base select-none shrink-0"
      >
        −
      </button>

      <span className="relative inline-flex items-center">
        <input
          id={id}
          name={name}
          type="number"
          min={min}
          max={max}
          step={step}
          required={required}
          value={displayVal}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          placeholder={placeholder}
          className={`w-32 text-center px-2 py-1.5 font-mono text-sm rounded-lg border border-border-default bg-surface-card text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow ${
            unit ? "pr-8" : ""
          }`}
        />
        {unit && (
          <span className="absolute right-2.5 pointer-events-none text-[11px] font-mono text-text-muted">
            {unit}
          </span>
        )}
      </span>

      <button
        type="button"
        aria-label={`Increase ${label}`}
        onClick={() => onStep(step)}
        disabled={max !== undefined && value >= max}
        className="h-9 w-9 flex items-center justify-center rounded-lg border border-border-default bg-surface-elevated text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-30 disabled:pointer-events-none transition-all cursor-pointer font-bold text-base select-none shrink-0"
      >
        +
      </button>
    </span>
  );
}

interface DistanceSliderProps {
  id: string;
  label: string;
  value: number;
  draftValue?: string;
  onChange: (val: string) => void;
  onBlur?: () => void;
  onStep: (delta: number) => void;
  min: number;
  max: number;
  unit: string;
}

function DistanceSliderWithStepper({
  id,
  label,
  value,
  draftValue,
  onChange,
  onBlur,
  onStep,
  min,
  max,
  unit,
}: DistanceSliderProps) {
  const displayVal = draftValue !== undefined ? draftValue : String(value);

  return (
    <span className="inline-flex flex-col sm:flex-row items-end sm:items-center gap-3 w-full justify-end">
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={`${label} slider`}
        className="w-28 sm:w-36 accent-accent-primary cursor-pointer shrink-0"
      />

      <span className="inline-flex items-center gap-1.5">
        <button
          type="button"
          aria-label={`Decrease ${label}`}
          onClick={() => onStep(-1)}
          disabled={value <= min}
          className="h-8 w-8 flex items-center justify-center rounded-lg border border-border-default bg-surface-elevated text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-30 disabled:pointer-events-none transition-all cursor-pointer font-bold text-sm select-none shrink-0"
        >
          −
        </button>

        <span className="relative inline-flex items-center">
          <input
            id={id}
            type="number"
            min={min}
            max={max}
            step={1}
            value={displayVal}
            onChange={(e) => onChange(e.target.value)}
            onBlur={onBlur}
            className="w-20 text-center px-1.5 py-1 font-mono text-sm rounded-lg border border-border-default bg-surface-card text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
          />
          <span className="text-xs font-mono text-text-muted shrink-0 ml-1.5">
            {unit}
          </span>
        </span>

        <button
          type="button"
          aria-label={`Increase ${label}`}
          onClick={() => onStep(1)}
          disabled={value >= max}
          className="h-8 w-8 flex items-center justify-center rounded-lg border border-border-default bg-surface-elevated text-text-secondary hover:text-text-primary hover:bg-surface-hover active:scale-95 disabled:opacity-30 disabled:pointer-events-none transition-all cursor-pointer font-bold text-sm select-none shrink-0"
        >
          +
        </button>
      </span>
    </span>
  );
}

interface BooleanSwitchRowProps {
  id: string;
  title: string;
  description?: string;
  propertyKey?: string;
  badge?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  icon?: IconName;
}

function BooleanSwitchRow({
  id,
  title,
  description,
  propertyKey,
  badge,
  checked,
  onChange,
  icon,
}: BooleanSwitchRowProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_minmax(260px,360px)] items-center gap-4 px-5 py-4 border-b border-border-subtle last:border-b-0">
      <section className="space-y-1">
        <div className="flex items-center gap-2">
          {icon && (
            <span className="p-1 rounded-md bg-surface-elevated border border-border-subtle text-text-secondary shrink-0">
              <Icon name={icon} size={14} />
            </span>
          )}
          <label htmlFor={id} className="text-sm font-bold text-text-primary cursor-pointer">
            {title}
          </label>
          {badge && (
            <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-medium uppercase bg-status-warning-bg text-status-warning border border-status-warning-border shrink-0">
              {badge}
            </span>
          )}
        </div>
        {description && (
          <p className="text-xs text-text-secondary mt-0.5 leading-relaxed">
            {description}
          </p>
        )}
        {propertyKey && (
          <div className="pt-0.5">
            <code className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-surface-elevated text-text-muted border border-border-subtle inline-block">
              {propertyKey}
            </code>
          </div>
        )}
      </section>

      <section className="w-full lg:max-w-[360px] lg:ml-auto flex items-center justify-end gap-3">
        <span
          className={`text-[10px] font-bold font-mono uppercase tracking-wider px-2 py-0.5 rounded-full border transition-colors ${
            checked
              ? "bg-status-success-bg text-status-success border-status-success-border"
              : "bg-surface-elevated text-text-muted border-border-subtle"
          }`}
        >
          {checked ? "ENABLED" : "DISABLED"}
        </span>

        <label className="relative inline-flex items-center cursor-pointer select-none">
          <input
            id={id}
            type="checkbox"
            role="switch"
            aria-label={title}
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
            className="sr-only peer"
          />
          <div
            className={`w-11 h-6 rounded-full transition-colors duration-200 ease-in-out ${
              checked ? "bg-accent-primary" : "bg-border-strong"
            }`}
          >
            <div
              className={`w-5 h-5 bg-accent-contrast-text rounded-full shadow-md transform transition-transform duration-200 ease-in-out mt-0.5 ${
                checked ? "translate-x-5.5 ml-0.5" : "translate-x-0.5"
              }`}
            />
          </div>
        </label>
      </section>
    </div>
  );
}

export function ServerSettingsSection({
  serverId,
  server,
  branch,
  gitBacked = false,
}: ServerSettingsSectionProps) {
  const isMainBranchSettings = Boolean(gitBacked && (!branch || branch === "main"));
  const isWorkingBranchSettings = Boolean(gitBacked && branch && branch !== "main");
  const updateServer = useUpdateServer();
  const { data: hostBudget } = useHostResources();
  const formId = useId();

  // Active Category & Quick Search State
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>("all");
  const [searchQuery, setSearchQuery] = useState("");

  // String draft state for numeric inputs (prevents 0 coercion / clamping while typing)
  const [rawDrafts, setRawDrafts] = useState<Record<string, string>>({});

  // General & Identity
  const [name, setName] = useState(server.name || "");
  const [port, setPort] = useState<number>(server.port || 25565);
  const [motd, setMotd] = useState(server.motd || "");

  // Resource Allocation
  const [minRam, setMinRam] = useState<number>(server.min_memory_mb || 1024);
  const [maxRam, setMaxRam] = useState<number>(server.max_memory_mb || 2048);
  const [cpuCores, setCpuCores] = useState<number>(server.cpu_cores ?? 0);
  const [cpuAffinity, setCpuAffinity] = useState(server.cpu_affinity || "");
  const [javaArgs, setJavaArgs] = useState(
    server.java_args
      ? server.java_args
          .split(/\s+/)
          .filter(Boolean)
          .join("\n")
      : ""
  );

  // Gameplay & World Properties
  const [gamemode, setGamemode] = useState(server.gamemode || "survival");
  const [difficulty, setDifficulty] = useState(server.difficulty || "easy");
  const [maxPlayers, setMaxPlayers] = useState<number>(server.max_players || 20);
  const [spawnProtection, setSpawnProtection] = useState<number>(server.spawn_protection ?? 16);
  const [viewDistance, setViewDistance] = useState<number>(server.view_distance ?? 10);
  const [simulationDistance, setSimulationDistance] = useState<number>(server.simulation_distance ?? 10);

  // Core Boolean Toggles
  const [pvp, setPvp] = useState<boolean>(server.pvp ?? true);
  const [onlineMode, setOnlineMode] = useState<boolean>(server.online_mode ?? true);
  const [whitelist, setWhitelist] = useState<boolean>(server.whitelist ?? false);
  const [enableCommandBlock, setEnableCommandBlock] = useState<boolean>(server.enable_command_block ?? false);

  // Extended GUI Toggles
  const [allowFlight, setAllowFlight] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["allow-flight"], false)
  );
  const [spawnMonsters, setSpawnMonsters] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["spawn-monsters"], true)
  );
  const [spawnAnimals, setSpawnAnimals] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["spawn-animals"], true)
  );
  const [spawnNpcs, setSpawnNpcs] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["spawn-npcs"], true)
  );
  const [allowNether, setAllowNether] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["allow-nether"], true)
  );
  const [hardcore, setHardcore] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["hardcore"], false)
  );
  const [forceGamemode, setForceGamemode] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["force-gamemode"], false)
  );
  const [enforceSecureProfile, setEnforceSecureProfile] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["enforce-secure-profile"], false)
  );
  const [generateStructures, setGenerateStructures] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["generate-structures"], true)
  );
  const [syncChunkWrites, setSyncChunkWrites] = useState<boolean>(() =>
    parseBool(server.raw_properties?.["sync-chunk-writes"], true)
  );

  // Numeric input draft helpers
  const handleNumericChange = (
    key: string,
    val: string,
    setter: (n: number) => void
  ) => {
    setRawDrafts((prev) => ({ ...prev, [key]: val }));
    if (val.trim() !== "") {
      const num = Number(val);
      if (!isNaN(num)) {
        setter(num);
      }
    }
  };

  const handleNumericBlur = (
    key: string,
    current: number,
    setter: (n: number) => void,
    min?: number,
    max?: number
  ) => {
    const draft = rawDrafts[key];
    if (draft === undefined) return;
    if (draft.trim() === "" || isNaN(Number(draft))) {
      const fallback = min !== undefined ? Math.max(min, current) : current;
      setter(fallback);
    } else {
      let parsed = Number(draft);
      if (min !== undefined && parsed < min) parsed = min;
      if (max !== undefined && parsed > max) parsed = max;
      setter(parsed);
    }
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleStep = (
    key: string,
    current: number,
    delta: number,
    setter: (n: number) => void,
    min?: number,
    max?: number
  ) => {
    let nextVal = current + delta;
    if (min !== undefined && nextVal < min) nextVal = min;
    if (max !== undefined && nextVal > max) nextVal = max;
    nextVal = Math.round(nextVal * 10) / 10;
    setter(nextVal);
    setRawDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  // Preserve any custom plugin or mod properties not controlled by the GUI
  const customProperties = useMemo(() => {
    if (!server.raw_properties) return {};
    const customs: Record<string, string> = {};
    for (const [k, v] of Object.entries(server.raw_properties)) {
      const normKey = k.toLowerCase().trim();
      if (!KNOWN_PROPERTY_KEYS.has(normKey)) {
        customs[k] = v;
      }
    }
    return customs;
  }, [server.raw_properties]);

  const maxAllocRam = hostBudget?.allocatable_ram_mb ?? 262144;
  const maxAllocCpus = hostBudget?.allocatable_cpus;

  // RAM Validation
  const ramError = useMemo(() => {
    if (minRam < 128) return "Min RAM must be at least 128 MB";
    if (maxRam > maxAllocRam) {
      return hostBudget
        ? `Max RAM cannot exceed ${hostBudget.allocatable_ram_mb} MB host allocatable ceiling`
        : "Max RAM cannot exceed 262,144 MB (256 GB)";
    }
    if (minRam > maxRam) return "Min RAM cannot exceed Max RAM";
    return null;
  }, [minRam, maxRam, maxAllocRam, hostBudget]);

  // CPU Validation
  const cpuAffinityValid = useMemo(() => parseAffinity(cpuAffinity.trim()), [cpuAffinity]);

  // JVM Flags Validation
  const jvmFlagsValid = useMemo(() => {
    const lines = javaArgs.split("\n").map((l) => l.trim()).filter(Boolean);
    const rejectedShellChars = /[`$;|&<>()!{}]/;
    return lines.every(
      (line) => line.startsWith("-") && line.length <= 1024 && !rejectedShellChars.test(line)
    );
  }, [javaArgs]);

  // Port and Player limits
  const portValid = port >= 1024 && port <= 65535;
  const maxPlayersValid = maxPlayers >= 1 && maxPlayers <= 500;

  // Unsaved Changes Dirty Detection
  const isDirty = useMemo(() => {
    if (name !== (server.name || "")) return true;
    if (port !== (server.port || 25565)) return true;
    if (motd !== (server.motd || "")) return true;
    if (minRam !== (server.min_memory_mb || 1024)) return true;
    if (maxRam !== (server.max_memory_mb || 2048)) return true;
    if (cpuCores !== (server.cpu_cores ?? 0)) return true;
    if (cpuAffinity !== (server.cpu_affinity || "")) return true;
    const initialJavaArgs = server.java_args
      ? server.java_args.split(/\s+/).filter(Boolean).join("\n")
      : "";
    if (javaArgs !== initialJavaArgs) return true;
    if (gamemode !== (server.gamemode || "survival")) return true;
    if (difficulty !== (server.difficulty || "easy")) return true;
    if (maxPlayers !== (server.max_players || 20)) return true;
    if (spawnProtection !== (server.spawn_protection ?? 16)) return true;
    if (viewDistance !== (server.view_distance ?? 10)) return true;
    if (simulationDistance !== (server.simulation_distance ?? 10)) return true;
    if (pvp !== (server.pvp ?? true)) return true;
    if (onlineMode !== (server.online_mode ?? true)) return true;
    if (whitelist !== (server.whitelist ?? false)) return true;
    if (enableCommandBlock !== (server.enable_command_block ?? false)) return true;
    if (allowFlight !== parseBool(server.raw_properties?.["allow-flight"], false)) return true;
    if (spawnMonsters !== parseBool(server.raw_properties?.["spawn-monsters"], true)) return true;
    if (spawnAnimals !== parseBool(server.raw_properties?.["spawn-animals"], true)) return true;
    if (spawnNpcs !== parseBool(server.raw_properties?.["spawn-npcs"], true)) return true;
    if (allowNether !== parseBool(server.raw_properties?.["allow-nether"], true)) return true;
    if (hardcore !== parseBool(server.raw_properties?.["hardcore"], false)) return true;
    if (forceGamemode !== parseBool(server.raw_properties?.["force-gamemode"], false)) return true;
    if (enforceSecureProfile !== parseBool(server.raw_properties?.["enforce-secure-profile"], false)) return true;
    if (generateStructures !== parseBool(server.raw_properties?.["generate-structures"], true)) return true;
    if (syncChunkWrites !== parseBool(server.raw_properties?.["sync-chunk-writes"], true)) return true;
    return false;
  }, [
    name, port, motd, minRam, maxRam, cpuCores, cpuAffinity, javaArgs,
    gamemode, difficulty, maxPlayers, spawnProtection, viewDistance,
    simulationDistance, pvp, onlineMode, whitelist, enableCommandBlock,
    allowFlight, spawnMonsters, spawnAnimals, spawnNpcs, allowNether,
    hardcore, forceGamemode, enforceSecureProfile, generateStructures,
    syncChunkWrites, server
  ]);

  const handleReset = () => {
    setName(server.name || "");
    setPort(server.port || 25565);
    setMotd(server.motd || "");
    setMinRam(server.min_memory_mb || 1024);
    setMaxRam(server.max_memory_mb || 2048);
    setCpuCores(server.cpu_cores ?? 0);
    setCpuAffinity(server.cpu_affinity || "");
    setJavaArgs(
      server.java_args
        ? server.java_args.split(/\s+/).filter(Boolean).join("\n")
        : ""
    );
    setGamemode(server.gamemode || "survival");
    setDifficulty(server.difficulty || "easy");
    setMaxPlayers(server.max_players || 20);
    setSpawnProtection(server.spawn_protection ?? 16);
    setViewDistance(server.view_distance ?? 10);
    setSimulationDistance(server.simulation_distance ?? 10);
    setPvp(server.pvp ?? true);
    setOnlineMode(server.online_mode ?? true);
    setWhitelist(server.whitelist ?? false);
    setEnableCommandBlock(server.enable_command_block ?? false);
    setAllowFlight(parseBool(server.raw_properties?.["allow-flight"], false));
    setSpawnMonsters(parseBool(server.raw_properties?.["spawn-monsters"], true));
    setSpawnAnimals(parseBool(server.raw_properties?.["spawn-animals"], true));
    setSpawnNpcs(parseBool(server.raw_properties?.["spawn-npcs"], true));
    setAllowNether(parseBool(server.raw_properties?.["allow-nether"], true));
    setHardcore(parseBool(server.raw_properties?.["hardcore"], false));
    setForceGamemode(parseBool(server.raw_properties?.["force-gamemode"], false));
    setEnforceSecureProfile(parseBool(server.raw_properties?.["enforce-secure-profile"], false));
    setGenerateStructures(parseBool(server.raw_properties?.["generate-structures"], true));
    setSyncChunkWrites(parseBool(server.raw_properties?.["sync-chunk-writes"], true));
    setRawDrafts({});
  };

  const isSaveDisabled =
    updateServer.isPending ||
    ramError !== null ||
    !cpuAffinityValid ||
    !jvmFlagsValid ||
    !portValid ||
    !maxPlayersValid ||
    !name.trim();

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSaveDisabled) return;

    const jvmArgList = javaArgs
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);

    const payload: ServerUpdateRequest = {
      name: name.trim(),
      min_memory_mb: minRam,
      max_memory_mb: maxRam,
      cpu_cores: cpuCores,
      cpu_affinity: cpuAffinity.trim(),
      java_args: jvmArgList,
      properties: {
        "server-port": port,
        motd,
        gamemode,
        difficulty,
        "max-players": maxPlayers,
        "spawn-protection": spawnProtection,
        "view-distance": viewDistance,
        "simulation-distance": simulationDistance,
        pvp,
        "online-mode": onlineMode,
        "white-list": whitelist,
        "enable-command-block": enableCommandBlock,
        "allow-flight": allowFlight,
        "spawn-monsters": spawnMonsters,
        "spawn-animals": spawnAnimals,
        "spawn-npcs": spawnNpcs,
        "allow-nether": allowNether,
        hardcore,
        "force-gamemode": forceGamemode,
        "enforce-secure-profile": enforceSecureProfile,
        "generate-structures": generateStructures,
        "sync-chunk-writes": syncChunkWrites,
        ...customProperties,
      },
    };

    try {
      await updateServer.mutateAsync({
        serverId,
        body: payload,
        branch: gitBacked ? branch : undefined,
      });
      setRawDrafts({});
      if (isMainBranchSettings) {
        toast("success", "Settings queued to pending settings branch. Restart server to auto-merge and apply.");
      } else if (isWorkingBranchSettings) {
        toast("success", `Settings committed to branch "${branch}".`);
      } else {
        toast("success", "Settings updated. Restart server to apply.");
      }
    } catch (err) {
      toast("error", "Update failed", err instanceof Error ? err.message : "Failed to save settings");
    }
  };

  // Search Matching
  const normalizedQuery = searchQuery.trim().toLowerCase();

  const card1Matches = useMemo(() => {
    if (!normalizedQuery) return true;
    const terms = [
      "general",
      "identity",
      "name",
      "server name",
      name,
      "port",
      "server port",
      String(port),
      "motd",
      motd,
      "network",
    ];
    return terms.some((t) => t.toLowerCase().includes(normalizedQuery));
  }, [normalizedQuery, name, port, motd]);

  const card2Matches = useMemo(() => {
    if (!normalizedQuery) return true;
    const terms = [
      "resource",
      "allocation",
      "ram",
      "memory",
      "min ram",
      "max ram",
      String(minRam),
      String(maxRam),
      "cpu",
      "cores",
      "affinity",
      "jvm",
      "java",
      "args",
      "flags",
      javaArgs,
      "heap",
      "preset",
    ];
    return terms.some((t) => t.toLowerCase().includes(normalizedQuery));
  }, [normalizedQuery, minRam, maxRam, javaArgs]);

  const card3Matches = useMemo(() => {
    if (!normalizedQuery) return true;
    const terms = [
      "gameplay",
      "world",
      "gamemode",
      "difficulty",
      "players",
      "capacity",
      "spawn protection",
      "view distance",
      "simulation distance",
      "pvp",
      "online mode",
      "whitelist",
      "command blocks",
      "allow flight",
      "spawn monsters",
      "spawn animals",
      "spawn npcs",
      "allow nether",
      "hardcore",
      "force gamemode",
      "enforce secure profile",
      "generate structures",
      "sync chunk writes",
      "rules",
      "security",
      "combat",
      "entities",
      "dimensions",
    ];
    return terms.some((t) => t.toLowerCase().includes(normalizedQuery));
  }, [normalizedQuery]);

  const card4Matches = useMemo(() => {
    if (!normalizedQuery) return true;
    const terms = [
      "advanced",
      "configuration",
      "server.properties",
      "file manager",
      "files",
      "direct file access",
      "raw properties",
      "custom",
    ];
    return terms.some((t) => t.toLowerCase().includes(normalizedQuery));
  }, [normalizedQuery]);

  // Tab & Search Visibility Logic
  const isAll = activeCategory === "all";
  const showCard1 = (isAll || activeCategory === "identity") && card1Matches;
  const showCard2 = (isAll || activeCategory === "resources") && card2Matches;
  const showCard3 = (isAll || activeCategory === "gameplay" || activeCategory === "rules") && card3Matches;
  const showCard4 = (isAll || activeCategory === "advanced") && card4Matches;
  const hasVisibleCards = showCard1 || showCard2 || showCard3 || showCard4;

  return (
    <form onSubmit={handleSave} className="space-y-6" data-testid="server-settings-form">
      {/* Category Navigation & Quick Filter Bar */}
      <div className="space-y-3">
        {/* Category Tabs */}
        <div
          className="flex flex-wrap items-center gap-1.5 p-1.5 rounded-2xl bg-surface-muted border border-border-default"
          role="tablist"
          aria-label="Settings Categories"
        >
          {CATEGORY_TABS.map((cat) => {
            const isActive = activeCategory === cat.id;
            return (
              <button
                key={cat.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => setActiveCategory(cat.id)}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer ${
                  isActive
                    ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                <Icon name={cat.icon} size={15} />
                <span>{cat.label}</span>
              </button>
            );
          })}
        </div>

        {/* Quick Search Bar */}
        <div className="relative">
          <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-text-muted">
            <Icon name="search" size={16} />
          </div>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search server settings (e.g. whitelist, memory, pvp, port)..."
            className="w-full pl-10 pr-9 py-2.5 rounded-xl border border-border-default bg-surface-card text-xs text-text-primary placeholder:text-text-muted focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
          />
          {searchQuery && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setSearchQuery("")}
              className="absolute inset-y-0 right-0 pr-3 flex items-center text-text-muted hover:text-text-primary cursor-pointer"
            >
              <Icon name="x" size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Running State Advisory Banner */}
      {server.status === "running" && (
        <div
          role="region"
          aria-label="Server is Currently Running"
          className="rounded-2xl border border-status-warning-border bg-status-warning-bg p-4.5 text-text-primary shadow-xs"
        >
          <div className="flex items-start gap-3.5">
            <div className="p-2 rounded-xl bg-status-warning-bg text-status-warning shrink-0">
              <Icon name="alert" size={20} />
            </div>
            <div>
              <h4 className="text-sm font-bold text-text-primary">
                Server is Currently Running
              </h4>
              <p className="mt-1 text-xs text-text-secondary leading-relaxed">
                Configuration edits are saved immediately to disk and database, but require a server restart to be applied to the active process.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Empty Search State */}
      {!hasVisibleCards && (
        <div className="text-center py-12 px-4 rounded-2xl border border-border-default bg-surface-card space-y-3">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-surface-muted text-text-muted">
            <Icon name="search" size={24} />
          </div>
          <h4 className="text-sm font-semibold text-text-primary">No settings found</h4>
          <p className="text-xs text-text-muted max-w-sm mx-auto">
            No configuration settings match &ldquo;{searchQuery}&rdquo;. Try another search term or reset category filters.
          </p>
          <button
            type="button"
            onClick={() => {
              setSearchQuery("");
              setActiveCategory("all");
            }}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-surface-muted hover:bg-surface-hover text-text-primary border border-border-default transition-colors cursor-pointer"
          >
            Clear Search
          </button>
        </div>
      )}

      {/* Card 1: General & Identity (Split-Row Card) */}
      {showCard1 && (
        <section className="bg-surface-card rounded-2xl border border-border-default shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-status-info-bg text-accent-primary">
              <Icon name="server" size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold tracking-wide uppercase text-text-primary">
                General & Identity
              </h3>
              <p className="text-xs text-text-muted">
                Basic server metadata, network listening port, and server list description.
              </p>
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* Server Name */}
            <SplitRow
              id={`${formId}-name`}
              title="Server Name"
              description="Primary server label and identity displayed in the fleet dashboard."
              propertyKey="server-name"
            >
              <input
                id={`${formId}-name`}
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="w-full px-3.5 py-2 rounded-xl border border-border-default bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
              />
            </SplitRow>

            {/* Server Port */}
            <SplitRow
              id={`${formId}-port`}
              title="Server Port (1024–65535)"
              description="Primary TCP/UDP network socket port listening for game traffic."
              propertyKey="server-port"
            >
              <div className="flex flex-col items-end gap-1 w-full">
                <StepperNumberInput
                  id={`${formId}-port`}
                  label="Server Port"
                  value={port}
                  draftValue={rawDrafts["port"]}
                  onChange={(v) => handleNumericChange("port", v, setPort)}
                  onBlur={() => handleNumericBlur("port", port, setPort, 1024, 65535)}
                  onStep={(delta) => handleStep("port", port, delta, setPort, 1024, 65535)}
                  min={1024}
                  max={65535}
                  required
                />
                {!portValid && (
                  <p className="text-xs text-status-danger font-medium mt-0.5">
                    Port must be between 1024 and 65535
                  </p>
                )}
              </div>
            </SplitRow>

            {/* MOTD */}
            <SplitRow
              id={`${formId}-motd`}
              title="MOTD (Message of the Day)"
              description="Short server tagline broadcasted in multiplayer lobby listings."
              propertyKey="motd"
            >
              <input
                id={`${formId}-motd`}
                type="text"
                value={motd}
                onChange={(e) => setMotd(e.target.value)}
                placeholder="A Minecraft Server"
                className="w-full px-3.5 py-2 rounded-xl border border-border-default bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
              />
            </SplitRow>
          </div>
        </section>
      )}

      {/* Card 2: Resource Allocation (RAM & CPU) */}
      {showCard2 && (
        <section className="bg-surface-card rounded-2xl border border-border-default shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-status-info-bg text-accent-primary">
              <Icon name="cpu" size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold tracking-wide uppercase text-text-primary">
                Resource Allocation (RAM & CPU)
              </h3>
              <p className="text-xs text-text-muted">
                Hardware bounds and JVM memory parameters for the server process.
              </p>
            </div>
          </div>

          {/* Visual Memory Allocation Ratio Bar */}
          <div className="p-5 border-b border-border-subtle bg-surface-muted/30 space-y-3">
            {hostBudget && (
              <HostResourceBudgetBar
                budget={hostBudget}
                requestedRamMb={maxRam}
                requestedCpuCores={cpuCores}
                compact
              />
            )}
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-text-primary flex items-center gap-1.5">
                  <Icon name="cpu" size={14} className="text-accent-primary" />
                  Memory Allocation
                </span>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-surface-card border border-border-subtle text-text-secondary">
                  Min: {(minRam / 1024).toFixed(1)} GB / Max: {(maxRam / 1024).toFixed(1)} GB
                </span>
              </div>
              <span className="text-xs font-semibold text-accent-primary font-mono">
                {Math.round((minRam / (maxRam || 1)) * 100)}% Heap Ratio
              </span>
            </div>
            <div className="w-full h-3 rounded-full bg-surface-card border border-border-subtle overflow-hidden p-0.5">
              <div
                className="h-full rounded-full bg-accent-primary transition-all duration-300"
                style={{
                  width: `${Math.min(100, Math.max(4, Math.round((minRam / (maxRam || 1)) * 100)))}%`,
                }}
              />
            </div>
            <div className="flex items-center justify-between text-[11px] text-text-muted">
              <span>Initial JVM Heap (-Xms): {minRam} MB</span>
              <span>Maximum JVM Heap (-Xmx): {maxRam} MB</span>
            </div>

            {/* RAM Quick Presets */}
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="text-xs font-semibold text-text-muted mr-1">
                Memory Presets:
              </span>
              {RAM_PRESETS.map((preset) => {
                const isSelected = minRam === preset.min && maxRam === preset.max;
                const overCeiling = Boolean(hostBudget && preset.max > hostBudget.allocatable_ram_mb);
                return (
                  <button
                    key={preset.label}
                    type="button"
                    disabled={overCeiling}
                    onClick={() => {
                      setMinRam(preset.min);
                      setMaxRam(preset.max);
                      setRawDrafts((prev) => {
                        const next = { ...prev };
                        delete next["minRam"];
                        delete next["maxRam"];
                        return next;
                      });
                    }}
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all border ${
                      overCeiling
                        ? "bg-surface-elevated text-text-muted border-border-subtle opacity-40 cursor-not-allowed"
                        : isSelected
                          ? "bg-accent-primary text-accent-contrast-text border-accent-primary shadow-xs cursor-pointer"
                          : "bg-surface-card text-text-secondary border-border-default hover:bg-surface-hover cursor-pointer"
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* Minimum Memory */}
            <SplitRow
              id={`${formId}-min-ram`}
              title="Minimum Memory (MB)"
              description={`Initial JVM heap (-Xms) allocated at launch (~${(minRam / 1024).toFixed(1)} GB).`}
              propertyKey="-Xms (min_memory_mb)"
            >
              <StepperNumberInput
                id={`${formId}-min-ram`}
                label="Minimum Memory"
                value={minRam}
                draftValue={rawDrafts["minRam"]}
                onChange={(v) => handleNumericChange("minRam", v, setMinRam)}
                onBlur={() => handleNumericBlur("minRam", minRam, setMinRam, 128, maxAllocRam)}
                onStep={(delta) => handleStep("minRam", minRam, delta, setMinRam, 128, maxAllocRam)}
                min={128}
                max={maxAllocRam}
                step={128}
                unit="MB"
              />
            </SplitRow>

            {/* Maximum Memory */}
            <SplitRow
              id={`${formId}-max-ram`}
              title="Maximum Memory (MB)"
              description={`Upper limit for Java heap (-Xmx) allocation (~${(maxRam / 1024).toFixed(1)} GB).`}
              propertyKey="-Xmx (max_memory_mb)"
            >
              <div className="flex flex-col items-end gap-1 w-full">
                <StepperNumberInput
                  id={`${formId}-max-ram`}
                  label="Maximum Memory"
                  value={maxRam}
                  draftValue={rawDrafts["maxRam"]}
                  onChange={(v) => handleNumericChange("maxRam", v, setMaxRam)}
                  onBlur={() => handleNumericBlur("maxRam", maxRam, setMaxRam, 128, maxAllocRam)}
                  onStep={(delta) => handleStep("maxRam", maxRam, delta, setMaxRam, 128, maxAllocRam)}
                  min={128}
                  max={maxAllocRam}
                  step={128}
                  unit="MB"
                />
                {ramError && (
                  <p className="text-xs text-status-danger font-medium mt-0.5">
                    {ramError}
                  </p>
                )}
              </div>
            </SplitRow>

            {/* Maximum CPU Cores */}
            <SplitRow
              id={`${formId}-cpu-cores`}
              title="Maximum CPU Cores (0 = unconstrained)"
              description="Pins runtime threads to an upper bound on logical execution units."
              propertyKey="cpu_cores"
            >
              <StepperNumberInput
                id={`${formId}-cpu-cores`}
                label="CPU Cores"
                value={cpuCores}
                draftValue={rawDrafts["cpuCores"]}
                onChange={(v) => handleNumericChange("cpuCores", v, setCpuCores)}
                onBlur={() =>
                  handleNumericBlur(
                    "cpuCores",
                    cpuCores,
                    setCpuCores,
                    0,
                    maxAllocCpus ? Math.floor(maxAllocCpus) : undefined,
                  )
                }
                onStep={(delta) =>
                  handleStep(
                    "cpuCores",
                    cpuCores,
                    delta,
                    setCpuCores,
                    0,
                    maxAllocCpus ? Math.floor(maxAllocCpus) : undefined,
                  )
                }
                min={0}
                max={maxAllocCpus ? Math.floor(maxAllocCpus) : undefined}
                step={1}
              />
            </SplitRow>

            {/* CPU Affinity Mask */}
            <SplitRow
              id={`${formId}-cpu-affinity`}
              title="CPU Affinity Mask"
              description="Pins the server process to specified logical CPU cores."
              propertyKey="cpu_affinity"
            >
              <div className="w-full">
                <input
                  id={`${formId}-cpu-affinity`}
                  type="text"
                  placeholder="e.g. 0-3 or 0,2,4"
                  value={cpuAffinity}
                  onChange={(e) => setCpuAffinity(e.target.value)}
                  className="w-full font-mono px-3.5 py-2 rounded-xl border border-border-default bg-surface-page text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
                {!cpuAffinityValid && (
                  <p className="text-xs text-status-danger mt-1 font-medium">
                    Invalid core format (e.g. &quot;0-3&quot; or &quot;0,2,4&quot;)
                  </p>
                )}
              </div>
            </SplitRow>

            {/* Custom JVM Arguments */}
            <SplitRow
              id={`${formId}-jvm-args`}
              title="Custom JVM Arguments (one flag per line)"
              description="Low-level Java VM parameters passed directly to the launch command."
              propertyKey="java_args"
            >
              <div className="w-full">
                <textarea
                  id={`${formId}-jvm-args`}
                  rows={3}
                  value={javaArgs}
                  onChange={(e) => setJavaArgs(e.target.value)}
                  placeholder="-XX:+UseG1GC&#10;-XX:+ParallelRefProcEnabled"
                  className="w-full font-mono px-3.5 py-2 rounded-xl border border-border-default bg-surface-page text-xs text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
                {!jvmFlagsValid && (
                  <p className="text-xs text-status-danger mt-1 font-medium">
                    All flags must start with &apos;-&apos; and cannot contain prohibited shell characters
                  </p>
                )}
              </div>
            </SplitRow>
          </div>
        </section>
      )}

      {/* Card 3: Gameplay & World Properties */}
      {showCard3 && (
        <section className="bg-surface-card rounded-2xl border border-border-default shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-status-success-bg text-status-success">
              <Icon name="activity" size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold tracking-wide uppercase text-text-primary">
                Gameplay & World Properties
              </h3>
              <p className="text-xs text-text-muted">
                In-game mechanics, combat settings, access restrictions, and mob generation toggles.
              </p>
            </div>
          </div>

          <div className="divide-y divide-border-subtle">
            {/* Gamemode, Difficulty & Distances (hidden if focusing purely on rules) */}
            {activeCategory !== "rules" && (
              <>
                {/* Default Gamemode */}
                <SplitRow
                  id={`${formId}-gamemode`}
                  title="Default Gamemode"
                  description="Initial game mode assigned to new players joining the server."
                  propertyKey="gamemode"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="inline-flex p-1 rounded-xl bg-surface-elevated border border-border-default gap-1">
                      {GAMEMODE_OPTIONS.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setGamemode(opt.value)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                            gamemode === opt.value
                              ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                              : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </span>
                    <select
                      id={`${formId}-gamemode`}
                      value={gamemode}
                      onChange={(e) => setGamemode(e.target.value)}
                      className="sr-only"
                    >
                      {GAMEMODE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </SplitRow>

                {/* Difficulty */}
                <SplitRow
                  id={`${formId}-difficulty`}
                  title="Difficulty"
                  description="World hostility scale controlling mob damage, hunger depletion, and hazard severity."
                  propertyKey="difficulty"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="inline-flex p-1 rounded-xl bg-surface-elevated border border-border-default gap-1">
                      {DIFFICULTY_OPTIONS.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setDifficulty(opt.value)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                            difficulty === opt.value
                              ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                              : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </span>
                    <select
                      id={`${formId}-difficulty`}
                      value={difficulty}
                      onChange={(e) => setDifficulty(e.target.value)}
                      className="sr-only"
                    >
                      {DIFFICULTY_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </SplitRow>

                {/* Player Capacity */}
                <SplitRow
                  id={`${formId}-max-players`}
                  title="Player Capacity (1–500)"
                  description="Maximum simultaneous player slots available on this server."
                  propertyKey="max-players"
                >
                  <div className="flex flex-col items-end gap-1 w-full">
                    <StepperNumberInput
                      id={`${formId}-max-players`}
                      label="Player Capacity"
                      value={maxPlayers}
                      draftValue={rawDrafts["maxPlayers"]}
                      onChange={(v) => handleNumericChange("maxPlayers", v, setMaxPlayers)}
                      onBlur={() => handleNumericBlur("maxPlayers", maxPlayers, setMaxPlayers, 1, 500)}
                      onStep={(delta) => handleStep("maxPlayers", maxPlayers, delta, setMaxPlayers, 1, 500)}
                      min={1}
                      max={500}
                    />
                    {!maxPlayersValid && (
                      <p className="text-xs text-status-danger font-medium mt-0.5">
                        Must be between 1 and 500
                      </p>
                    )}
                  </div>
                </SplitRow>

                {/* Spawn Protection */}
                <SplitRow
                  id={`${formId}-spawn-protection`}
                  title="Spawn Protection (blocks)"
                  description="Radius in blocks around the world spawn where non-operator players cannot place or break blocks."
                  propertyKey="spawn-protection"
                >
                  <DistanceSliderWithStepper
                    id={`${formId}-spawn-protection`}
                    label="Spawn Protection"
                    value={spawnProtection}
                    draftValue={rawDrafts["spawnProtection"]}
                    onChange={(v) => handleNumericChange("spawnProtection", v, setSpawnProtection)}
                    onBlur={() => handleNumericBlur("spawnProtection", spawnProtection, setSpawnProtection, 0, 1000)}
                    onStep={(delta) => handleStep("spawnProtection", spawnProtection, delta, setSpawnProtection, 0, 1000)}
                    min={0}
                    max={100}
                    unit="blocks"
                  />
                </SplitRow>

                {/* View Distance */}
                <SplitRow
                  id={`${formId}-view-distance`}
                  title="View Distance (2–32 chunks)"
                  description="Client render distance sent by the server; affects memory and network bandwidth."
                  propertyKey="view-distance"
                >
                  <DistanceSliderWithStepper
                    id={`${formId}-view-distance`}
                    label="View Distance"
                    value={viewDistance}
                    draftValue={rawDrafts["viewDistance"]}
                    onChange={(v) => handleNumericChange("viewDistance", v, setViewDistance)}
                    onBlur={() => handleNumericBlur("viewDistance", viewDistance, setViewDistance, 2, 32)}
                    onStep={(delta) => handleStep("viewDistance", viewDistance, delta, setViewDistance, 2, 32)}
                    min={2}
                    max={32}
                    unit="chunks"
                  />
                </SplitRow>

                {/* Simulation Distance */}
                <SplitRow
                  id={`${formId}-sim-distance`}
                  title="Simulation Distance (2–32 chunks)"
                  description="Chunk radius around active players in which ticks, mobs, and redstone run."
                  propertyKey="simulation-distance"
                >
                  <DistanceSliderWithStepper
                    id={`${formId}-sim-distance`}
                    label="Simulation Distance"
                    value={simulationDistance}
                    draftValue={rawDrafts["simulationDistance"]}
                    onChange={(v) => handleNumericChange("simulationDistance", v, setSimulationDistance)}
                    onBlur={() => handleNumericBlur("simulationDistance", simulationDistance, setSimulationDistance, 2, 32)}
                    onStep={(delta) => handleStep("simulationDistance", simulationDistance, delta, setSimulationDistance, 2, 32)}
                    min={2}
                    max={32}
                    unit="chunks"
                  />
                </SplitRow>
              </>
            )}

            {/* Sub-Group 1: Access & Security */}
            <div className="px-5 py-2.5 bg-surface-muted/30">
              <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-2">
                <Icon name="check" size={14} className="text-accent-primary" />
                Access & Security
              </h4>
            </div>

            <BooleanSwitchRow
              id={`${formId}-online-mode`}
              title="Online Mode"
              badge="CRITICAL"
              description="Verify players with Mojang authentication. Turn OFF to allow offline / cracked launchers."
              propertyKey="online-mode"
              checked={onlineMode}
              onChange={setOnlineMode}
              icon="globe"
            />
            <BooleanSwitchRow
              id={`${formId}-whitelist`}
              title="Whitelist"
              description="Restrict server connection exclusively to players enrolled on whitelist.json."
              propertyKey="white-list"
              checked={whitelist}
              onChange={setWhitelist}
              icon="users"
            />
            <BooleanSwitchRow
              id={`${formId}-enforce-secure-profile`}
              title="Enforce Secure Profile"
              description="Require Mojang-signed cryptographic public keys for player chat."
              propertyKey="enforce-secure-profile"
              checked={enforceSecureProfile}
              onChange={setEnforceSecureProfile}
              icon="check"
            />
            <BooleanSwitchRow
              id={`${formId}-force-gamemode`}
              title="Force Gamemode"
              description="Force reconnecting players back into the default world gamemode."
              propertyKey="force-gamemode"
              checked={forceGamemode}
              onChange={setForceGamemode}
              icon="settings"
            />

            {/* Sub-Group 2: Combat & Player Rules */}
            <div className="px-5 py-2.5 bg-surface-muted/30">
              <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-2">
                <Icon name="activity" size={14} className="text-status-danger" />
                Combat & Player Rules
              </h4>
            </div>

            <BooleanSwitchRow
              id={`${formId}-pvp`}
              title="PvP"
              description="Enable combat damage between players in all dimensions."
              propertyKey="pvp"
              checked={pvp}
              onChange={setPvp}
              icon="activity"
            />
            <BooleanSwitchRow
              id={`${formId}-hardcore`}
              title="Hardcore Mode"
              description="Permadeath rule: players are permanently locked in spectator or banned on death."
              propertyKey="hardcore"
              checked={hardcore}
              onChange={setHardcore}
              icon="alert"
            />
            <BooleanSwitchRow
              id={`${formId}-command-block`}
              title="Command Blocks"
              description="Allow redstone-triggered command blocks to execute commands."
              propertyKey="enable-command-block"
              checked={enableCommandBlock}
              onChange={setEnableCommandBlock}
              icon="settings"
            />
            <BooleanSwitchRow
              id={`${formId}-allow-flight`}
              title="Allow Flight"
              description="Allow survival mode players to fly without triggering automated anti-float kicks."
              propertyKey="allow-flight"
              checked={allowFlight}
              onChange={setAllowFlight}
              icon="paper"
            />

            {/* Sub-Group 3: Entities & Dimensions */}
            <div className="px-5 py-2.5 bg-surface-muted/30">
              <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-2">
                <Icon name="globe" size={14} className="text-status-success" />
                Entities & Dimensions
              </h4>
            </div>

            <BooleanSwitchRow
              id={`${formId}-allow-nether`}
              title="Allow Nether"
              description="Enable Nether portal transit and the Nether dimension."
              propertyKey="allow-nether"
              checked={allowNether}
              onChange={setAllowNether}
              icon="globe"
            />
            <BooleanSwitchRow
              id={`${formId}-spawn-monsters`}
              title="Spawn Monsters"
              description="Spawn hostile entities (skeletons, zombies, creepers, phantoms)."
              propertyKey="spawn-monsters"
              checked={spawnMonsters}
              onChange={setSpawnMonsters}
              icon="alert"
            />
            <BooleanSwitchRow
              id={`${formId}-spawn-animals`}
              title="Spawn Animals"
              description="Spawn passive wildlife (cows, sheep, pigs, chickens, horses)."
              propertyKey="spawn-animals"
              checked={spawnAnimals}
              onChange={setSpawnAnimals}
              icon="heart"
            />
            <BooleanSwitchRow
              id={`${formId}-spawn-npcs`}
              title="Spawn NPCs"
              description="Spawn villagers and wandering traders in generated settlements."
              propertyKey="spawn-npcs"
              checked={spawnNpcs}
              onChange={setSpawnNpcs}
              icon="users"
            />

            {/* Sub-Group 4: World Mechanics */}
            <div className="px-5 py-2.5 bg-surface-muted/30">
              <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary flex items-center gap-2">
                <Icon name="file" size={14} className="text-accent-primary" />
                World Mechanics
              </h4>
            </div>

            <BooleanSwitchRow
              id={`${formId}-generate-structures`}
              title="Generate Structures"
              description="Generate villages, strongholds, dungeons, and temples during world generation."
              propertyKey="generate-structures"
              checked={generateStructures}
              onChange={setGenerateStructures}
              icon="globe"
            />
            <BooleanSwitchRow
              id={`${formId}-sync-chunk-writes`}
              title="Sync Chunk Writes"
              description="Synchronously flush chunks to disk immediately when saved to prevent corruption."
              propertyKey="sync-chunk-writes"
              checked={syncChunkWrites}
              onChange={setSyncChunkWrites}
              icon="file"
            />
          </div>
        </section>
      )}

      {/* Card 4: Advanced Configuration */}
      {showCard4 && (
        <section className="bg-surface-card rounded-2xl border border-border-default shadow-xs overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 bg-surface-muted/50 border-b border-border-default">
            <div className="p-2 rounded-xl bg-status-warning-bg text-status-warning">
              <Icon name="settings" size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold tracking-wide uppercase text-text-primary">
                Advanced Configuration
              </h3>
              <p className="text-xs text-text-muted">
                Directly edit raw properties, custom mod options, or low-level server settings.
              </p>
            </div>
          </div>

          <div className="p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-accent-primary">server.properties</span>
                <span className="text-[10px] px-2 py-0.5 rounded font-mono uppercase bg-surface-elevated text-text-secondary border border-border-subtle">
                  Direct File Access
                </span>
              </div>
              <p className="text-xs text-text-muted max-w-xl leading-relaxed">
                Edit the complete configuration file directly in the File Manager with full code editing, custom mod settings, and raw property definitions.
              </p>
            </div>
            <Link
              to={`/servers/${serverId}/files?file=server.properties`}
              className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-semibold shadow-xs transition-colors shrink-0 cursor-pointer"
              aria-label="Open server.properties in File Manager"
            >
              <Icon name="file" size={14} />
              <span>Open in File Manager</span>
              <Icon name="chevron-right" size={14} />
            </Link>
          </div>
        </section>
      )}

      {/* Save Button Action Bar */}
      <div className="sticky bottom-4 z-20 flex flex-wrap items-center justify-between gap-3 p-4 rounded-2xl bg-surface-card/95 backdrop-blur-md border border-border-default shadow-lg">
        <div className="flex items-center gap-3">
          {isDirty ? (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-status-warning-bg text-status-warning border border-status-warning-border">
              <span className="w-1.5 h-1.5 rounded-full bg-status-warning animate-pulse" />
              Unsaved Changes
            </span>
          ) : (
            <div className="flex items-center gap-2 text-xs text-text-muted">
              <Icon name="info" size={14} className="text-accent-primary" />
              <span>
                {isMainBranchSettings
                  ? "Edits to main create/update a pending settings/... branch and auto-merge on next server restart"
                  : isWorkingBranchSettings
                    ? `Edits auto-commit directly to branch "${branch}"`
                    : "Edits are written directly to server.properties & database"}
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleReset}
            disabled={!isDirty || updateServer.isPending}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            Reset to Saved
          </button>

          <button
            type="submit"
            disabled={isSaveDisabled}
            className="px-6 py-2.5 rounded-xl bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-semibold shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer"
          >
            {updateServer.isPending ? (
              <>
                <Icon name="restart" size={16} className="animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Icon name="check" size={16} />
                {isMainBranchSettings
                  ? "Save to Pending Settings Branch (Auto-Merges on Restart)"
                  : isWorkingBranchSettings
                    ? `Commit Changes to ${branch}`
                    : "Save Changes"}
              </>
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
