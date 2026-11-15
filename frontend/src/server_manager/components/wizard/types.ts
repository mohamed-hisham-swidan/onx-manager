import type { ServerMode } from "../../types";

export type Step = "software" | "version" | "config" | "properties" | "review" | "done";

export const STEPS: { key: Step; label: string }[] = [
  { key: "software", label: "Software" },
  { key: "version", label: "Version" },
  { key: "config", label: "Configuration" },
  { key: "properties", label: "Properties" },
  { key: "review", label: "Review" },
];

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
  provider: string;
}

export const INITIAL_DATA: WizardData = {
  serverType: "",
  minecraftVersion: "",
  name: "",
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
  provider: "",
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
