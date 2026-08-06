import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerMetricsCharts } from "./ServerMetricsCharts";
import type { MetricsSnapshot } from "@/services/api";

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
});