import { describe, it, expect } from "vitest";
import { ChannelManager, MAX_CHANNELS, extractChannelFromErrorMessage } from "./channels";
import { ChannelStatus } from "./types";

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
    expect(ChannelManager.validateChannel("server:s01:console")).toBe(true);
    expect(ChannelManager.validateChannel("provision:s01")).toBe(true);
    expect(ChannelManager.validateChannel("backup:*")).toBe(true);
    expect(ChannelManager.validateChannel("")).toBe(false);
    expect(ChannelManager.validateChannel("invalid")).toBe(false);
    expect(ChannelManager.validateChannel("a:b:c")).toBe(false);
    expect(ChannelManager.validateChannel("server:s01:invalid")).toBe(false);
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

describe("ChannelManager per-channel state", () => {
  it("markRejected updates only the target channel, not others", () => {
    const cm = new ChannelManager();
    cm.add("server:s01");
    cm.add("backup:b01");
    cm.add("plugin:p01");

    cm.markRejected("server:s01", "Not authorized for channel: server:s01");

    const rejected = cm.getChannelState("server:s01");
    expect(rejected).toEqual({
      channel: "server:s01",
      status: ChannelStatus.REJECTED,
      authorized: false,
      error: "Not authorized for channel: server:s01",
      retryCount: 1,
    });

    const backup = cm.getChannelState("backup:b01");
    expect(backup).toEqual({
      channel: "backup:b01",
      status: ChannelStatus.SUBSCRIBED,
      authorized: true,
      retryCount: 0,
    });

    const plugin = cm.getChannelState("plugin:p01");
    expect(plugin).toEqual({
      channel: "plugin:p01",
      status: ChannelStatus.SUBSCRIBED,
      authorized: true,
      retryCount: 0,
    });
  });

  it("markRejected increments retryCount on repeat rejections", () => {
    const cm = new ChannelManager();
    cm.add("server:s01");
    cm.markRejected("server:s01", "Not authorized for channel: server:s01");
    cm.markRejected("server:s01", "Not authorized for channel: server:s01");
    expect(cm.getChannelState("server:s01")?.retryCount).toBe(2);
  });

  it("getChannelState returns undefined for an unknown channel", () => {
    const cm = new ChannelManager();
    expect(cm.getChannelState("never:seen")).toBeUndefined();
  });

  it("getAllChannelStates returns a complete, accurate snapshot", () => {
    const cm = new ChannelManager();
    cm.add("server:s01");
    cm.add("backup:b01");
    cm.markRejected("server:s01", "Not authorized for channel: server:s01");

    const snapshot = cm.getAllChannelStates();
    expect(Object.keys(snapshot).sort()).toEqual(["backup:b01", "server:s01"]);
    expect(snapshot["server:s01"].status).toBe(ChannelStatus.REJECTED);
    expect(snapshot["server:s01"].retryCount).toBe(1);
    expect(snapshot["backup:b01"].status).toBe(ChannelStatus.SUBSCRIBED);
    expect(snapshot["backup:b01"].authorized).toBe(true);
  });

  it("resetRetryCount zeroes retryCount without changing status/authorized", () => {
    const cm = new ChannelManager();
    cm.add("server:s01");
    cm.markRejected("server:s01", "Not authorized for channel: server:s01");
    cm.markRejected("server:s01", "Not authorized for channel: server:s01");

    cm.resetRetryCount("server:s01");

    const state = cm.getChannelState("server:s01");
    expect(state?.retryCount).toBe(0);
    expect(state?.status).toBe(ChannelStatus.REJECTED);
    expect(state?.authorized).toBe(false);
  });
});

describe("extractChannelFromErrorMessage", () => {
  it("extracts the channel from a well-formed backend message", () => {
    expect(
      extractChannelFromErrorMessage("Not authorized for channel: server:s01"),
    ).toBe("server:s01");
  });

  it("extracts a wildcard channel", () => {
    expect(
      extractChannelFromErrorMessage("Not authorized for channel: backup:*"),
    ).toBe("backup:*");
  });

  it("returns null for an empty string", () => {
    expect(extractChannelFromErrorMessage("")).toBeNull();
  });

  it("returns null for an unrelated error message", () => {
    expect(
      extractChannelFromErrorMessage("Maximum 50 channel subscriptions"),
    ).toBeNull();
  });

  it("returns null for malformed text resembling the pattern", () => {
    expect(
      extractChannelFromErrorMessage("Not authorized for channel:"),
    ).toBeNull();
  });
});
