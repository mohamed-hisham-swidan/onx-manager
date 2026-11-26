import type { IconName } from "@/components/ui/Icon";
import type { HostResourceBudget } from "@/types";
import type { ServerDetailResponse, ServerUpdateRequest } from "@/server_manager/types";

export type ServerSettingsTabId =
  | "general"
  | "resources"
  | "gameplay"
  | "rules"
  | "lifecycle"
  | "danger";

export interface ServerSettingsNavItem {
  id: ServerSettingsTabId;
  label: string;
  icon: IconName;
  group: "configuration" | "lifecycle";
  danger?: boolean;
}

export const SERVER_SETTINGS_NAV_ITEMS: ServerSettingsNavItem[] = [
  { id: "general", label: "General", icon: "sliders", group: "configuration" },
  { id: "resources", label: "Resources & JVM", icon: "cpu", group: "configuration" },
  { id: "gameplay", label: "Gameplay & World", icon: "world", group: "configuration" },
  { id: "rules", label: "Rules & Security", icon: "shield", group: "configuration" },
  { id: "lifecycle", label: "Upgrades & Mode", icon: "version-branch", group: "lifecycle" },
  { id: "danger", label: "Danger Zone", icon: "alert", group: "lifecycle", danger: true },
];

export const FORBIDDEN_JVM_HOOK_FLAGS: readonly string[] = [
  "-XX:OnError",
  "-XX:OnOutOfMemoryError",
  "-XX:Flags=",
  "-XX:VMOptionsFile",
  "-javaagent:",
  "-agentpath:",
  "-agentlib:",
  "-Xrun",
];

export const AIKARS_JVM_FLAGS: readonly string[] = [
  "-XX:+UseG1GC",
  "-XX:+ParallelRefProcEnabled",
  "-XX:MaxGCPauseMillis=200",
  "-XX:+UnlockExperimentalVMOptions",
  "-XX:+DisableExplicitGC",
  "-XX:+AlwaysPreTouch",
  "-XX:G1NewSizePercent=30",
  "-XX:G1MaxNewSizePercent=40",
  "-XX:G1HeapRegionSize=8M",
  "-XX:G1ReservePercent=20",
  "-XX:G1HeapWastePercent=5",
  "-XX:G1MixedGCCountTarget=4",
  "-XX:InitiatingHeapOccupancyPercent=15",
  "-XX:G1MixedGCLiveThresholdPercent=90",
  "-XX:G1RSetUpdatingPauseTimePercent=5",
  "-XX:SurvivorRatio=32",
  "-XX:+PerfDisableSharedMem",
  "-XX:MaxTenuringThreshold=1",
];

export const RAM_PRESETS = [
  { label: "1 GB", min: 512, max: 1024 },
  { label: "2 GB", min: 1024, max: 2048 },
  { label: "4 GB", min: 2048, max: 4096 },
  { label: "6 GB", min: 3072, max: 6144 },
  { label: "8 GB", min: 4096, max: 8192 },
  { label: "16 GB", min: 8192, max: 16384 },
] as const;

export const STARTUP_TIMEOUT_PRESETS = [
  { label: "60s", value: 60 },
  { label: "120s", value: 120 },
  { label: "300s (Modpacks)", value: 300 },
] as const;

export const MAX_PLAYERS_PRESETS = [10, 20, 50, 100] as const;

export const GAMEMODE_OPTIONS = [
  { value: "survival", label: "Survival" },
  { value: "creative", label: "Creative" },
  { value: "adventure", label: "Adventure" },
  { value: "spectator", label: "Spectator" },
] as const;

export const DIFFICULTY_OPTIONS = [
  { value: "peaceful", label: "Peaceful" },
  { value: "easy", label: "Easy" },
  { value: "normal", label: "Normal" },
  { value: "hard", label: "Hard" },
] as const;

export const SPAWN_PROTECTION_MIN = 0;
export const SPAWN_PROTECTION_MAX = 256;
export const DISTANCE_MIN = 2;
export const DISTANCE_MAX = 32;
export const PORT_MIN = 1024;
export const PORT_MAX = 65535;
export const MAX_PLAYERS_MIN = 1;
export const MAX_PLAYERS_MAX = 500;
export const STARTUP_TIMEOUT_MIN = 30;
export const STARTUP_TIMEOUT_MAX = 1800;
export const MIN_RAM_FLOOR = 128;

