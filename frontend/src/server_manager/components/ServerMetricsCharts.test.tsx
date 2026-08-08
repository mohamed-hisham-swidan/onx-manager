import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerMetricsCharts } from "./ServerMetricsCharts";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState, ChannelStatus } from "@/websocket/types";
import type { ChannelState } from "@/websocket/types";
import type { MetricsSnapshot } from "@/services/api";

function rejectedChannelState(channel: string): ChannelState {
  return {
    channel,
    status: ChannelStatus.REJECTED,
    authorized: false,
    error: `Not authorized for channel: ${channel}`,
    retryCount: 3,
  };
}

const getMetricsMock = vi.fn();

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...actual,
    createAuthenticatedApi: () => ({ getMetrics: getMetricsMock }),
  };
});

const qc = new QueryClient();

function renderCharts() {
  return render(
    <QueryClientProvider client={qc}>
      <ServerMetricsCharts serverId="srv-1" />
    </QueryClientProvider>,
  );
}

function makePoint(timestamp: string, players: number, tps = 20.0): MetricsSnapshot {
  return { tps, players, ram_used_mb: 4.86, cpu_percent: 7.4, timestamp };
}

describe("ServerMetricsCharts", () => {
  beforeEach(() => {
    getMetricsMock.mockReset();
    getMetricsMock.mockResolvedValue([]);
    useWSStore.setState({
      connectionState: ConnectionState.CONNECTED,
      connected: true,
      channelStates: {},
      unattributedRejection: false,
    });
  });

  it("renders the newest metric snapshot as current, not the oldest", async () => {
    getMetricsMock.mockResolvedValue([
      makePoint("2026-08-06T10:18:00", 1),
      makePoint("2026-08-06T10:17:00", 0),
      makePoint("2026-08-06T10:16:00", 0),
    ]);

    renderCharts();
    expect(await screen.findByText("1")).toBeInTheDocument();
  });

  it("shows fallback placeholder when there are no metrics yet", async () => {
    getMetricsMock.mockResolvedValue([]);

    renderCharts();
    const placeholders = await screen.findAllByText("—");
    expect(placeholders).toHaveLength(4);
  });

  it.each([
    [ConnectionState.CONNECTED, false],
    [ConnectionState.CONNECTING, true],
    [ConnectionState.RECONNECTING, true],
    [ConnectionState.DISCONNECTED, true],
  ] as const)("connectionState=%s shows the not-live note only when not connected", async (state, expectNote) => {
    useWSStore.setState({ connectionState: state, connected: state === ConnectionState.CONNECTED });
    useWSStore.setState({ connectionState: state, connected: state === "connected" });
    renderCharts();
    if (expectNote) {
      expect(await screen.findByRole("status")).toBeInTheDocument();
    } else {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    }
  });

  it("shows the subscription-rejected note when transport is connected but this server's metrics channel is rejected (K1)", async () => {
    useWSStore.setState({
      connectionState: ConnectionState.CONNECTED,
      connected: true,
      channelStates: { "metrics:srv-1": rejectedChannelState("metrics:srv-1") },
    });
    renderCharts();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Metrics not live — subscription rejected",
    );
  });

  it("does not show the note when another server's metrics channel is rejected", async () => {
    useWSStore.setState({
      connectionState: ConnectionState.CONNECTED,
      connected: true,
      channelStates: { "metrics:other": rejectedChannelState("metrics:other") },
    });
    renderCharts();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(await screen.findAllByText("—")).toHaveLength(4);
  });
});