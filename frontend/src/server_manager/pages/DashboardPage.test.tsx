import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "./DashboardPage";
import { useActivityStore } from "@/stores/activityStore";
import type { ServerResponse } from "@/server_manager/types";

const mockServers: ServerResponse[] = [
  {
    server_id: "srv-1",
    name: "Online Server",
    server_type: "vanilla",
    minecraft_version: "1.21.4",
    status: "running",
    group_id: "default",
    port: 25565,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "easy",
    created_at: "",
    updated_at: "",
  },
  {
    server_id: "srv-2",
    name: "Stopped Server",
    server_type: "paper",
    minecraft_version: "1.21",
    status: "stopped",
    group_id: "default",
    port: 25566,
    motd: "",
    max_players: 10,
    gamemode: "creative",
    difficulty: "peaceful",
    created_at: "",
    updated_at: "",
  },
  {
    server_id: "srv-3",
    name: "Crashed Server",
    server_type: "fabric",
    minecraft_version: "1.20.4",
    status: "crashed",
    group_id: "default",
    port: 25567,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    created_at: "",
    updated_at: "",
  },
];

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRetryProvisioningServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

import { useServersList } from "@/server_manager/hooks/useServers";

const qc = new QueryClient();

function renderPage() {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/servers/:serverId/console" element={<div data-testid="attached-console-route">Attached Console</div>} />
          <Route path="/servers/:serverId" element={<div data-testid="server-detail-route">Server Detail</div>} />
          <Route path="/servers" element={<div data-testid="servers-page-route">Servers Page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DashboardPage Command Center", () => {
  beforeEach(() => {
    vi.mocked(useServersList).mockReturnValue({
      data: mockServers,
      isLoading: false,
    } as unknown as ReturnType<typeof useServersList>);
    useActivityStore.getState().clear();
  });

  it("renders page header, breadcrumbs, and Command Center title", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText("Command Center")).toBeInTheDocument();
    expect(screen.getByText("ONX Manager")).toBeInTheDocument();
    expect(
      screen.getByText("Real-time node telemetry & server orchestration"),
    ).toBeInTheDocument();
  });

  it("renders honest system status pill based on server states", () => {
    // With 1 crashed server in mockServers -> DEGRADED
    renderPage();
    expect(screen.getByText(/DEGRADED \(1 CRASHED\)/i)).toBeInTheDocument();

    // With only running & stopped servers -> NODE ACTIVE
    vi.mocked(useServersList).mockReturnValue({
      data: [mockServers[0], mockServers[1]],
      isLoading: false,
    } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByText(/NODE ACTIVE \(1\/2 ONLINE\)/i)).toBeInTheDocument();

    // With all servers stopped -> DAEMON STANDBY
    vi.mocked(useServersList).mockReturnValue({
      data: [mockServers[1]],
      isLoading: false,
    } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByText(/DAEMON STANDBY \(ALL OFFLINE\)/i)).toBeInTheDocument();
  });

  it("renders quick actions: Import Server and Create Server", () => {
    renderPage();
    const importBtn = screen.getByRole("link", { name: /Import Server/i });
    expect(importBtn).toHaveAttribute("href", "/servers/import");

    const createBtn = screen.getByRole("link", { name: /Create Server/i });
    expect(createBtn).toHaveAttribute("href", "/servers/create");
  });

  it("ensures 'Create Server' button has no duplicate '+ ' and no 'Deploy Server' occurrences", () => {
    renderPage();
    const createBtn = screen.getByRole("link", { name: /Create Server/i });
    expect(createBtn).toBeInTheDocument();
    expect(createBtn.textContent?.replace(/\s+/g, " ").trim()).toBe("Create Server");
    expect(screen.queryByText(/Deploy Server/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\+\s*Create Server/i)).not.toBeInTheDocument();
  });

  it("navigates to the crashed server detail page when 1 server is crashed", () => {
    // mockServers has exactly 1 crashed server (srv-3, 'Crashed Server')
    renderPage();
    const badge = screen.getByRole("link", { name: /Open crashed server Crashed Server/i });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("href", "/servers/srv-3");

    fireEvent.click(badge);
    expect(screen.getByTestId("server-detail-route")).toBeInTheDocument();
  });

  it("navigates to servers page with status filter when more than 1 server is crashed", () => {
    const twoCrashedServers: ServerResponse[] = [
      mockServers[0],
      mockServers[2],
      {
        ...mockServers[1],
        server_id: "srv-4",
        name: "Second Crashed Server",
        status: "crashed",
      },
    ];
    vi.mocked(useServersList).mockReturnValue({
      data: twoCrashedServers,
      isLoading: false,
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    const badge = screen.getByRole("link", { name: /View 2 crashed servers/i });
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("href", "/servers?status=crashed");

    fireEvent.click(badge);
    expect(screen.getByTestId("servers-page-route")).toBeInTheDocument();
  });

  it("implements accessible stretched link pattern on server cards and preserves control actions", () => {
    // NOTE: Overlay geometry and hit-testing of pseudo-elements (after:absolute after:inset-0)
    // cannot be computed in JSDOM. This test asserts DOM structure, stretched link classes,
    // presence of relative z-10 on child controls, and independent handler execution.
    renderPage();

    // Check Online Server (srv-1) card
    const serverNameLink = screen.getByRole("link", { name: "Online Server" });
    expect(serverNameLink).toHaveAttribute("href", "/servers/srv-1");
    // Verify after:absolute and after:inset-0 overlay classes on stretched link
    expect(serverNameLink.className).toContain("after:absolute");
    expect(serverNameLink.className).toContain("after:inset-0");

    // Parent card must have relative, cursor-pointer, and hover styling
    const card = serverNameLink.closest(".group");
    expect(card).not.toBeNull();
    expect(card).toHaveClass("relative");
    expect(card).toHaveClass("cursor-pointer");

    // Server card must contain exactly one link to the server detail
    const cardLinks = card ? Array.from(card.querySelectorAll('a[href="/servers/srv-1"]')) : [];
    expect(cardLinks).toHaveLength(1);

    // Interactive children within the card must have relative and z-10
    const copyBtn = within(card as HTMLElement).getByTitle("Click to copy server port");
    expect(copyBtn).toHaveClass("relative");
    expect(copyBtn).toHaveClass("z-10");

    const stopBtn = within(card as HTMLElement).getByRole("button", { name: "Stop" });
    expect(stopBtn).toHaveClass("relative");
    expect(stopBtn).toHaveClass("z-10");

    const terminalLink = within(card as HTMLElement).getByTitle("Open Console & Terminal");
    expect(terminalLink).toHaveClass("relative");
    expect(terminalLink).toHaveClass("z-10");
    expect(terminalLink).toHaveAttribute("href", "/servers/srv-1/console");

    const settingsLink = within(card as HTMLElement).getByTitle("Configure Server");
    expect(settingsLink).toHaveClass("relative");
    expect(settingsLink).toHaveClass("z-10");
    expect(settingsLink).toHaveAttribute("href", "/servers/srv-1/settings");

    // Check Start button on Stopped Server (srv-2)
    const startBtns = screen.getAllByRole("button", { name: "Start" });
    expect(startBtns[0]).toHaveClass("relative");
    expect(startBtns[0]).toHaveClass("z-10");

    // Clicking Stop button triggers stop confirmation dialog, not navigation to server detail
    fireEvent.click(stopBtn);
    expect(screen.getByText(/Are you sure you want to stop "Online Server"\?/i)).toBeInTheDocument();
    expect(screen.queryByTestId("server-detail-route")).not.toBeInTheDocument();
  });

  it("renders the 4-Column Hardware & Fleet KPI Grid with sparkline and metrics", () => {
    renderPage();
    expect(screen.getByRole("region", { name: "Fleet Availability" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Compute and Tickrate" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Memory Allocation" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Storage and Snapshots" })).toBeInTheDocument();

    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.getByText("Instances Online")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "1 Online" })).toHaveAttribute(
      "href",
      "/servers?status=running",
    );
    expect(screen.getByRole("link", { name: "1 Offline" })).toHaveAttribute(
      "href",
      "/servers?status=stopped",
    );
    expect(screen.getByRole("link", { name: "1 Crashed" })).toHaveAttribute(
      "href",
      "/servers?status=crashed",
    );
    expect(screen.getByRole("link", { name: "Run Backup" })).toHaveAttribute("href", "/backups");
  });

  it("renders rich server rows with identity, copyable ports, telemetry, and actions", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "Online Server" })).toHaveAttribute(
      "href",
      "/servers/srv-1",
    );
    expect(screen.getByRole("link", { name: "Stopped Server" })).toHaveAttribute(
      "href",
      "/servers/srv-2",
    );
    expect(screen.getByRole("link", { name: "Crashed Server" })).toHaveAttribute(
      "href",
      "/servers/srv-3",
    );

    expect(screen.getByText(":25565")).toBeInTheDocument();
    const copyPortBtn = screen.getByRole("button", { name: "Copy port 25565" });
    expect(copyPortBtn).toBeInTheDocument();

    const vanillaBadge = screen.getByText("vanilla 1.21.4");
    expect(vanillaBadge).toBeInTheDocument();
    expect(vanillaBadge.className).toContain("bg-surface-muted");
    expect(vanillaBadge.className).not.toContain("border");

    expect(screen.getByText("paper 1.21")).toBeInTheDocument();

    // Action buttons: Stop for running, Start for stopped/crashed
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Start" })).toHaveLength(2);
  });

  it("filters server rows by search text and status pills", () => {
    renderPage();
    const searchInput = screen.getByPlaceholderText("Filter by name, port, or tag...");
    fireEvent.change(searchInput, { target: { value: "Stopped" } });

    expect(screen.getByText("Stopped Server")).toBeInTheDocument();
    expect(screen.queryByText("Online Server")).not.toBeInTheDocument();

    // Clear search and click 'Online' pill
    fireEvent.change(searchInput, { target: { value: "" } });
    const onlinePill = screen.getByRole("button", { name: "Online (1)" });
    fireEvent.click(onlinePill);

    expect(screen.getByText("Online Server")).toBeInTheDocument();
    expect(screen.queryByText("Stopped Server")).not.toBeInTheDocument();
  });

  it("renders daemon event stream with live system timeline and clear function", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Daemon Event Stream" })).toBeInTheDocument();
    expect(screen.getByText(/ONX Manager v0\.1\.0 control plane initialized/i)).toBeInTheDocument();
    expect(screen.getByText(/Socket connection established/i)).toBeInTheDocument();

    const streamLog = screen.getByRole("log", { name: "System event logs" });
    expect(streamLog.className).toContain("text-xs");
    expect(streamLog.className).toContain("font-mono");

    const sysTag = screen.getAllByText("[SYS]")[0];
    expect(sysTag.className).toContain("text-status-info");
    expect(sysTag.className).not.toContain("border");

    const clearBtn = screen.getByRole("button", { name: "Clear" });
    fireEvent.click(clearBtn);
    expect(screen.getByText(/Event buffer cleared/i)).toBeInTheDocument();
  });

  it("renders live activity store events in daemon event stream", () => {
    useActivityStore.getState().addEvent({
      event_type: "ServerStartedEvent",
      server_id: "srv-1",
      name: "Online Server",
      timestamp: 1700000000,
    });
    renderPage();
    expect(screen.getByText(/Instance 'Online Server' start event dispatched/i)).toBeInTheDocument();
  });

  it("shows loading state with skeleton cards", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: undefined,
      isLoading: true,
    } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("shows empty state when server list is empty", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: [],
      isLoading: false,
    } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByText("No servers yet")).toBeInTheDocument();
    expect(
      screen.getByText("Create your first Minecraft server to get started."),
    ).toBeInTheDocument();
  });

  it("shows error state on failure", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("Network timeout"),
    } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByText("Network timeout")).toBeInTheDocument();
  });

  it("allows selecting a server to attach console and navigates to /servers/:id/console", () => {
    renderPage();
    const select = screen.getByRole("combobox", { name: /select a server to attach/i });
    expect(select).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Online Server/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Stopped Server/i })).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "srv-1" } });
    expect(screen.getByTestId("attached-console-route")).toBeInTheDocument();
  });

  it("displays live server CPU, RAM, TPS, players, and allocatable RAM after OS reserve", () => {
    const customQc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    // Pre-populate React Query cache for hostResources, server details, and server metrics
    customQc.setQueryData(["hostResources"], {
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
          name: "Online Server",
          kind: "server",
          status: "running",
          ram_mb: 4096,
          cpu_cores: 2,
        },
      ],
    });
    customQc.setQueryData(["servers", "detail", "srv-1"], {
      ...mockServers[0],
      min_memory_mb: 1024,
      max_memory_mb: 4096,
      java_args: "",
      spawn_protection: 16,
      pvp: true,
      enable_command_block: false,
      online_mode: true,
      whitelist: false,
      view_distance: 10,
      simulation_distance: 10,
      provider: "docker",
      deployment_host: null,
      deployment_port: null,
      deployment_pid: null,
      location_type: null,
      location_uri: null,
      root_path: null,
      working_directory: null,
      startup_jar: null,
      startup_command: null,
      primary_world: null,
    });
    customQc.setQueryData(["monitoring", "metrics", "srv-1"], [
      {
        tps: 19.8,
        players: 3,
        ram_used_mb: 2457.6,
        cpu_percent: 34.5,
        timestamp: "2026-11-23T12:00:00Z",
      },
    ]);

    vi.mocked(useServersList).mockReturnValue({
      data: [mockServers[0]],
      isLoading: false,
    } as unknown as ReturnType<typeof useServersList>);

    render(
      <QueryClientProvider client={customQc}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const cpuRegion = screen.getByRole("region", { name: "Compute and Tickrate" });
    expect(within(cpuRegion).getByText("34.5%")).toBeInTheDocument();
    expect(within(cpuRegion).getByText("19.8 TPS avg")).toBeInTheDocument();

    const memRegion = screen.getByRole("region", { name: "Memory Allocation" });
    expect(within(memRegion).getByText("2.4 / 12.0 GB")).toBeInTheDocument();
    expect(within(memRegion).getByText("4.0 GB Reserved (20.0% Used)")).toBeInTheDocument();
    expect(within(memRegion).getByText("9.6 GB Free")).toBeInTheDocument();

    const row = screen.getByRole("link", { name: "Online Server" }).closest(".group") as HTMLElement;
    expect(within(row).getByText("3 / 20 Players")).toBeInTheDocument();
    expect(within(row).getByText("CPU: 34.5%")).toBeInTheDocument();
    expect(within(row).getByText("RAM: 2.4 / 4.0 GB")).toBeInTheDocument();

    // Ensure telemetry column guards against overflowing into action buttons
    const telemetryCol = within(row).getByText("CPU: 34.5%").closest(".flex-1") as HTMLElement;
    expect(telemetryCol).toHaveClass("overflow-hidden");
    expect(telemetryCol).toHaveClass("min-w-0");
    expect(row).toHaveClass("@3xl:flex-row");
  });
});
