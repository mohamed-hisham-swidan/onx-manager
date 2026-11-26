import type { ServerMode } from "../../types";
import { isModpackSupportedLoader, isPluginLoader } from "@/server_manager/utils/loaderCapabilities";

export type Step = "software" | "version" | "config" | "properties" | "addons" | "review" | "done";

export interface SelectedWizardAddon {
  project_id: string;
  title: string;
  author: string;
  description: string;
  icon_url: string | null;
  downloads: number;
  project_type: "mod" | "plugin";
}

export const STEPS: { key: Step; label: string }[] = [
  { key: "software", label: "Software" },
  { key: "version", label: "Version" },
  { key: "config", label: "Configuration" },
  { key: "properties", label: "Properties" },
  { key: "review", label: "Review" },
];

export function getWizardSteps(serverType: string): { key: Step; label: string }[] {
  const modded = isModpackSupportedLoader(serverType);
  const pluginBased = isPluginLoader(serverType);
  if (!modded && !pluginBased) {
    return STEPS;
  }
  const addonsLabel = modded ? "Mods & Modpack" : "Plugins";
  return [
    { key: "software", label: "Software" },
    { key: "version", label: "Version" },
    { key: "config", label: "Configuration" },
    { key: "properties", label: "Properties" },
    { key: "addons", label: addonsLabel },
    { key: "review", label: "Review" },
  ];
}

export function generateNextServerName(existingNames: string[], baseName = "Server"): string {
  const trimmedBase = baseName.trim() || "Server";
  const taken = new Set(existingNames.map((n) => n.trim().toLowerCase()).filter(Boolean));
  if (!taken.has(trimmedBase.toLowerCase())) {
    return trimmedBase;
  }
  let counter = 2;
  while (taken.has(`${trimmedBase} ${counter}`.toLowerCase())) {
    counter += 1;
  }
  return `${trimmedBase} ${counter}`;
}

export interface WizardData {
  serverType: string;
  minecraftVersion: string;
  name: string;
  mode: ServerMode;
  port: number | "";
  maxPlayers: number | "";
  minMemoryMb: number | "";
  maxMemoryMb: number | "";
  motd: string;
  gamemode: string;
  difficulty: string;
  spawnProtection: number | "";
  pvp: boolean;
  enableCommandBlock: boolean;
  onlineMode: boolean;
  whitelist: boolean;
  viewDistance: number | "";
  simulationDistance: number | "";
  levelSeed?: string;
  provider: string;
  selectedAddons: SelectedWizardAddon[];
}

export const INITIAL_DATA: WizardData = {
  serverType: "",
  minecraftVersion: "",
  name: "Server",
  mode: "simple",
  port: 25565,
  maxPlayers: 20,
  minMemoryMb: 1024,
  maxMemoryMb: 2048,
  motd: "A Minecraft Server",
  gamemode: "survival",
  difficulty: "easy",
  spawnProtection: 16,
  pvp: true,
  enableCommandBlock: false,
  onlineMode: true,
  whitelist: false,
  viewDistance: 10,
  simulationDistance: 10,
  provider: "docker",
  selectedAddons: [],
};

export const RAM_PRESETS = [
  { label: "512 MB", min: 512, max: 512 },
  { label: "1 GB", min: 1024, max: 1024 },
  { label: "2 GB", min: 1024, max: 2048 },
  { label: "4 GB", min: 2048, max: 4096 },
  { label: "8 GB", min: 4096, max: 8192 },
  { label: "16 GB", min: 8192, max: 16384 },
  { label: "32 GB", min: 16384, max: 32768 },
  { label: "64 GB", min: 32768, max: 65536 },
  { label: "128 GB", min: 65536, max: 131072 },
];
