import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HostResourceBudgetBar } from "./HostResourceBudgetBar";
import { ConfigStep } from "./wizard/ConfigStep";
import { INITIAL_DATA } from "./wizard/types";
import type { HostResourceBudget } from "@/types";

const sampleLocalBudget: HostResourceBudget = {
  total_ram_mb: 16384,
  os_reserve_ram_mb: 4096,
  allocatable_ram_mb: 12288,
  allocated_ram_mb: 4096,
  available_ram_mb: 8192,
  total_cpus: 8,
  reserved_cpus: 2,
  allocatable_cpus: 6,
  allocated_cpus: 2,
  available_cpus: 4,
  profile: "local",
  ram_reserve_override_mb: 0,
  cpu_reserve_override: 0,
  allocations: [
    {
      id: "srv-1",
      name: "Survival",
      kind: "server",
      status: "running",
      ram_mb: 4096,
      cpu_cores: 2,
    },
  ],
};

describe("HostResourceBudgetBar", () => {
  it("renders desktop safe reserve, allocated count, and free capacity in local profile", () => {
    render(<HostResourceBudgetBar budget={sampleLocalBudget} />);
    expect(screen.getByText("Desktop Safe Reserve")).toBeInTheDocument();
    expect(screen.getByText(/OS Reserve: 4 GB/i)).toBeInTheDocument();
    expect(screen.getByText(/Allocated: 4 GB \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Available: 8 GB \/ 12 GB max/i)).toBeInTheDocument();
  });

  it("shows ceiling alert when requested RAM exceeds allocatable host limit", () => {
    render(<HostResourceBudgetBar budget={sampleLocalBudget} requestedRamMb={16384} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/exceeds the 12 GB host allocatable ceiling/i);
  });

  it("shows busy-host status warning when requested RAM exceeds currently free memory", () => {
    render(<HostResourceBudgetBar budget={sampleLocalBudget} requestedRamMb={10240} />);
    expect(screen.getByRole("status")).toHaveTextContent(/exceeds currently unallocated RAM \(8 GB free\)/i);
  });

  it("ConfigStep renders budget bar, disables presets above ceiling, and blocks Next on over-limit", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const cappedBudget: HostResourceBudget = {
      ...sampleLocalBudget,
      total_ram_mb: 10240,
      os_reserve_ram_mb: 4096,
      allocatable_ram_mb: 6144,
      allocated_ram_mb: 0,
      available_ram_mb: 6144,
      allocations: [],
    };
    qc.setQueryData(["hostResources"], cappedBudget);

    render(
      <QueryClientProvider client={qc}>
        <ConfigStep
          data={{ ...INITIAL_DATA, name: "My Server", maxMemoryMb: 8192 }}
          onChange={() => {}}
          onNext={() => {}}
          onBack={() => {}}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByRole("region", { name: "Host Resource Budget" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "8 GB" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "16 GB" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "4 GB" })).not.toBeDisabled();
    const submitBtns = screen.getAllByRole("button");
    expect(submitBtns[submitBtns.length - 1]).toBeDisabled();
  });
});
