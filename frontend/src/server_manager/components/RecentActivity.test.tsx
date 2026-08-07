import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { RecentActivity } from "./RecentActivity";
import { useActivityStore } from "@/stores/activityStore";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState } from "@/websocket/types";

function seedEvent(event_type: string, name = "Server A", minutesAgo = 0) {
  useActivityStore.getState().addEvent({
    event_type,
    server_id: "srv-1",
    name,
    timestamp: (Date.now() - minutesAgo * 60_000) / 1000,
  });
}

describe("RecentActivity", () => {
  beforeEach(() => {
    useActivityStore.getState().clear();
    useWSStore.setState({ connectionState: ConnectionState.CONNECTED, connected: true });
  });

  it("renders nothing when there are no events", () => {
    render(<RecentActivity />);
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("renders started events with the server name", () => {
    seedEvent("ServerStartedEvent");
    render(<RecentActivity />);
    expect(screen.getByText("Server A")).toBeInTheDocument();
    expect(screen.getByText("started")).toBeInTheDocument();
  });

  it("renders crashed events", () => {
    seedEvent("ServerCrashedEvent", "Broken");
    render(<RecentActivity />);
    expect(screen.getByText("Broken")).toBeInTheDocument();
    expect(screen.getByText("crashed")).toBeInTheDocument();
  });

  it("renders created events", () => {
    seedEvent("ServerCreatedEvent", "New One");
    render(<RecentActivity />);
    expect(screen.getByText("New One")).toBeInTheDocument();
    expect(screen.getByText("created")).toBeInTheDocument();
  });

  it("shows relative timestamps", () => {
    seedEvent("ServerStartedEvent", "Old", 5);
    render(<RecentActivity />);
    expect(screen.getByText("5m ago")).toBeInTheDocument();
  });

  it("limits rendering to the 8 most recent events", () => {
    for (let i = 0; i < 10; i++) {
      seedEvent("ServerStartedEvent", `Server ${i}`, i);
    }
    render(<RecentActivity />);
    expect(screen.getAllByRole("listitem")).toHaveLength(8);
  });

  it.each([
    [ConnectionState.CONNECTED, false],
    [ConnectionState.CONNECTING, true],
    [ConnectionState.RECONNECTING, true],
    [ConnectionState.DISCONNECTED, true],
  ] as const)("connectionState=%s renders the live-updates note only when not connected", (state, expectNote) => {
    useWSStore.setState({ connectionState: state, connected: state === ConnectionState.CONNECTED });
    seedEvent("ServerStartedEvent");
    render(<RecentActivity />);
    if (expectNote) {
      expect(screen.getByRole("status")).toBeInTheDocument();
    } else {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    }
    expect(screen.getByText("Server A")).toBeInTheDocument();
  });

  it("shows reconnecting note text", () => {
    useWSStore.setState({ connectionState: ConnectionState.RECONNECTING, connected: false });
    render(<RecentActivity />);
    expect(screen.getByText("Live updates paused — reconnecting…")).toBeInTheDocument();
  });

  it("shows unavailable note when disconnected", () => {
    useWSStore.setState({ connectionState: ConnectionState.DISCONNECTED, connected: false });
    render(<RecentActivity />);
    expect(screen.getByText("Live updates unavailable")).toBeInTheDocument();
  });
});
