import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WSClient } from "./client";
import { ConnectionState } from "./types";

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
});
