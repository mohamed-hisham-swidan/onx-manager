import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardFleetPanel } from "./DashboardFleetPanel";
import type { ServerResponse } from "@/server_manager/types";
import type { HostResourceBudget } from "@/types";

const servers: ServerResponse[] = [
  {
    server_id: "s1",
    name: "Lobby",
    server_type: "velocity",
    minecraft_version: "3.4.0",
    status: "stopped",
    group_id: "default",
    port: 25577,
    motd: "",
    max_players: 100,
    gamemode: "adventure",
    difficulty: "peaceful",
    max_memory_mb: 4096,
    mode: "simple",
    created_at: "",
    updated_at: "",
  },
  {
    server_id: "s2",
    name: "Survival",
    server_type: "paper",
    minecraft_version: "1.21.4",
    status: "stopped",
    group_id: "default",
    port: 25565,
    public_address: "play.example.net:25565",
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    max_memory_mb: 6144,
    mode: "advanced",
    active_branch: "release-2",
    created_at: "",
    updated_at: "",
  },
];

const tightBudget: HostResourceBudget = {
  total_ram_mb: 16384,
  os_reserve_ram_mb: 4096,
  allocatable_ram_mb: 12288,
  allocated_ram_mb: 6144,
  available_ram_mb: 6144,
  total_cpus: 8,
  reserved_cpus: 2,
  allocatable_cpus: 6,
  allocated_cpus: 0,
  available_cpus: 6,
  profile: "local",
  ram_reserve_override_mb: 0,
  cpu_reserve_override: 0,
  allocations: [],
};

describe("DashboardFleetPanel", () => {
  it("displays public join address with globe icon, branch chip, and RAM budget warning on Start All", () => {
    const onStartAll = vi.fn();
    const onCopyAddress = vi.fn();

    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <DashboardFleetPanel
            servers={servers}
            metricsByServerId={{}}
            hostBudget={tightBudget}
            busyServerIds={new Set()}
            startCooldowns={{}}
            nowMs={Date.now()}
            copiedAddressId={null}
            canPower={() => true}
            onStart={vi.fn()}
            onStartAll={onStartAll}
            onStop={vi.fn()}
            onRestart={vi.fn()}
            onRetryProvisioning={vi.fn()}
            onCopyAddress={onCopyAddress}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText("release-2")).toBeInTheDocument();
    const pubCopy = screen.getByRole("button", { name: "Copy join address play.example.net:25565" });
    fireEvent.click(pubCopy);
    expect(onCopyAddress).toHaveBeenCalledWith("play.example.net:25565", "s2", expect.any(Object));

    fireEvent.click(screen.getByRole("button", { name: "Start All" }));
    expect(screen.getByText(/exceeds 6 GB currently free host memory/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start All Servers" }));
    expect(onStartAll).toHaveBeenCalledWith(servers);
  });
});
