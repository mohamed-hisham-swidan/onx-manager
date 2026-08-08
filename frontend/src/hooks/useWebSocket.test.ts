import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "./useWebSocket";
import { useAuthStore } from "@/stores/authStore";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState, ChannelStatus } from "@/websocket/types";
import type { ChannelState } from "@/websocket/types";

const { WSClientMock, WSHandlerMock } = vi.hoisted(() => ({
  WSClientMock: vi.fn(),
  WSHandlerMock: vi.fn(),
}));

vi.mock("@/websocket/client", () => ({ WSClient: WSClientMock }));
vi.mock("@/websocket/handler", () => ({ WSHandler: WSHandlerMock }));

function rejectedState(channel: string): ChannelState {
  return {
    channel,
    status: ChannelStatus.REJECTED,
    authorized: false,
    error: `Not authorized for channel: ${channel}`,
    retryCount: 1,
  };
}

describe("useWebSocket store wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ isAuthenticated: true, accessToken: "tok", refreshToken: "rtok" });
    useWSStore.setState({
      connectionState: ConnectionState.DISCONNECTED,
      connected: false,
      channelStates: {},
      unattributedRejection: false,
    });

    WSClientMock.mockImplementation(() => ({
      connect: vi.fn(),
      disconnect: vi.fn(),
      subscribe: vi.fn(),
      unsubscribe: vi.fn(),
      send: vi.fn(),
      setHandlers: vi.fn(),
      setUnattributedRejectionHandler: vi.fn(),
      setChannelStateChangeHandler: vi.fn(),
    }));

    WSHandlerMock.mockImplementation(() => ({
      attach: vi.fn(),
      clearReconnectBuffer: vi.fn(),
      get reconnectBuffer() {
        return [];
      },
    }));
  });

  it("registers onStateChange and onChannelStateChange handlers with WSClient", () => {
    renderHook(() => useWebSocket({ url: "ws://test", autoConnect: true }));
    expect(WSClientMock).toHaveBeenCalledTimes(1);
    const handlers = WSClientMock.mock.calls[0][1];
    expect(typeof handlers.onStateChange).toBe("function");
    expect(typeof handlers.onChannelStateChange).toBe("function");
  });

  it("forwards channel state changes into the store", () => {
    renderHook(() => useWebSocket({ url: "ws://test", autoConnect: true }));
    const handlers = WSClientMock.mock.calls[0][1];

    act(() => handlers.onChannelStateChange("server:s01", rejectedState("server:s01")));
    expect(useWSStore.getState().channelStates["server:s01"]?.status).toBe(ChannelStatus.REJECTED);

    act(() => handlers.onChannelStateChange("server:s01", null));
    expect(useWSStore.getState().channelStates["server:s01"]).toBeUndefined();
  });

  it("wires the unattributed-rejection handler to set the store flag", () => {
    renderHook(() => useWebSocket({ url: "ws://test", autoConnect: true }));
    const client = WSClientMock.mock.results[0].value;
    const unattributedHandler = client.setUnattributedRejectionHandler.mock.calls[0][0];

    act(() => unattributedHandler());
    expect(useWSStore.getState().unattributedRejection).toBe(true);
  });

  it("forwards transport state and clears the unattributed flag on CONNECTED", () => {
    renderHook(() => useWebSocket({ url: "ws://test", autoConnect: true }));
    const handlers = WSClientMock.mock.calls[0][1];

    act(() => useWSStore.getState().setUnattributedRejection(true));
    act(() => handlers.onStateChange(ConnectionState.CONNECTED));
    expect(useWSStore.getState().connectionState).toBe(ConnectionState.CONNECTED);
    expect(useWSStore.getState().unattributedRejection).toBe(false);

    act(() => handlers.onStateChange(ConnectionState.RECONNECTING));
    expect(useWSStore.getState().connectionState).toBe(ConnectionState.RECONNECTING);
  });

  it("resets channel states and the unattributed flag on teardown", () => {
    const { unmount } = renderHook(() => useWebSocket({ url: "ws://test", autoConnect: true }));
    const handlers = WSClientMock.mock.calls[0][1];

    act(() => handlers.onChannelStateChange("server:s01", rejectedState("server:s01")));
    act(() => handlers.onStateChange(ConnectionState.CONNECTED));
    act(() => useWSStore.getState().setUnattributedRejection(true));

    act(() => unmount());
    expect(useWSStore.getState().channelStates).toEqual({});
    expect(useWSStore.getState().unattributedRejection).toBe(false);
    expect(WSClientMock.mock.results[0].value.disconnect).toHaveBeenCalled();
  });

  it("does not create a client when not authenticated", () => {
    useAuthStore.setState({ isAuthenticated: false, accessToken: null, refreshToken: null });
    renderHook(() => useWebSocket({ url: "ws://test", autoConnect: true }));
    expect(WSClientMock).not.toHaveBeenCalled();
  });
});
