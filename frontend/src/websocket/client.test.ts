import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WSClient } from "./client";
import { ConnectionState, ChannelStatus } from "./types";

function createMockWebSocket() {
  const handlers: Record<string, ((...args: unknown[]) => void) | null> = {};
  let currentReadyState: number = WebSocket.CONNECTING;
  const ws = {
    get readyState() { return currentReadyState; },
    set readyState(v: number) { currentReadyState = v; },
    send: vi.fn(),
    close: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
    set onopen(fn: ((...args: unknown[]) => void) | null) { handlers.open = fn; },
    set onclose(fn: ((...args: unknown[]) => void) | null) { handlers.close = fn; },
    set onmessage(fn: ((...args: unknown[]) => void) | null) { handlers.message = fn; },
    set onerror(fn: ((...args: unknown[]) => void) | null) { handlers.error = fn; },
    trigger(event: string, ...args: unknown[]) {
      if (event === "open") currentReadyState = WebSocket.OPEN;
      if (event === "close") currentReadyState = WebSocket.CLOSED;
      const handler = handlers[event];
      if (handler) {
        if (event === "message") {
          handler({ data: (args[0] as any)?.data ?? args[0] });
        } else {
          handler();
        }
      }
    },
  };
  return ws;
}

let mockWs: ReturnType<typeof createMockWebSocket>;

