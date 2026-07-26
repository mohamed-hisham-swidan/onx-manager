import { describe, it, expect, beforeEach } from "vitest";
import { useWSStore } from "./wsStore";

describe("wsStore", () => {
  beforeEach(() => {
    useWSStore.setState({ connectionState: "disconnected", connected: false });
  });

  it("starts disconnected", () => {
    const state = useWSStore.getState();
    expect(state.connectionState).toBe("disconnected");
    expect(state.connected).toBe(false);
  });

  it("setConnectionState updates state", () => {
    useWSStore.getState().setConnectionState("connected");
    const state = useWSStore.getState();
    expect(state.connectionState).toBe("connected");
    expect(state.connected).toBe(true);
  });

  it("setConnectionState to connecting sets connected false", () => {
    useWSStore.getState().setConnectionState("connected");
    useWSStore.getState().setConnectionState("connecting");
    const state = useWSStore.getState();
    expect(state.connectionState).toBe("connecting");
    expect(state.connected).toBe(false);
  });

  it("setConnectionState to reconnecting sets connected false", () => {
    useWSStore.getState().setConnectionState("reconnecting");
    const state = useWSStore.getState();
    expect(state.connectionState).toBe("reconnecting");
    expect(state.connected).toBe(false);
  });
});
