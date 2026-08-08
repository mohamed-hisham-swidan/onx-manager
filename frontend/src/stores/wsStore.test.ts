import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { ConnectionState, ChannelStatus } from "@/websocket/types";
import type { ChannelState } from "@/websocket/types";
import {
  useWSStore,
  computeEffectiveConnectionState,
  useEffectiveConnectionState,
  useChannelStatus,
  useIsChannelDegraded,
} from "./wsStore";

function rejectedState(channel: string): ChannelState {
  return {
    channel,
    status: ChannelStatus.REJECTED,
    authorized: false,
    error: `Not authorized for channel: ${channel}`,
    retryCount: 3,
  };
}

function retryingState(channel: string): ChannelState {
  return { channel, status: ChannelStatus.RETRYING, authorized: true, retryCount: 1 };
}

function subscribedState(channel: string): ChannelState {
  return { channel, status: ChannelStatus.SUBSCRIBED, authorized: true, retryCount: 0 };
}

describe("wsStore", () => {
  beforeEach(() => {
    useWSStore.setState({
      connectionState: ConnectionState.DISCONNECTED,
      connected: false,
      channelStates: {},
      unattributedRejection: false,
    });
  });

  it("starts disconnected", () => {
    const state = useWSStore.getState();
    expect(state.connectionState).toBe(ConnectionState.DISCONNECTED);
    expect(state.connected).toBe(false);
    expect(state.channelStates).toEqual({});
    expect(state.unattributedRejection).toBe(false);
  });

  it("setConnectionState updates state", () => {
    useWSStore.getState().setConnectionState(ConnectionState.CONNECTED);
    const state = useWSStore.getState();
    expect(state.connectionState).toBe(ConnectionState.CONNECTED);
    expect(state.connected).toBe(true);
  });

  it("setConnectionState to connecting sets connected false", () => {
    useWSStore.getState().setConnectionState(ConnectionState.CONNECTED);
    useWSStore.getState().setConnectionState(ConnectionState.CONNECTING);
    const state = useWSStore.getState();
    expect(state.connectionState).toBe(ConnectionState.CONNECTING);
    expect(state.connected).toBe(false);
  });

  it("setConnectionState to reconnecting sets connected false", () => {
    useWSStore.getState().setConnectionState(ConnectionState.RECONNECTING);
    const state = useWSStore.getState();
    expect(state.connectionState).toBe(ConnectionState.RECONNECTING);
    expect(state.connected).toBe(false);
  });

  it("setChannelState adds and updates an entry", () => {
    useWSStore.getState().setChannelState("server:s01", subscribedState("server:s01"));
    expect(useWSStore.getState().channelStates["server:s01"]).toEqual(subscribedState("server:s01"));

    useWSStore.getState().setChannelState("server:s01", rejectedState("server:s01"));
    expect(useWSStore.getState().channelStates["server:s01"]).toEqual(rejectedState("server:s01"));
  });

  it("removeChannelState removes an entry and is a no-op when absent", () => {
    useWSStore.getState().setChannelState("server:s01", subscribedState("server:s01"));
    useWSStore.getState().removeChannelState("server:s01");
    expect(useWSStore.getState().channelStates).toEqual({});

    useWSStore.getState().removeChannelState("server:s01");
    expect(useWSStore.getState().channelStates).toEqual({});
  });

  it("setUnattributedRejection toggles the flag", () => {
    useWSStore.getState().setUnattributedRejection(true);
    expect(useWSStore.getState().unattributedRejection).toBe(true);
    useWSStore.getState().setUnattributedRejection(false);
    expect(useWSStore.getState().unattributedRejection).toBe(false);
  });

  describe("computeEffectiveConnectionState", () => {
    it("returns CONNECTED when transport connected and no channels unhealthy", () => {
      expect(
        computeEffectiveConnectionState(
          ConnectionState.CONNECTED,
          { "server:s01": subscribedState("server:s01") },
          false,
        ),
      ).toBe(ConnectionState.CONNECTED);
    });

    it("returns CONNECTED when transport connected and no channel states", () => {
      expect(computeEffectiveConnectionState(ConnectionState.CONNECTED, {}, false)).toBe(ConnectionState.CONNECTED);
    });

    it("returns DEGRADED when one channel is REJECTED", () => {
      expect(
        computeEffectiveConnectionState(ConnectionState.CONNECTED, { "server:s01": rejectedState("server:s01") }, false),
      ).toBe(ConnectionState.DEGRADED);
    });

    it("returns DEGRADED when one channel is RETRYING", () => {
      expect(
        computeEffectiveConnectionState(ConnectionState.CONNECTED, { "server:s01": retryingState("server:s01") }, false),
      ).toBe(ConnectionState.DEGRADED);
    });

    it("returns DEGRADED when unattributed rejection flag is set", () => {
      expect(
        computeEffectiveConnectionState(ConnectionState.CONNECTED, { "server:s01": subscribedState("server:s01") }, true),
      ).toBe(ConnectionState.DEGRADED);
    });

    it("returns CONNECTED again once the only unhealthy channel is removed", () => {
      const channelStates = { "server:s01": rejectedState("server:s01") };
      expect(computeEffectiveConnectionState(ConnectionState.CONNECTED, channelStates, false)).toBe(
        ConnectionState.DEGRADED,
      );
      expect(computeEffectiveConnectionState(ConnectionState.CONNECTED, {}, false)).toBe(ConnectionState.CONNECTED);
    });

    it("transport states take precedence over channel health", () => {
      const channelStates = { "server:s01": rejectedState("server:s01") };
      expect(computeEffectiveConnectionState(ConnectionState.DISCONNECTED, channelStates, false)).toBe(
        ConnectionState.DISCONNECTED,
      );
      expect(computeEffectiveConnectionState(ConnectionState.RECONNECTING, channelStates, false)).toBe(
        ConnectionState.RECONNECTING,
      );
      expect(computeEffectiveConnectionState(ConnectionState.CONNECTING, channelStates, true)).toBe(
        ConnectionState.CONNECTING,
      );
    });
  });

  describe("useEffectiveConnectionState", () => {
    it("returns CONNECTED when no channels are unhealthy", () => {
      useWSStore.setState({ connectionState: ConnectionState.CONNECTED });
      const { result } = renderHook(() => useEffectiveConnectionState());
      expect(result.current).toBe(ConnectionState.CONNECTED);
    });

    it("returns DEGRADED when a channel is rejected", () => {
      useWSStore.setState({ connectionState: ConnectionState.CONNECTED });
      const { result } = renderHook(() => useEffectiveConnectionState());
      act(() => useWSStore.getState().setChannelState("server:s01", rejectedState("server:s01")));
      expect(result.current).toBe(ConnectionState.DEGRADED);
    });

    it("returns RECONNECTING when transport is reconnecting even with a rejected channel", () => {
      useWSStore.setState({ connectionState: ConnectionState.CONNECTED });
      const { result } = renderHook(() => useEffectiveConnectionState());
      act(() => {
        useWSStore.getState().setChannelState("server:s01", rejectedState("server:s01"));
        useWSStore.getState().setConnectionState(ConnectionState.RECONNECTING);
      });
      expect(result.current).toBe(ConnectionState.RECONNECTING);
    });

    it("returns DEGRADED when unattributed rejection flag is set, then CONNECTED when cleared", () => {
      useWSStore.setState({ connectionState: ConnectionState.CONNECTED });
      const { result } = renderHook(() => useEffectiveConnectionState());
      act(() => useWSStore.getState().setUnattributedRejection(true));
      expect(result.current).toBe(ConnectionState.DEGRADED);
      act(() => useWSStore.getState().setUnattributedRejection(false));
      expect(result.current).toBe(ConnectionState.CONNECTED);
    });
  });

  describe("useChannelStatus", () => {
    it("returns the stored status for a known channel", () => {
      useWSStore.setState({
        connectionState: ConnectionState.CONNECTED,
        channelStates: { "server:s01": rejectedState("server:s01") },
      });
      const { result } = renderHook(() => useChannelStatus("server:s01"));
      expect(result.current).toBe(ChannelStatus.REJECTED);
    });

    it("returns undefined for an unknown channel", () => {
      useWSStore.setState({ connectionState: ConnectionState.CONNECTED });
      const { result } = renderHook(() => useChannelStatus("server:s01"));
      expect(result.current).toBeUndefined();
    });
  });

  describe("useIsChannelDegraded", () => {
    beforeEach(() => {
      useWSStore.setState({
        connectionState: ConnectionState.CONNECTED,
        channelStates: {
          "server:s01": rejectedState("server:s01"),
          "server:s02": subscribedState("server:s02"),
        },
      });
    });

    it("matches by exact channel name", () => {
      const { result } = renderHook(() => useIsChannelDegraded("server:s01"));
      expect(result.current).toBe(true);
    });

    it("does not match a healthy channel by exact name", () => {
      const { result } = renderHook(() => useIsChannelDegraded("server:s02"));
      expect(result.current).toBe(false);
    });

    it("matches any unhealthy channel by segment prefix", () => {
      const { result } = renderHook(() => useIsChannelDegraded("server:"));
      expect(result.current).toBe(true);
    });

    it("matches any unhealthy channel by wildcard", () => {
      const { result } = renderHook(() => useIsChannelDegraded("server:*"));
      expect(result.current).toBe(true);
    });

    it("returns false for an unrelated prefix", () => {
      const { result } = renderHook(() => useIsChannelDegraded("metrics:"));
      expect(result.current).toBe(false);
    });
  });
});
