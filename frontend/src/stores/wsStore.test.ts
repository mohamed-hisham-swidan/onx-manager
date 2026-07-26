import { describe, it, expect, beforeEach } from "vitest";
import { ConnectionState } from "@/websocket/types";
import { useWSStore } from "./wsStore";

describe("wsStore", () => {
  beforeEach(() => {
    useWSStore.setState({ connectionState: ConnectionState.DISCONNECTED, connected: false });
  });

  it("starts disconnected", () => {
    const state = useWSStore.getState();
    expect(state.connectionState).toBe(ConnectionState.DISCONNECTED);
    expect(state.connected).toBe(false);
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
});