describe("WSClient", () => {
  beforeEach(() => {
    mockWs = createMockWebSocket();
    vi.stubGlobal("WebSocket", vi.fn(() => mockWs));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts disconnected", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    expect(client.state).toBe(ConnectionState.DISCONNECTED);
  });

  it("connects and sets state to connected", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    const stateSpy = vi.fn();
    client.setHandlers({ onStateChange: stateSpy });

    client.connect();
    expect(client.state).toBe(ConnectionState.CONNECTING);

    mockWs.trigger("open");
    expect(client.state).toBe(ConnectionState.CONNECTED);
    expect(stateSpy).toHaveBeenCalledWith(ConnectionState.CONNECTED);
  });

  it("disconnects cleanly", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    client.connect();
    mockWs.trigger("open");
    client.disconnect();
    expect(client.state).toBe(ConnectionState.DISCONNECTED);
    expect(mockWs.close).toHaveBeenCalledWith(1000, "Client disconnect");
  });

  it("sends messages when connected", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    client.connect();
    mockWs.trigger("open");
    client.send({ type: "ping" });
    expect(mockWs.send).toHaveBeenCalledWith(JSON.stringify({ type: "ping" }));
  });

  it("queues messages when disconnected", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    client.send({ type: "ping" });
    expect(mockWs.send).not.toHaveBeenCalled();
    client.connect();
    mockWs.trigger("open");
    expect(mockWs.send).toHaveBeenCalledWith(JSON.stringify({ type: "ping" }));
  });

  it("subscribes to channels", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01", "backup:*"]);
    expect(client.channels.has("server:s01")).toBe(true);
    expect(mockWs.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "subscribe", channels: ["server:s01", "backup:*"] }),
    );
  });

  it("unsubscribes from channels", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01"]);
    client.unsubscribe(["server:s01"]);
    expect(client.channels.has("server:s01")).toBe(false);
  });

  it("handles incoming messages", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    const msgSpy = vi.fn();
    client.setHandlers({ onMessage: msgSpy });
    client.connect();
    mockWs.trigger("open");

    const message = JSON.stringify({ type: "pong" });
    mockWs.trigger("message", { data: message });
    expect(msgSpy).toHaveBeenCalledWith({ type: "pong" });
  });

  it("disconnects on auth_expired", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    const stateSpy = vi.fn();
    client.setHandlers({ onStateChange: stateSpy });
    client.connect();
    mockWs.trigger("open");

    const message = JSON.stringify({ type: "auth_expired" });
    mockWs.trigger("message", { data: message });
    expect(client.state).toBe(ConnectionState.DISCONNECTED);
  });

  it("can refresh token", () => {
    const client = new WSClient({ url: "ws://test", token: "old-token" });
    client.connect();
    mockWs.trigger("open");
    client.refreshToken("new-token", "user1");
    expect(mockWs.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "refresh_token", token: "new-token", sub: "user1" }),
    );
  });

  it("does not reconnect when destroyed", () => {
    vi.useFakeTimers();
    const client = new WSClient({
      url: "ws://test",
      token: "test-token",
      autoReconnect: true,
      baseDelay: 100,
      maxRetries: 3,
    });
    client.connect();
    mockWs.trigger("open");
    client.disconnect();
    vi.advanceTimersByTime(1000);
    expect(WebSocket).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("marks a channel rejected on PERMISSION_DENIED and does not change connection state", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    const stateSpy = vi.fn();
    client.setHandlers({ onStateChange: stateSpy });
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01"]);

    mockWs.trigger("message", {
      data: JSON.stringify({
        type: "error",
        code: "PERMISSION_DENIED",
        message: "Not authorized for channel: server:s01",
      }),
    });

    const state = client.channels.getChannelState("server:s01");
    expect(state?.status).toBe(ChannelStatus.REJECTED);
    expect(state?.authorized).toBe(false);
    expect(state?.error).toBe("Not authorized for channel: server:s01");
    expect(client.state).toBe(ConnectionState.CONNECTED);
    expect(stateSpy).not.toHaveBeenCalledWith(ConnectionState.RECONNECTING);
    expect(stateSpy).not.toHaveBeenCalledWith(ConnectionState.DISCONNECTED);
  });

  it("triggers the unattributed-rejection callback on unparseable PERMISSION_DENIED", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    const unattributedSpy = vi.fn();
    client.setUnattributedRejectionHandler(unattributedSpy);
    client.connect();
    mockWs.trigger("open");

    mockWs.trigger("message", {
      data: JSON.stringify({ type: "error", code: "PERMISSION_DENIED", message: "random text" }),
    });

    expect(unattributedSpy).toHaveBeenCalledTimes(1);
    expect(client.state).toBe(ConnectionState.CONNECTED);
  });

  it("resubscribes a rejected channel with bounded exponential backoff, then settles", () => {
    vi.useFakeTimers();
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01"]);
    mockWs.send.mockClear();

    const reject = () =>
      mockWs.trigger("message", {
        data: JSON.stringify({
          type: "error",
          code: "PERMISSION_DENIED",
          message: "Not authorized for channel: server:s01",
        }),
      });

    // Rejection 1 → schedules retry at 2000ms.
    reject();
    expect(client.channels.getChannelState("server:s01")?.retryCount).toBe(1);

    // Retry 1 fires at ~2000ms.
    vi.advanceTimersByTime(1999);
    expect(mockWs.send).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(mockWs.send).toHaveBeenCalledTimes(1);
    expect(mockWs.send).toHaveBeenCalledWith(JSON.stringify({ type: "subscribe", channels: ["server:s01"] }));

    // Retry 1 rejected → schedules retry 2 at 4000ms.
    reject();
    expect(client.channels.getChannelState("server:s01")?.retryCount).toBe(2);
    mockWs.send.mockClear();
    vi.advanceTimersByTime(3999);
    expect(mockWs.send).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(mockWs.send).toHaveBeenCalledTimes(1);

    // Retry 2 rejected → schedules retry 3 at 8000ms.
    reject();
    expect(client.channels.getChannelState("server:s01")?.retryCount).toBe(3);
    mockWs.send.mockClear();
    vi.advanceTimersByTime(7999);
    expect(mockWs.send).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(mockWs.send).toHaveBeenCalledTimes(1);

    // Retry 3 rejected → retryCount exceeds max, no further retry scheduled.
    reject();
    expect(client.channels.getChannelState("server:s01")?.retryCount).toBe(4);
    mockWs.send.mockClear();
    vi.advanceTimersByTime(10000);
    expect(mockWs.send).not.toHaveBeenCalled();

    // Channel settles as REJECTED after exhaustion.
    expect(client.channels.getChannelState("server:s01")?.status).toBe(ChannelStatus.REJECTED);
    vi.useRealTimers();
  });

  it("keeps per-channel retry timers isolated", () => {
    vi.useFakeTimers();
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01", "server:s02"]);
    mockWs.send.mockClear();

    mockWs.trigger("message", {
      data: JSON.stringify({ type: "error", code: "PERMISSION_DENIED", message: "Not authorized for channel: server:s01" }),
    });

    // Only channel A is rejected; channel B stays SUBSCRIBED and untimed.
    expect(client.channels.getChannelState("server:s01")?.status).toBe(ChannelStatus.REJECTED);
    expect(client.channels.getChannelState("server:s02")?.status).toBe(ChannelStatus.SUBSCRIBED);

    // Advance past retry 1 for A — B must never be resubscribed.
    vi.advanceTimersByTime(2000);
    expect(mockWs.send).toHaveBeenCalledTimes(1);
    expect(mockWs.send).toHaveBeenCalledWith(JSON.stringify({ type: "subscribe", channels: ["server:s01"] }));
    vi.useRealTimers();
  });

  it("clears pending resubscribe timers on disconnect", () => {
    vi.useFakeTimers();
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01"]);
    mockWs.send.mockClear();

    mockWs.trigger("message", {
      data: JSON.stringify({ type: "error", code: "PERMISSION_DENIED", message: "Not authorized for channel: server:s01" }),
    });

    client.disconnect();
    vi.advanceTimersByTime(10000);
    expect(mockWs.send).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("resets rejected channels on token refresh and resubscribes them", () => {
    vi.useFakeTimers();
    const client = new WSClient({ url: "ws://test", token: "old-token" });
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01"]);
    mockWs.trigger("message", {
      data: JSON.stringify({ type: "error", code: "PERMISSION_DENIED", message: "Not authorized for channel: server:s01" }),
    });
    mockWs.send.mockClear();

    client.refreshToken("new-token", "user1");

    const state = client.channels.getChannelState("server:s01");
    expect(state?.retryCount).toBe(0);
    expect(mockWs.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "refresh_token", token: "new-token", sub: "user1" }),
    );
    expect(mockWs.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "subscribe", channels: ["server:s01"] }),
    );
    vi.useRealTimers();
  });

  it("emits SUBSCRIBED channel state on subscribe", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    const channelSpy = vi.fn();
    client.setChannelStateChangeHandler(channelSpy);
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01"]);
    expect(channelSpy).toHaveBeenCalledWith(
      "server:s01",
      expect.objectContaining({ channel: "server:s01", status: ChannelStatus.SUBSCRIBED }),
    );
  });

  it("emits REJECTED channel state on PERMISSION_DENIED", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    const channelSpy = vi.fn();
    client.setChannelStateChangeHandler(channelSpy);
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01"]);
    channelSpy.mockClear();

    mockWs.trigger("message", {
      data: JSON.stringify({ type: "error", code: "PERMISSION_DENIED", message: "Not authorized for channel: server:s01" }),
    });

    expect(channelSpy).toHaveBeenCalledWith(
      "server:s01",
      expect.objectContaining({ channel: "server:s01", status: ChannelStatus.REJECTED }),
    );
  });

  it("emits null channel state on unsubscribe", () => {
    const client = new WSClient({ url: "ws://test", token: "test-token" });
    const channelSpy = vi.fn();
    client.setChannelStateChangeHandler(channelSpy);
    client.connect();
    mockWs.trigger("open");
    client.subscribe(["server:s01"]);
    client.unsubscribe(["server:s01"]);
    expect(channelSpy).toHaveBeenCalledWith("server:s01", null);
  });
});
