import { describe, it, expect } from "vitest";
import { ChannelManager, MAX_CHANNELS } from "./channels";

describe("ChannelManager", () => {
  it("starts empty", () => {
    const cm = new ChannelManager();
    expect(cm.size).toBe(0);
    expect(cm.channels).toEqual([]);
  });

  it("adds a channel", () => {
    const cm = new ChannelManager();
    expect(cm.add("server:s01")).toBe(true);
    expect(cm.has("server:s01")).toBe(true);
    expect(cm.size).toBe(1);
  });

  it("does not allow duplicates", () => {
    const cm = new ChannelManager();
    cm.add("server:s01");
    cm.add("server:s01");
    expect(cm.size).toBe(1);
  });

  it("removes a channel", () => {
    const cm = new ChannelManager();
    cm.add("server:s01");
    expect(cm.remove("server:s01")).toBe(true);
    expect(cm.has("server:s01")).toBe(false);
  });

  it("removes a nonexistent channel", () => {
    const cm = new ChannelManager();
    expect(cm.remove("nonexistent")).toBe(false);
  });

  it("enforces max channels", () => {
    const cm = new ChannelManager();
    for (let i = 0; i < MAX_CHANNELS; i++) {
      expect(cm.add(`server:s${i}`)).toBe(true);
    }
    expect(cm.add("extra:channel")).toBe(false);
    expect(cm.isFull()).toBe(true);
  });

  it("clears all channels", () => {
    const cm = new ChannelManager();
    cm.add("server:s01");
    cm.add("backup:*");
    cm.clear();
    expect(cm.size).toBe(0);
  });

  it("returns a snapshot", () => {
    const cm = new ChannelManager();
    cm.add("server:s01");
    cm.add("backup:*");
    expect(cm.snapshot()).toEqual(["server:s01", "backup:*"]);
  });

  it("validates channel format", () => {
    expect(ChannelManager.validateChannel("server:s01")).toBe(true);
    expect(ChannelManager.validateChannel("backup:*")).toBe(true);
    expect(ChannelManager.validateChannel("")).toBe(false);
    expect(ChannelManager.validateChannel("invalid")).toBe(false);
    expect(ChannelManager.validateChannel("a:b:c")).toBe(false);
    expect(ChannelManager.validateChannel("unknown:test")).toBe(false);
  });

  it("detects wildcard channels", () => {
    expect(ChannelManager.isWildcard("server:*")).toBe(true);
    expect(ChannelManager.isWildcard("backup:*")).toBe(true);
    expect(ChannelManager.isWildcard("server:s01")).toBe(false);
  });

  it("detects channel types", () => {
    expect(ChannelManager.isServerChannel("server:s01")).toBe(true);
    expect(ChannelManager.isServerChannel("backup:*")).toBe(false);
    expect(ChannelManager.isBackupChannel("backup:*")).toBe(true);
    expect(ChannelManager.isPluginChannel("plugin:essentials")).toBe(true);
    expect(ChannelManager.isMonitoringChannel("monitoring:s01")).toBe(true);
    expect(ChannelManager.isMonitoringChannel("metrics:s01")).toBe(true);
  });

  it("tracks authorization", () => {
    const cm = new ChannelManager();
    cm.add("server:s01", true);
    cm.add("backup:*", false);
    expect(cm.subscriptions).toEqual([
      { channel: "server:s01", authorized: true },
      { channel: "backup:*", authorized: false },
    ]);
  });
});
