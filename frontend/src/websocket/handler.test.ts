import { describe, it, expect, vi } from "vitest";
import { WSHandler } from "./handler";

describe("WSHandler", () => {
  it("handles state_sync messages", () => {
    const onStateSync = vi.fn();
    const onCacheUpdate = vi.fn();
    const handler = new WSHandler({ onStateSync, onCacheUpdate });

    handler["_route"]({
      type: "state_sync",
      events: [{ event_type: "ServerStarted", server_id: "s01" }],
    });

    expect(onStateSync).toHaveBeenCalledWith([{ event_type: "ServerStarted", server_id: "s01" }]);
    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "server:s01",
      data: null,
      action: "invalidate",
    });
  });

  it("handles state messages", () => {
    const onServerState = vi.fn();
    const onCacheUpdate = vi.fn();
    const handler = new WSHandler({ onServerState, onCacheUpdate });

    handler["_route"]({
      type: "state",
      server_id: "s01",
      status: { running: true },
    });

    expect(onServerState).toHaveBeenCalledWith("s01", { running: true });
    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "server:s01",
      data: null,
      action: "invalidate",
    });
  });

  it("handles metrics messages", () => {
    const onMetrics = vi.fn();
    const onCacheUpdate = vi.fn();
    const handler = new WSHandler({ onMetrics, onCacheUpdate });

    handler["_route"]({
      type: "metrics",
      server_id: "s01",
      tps: 20.0,
      players: 5,
      ram_mb: 2048,
    });

    expect(onMetrics).toHaveBeenCalledWith("s01", 20.0, 5, 2048);
    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "metrics:s01",
      data: { tps: 20.0, players: 5, ram_mb: 2048 },
      action: "set",
    });
  });

  it("handles metrics_batch messages", () => {
    const onMetricsBatch = vi.fn();
    const onCacheUpdate = vi.fn();
    const samples = [{ ts: 1000, tps: 19.5, players: 3, ram_mb: 2048, cpu: 45.0 }];
    const handler = new WSHandler({ onMetricsBatch, onCacheUpdate });

    handler["_route"]({
      type: "metrics_batch",
      server_id: "s01",
      samples,
    });

    expect(onMetricsBatch).toHaveBeenCalledWith("s01", samples);
    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "metrics_batch:s01",
      data: { samples },
      action: "merge",
    });
  });

  it("handles event messages", () => {
    const onEvent = vi.fn();
    const handler = new WSHandler({ onEvent });

    handler["_route"]({
      type: "event",
      event: { event_type: "BackupCompleted" },
    });

    expect(onEvent).toHaveBeenCalledWith({ event_type: "BackupCompleted" });
  });

  it("handles error messages", () => {
    const onError = vi.fn();
    const handler = new WSHandler({ onError });

    handler["_route"]({
      type: "error",
      code: "RATE_LIMITED",
      message: "Too many requests",
    });

    expect(onError).toHaveBeenCalledWith("RATE_LIMITED", "Too many requests");
  });

  it("ignores pong messages", () => {
    const handler = new WSHandler({});
    expect(() => handler["_route"]({ type: "pong" })).not.toThrow();
  });

  it("invalidates server list on create/delete events", () => {
    const onCacheUpdate = vi.fn();
    const handler = new WSHandler({ onCacheUpdate });

    handler["_route"]({
      type: "event",
      event: { event_type: "ServerCreated" },
    });

    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "servers:list",
      data: null,
      action: "invalidate",
    });
  });

  it("invalidates both server list and server detail on ServerStarting, ServerStopping, ServerCrashed, ServerRestarted, ServerConfigChanged, ServerDiscovered, and ServerVanished events", () => {
    const lifecycleEvents = [
      "ServerStarting",
      "ServerStarted",
      "ServerStopping",
      "ServerStopped",
      "ServerCrashed",
      "ServerRestarted",
      "ServerConfigChangedEvent",
      "ServerDiscoveredEvent",
      "ServerVanishedEvent",
    ];

    for (const eventType of lifecycleEvents) {
      const onCacheUpdate = vi.fn();
      const handler = new WSHandler({ onCacheUpdate });

      handler["_route"]({
        type: "event",
        event: { event_type: eventType, server_id: "s-test-42" },
      });

      expect(onCacheUpdate).toHaveBeenCalledWith({
        key: "servers:list",
        data: null,
        action: "invalidate",
      });
      expect(onCacheUpdate).toHaveBeenCalledWith({
        key: "server:s-test-42",
        data: null,
        action: "invalidate",
      });
    }
  });

  it("invalidates backups:list, servers:list, and server detail on BackupRestoredEvent", () => {
    const onCacheUpdate = vi.fn();
    const handler = new WSHandler({ onCacheUpdate });

    handler["_route"]({
      type: "event",
      event: { event_type: "BackupRestoredEvent", server_id: "s-restore-1" },
    });

    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "backups:list",
      data: null,
      action: "invalidate",
    });
    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "servers:list",
      data: null,
      action: "invalidate",
    });
    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "server:s-restore-1",
      data: null,
      action: "invalidate",
    });
  });

  it("invalidates backup list on backup events", () => {
    const onCacheUpdate = vi.fn();
    const handler = new WSHandler({ onCacheUpdate });

    handler["_route"]({
      type: "event",
      event: { event_type: "BackupCompleted" },
    });

    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "backups:list",
      data: null,
      action: "invalidate",
    });
  });

  it("invalidates plugin list on plugin events", () => {
    const onCacheUpdate = vi.fn();
    const handler = new WSHandler({ onCacheUpdate });

    handler["_route"]({
      type: "event",
      event: { event_type: "PluginInstalled" },
    });

    expect(onCacheUpdate).toHaveBeenCalledWith({
      key: "plugins:list",
      data: null,
      action: "invalidate",
    });
  });

  it("manages reconnect buffer", () => {
    const handler = new WSHandler();
    expect(handler.reconnectBuffer).toEqual([]);

    handler["_route"]({
      type: "state_sync",
      events: [{ event_type: "ServerStarted" }],
    });

    expect(handler.reconnectBuffer).toHaveLength(1);
    handler.clearReconnectBuffer();
    expect(handler.reconnectBuffer).toEqual([]);
  });

  it("handles console messages", () => {
    const onConsole = vi.fn();
    const handler = new WSHandler({ onConsole });

    handler["_route"]({
      type: "console",
      server_id: "s01",
      lines: ["[INFO] Starting minecraft server version 1.20.4", "[INFO] Loading properties"],
    });

    expect(onConsole).toHaveBeenCalledWith("s01", [
      "[INFO] Starting minecraft server version 1.20.4",
      "[INFO] Loading properties",
    ]);
  });
});