const KNOWN_GUI_PROPERTY_KEYS = new Set([
  "server-name",
  "server_name",
  "name",
  "server-port",
  "server_port",
  "port",
  "motd",
  "gamemode",
  "difficulty",
  "max-players",
  "max_players",
  "spawn-protection",
  "spawn_protection",
  "view-distance",
  "view_distance",
  "simulation-distance",
  "simulation_distance",
  "pvp",
  "online-mode",
  "online_mode",
  "white-list",
  "whitelist",
  "enable-command-block",
  "enable_command_block",
  "allow-flight",
  "allow_flight",
  "spawn-monsters",
  "spawn_monsters",
  "spawn-animals",
  "spawn_animals",
  "spawn-npcs",
  "spawn_npcs",
  "allow-nether",
  "allow_nether",
  "hardcore",
  "force-gamemode",
  "force_gamemode",
  "enforce-secure-profile",
  "enforce_secure_profile",
  "generate-structures",
  "generate_structures",
  "sync-chunk-writes",
  "sync_chunk_writes",
]);

const CLASS_D_PANEL_KEYS = new Set([
  "server-port",
  "query.port",
  "rcon.port",
  "rcon.password",
  "enable-rcon",
  "enable-query",
  "broadcast-rcon-to-ops",
]);

export interface ServerSettingsFormState {
  name: string;
  port: number;
  motd: string;
  minRam: number;
  maxRam: number;
  cpuCores: number;
  cpuAffinity: string;
  javaArgs: string;
  startupTimeout: number;
  gamemode: string;
  difficulty: string;
  maxPlayers: number;
  spawnProtection: number;
  viewDistance: number;
  simulationDistance: number;
  pvp: boolean;
  onlineMode: boolean;
  whitelist: boolean;
  enableCommandBlock: boolean;
  allowFlight: boolean;
  spawnMonsters: boolean;
  spawnAnimals: boolean;
  spawnNpcs: boolean;
  allowNether: boolean;
  hardcore: boolean;
  forceGamemode: boolean;
  enforceSecureProfile: boolean;
  generateStructures: boolean;
  syncChunkWrites: boolean;
}

export type NumericDraftKey =
  | "port"
  | "minRam"
  | "maxRam"
  | "cpuCores"
  | "startupTimeout"
  | "maxPlayers"
  | "spawnProtection"
  | "viewDistance"
  | "simulationDistance";

export interface NumericBound {
  min: number;
  max: number;
  integer?: boolean;
}

export function parseBoolProp(val: unknown, defaultVal = false): boolean {
  if (typeof val === "boolean") return val;
  if (typeof val === "string") {
    const s = val.toLowerCase().trim();
    if (s === "true" || s === "1" || s === "yes" || s === "on") return true;
    if (s === "false" || s === "0" || s === "no" || s === "off") return false;
  }
  return defaultVal;
}

