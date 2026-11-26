import { describe, it, expect } from "vitest";
import { getServerCapabilities } from "./serverCapabilities";

describe("getServerCapabilities", () => {
  it("handles a mods-only type (fabric, forge)", () => {
    expect(getServerCapabilities("fabric")).toEqual({ supportsMods: true, supportsPlugins: false });
    expect(getServerCapabilities("forge")).toEqual({ supportsMods: true, supportsPlugins: false });
  });

  it("handles a plugins-only type (paper, purpur, spigot, bukkit, folia, velocity, bungeecord, waterfall, minestom)", () => {
    expect(getServerCapabilities("paper")).toEqual({ supportsMods: false, supportsPlugins: true });
    expect(getServerCapabilities("purpur")).toEqual({ supportsMods: false, supportsPlugins: true });
    expect(getServerCapabilities("spigot")).toEqual({ supportsMods: false, supportsPlugins: true });
    expect(getServerCapabilities("bukkit")).toEqual({ supportsMods: false, supportsPlugins: true });
    expect(getServerCapabilities("folia")).toEqual({ supportsMods: false, supportsPlugins: true });
    expect(getServerCapabilities("velocity")).toEqual({ supportsMods: false, supportsPlugins: true });
    expect(getServerCapabilities("bungeecord")).toEqual({ supportsMods: false, supportsPlugins: true });
    expect(getServerCapabilities("waterfall")).toEqual({ supportsMods: false, supportsPlugins: true });
    expect(getServerCapabilities("minestom")).toEqual({ supportsMods: false, supportsPlugins: true });
  });

  it("handles vanilla (neither mods nor plugins)", () => {
    expect(getServerCapabilities("vanilla")).toEqual({ supportsMods: false, supportsPlugins: false });
    expect(getServerCapabilities("VANILLA")).toEqual({ supportsMods: false, supportsPlugins: false });
  });

  it("returns false for empty/null/undefined serverType (prevents tab flash on load) and permissive for unrecognized types", () => {
    expect(getServerCapabilities("custom_unknown_type")).toEqual({ supportsMods: true, supportsPlugins: true });
    expect(getServerCapabilities("")).toEqual({ supportsMods: false, supportsPlugins: false });
    expect(getServerCapabilities(null)).toEqual({ supportsMods: false, supportsPlugins: false });
    expect(getServerCapabilities(undefined)).toEqual({ supportsMods: false, supportsPlugins: false });
  });
});
