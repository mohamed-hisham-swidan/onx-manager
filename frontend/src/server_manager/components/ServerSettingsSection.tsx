import { useState, useMemo, useId } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "@/components/ui/Icon";
import { useUpdateServer } from "@/server_manager/hooks/useServers";
import { toast } from "@/stores/toastStore";
import type { ServerDetailResponse, ServerUpdateRequest } from "@/server_manager/types";

interface ServerSettingsSectionProps {
  serverId: string;
  server: ServerDetailResponse;
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

interface ToggleSwitchProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  icon?: IconName;
  badge?: string;
}

function ToggleSwitch({ label, description, checked, onChange, icon, badge }: ToggleSwitchProps) {
  return (
    <label
      className={`group relative flex items-center justify-between p-4 rounded-xl border transition-all cursor-pointer select-none ${
        checked
          ? "bg-status-info-bg border-accent-primary shadow-xs"
          : "bg-surface-card border-border-default hover:bg-surface-hover"
      }`}
    >
      <div className="flex items-start gap-3 pr-3">
        {icon && (
          <div
            className={`p-2 rounded-lg mt-0.5 shrink-0 transition-colors ${
              checked
                ? "bg-accent-primary text-accent-contrast-text"
                : "bg-surface-muted text-text-muted"
            }`}
          >
            <Icon name={icon} size={16} />
          </div>
        )}
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-text-primary">
              {label}
            </span>
            {badge && (
              <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-medium uppercase bg-status-warning-bg text-status-warning border border-status-warning-border">
                {badge}
              </span>
            )}
          </div>
          {description && (
            <p className="mt-0.5 text-xs text-text-muted leading-relaxed">
              {description}
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2.5 shrink-0">
        <span
          className={`text-[11px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded transition-colors ${
            checked
              ? "text-accent-primary"
              : "text-text-muted"
          }`}
        >
          {checked ? "ON" : "OFF"}
        </span>
        <div className="relative inline-flex items-center">
          <input
            type="checkbox"
            role="switch"
            aria-label={label}
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
        </div>
      </div>
    </label>
  );
}

const RAM_PRESETS = [
  { label: "1 GB", min: 512, max: 1024 },
  { label: "2 GB", min: 1024, max: 2048 },
  { label: "4 GB", min: 2048, max: 4096 },
  { label: "6 GB", min: 3072, max: 6144 },
  { label: "8 GB", min: 4096, max: 8192 },
  { label: "16 GB", min: 8192, max: 16384 },
];

export function ServerSettingsSection({ serverId, server }: ServerSettingsSectionProps) {
  const updateServer = useUpdateServer();
  const formId = useId();

  // Active Category & Quick Search State
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>("all");
  const [searchQuery, setSearchQuery] = useState("");

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

  // RAM Validation
  const ramError = useMemo(() => {
    if (minRam < 128) return "Min RAM must be at least 128 MB";
    if (maxRam > 262144) return "Max RAM cannot exceed 262,144 MB (256 GB)";
    if (minRam > maxRam) return "Min RAM cannot exceed Max RAM";
    return null;
  }, [minRam, maxRam]);

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
    return false;
  }, [
    name, port, motd, minRam, maxRam, cpuCores, cpuAffinity, javaArgs,
    gamemode, difficulty, maxPlayers, spawnProtection, viewDistance,
    simulationDistance, pvp, onlineMode, whitelist, enableCommandBlock,
    allowFlight, spawnMonsters, spawnAnimals, spawnNpcs, allowNether,
    hardcore, forceGamemode, enforceSecureProfile, server
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
        ...customProperties,
      },
    };

    try {
      await updateServer.mutateAsync({
        serverId,
        body: payload,
      });
      toast("success", "Settings updated. Restart server to apply.");
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
                className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold transition-all ${
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
              className="absolute inset-y-0 right-0 pr-3 flex items-center text-text-muted hover:text-text-primary"
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
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-surface-muted hover:bg-surface-hover text-text-primary border border-border-default transition-colors"
          >
            Clear Search
          </button>
        </div>
      )}

      {/* Card 1: General & Identity */}
      {showCard1 && (
        <section className="p-5 sm:p-6 bg-surface-card rounded-2xl border border-border-default shadow-xs space-y-5">
          <div className="flex items-center gap-3 border-b border-border-subtle pb-3.5">
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

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4.5">
            <div>
              <label
                htmlFor={`${formId}-name`}
                className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
              >
                Server Name
              </label>
              <input
                id={`${formId}-name`}
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
              />
            </div>
            <div>
              <label
                htmlFor={`${formId}-port`}
                className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
              >
                Server Port (1024–65535)
              </label>
              <input
                id={`${formId}-port`}
                type="number"
                min={1024}
                max={65535}
                value={port}
                onChange={(e) => setPort(Number(e.target.value))}
                required
                className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
              />
              {!portValid && (
                <p className="text-xs text-status-danger mt-1 font-medium">
                  Port must be between 1024 and 65535
                </p>
              )}
            </div>
            <div className="md:col-span-2">
              <label
                htmlFor={`${formId}-motd`}
                className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
              >
                MOTD (Message of the Day)
              </label>
              <input
                id={`${formId}-motd`}
                type="text"
                value={motd}
                onChange={(e) => setMotd(e.target.value)}
                placeholder="A Minecraft Server"
                className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
              />
            </div>
          </div>
        </section>
      )}

      {/* Card 2: Resource Allocation (RAM & CPU) */}
      {showCard2 && (
        <section className="p-5 sm:p-6 bg-surface-card rounded-2xl border border-border-default shadow-xs space-y-5">
          <div className="flex items-center gap-3 border-b border-border-subtle pb-3.5">
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
          <div className="p-4 rounded-xl border border-border-default bg-surface-muted space-y-2.5">
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
          </div>

          {/* RAM Quick Presets */}
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <span className="text-xs font-semibold text-text-muted mr-1">
                Memory Presets:
              </span>
              {RAM_PRESETS.map((preset) => {
                const isSelected = minRam === preset.min && maxRam === preset.max;
                return (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => {
                      setMinRam(preset.min);
                      setMaxRam(preset.max);
                    }}
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all border ${
                      isSelected
                        ? "bg-accent-primary text-accent-contrast-text border-accent-primary shadow-xs"
                        : "bg-surface-muted text-text-secondary border-border-default hover:bg-surface-hover"
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4.5">
              <div>
                <label
                  htmlFor={`${formId}-min-ram`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Minimum Memory (MB)
                </label>
                <input
                  id={`${formId}-min-ram`}
                  type="number"
                  min={128}
                  max={262144}
                  value={minRam}
                  onChange={(e) => setMinRam(Number(e.target.value))}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
              </div>
              <div>
                <label
                  htmlFor={`${formId}-max-ram`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Maximum Memory (MB)
                </label>
                <input
                  id={`${formId}-max-ram`}
                  type="number"
                  min={128}
                  max={262144}
                  value={maxRam}
                  onChange={(e) => setMaxRam(Number(e.target.value))}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
              </div>
              {ramError && (
                <p className="md:col-span-2 text-xs text-status-danger font-medium">
                  {ramError}
                </p>
              )}

              <div>
                <label
                  htmlFor={`${formId}-cpu-cores`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Maximum CPU Cores (0 = unconstrained)
                </label>
                <input
                  id={`${formId}-cpu-cores`}
                  type="number"
                  min={0}
                  value={cpuCores}
                  onChange={(e) => setCpuCores(Math.max(0, Number(e.target.value)))}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
                <p className="mt-1 text-[11px] text-text-muted">
                  Sets active processor count limits on the JVM runtime.
                </p>
              </div>
              <div>
                <label
                  htmlFor={`${formId}-cpu-affinity`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  CPU Affinity Mask
                </label>
                <input
                  id={`${formId}-cpu-affinity`}
                  type="text"
                  placeholder="e.g. 0-3 or 0,2,4"
                  value={cpuAffinity}
                  onChange={(e) => setCpuAffinity(e.target.value)}
                  className="w-full font-mono px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
                {!cpuAffinityValid ? (
                  <p className="text-xs text-status-danger mt-1 font-medium">
                    Invalid core format (e.g. &quot;0-3&quot; or &quot;0,2,4&quot;)
                  </p>
                ) : (
                  <p className="mt-1 text-[11px] text-text-muted">
                    Pins the server process to specified logical CPU cores.
                  </p>
                )}
              </div>

              <div className="md:col-span-2">
                <label
                  htmlFor={`${formId}-jvm-args`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Custom JVM Arguments (one flag per line)
                </label>
                <textarea
                  id={`${formId}-jvm-args`}
                  rows={3}
                  value={javaArgs}
                  onChange={(e) => setJavaArgs(e.target.value)}
                  placeholder="-XX:+UseG1GC&#10;-XX:+ParallelRefProcEnabled"
                  className="w-full font-mono px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-xs text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
                {!jvmFlagsValid && (
                  <p className="text-xs text-status-danger mt-1 font-medium">
                    All flags must start with &apos;-&apos; and cannot contain prohibited shell characters
                  </p>
                )}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Card 3: Gameplay & World Properties */}
      {showCard3 && (
        <section className="p-5 sm:p-6 bg-surface-card rounded-2xl border border-border-default shadow-xs space-y-6">
          <div className="flex items-center gap-3 border-b border-border-subtle pb-3.5">
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

          {/* Typed World Numeric & Select Controls (hidden if focusing purely on rules) */}
          {activeCategory !== "rules" && (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4.5">
              <div>
                <label
                  htmlFor={`${formId}-gamemode`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Default Gamemode
                </label>
                <select
                  id={`${formId}-gamemode`}
                  value={gamemode}
                  onChange={(e) => setGamemode(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                >
                  <option value="survival">Survival</option>
                  <option value="creative">Creative</option>
                  <option value="adventure">Adventure</option>
                  <option value="spectator">Spectator</option>
                </select>
              </div>

              <div>
                <label
                  htmlFor={`${formId}-difficulty`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Difficulty
                </label>
                <select
                  id={`${formId}-difficulty`}
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                >
                  <option value="peaceful">Peaceful</option>
                  <option value="easy">Easy</option>
                  <option value="normal">Normal</option>
                  <option value="hard">Hard</option>
                </select>
              </div>

              <div>
                <label
                  htmlFor={`${formId}-max-players`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Player Capacity (1–500)
                </label>
                <input
                  id={`${formId}-max-players`}
                  type="number"
                  min={1}
                  max={500}
                  value={maxPlayers}
                  onChange={(e) => setMaxPlayers(Number(e.target.value))}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
                {!maxPlayersValid && (
                  <p className="text-xs text-status-danger mt-1 font-medium">
                    Must be between 1 and 500
                  </p>
                )}
              </div>

              <div>
                <label
                  htmlFor={`${formId}-spawn-protection`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Spawn Protection (blocks)
                </label>
                <input
                  id={`${formId}-spawn-protection`}
                  type="number"
                  min={0}
                  value={spawnProtection}
                  onChange={(e) => setSpawnProtection(Number(e.target.value))}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
              </div>

              <div>
                <label
                  htmlFor={`${formId}-view-distance`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  View Distance (2–32 chunks)
                </label>
                <input
                  id={`${formId}-view-distance`}
                  type="number"
                  min={2}
                  max={32}
                  value={viewDistance}
                  onChange={(e) => setViewDistance(Number(e.target.value))}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
              </div>

              <div>
                <label
                  htmlFor={`${formId}-sim-distance`}
                  className="block text-xs font-semibold uppercase tracking-wider text-text-secondary mb-1.5"
                >
                  Simulation Distance (2–32 chunks)
                </label>
                <input
                  id={`${formId}-sim-distance`}
                  type="number"
                  min={2}
                  max={32}
                  value={simulationDistance}
                  onChange={(e) => setSimulationDistance(Number(e.target.value))}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-border-default bg-surface-card text-sm text-text-primary focus:ring-2 focus:ring-border-focus focus:outline-none transition-shadow"
                />
              </div>
            </div>
          )}

          {/* Sub-Group 1: Access & Security GUI Toggles */}
          <div className="pt-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary mb-3 flex items-center gap-2">
              <Icon name="check" size={14} className="text-accent-primary" />
              Access & Security
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              <ToggleSwitch
                label="Online Mode"
                badge="CRITICAL"
                description="Verify players with Mojang authentication. Turn OFF to allow offline / cracked launchers."
                checked={onlineMode}
                onChange={setOnlineMode}
                icon="globe"
              />
              <ToggleSwitch
                label="Whitelist"
                description="Restrict server connection exclusively to players enrolled on whitelist.json."
                checked={whitelist}
                onChange={setWhitelist}
                icon="users"
              />
              <ToggleSwitch
                label="Enforce Secure Profile"
                description="Require Mojang-signed cryptographic public keys for player chat."
                checked={enforceSecureProfile}
                onChange={setEnforceSecureProfile}
                icon="check"
              />
              <ToggleSwitch
                label="Force Gamemode"
                description="Force reconnecting players back into the default world gamemode."
                checked={forceGamemode}
                onChange={setForceGamemode}
                icon="settings"
              />
            </div>
          </div>

          {/* Sub-Group 2: Combat & Gameplay Rules */}
          <div className="pt-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary mb-3 flex items-center gap-2">
              <Icon name="activity" size={14} className="text-status-danger" />
              Combat & Player Rules
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              <ToggleSwitch
                label="PvP"
                description="Enable combat damage between players in all dimensions."
                checked={pvp}
                onChange={setPvp}
                icon="activity"
              />
              <ToggleSwitch
                label="Hardcore Mode"
                description="Permadeath rule: players are permanently locked in spectator or banned on death."
                checked={hardcore}
                onChange={setHardcore}
                icon="alert"
              />
              <ToggleSwitch
                label="Command Blocks"
                description="Allow redstone-triggered command blocks to execute commands."
                checked={enableCommandBlock}
                onChange={setEnableCommandBlock}
                icon="settings"
              />
              <ToggleSwitch
                label="Allow Flight"
                description="Allow survival mode players to fly without triggering automated anti-float kicks."
                checked={allowFlight}
                onChange={setAllowFlight}
                icon="paper"
              />
            </div>
          </div>

          {/* Sub-Group 3: World Generation & Entities */}
          <div className="pt-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary mb-3 flex items-center gap-2">
              <Icon name="globe" size={14} className="text-status-success" />
              Entities & Dimensions
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              <ToggleSwitch
                label="Allow Nether"
                description="Enable Nether portal transit and the Nether dimension."
                checked={allowNether}
                onChange={setAllowNether}
                icon="globe"
              />
              <ToggleSwitch
                label="Spawn Monsters"
                description="Spawn hostile entities (skeletons, zombies, creepers, phantoms)."
                checked={spawnMonsters}
                onChange={setSpawnMonsters}
                icon="alert"
              />
              <ToggleSwitch
                label="Spawn Animals"
                description="Spawn passive wildlife (cows, sheep, pigs, chickens, horses)."
                checked={spawnAnimals}
                onChange={setSpawnAnimals}
                icon="heart"
              />
              <ToggleSwitch
                label="Spawn NPCs"
                description="Spawn villagers and wandering traders in generated settlements."
                checked={spawnNpcs}
                onChange={setSpawnNpcs}
                icon="users"
              />
            </div>
          </div>
        </section>
      )}

      {/* Card 4: Advanced Configuration */}
      {showCard4 && (
        <section className="p-5 sm:p-6 bg-surface-card rounded-2xl border border-border-default shadow-xs space-y-4">
          <div className="flex items-center gap-3 border-b border-border-subtle pb-3.5">
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

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4.5 rounded-xl bg-surface-muted border border-border-default">
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
              className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-semibold shadow-xs transition-colors shrink-0"
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
              <span>Edits are written directly to server.properties &amp; database</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleReset}
            disabled={!isDirty || updateServer.isPending}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Reset to Saved
          </button>

          <button
            type="submit"
            disabled={isSaveDisabled}
            className="px-6 py-2.5 rounded-xl bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-semibold shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {updateServer.isPending ? (
              <>
                <Icon name="restart" size={16} className="animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Icon name="check" size={16} />
                Save Changes
              </>
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