export function validateCpuAffinity(affinity: string): boolean {
  const trimmed = affinity.trim();
  if (!trimmed) return true;
  const regex = /^[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*$/;
  if (!regex.test(trimmed)) return false;
  const parts = trimmed.replace(/,/g, " ").split(/\s+/);
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

export function validateJvmArgs(javaArgsText: string): string | null {
  const lines = javaArgsText
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const rejectedShellChars = /[`$;|&<>()!{}]/;

  for (const line of lines) {
    if (!line.startsWith("-")) {
      return "Every JVM flag must start with '-'.";
    }
    if (line.length > 1024) {
      return "Each JVM flag must be 1024 characters or fewer.";
    }
    if (rejectedShellChars.test(line)) {
      return "JVM flags cannot contain prohibited shell characters.";
    }
    const lower = line.toLowerCase();
    for (const forbidden of FORBIDDEN_JVM_HOOK_FLAGS) {
      if (lower.startsWith(forbidden.toLowerCase())) {
        return `Disallowed JVM flag: ${forbidden}`;
      }
    }
  }
  return null;
}

export function normalizeJavaArgsDisplay(raw: string | null | undefined): string {
  if (!raw) return "";
  return raw.split(/\s+/).filter(Boolean).join("\n");
}

export function buildInitialFormState(server: ServerDetailResponse): ServerSettingsFormState {
  const raw = server.raw_properties;
  return {
    name: server.name || "",
    port: server.port || 25565,
    motd: server.motd || "",
    minRam: server.min_memory_mb || 1024,
    maxRam: server.max_memory_mb || 2048,
    cpuCores: server.cpu_cores ?? 0,
    cpuAffinity: server.cpu_affinity || "",
    javaArgs: normalizeJavaArgsDisplay(server.java_args),
    startupTimeout: server.startup_timeout_seconds ?? 120,
    gamemode: server.gamemode || "survival",
    difficulty: server.difficulty || "easy",
    maxPlayers: server.max_players || 20,
    spawnProtection: server.spawn_protection ?? 16,
    viewDistance: server.view_distance ?? 10,
    simulationDistance: server.simulation_distance ?? 10,
    pvp: server.pvp ?? true,
    onlineMode: server.online_mode ?? true,
    whitelist: server.whitelist ?? false,
    enableCommandBlock: server.enable_command_block ?? false,
    allowFlight: parseBoolProp(raw?.["allow-flight"], false),
    spawnMonsters: parseBoolProp(raw?.["spawn-monsters"], true),
    spawnAnimals: parseBoolProp(raw?.["spawn-animals"], true),
    spawnNpcs: parseBoolProp(raw?.["spawn-npcs"], true),
    allowNether: parseBoolProp(raw?.["allow-nether"], true),
    hardcore: parseBoolProp(raw?.["hardcore"], false),
    forceGamemode: parseBoolProp(raw?.["force-gamemode"], false),
    enforceSecureProfile: parseBoolProp(raw?.["enforce-secure-profile"], false),
    generateStructures: parseBoolProp(raw?.["generate-structures"], true),
    syncChunkWrites: parseBoolProp(raw?.["sync-chunk-writes"], true),
  };
}

export function buildServerSnapshotKey(server: ServerDetailResponse): string {
  return JSON.stringify(buildInitialFormState(server));
}

export function extractCustomProperties(
  server: ServerDetailResponse,
): Record<string, string> {
  if (!server.raw_properties) return {};
  const customs: Record<string, string> = {};
  for (const [k, v] of Object.entries(server.raw_properties)) {
    const norm = k.toLowerCase().trim();
    if (
      KNOWN_GUI_PROPERTY_KEYS.has(norm) ||
      CLASS_D_PANEL_KEYS.has(norm) ||
      norm.startsWith("management-server-")
    ) {
      continue;
    }
    customs[k] = v;
  }
  return customs;
}

export function computeDirtyFields(
  form: ServerSettingsFormState,
  baseline: ServerSettingsFormState,
): (keyof ServerSettingsFormState)[] {
  const keys = Object.keys(baseline) as (keyof ServerSettingsFormState)[];
  return keys.filter((k) => form[k] !== baseline[k]);
}

export function getNumericBounds(hostBudget?: HostResourceBudget | null): Record<
  NumericDraftKey,
  NumericBound
> {
  const maxAllocRam = hostBudget?.allocatable_ram_mb ?? 262144;
  const maxAllocCpus = hostBudget?.allocatable_cpus
    ? Math.max(1, Math.floor(hostBudget.allocatable_cpus))
    : 256;
  return {
    port: { min: PORT_MIN, max: PORT_MAX, integer: true },
    minRam: { min: MIN_RAM_FLOOR, max: maxAllocRam, integer: true },
    maxRam: { min: MIN_RAM_FLOOR, max: maxAllocRam, integer: true },
    cpuCores: { min: 0, max: maxAllocCpus, integer: true },
    startupTimeout: { min: STARTUP_TIMEOUT_MIN, max: STARTUP_TIMEOUT_MAX, integer: true },
    maxPlayers: { min: MAX_PLAYERS_MIN, max: MAX_PLAYERS_MAX, integer: true },
    spawnProtection: { min: SPAWN_PROTECTION_MIN, max: SPAWN_PROTECTION_MAX, integer: true },
    viewDistance: { min: DISTANCE_MIN, max: DISTANCE_MAX, integer: true },
    simulationDistance: { min: DISTANCE_MIN, max: DISTANCE_MAX, integer: true },
  };
}

export function clampNumericValue(
  raw: string,
  fallback: number,
  bound: NumericBound,
): number {
  if (raw.trim() === "" || isNaN(Number(raw))) {
    return Math.min(bound.max, Math.max(bound.min, fallback));
  }
  let num = Number(raw);
  if (bound.integer) num = Math.round(num);
  if (num < bound.min) num = bound.min;
  if (num > bound.max) num = bound.max;
  return num;
}

export function clampDraftsIntoState(
  form: ServerSettingsFormState,
  rawDrafts: Partial<Record<NumericDraftKey, string>>,
  hostBudget?: HostResourceBudget | null,
): ServerSettingsFormState {
  const entries = Object.entries(rawDrafts) as [NumericDraftKey, string | undefined][];
  if (entries.length === 0) return form;
  const bounds = getNumericBounds(hostBudget);
  const next = { ...form };
  for (const [key, draft] of entries) {
    if (draft !== undefined) {
      next[key] = clampNumericValue(draft, form[key], bounds[key]);
    }
  }
  return next;
}

export interface ServerValidationErrors {
  name: string | null;
  port: string | null;
  ram: string | null;
  cpuAffinity: string | null;
  jvmArgs: string | null;
  startupTimeout: string | null;
  maxPlayers: string | null;
  spawnProtection: string | null;
  viewDistance: string | null;
  simulationDistance: string | null;
  hasAny: boolean;
}

export function validateServerForm(
  form: ServerSettingsFormState,
  hostBudget?: HostResourceBudget | null,
): ServerValidationErrors {
  const maxAllocRam = hostBudget?.allocatable_ram_mb ?? 262144;
  const name = !form.name.trim()
    ? "Server name is required."
    : form.name.trim().length > 128
      ? "Server name must be 128 characters or fewer."
      : null;
  const port =
    !Number.isInteger(form.port) || form.port < PORT_MIN || form.port > PORT_MAX
      ? `Port must be between ${PORT_MIN} and ${PORT_MAX}.`
      : null;

  let ram: string | null = null;
  if (form.minRam < MIN_RAM_FLOOR) {
    ram = `Minimum RAM must be at least ${MIN_RAM_FLOOR} MB.`;
  } else if (form.maxRam > maxAllocRam) {
    ram = hostBudget
      ? `Maximum RAM cannot exceed ${hostBudget.allocatable_ram_mb} MB host limit.`
      : "Maximum RAM cannot exceed 262,144 MB.";
  } else if (form.minRam > form.maxRam) {
    ram = "Minimum RAM cannot exceed Maximum RAM.";
  }

  const cpuAffinity = validateCpuAffinity(form.cpuAffinity)
    ? null
    : "Use core ranges or lists like 0-3 or 0,2,4.";
  const jvmArgs = validateJvmArgs(form.javaArgs);
  const startupTimeout =
    form.startupTimeout < STARTUP_TIMEOUT_MIN || form.startupTimeout > STARTUP_TIMEOUT_MAX
      ? `Timeout must be between ${STARTUP_TIMEOUT_MIN} and ${STARTUP_TIMEOUT_MAX}s.`
      : null;
  const maxPlayers =
    form.maxPlayers < MAX_PLAYERS_MIN || form.maxPlayers > MAX_PLAYERS_MAX
      ? `Max players must be between ${MAX_PLAYERS_MIN} and ${MAX_PLAYERS_MAX}.`
      : null;
  const spawnProtection =
    form.spawnProtection < SPAWN_PROTECTION_MIN || form.spawnProtection > SPAWN_PROTECTION_MAX
      ? `Spawn protection must be between ${SPAWN_PROTECTION_MIN} and ${SPAWN_PROTECTION_MAX}.`
      : null;
  const viewDistance =
    form.viewDistance < DISTANCE_MIN || form.viewDistance > DISTANCE_MAX
      ? `View distance must be between ${DISTANCE_MIN} and ${DISTANCE_MAX}.`
      : null;
  const simulationDistance =
    form.simulationDistance < DISTANCE_MIN || form.simulationDistance > DISTANCE_MAX
      ? `Simulation distance must be between ${DISTANCE_MIN} and ${DISTANCE_MAX}.`
      : null;

  const hasAny = Boolean(
    name ||
      port ||
      ram ||
      cpuAffinity ||
      jvmArgs ||
      startupTimeout ||
      maxPlayers ||
      spawnProtection ||
      viewDistance ||
      simulationDistance,
  );

  return {
    name,
    port,
    ram,
    cpuAffinity,
    jvmArgs,
    startupTimeout,
    maxPlayers,
    spawnProtection,
    viewDistance,
    simulationDistance,
    hasAny,
  };
}

const FORM_PROP_KEYS: Array<{
  field: keyof ServerSettingsFormState;
  propKey: string;
}> = [
  { field: "motd", propKey: "motd" },
  { field: "gamemode", propKey: "gamemode" },
  { field: "difficulty", propKey: "difficulty" },
  { field: "maxPlayers", propKey: "max-players" },
  { field: "spawnProtection", propKey: "spawn-protection" },
  { field: "viewDistance", propKey: "view-distance" },
  { field: "simulationDistance", propKey: "simulation-distance" },
  { field: "pvp", propKey: "pvp" },
  { field: "onlineMode", propKey: "online-mode" },
  { field: "whitelist", propKey: "white-list" },
  { field: "enableCommandBlock", propKey: "enable-command-block" },
  { field: "allowFlight", propKey: "allow-flight" },
  { field: "spawnMonsters", propKey: "spawn-monsters" },
  { field: "spawnAnimals", propKey: "spawn-animals" },
  { field: "spawnNpcs", propKey: "spawn-npcs" },
  { field: "allowNether", propKey: "allow-nether" },
  { field: "hardcore", propKey: "hardcore" },
  { field: "forceGamemode", propKey: "force-gamemode" },
  { field: "enforceSecureProfile", propKey: "enforce-secure-profile" },
  { field: "generateStructures", propKey: "generate-structures" },
  { field: "syncChunkWrites", propKey: "sync-chunk-writes" },
];

export function buildServerUpdatePayload(
  form: ServerSettingsFormState,
  baseline: ServerSettingsFormState,
  customProperties: Record<string, string>,
  opts: { gitBacked: boolean; isWorkingBranch: boolean },
): ServerUpdateRequest {
  const jvmArgList = form.javaArgs
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

  if (!opts.gitBacked) {
    const payload: ServerUpdateRequest = {
      name: form.name.trim(),
      min_memory_mb: form.minRam,
      max_memory_mb: form.maxRam,
      cpu_cores: form.cpuCores,
      cpu_affinity: form.cpuAffinity.trim(),
      java_args: jvmArgList,
      properties: {
        "server-port": form.port,
        motd: form.motd,
        gamemode: form.gamemode,
        difficulty: form.difficulty,
        "max-players": form.maxPlayers,
        "spawn-protection": form.spawnProtection,
        "view-distance": form.viewDistance,
        "simulation-distance": form.simulationDistance,
        pvp: form.pvp,
        "online-mode": form.onlineMode,
        "white-list": form.whitelist,
        "enable-command-block": form.enableCommandBlock,
        "allow-flight": form.allowFlight,
        "spawn-monsters": form.spawnMonsters,
        "spawn-animals": form.spawnAnimals,
        "spawn-npcs": form.spawnNpcs,
        "allow-nether": form.allowNether,
        hardcore: form.hardcore,
        "force-gamemode": form.forceGamemode,
        "enforce-secure-profile": form.enforceSecureProfile,
        "generate-structures": form.generateStructures,
        "sync-chunk-writes": form.syncChunkWrites,
        ...customProperties,
      },
    };
    if (form.startupTimeout !== baseline.startupTimeout) {
      payload.startup_timeout_seconds = form.startupTimeout;
    }
    return payload;
  }

  // Advanced mode: only send changed fields so server-wide edits on main
  // (name, server-port, startup_timeout_seconds) never trigger empty pending branches.
  const payload: ServerUpdateRequest = {};

  if (form.name.trim() !== baseline.name.trim()) {
    payload.name = form.name.trim();
  }
  if (form.startupTimeout !== baseline.startupTimeout) {
    payload.startup_timeout_seconds = form.startupTimeout;
  }

  if (form.minRam !== baseline.minRam || form.maxRam !== baseline.maxRam) {
    payload.min_memory_mb = form.minRam;
    payload.max_memory_mb = form.maxRam;
  }
  if (form.cpuCores !== baseline.cpuCores || form.cpuAffinity !== baseline.cpuAffinity) {
    payload.cpu_cores = form.cpuCores;
    payload.cpu_affinity = form.cpuAffinity.trim();
  }
  if (form.javaArgs !== baseline.javaArgs) {
    payload.java_args = jvmArgList;
  }

  const changedProps: Record<string, unknown> = {};
  if (!opts.isWorkingBranch && form.port !== baseline.port) {
    changedProps["server-port"] = form.port;
  }
  for (const { field, propKey } of FORM_PROP_KEYS) {
    if (form[field] !== baseline[field]) {
      changedProps[propKey] = form[field];
    }
  }
  if (Object.keys(changedProps).length > 0) {
    payload.properties = changedProps;
  }

  return payload;
}

export type SearchRowControlId =
  | "server-icon"
  | "server-name"
  | "motd"
  | "server-port"
  | "ram-allocation"
  | "cpu-cores"
  | "startup-timeout"
  | "jvm-args"
  | "cpu-affinity"
  | "gamemode"
  | "difficulty"
  | "max-players"
  | "view-distance"
  | "simulation-distance"
  | "spawn-protection"
  | "online-mode"
  | "whitelist"
  | "enforce-secure-profile"
  | "force-gamemode"
  | "pvp"
  | "hardcore"
  | "enable-command-block"
  | "allow-flight"
  | "allow-nether"
  | "spawn-monsters"
  | "spawn-animals"
  | "spawn-npcs"
  | "generate-structures"
  | "sync-chunk-writes"
  | "p55-health-timeout"
  | "p55-optional-files"
  | "p55-experimental-paper"
  | "p55-allowlist"
  | "server-mode"
  | "delete-server";

export interface ServerSettingsSearchEntry {
  id: SearchRowControlId;
  label: string;
  description: string;
  tabId: ServerSettingsTabId;
  tabLabel: string;
  keywords: string[];
  sectionType: "form" | "jump";
}

export const SERVER_SETTINGS_SEARCH_INDEX: ServerSettingsSearchEntry[] = [
  {
    id: "server-icon",
    label: "Server Icon",
    description: "64×64 PNG icon shown in multiplayer lists.",
    tabId: "general",
    tabLabel: "General",
    keywords: ["icon", "png", "logo", "server-icon.png", "image"],
    sectionType: "form",
  },
  {
    id: "server-name",
    label: "Server Name",
    description: "Display name shown across the panel.",
    tabId: "general",
    tabLabel: "General",
    keywords: ["name", "title", "identity", "server-name"],
    sectionType: "form",
  },
  {
    id: "motd",
    label: "MOTD",
    description: "Tagline shown in the Minecraft server list.",
    tabId: "general",
    tabLabel: "General",
    keywords: ["motd", "message of the day", "description", "tagline"],
    sectionType: "form",
  },
  {
    id: "server-port",
    label: "Game Port",
    description: "Host TCP/UDP port players connect to.",
    tabId: "general",
    tabLabel: "General",
    keywords: ["port", "server-port", "network", "socket", "tcp", "udp"],
    sectionType: "form",
  },
  {
    id: "ram-allocation",
    label: "Memory Allocation (RAM)",
    description: "Minimum (-Xms) and maximum (-Xmx) Java heap.",
    tabId: "resources",
    tabLabel: "Resources & JVM",
    keywords: ["ram", "memory", "xms", "xmx", "heap", "min_memory_mb", "max_memory_mb", "preset"],
    sectionType: "form",
  },
  {
    id: "cpu-cores",
    label: "CPU Core Limit",
    description: "Maximum CPU cores allocated to the container.",
    tabId: "resources",
    tabLabel: "Resources & JVM",
    keywords: ["cpu", "cores", "cpu_cores", "processor", "threads"],
    sectionType: "form",
  },
  {
    id: "startup-timeout",
    label: "Server Startup Timeout",
    description: "Max seconds to wait before marking boot failed.",
    tabId: "resources",
    tabLabel: "Resources & JVM",
    keywords: ["startup", "timeout", "boot", "startup_timeout_seconds"],
    sectionType: "form",
  },
  {
    id: "jvm-args",
    label: "Custom JVM Arguments",
    description: "Extra Java flags passed on startup.",
    tabId: "resources",
    tabLabel: "Resources & JVM",
    keywords: ["jvm", "java", "args", "flags", "aikar", "g1gc", "java_args"],
    sectionType: "form",
  },
  {
    id: "cpu-affinity",
    label: "CPU Affinity Mask",
    description: "Pin process threads to specific host CPU cores.",
    tabId: "resources",
    tabLabel: "Resources & JVM",
    keywords: ["affinity", "pinning", "cpuset", "cpu_affinity"],
    sectionType: "form",
  },
  {
    id: "gamemode",
    label: "Default Gamemode",
    description: "Initial game mode for new players.",
    tabId: "gameplay",
    tabLabel: "Gameplay & World",
    keywords: ["gamemode", "survival", "creative", "adventure", "spectator"],
    sectionType: "form",
  },
  {
    id: "difficulty",
    label: "Difficulty",
    description: "World hazard and mob damage level.",
    tabId: "gameplay",
    tabLabel: "Gameplay & World",
    keywords: ["difficulty", "peaceful", "easy", "normal", "hard"],
    sectionType: "form",
  },
  {
    id: "max-players",
    label: "Max Players",
    description: "Maximum simultaneous connected players.",
    tabId: "gameplay",
    tabLabel: "Gameplay & World",
    keywords: ["players", "max-players", "slots", "capacity"],
    sectionType: "form",
  },
  {
    id: "view-distance",
    label: "View Distance",
    description: "Chunk radius streamed to connected clients.",
    tabId: "gameplay",
    tabLabel: "Gameplay & World",
    keywords: ["view", "distance", "chunks", "render", "view-distance"],
    sectionType: "form",
  },
  {
    id: "simulation-distance",
    label: "Simulation Distance",
    description: "Chunk radius where entities and redstone tick.",
    tabId: "gameplay",
    tabLabel: "Gameplay & World",
    keywords: ["simulation", "distance", "chunks", "tick", "simulation-distance"],
    sectionType: "form",
  },
  {
    id: "spawn-protection",
    label: "Spawn Protection",
    description: "Block radius around spawn locked for non-operators.",
    tabId: "gameplay",
    tabLabel: "Gameplay & World",
    keywords: ["spawn", "protection", "radius", "spawn-protection"],
    sectionType: "form",
  },
  {
    id: "online-mode",
    label: "Online Mode",
    description: "Verify accounts against Mojang authentication servers.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["online-mode", "mojang", "auth", "cracked", "offline"],
    sectionType: "form",
  },
  {
    id: "whitelist",
    label: "Whitelist",
    description: "Allow only players listed in whitelist.json.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["whitelist", "white-list", "access", "allow"],
    sectionType: "form",
  },
  {
    id: "enforce-secure-profile",
    label: "Enforce Secure Profile",
    description: "Require Mojang-signed keys for player chat.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["secure", "profile", "chat", "enforce-secure-profile", "signing"],
    sectionType: "form",
  },
  {
    id: "force-gamemode",
    label: "Force Gamemode",
    description: "Reset joining players to the default gamemode.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["force", "gamemode", "force-gamemode"],
    sectionType: "form",
  },
  {
    id: "pvp",
    label: "PvP",
    description: "Allow player-versus-player combat damage.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["pvp", "combat", "damage"],
    sectionType: "form",
  },
  {
    id: "hardcore",
    label: "Hardcore Mode",
    description: "Ban or lock players to spectator on death.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["hardcore", "permadeath"],
    sectionType: "form",
  },
  {
    id: "enable-command-block",
    label: "Command Blocks",
    description: "Allow redstone command blocks to execute commands.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["command", "block", "enable-command-block", "redstone"],
    sectionType: "form",
  },
  {
    id: "allow-flight",
    label: "Allow Flight",
    description: "Prevent survival flight kicks for modded movement.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["flight", "fly", "allow-flight", "kick"],
    sectionType: "form",
  },
  {
    id: "allow-nether",
    label: "Allow Nether",
    description: "Enable Nether portals and dimension.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["nether", "dimension", "allow-nether", "portal"],
    sectionType: "form",
  },
  {
    id: "spawn-monsters",
    label: "Spawn Monsters",
    description: "Spawn hostile mobs at night and in caves.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["monsters", "mobs", "hostile", "spawn-monsters"],
    sectionType: "form",
  },
  {
    id: "spawn-animals",
    label: "Spawn Animals",
    description: "Spawn passive wildlife across chunks.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["animals", "passive", "wildlife", "spawn-animals"],
    sectionType: "form",
  },
  {
    id: "spawn-npcs",
    label: "Spawn NPCs",
    description: "Spawn villagers and wandering traders.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["npcs", "villagers", "traders", "spawn-npcs"],
    sectionType: "form",
  },
  {
    id: "generate-structures",
    label: "Generate Structures",
    description: "Applies to newly generated chunks only.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["structures", "villages", "strongholds", "generate-structures"],
    sectionType: "form",
  },
  {
    id: "sync-chunk-writes",
    label: "Sync Chunk Writes",
    description: "Flush chunk saves synchronously to protect world data.",
    tabId: "rules",
    tabLabel: "Rules & Security",
    keywords: ["sync", "chunk", "writes", "disk", "sync-chunk-writes"],
    sectionType: "form",
  },
  {
    id: "p55-health-timeout",
    label: "Health Gate Boot Timeout",
    description: "Change Version health-gate boot wait window (300–900s).",
    tabId: "lifecycle",
    tabLabel: "Upgrades & Mode",
    keywords: ["health", "gate", "timeout", "upgrade", "modpack", "p55"],
    sectionType: "jump",
  },
  {
    id: "p55-optional-files",
    label: "Install Optional Server Files",
    description: "Include optional modpack server entries on install.",
    tabId: "lifecycle",
    tabLabel: "Upgrades & Mode",
    keywords: ["optional", "modpack", "files", "upgrade"],
    sectionType: "jump",
  },
  {
    id: "p55-experimental-paper",
    label: "Allow Experimental Paper Builds",
    description: "Permit fallback to experimental Paper builds.",
    tabId: "lifecycle",
    tabLabel: "Upgrades & Mode",
    keywords: ["experimental", "paper", "builds", "upgrade"],
    sectionType: "jump",
  },
  {
    id: "p55-allowlist",
    label: "Extra Allowed Download Hosts",
    description: "Trusted custom hostnames for modpack downloads.",
    tabId: "lifecycle",
    tabLabel: "Upgrades & Mode",
    keywords: ["allowlist", "hosts", "download", "domain", "mirror"],
    sectionType: "jump",
  },
  {
    id: "server-mode",
    label: "Server Mode (Simple ↔ Advanced)",
    description: "Convert between Simple mode and Git-backed Advanced mode.",
    tabId: "lifecycle",
    tabLabel: "Upgrades & Mode",
    keywords: ["mode", "simple", "advanced", "convert", "git", "branch"],
    sectionType: "jump",
  },
  {
    id: "delete-server",
    label: "Delete Server",
    description: "Permanently remove this server and all data.",
    tabId: "danger",
    tabLabel: "Danger Zone",
    keywords: ["delete", "remove", "destroy", "danger"],
    sectionType: "jump",
  },
];

export function filterSearchEntries(query: string): ServerSettingsSearchEntry[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return [];
  return SERVER_SETTINGS_SEARCH_INDEX.filter(
    (entry) =>
      entry.label.toLowerCase().includes(normalized) ||
      entry.description.toLowerCase().includes(normalized) ||
      entry.tabLabel.toLowerCase().includes(normalized) ||
      entry.keywords.some((k) => k.toLowerCase().includes(normalized)),
  );
}
