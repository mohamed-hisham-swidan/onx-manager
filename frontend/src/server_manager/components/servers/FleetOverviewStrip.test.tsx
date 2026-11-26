import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { FleetOverviewStrip } from "./FleetOverviewStrip";
import type { HostResourceBudget } from "@/types";

function makeBudget(overrides: Partial<HostResourceBudget> = {}): HostResourceBudget {
  return {
    total_ram_mb: 16384,
    os_reserve_ram_mb: 4096,
    allocatable_ram_mb: 12288,
    allocated_ram_mb: 4096,
    available_ram_mb: 8192,
    total_cpus: 8,
    reserved_cpus: 2,
    allocatable_cpus: 6,
    allocated_cpus: 0,
    available_cpus: 6,
    profile: "local",
    ram_reserve_override_mb: 0,
    cpu_reserve_override: 0,
    allocations: [],
    ...overrides,
  };
}

describe("FleetOverviewStrip", () => {
  it("renders Shared instead of 0 / N cores when allocated_cpus is 0 and servers are running", () => {
    render(
      <FleetOverviewStrip
        totalServers={1}
        runningCount={1}
        totalOnlinePlayers={2}
        totalOnlineCapacity={20}
        hostBudget={makeBudget({ allocated_cpus: 0, allocatable_cpus: 6 })}
        activeStatusFilter="all"
        onToggleRunningFilter={vi.fn()}
        fallbackAllocatedRamMb={4096}
      />,
    );

    const strip = screen.getByTestId("fleet-overview-strip");
    expect(strip).toHaveTextContent("Shared");
    expect(strip).toHaveTextContent("/ 6 cores");
    expect(strip).not.toHaveTextContent("0 / 6 cores");
  });

  it("renders numeric allocated_cpus / allocatable_cpus when servers have explicit CPU limits", () => {
    render(
      <FleetOverviewStrip
        totalServers={2}
        runningCount={1}
        totalOnlinePlayers={2}
        totalOnlineCapacity={40}
        hostBudget={makeBudget({ allocated_cpus: 2, allocatable_cpus: 6 })}
        activeStatusFilter="all"
        onToggleRunningFilter={vi.fn()}
        fallbackAllocatedRamMb={4096}
      />,
    );

    const strip = screen.getByTestId("fleet-overview-strip");
    expect(strip).toHaveTextContent("2");
    expect(strip).toHaveTextContent("/ 6 cores");
    expect(strip).not.toHaveTextContent("Shared");
  });

  it("renders 0 / N cores when allocated_cpus is 0 and no servers are running", () => {
    render(
      <FleetOverviewStrip
        totalServers={1}
        runningCount={0}
        totalOnlinePlayers={0}
        totalOnlineCapacity={20}
        hostBudget={makeBudget({ allocated_cpus: 0, allocatable_cpus: 6 })}
        activeStatusFilter="all"
        onToggleRunningFilter={vi.fn()}
        fallbackAllocatedRamMb={4096}
      />,
    );

    const strip = screen.getByTestId("fleet-overview-strip");
    expect(strip).toHaveTextContent("0");
    expect(strip).toHaveTextContent("/ 6 cores");
    expect(strip).not.toHaveTextContent("Shared");
  });
});
