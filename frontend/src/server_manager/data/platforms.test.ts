import { describe, it, expect } from "vitest";
import {
  getPlatformInfo,
  getPlatformIcon,
  getPlatformLabel,
  isKnownPlatform,
  platformProjectType,
} from "./platforms";

const BACKEND_SOFTWARE_KEYS = [
  "vanilla",
  "paper",
  "purpur",
  "fabric",
  "forge",
  "spigot",
];

const MARKETPLACE_LOADERS = [
  "paper",
  "purpur",
  "spigot",
  "bukkit",
  "folia",
  "velocity",
  "bungeecord",
  "waterfall",
  "fabric",
  "forge",
  "neoforge",
  "quilt",
  "datapack",
];

describe("platforms (single source of truth)", () => {
  it("knows every backend server-software key", () => {
    for (const key of BACKEND_SOFTWARE_KEYS) {
      expect(isKnownPlatform(key), key).toBe(true);
      expect(getPlatformLabel(key)).not.toBe("");
      expect(getPlatformInfo(key).icon).not.toBe("");
      expect(getPlatformInfo(key).color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("maps every marketplace loader to a real icon", () => {
    for (const key of MARKETPLACE_LOADERS) {
      expect(getPlatformIcon(key), key).not.toBe("download");
    }
  });

  it("maps server loaders to plugin projects and mod loaders to mod projects", () => {
    expect(platformProjectType("paper", "plugin")).toBe("plugin");
    expect(platformProjectType("Spigot", "plugin")).toBe("plugin");
    expect(platformProjectType("velocity", "plugin")).toBe("plugin");
    expect(platformProjectType("fabric", "plugin")).toBe("mod");
    expect(platformProjectType("NeoForge", "plugin")).toBe("mod");
    expect(platformProjectType("quilt", "plugin")).toBe("mod");
  });

  it("falls back gracefully for unknown keys", () => {
    expect(isKnownPlatform("minecraft")).toBe(false);
    expect(getPlatformLabel("minecraft")).toBe("minecraft");
    expect(platformProjectType("unknown", "plugin")).toBe("plugin");
  });
});