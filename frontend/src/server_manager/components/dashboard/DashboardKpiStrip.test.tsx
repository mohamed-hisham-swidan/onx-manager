import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DashboardKpiStrip } from "./DashboardKpiStrip";
import type { HostTelemetryMetrics, ServerStatusCounts } from "@/server_manager/utils/telemetryAdapter";

const baseCounts: ServerStatusCounts = {
  onlineCount: 1,
  offlineCount: 1,
  crashedCount: 1,
  startingCount: 0,
  stoppingCount: 0,
  attentionCount: 1,
};

const baseTelemetry: HostTelemetryMetrics = {
  onlinePlayers: 4,
  maxPlayers: 20,
  tpsAvg: 19.6,
  cpuPercent: 41.2,
  cpuHistory: [20, 35, 41.2],
  liveRssMb: 2048,
  liveRssGb: 2.0,
  activeAllocatedMb: 4096,
  activeAllocatedGb: 4.0,
  allocatableRamMb: 12288,
  allocatableRamGb: 12.0,
  availableRamMb: 8192,
  availableRamGb: 8.0,
  liveRssOfAllocatedPct: 50,
  backupTotalBytes: 2 * 1024 * 1024 * 1024,
  backupCompletedCount: 3,
  backupFailedCount: 1,
  backupTotalCount: 4,
  lastBackupRelative: "2h ago",
  activeSchedulesCount: 2,
};

describe("DashboardKpiStrip", () => {
  it("renders honest CPU, consistent free RAM, real backup metrics, and semantic sparkline", () => {
    render(
      <MemoryRouter>
        <DashboardKpiStrip
          counts={baseCounts}
          totalServers={3}
          telemetry={baseTelemetry}
          healthDashboard={{
            total_servers: 3,
            healthy: 1,
            warning: 1,
            critical: 1,
            broken: 0,
            unknown: 0,
            pending: 0,
            servers: [],
          }}
        />
      </MemoryRouter>,
    );

    const fleet = screen.getByRole("region", { name: "Fleet and Players" });
    expect(within(fleet).getByText("1 / 3")).toBeInTheDocument();
    expect(within(fleet).getByText("4 / 20 players")).toBeInTheDocument();
    expect(within(fleet).getByText("2 health warn")).toBeInTheDocument();

    const compute = screen.getByRole("region", { name: "Compute and Tickrate" });
    expect(within(compute).getByText("41.2%")).toBeInTheDocument();
    expect(within(compute).getByText("19.6 TPS")).toBeInTheDocument();
    expect(within(compute).getByText("Server CPU (1 active)")).toBeInTheDocument();
    expect(within(compute).getByRole("img", { name: "Server CPU trend sparkline" })).toBeInTheDocument();

    const mem = screen.getByRole("region", { name: "Memory and Capacity" });
    expect(within(mem).getByText("2.0 GB")).toBeInTheDocument();
    expect(within(mem).getByText("/ 4.0 GB")).toBeInTheDocument();
    expect(within(mem).getByText("8 GB free")).toBeInTheDocument();

    const backups = screen.getByRole("region", { name: "Backups and Schedules" });
    expect(within(backups).getByText("2.0 GB")).toBeInTheDocument();
    expect(within(backups).getByText("3 saved")).toBeInTheDocument();
    expect(within(backups).getByText("2 scheduled")).toBeInTheDocument();
    expect(within(backups).getByText("Last: 2h ago")).toBeInTheDocument();
  });

  it("renders Collecting baseline instead of fabricated chart points when fewer than 2 samples exist", () => {
    render(
      <MemoryRouter>
        <DashboardKpiStrip
          counts={baseCounts}
          totalServers={3}
          telemetry={{ ...baseTelemetry, cpuHistory: [12.4] }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Collecting...")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Server CPU trend sparkline" })).not.toBeInTheDocument();
  });
});
