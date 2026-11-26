import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "./DashboardPage";
import { useActivityStore } from "@/stores/activityStore";
import { useToastStore } from "@/stores/toastStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import type { ServerResponse } from "@/server_manager/types";
import type {
  BackupResponse,
  HealthDashboardResponse,
  HealthResponse,
  HostResourceBudget,
  ScheduleResponse,
} from "@/types";
import type { MetricsSnapshot } from "@/services/api";

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
    max_memory_mb: 4096,
    cpu_cores: 0,
    uptime_seconds: 3720,
    mode: "simple",
    active_branch: "main",
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
    motd: "§aWelcome Home",
    max_players: 10,
    gamemode: "creative",
    difficulty: "peaceful",
    max_memory_mb: 4096,
    mode: "simple",
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
    max_memory_mb: 4096,
    mode: "advanced",
    active_branch: "staging",
    created_at: "",
    updated_at: "",
  },
];

const mockBudget: HostResourceBudget = {
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
  allocations: [
    {
      id: "srv-1",
      name: "Online Server",
      kind: "server",
      status: "running",
      ram_mb: 4096,
      cpu_cores: 0,
    },
  ],
};

const mockHealth: HealthResponse = {
  status: "ok",
  version: "1.4.2",
  database: "connected",
  uptime_seconds: 3900,
  docker: true,
};

const mockHealthDashboard: HealthDashboardResponse = {
  total_servers: 3,
  healthy: 2,
  warning: 1,
  critical: 0,
  broken: 0,
  unknown: 0,
  pending: 0,
  servers: [],
};

const mockBackups: BackupResponse[] = [
  {
    backup_id: "bk-1",
    server_id: "srv-1",
    backup_type: "full",
    status: "completed",
    size_bytes: Math.round(1.5 * 1024 * 1024 * 1024),
    checksum: "abc",
    error_message: "",
    created_at: new Date(Date.now() - 120_000).toISOString(),
    completed_at: new Date(Date.now() - 60_000).toISOString(),
    tier: "tier_1",
    pinned: false,
  },
];

const mockSchedules: ScheduleResponse[] = [
  {
    id: "sch-1",
    name: "Nightly",
    cron_expression: "0 3 * * *",
    task_name: "backup",
    params: { server_id: "srv-1" },
    enabled: true,
    last_run_at: null,
    created_at: null,
  },
  {
    id: "sch-2",
    name: "Evening",
    cron_expression: "0 18 * * *",
    task_name: "backup",
    params: { server_id: "srv-1" },
    enabled: true,
    last_run_at: null,
    created_at: null,
  },
];

const mockMetrics: MetricsSnapshot[] = [
  {
    timestamp: "2026-11-23T11:59:50Z",
    tps: 19.8,
    players: 3,
    ram_used_mb: 2457.6,
    cpu_percent: 28.0,
  },
  {
    timestamp: "2026-11-23T12:00:00Z",
    tps: 19.8,
    players: 3,
    ram_used_mb: 2457.6,
    cpu_percent: 34.5,
  },
];

const startMutateMock = vi.fn();
const stopMutateMock = vi.fn();
const restartMutateMock = vi.fn();
const retryMutateMock = vi.fn();
const refetchServersMock = vi.fn();
const refetchBudgetMock = vi.fn();

const mockApi = {
  health: vi.fn(),
  getSetupStatus: vi.fn(),
  getHealthDashboard: vi.fn(),
  getHostResources: vi.fn(),
  getMetrics: vi.fn(),
  listBackups: vi.fn(),
  listSchedules: vi.fn(),
  listOperations: vi.fn(),
  getOperation: vi.fn(),
  getServerActivity: vi.fn(),
  getMe: vi.fn(),
  getServer: vi.fn(),
};

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
  useStartServer: vi.fn(),
  useStopServer: vi.fn(),
  useRestartServer: vi.fn(),
  useRetryProvisioningServer: vi.fn(),
}));

vi.mock("@/server_manager/hooks/useHostResources", () => ({
  useHostResources: vi.fn(),
}));

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...actual,
    createAuthenticatedApi: vi.fn(() => mockApi),
  };
});

import {
  useRestartServer,
  useRetryProvisioningServer,
  useServersList,
  useStartServer,
  useStopServer,
} from "@/server_manager/hooks/useServers";
import { useHostResources } from "@/server_manager/hooks/useHostResources";

function makeQueryClient(seedAdmin = true) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (seedAdmin) {
    qc.setQueryData(["auth", "me"], {
      user_id: "u1",
      username: "admin",
      email: null,
      display_name: "Admin",
      is_active: true,
      roles: ["owner"],
      permissions: ["admin:full"],
      created_at: "",
      last_login_at: null,
    });
  }
  return qc;
}

function renderPage(customQc?: QueryClient) {
  const client = customQc ?? makeQueryClient();
  return {
    qc: client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route
              path="/servers/:serverId/console"
              element={<div data-testid="attached-console-route">Attached Console</div>}
            />
            <Route
              path="/servers/:serverId/settings"
              element={<div data-testid="server-settings-route">Server Settings</div>}
            />
            <Route
              path="/servers/:serverId"
              element={<div data-testid="server-detail-route">Server Detail</div>}
            />
            <Route
              path="/servers"
              element={<div data-testid="servers-page-route">Servers Page</div>}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useActivityStore.getState().clear();
    useToastStore.getState().clear();
    useOperationStore.setState({ operations: {}, activeDrawerId: null });

    vi.mocked(useServersList).mockReturnValue({
      data: mockServers,
      isLoading: false,
      error: null,
      refetch: refetchServersMock,
    } as unknown as ReturnType<typeof useServersList>);

    vi.mocked(useHostResources).mockReturnValue({
      data: mockBudget,
      isLoading: false,
      refetch: refetchBudgetMock,
    } as unknown as ReturnType<typeof useHostResources>);

    vi.mocked(useStartServer).mockReturnValue({
      mutate: startMutateMock,
      isPending: false,
    } as unknown as ReturnType<typeof useStartServer>);

    vi.mocked(useStopServer).mockReturnValue({
      mutate: stopMutateMock,
      isPending: false,
    } as unknown as ReturnType<typeof useStopServer>);

    vi.mocked(useRestartServer).mockReturnValue({
      mutate: restartMutateMock,
      isPending: false,
    } as unknown as ReturnType<typeof useRestartServer>);

    vi.mocked(useRetryProvisioningServer).mockReturnValue({
      mutate: retryMutateMock,
      isPending: false,
    } as unknown as ReturnType<typeof useRetryProvisioningServer>);

    mockApi.health.mockResolvedValue(mockHealth);
    mockApi.getSetupStatus.mockResolvedValue({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "1.4.2",
      deployment_profile: "vps",
    });
    mockApi.getHealthDashboard.mockResolvedValue(mockHealthDashboard);
    mockApi.getMetrics.mockResolvedValue(mockMetrics);
    mockApi.listBackups.mockResolvedValue(mockBackups);
    mockApi.listSchedules.mockResolvedValue(mockSchedules);
    mockApi.listOperations.mockResolvedValue([]);
    mockApi.getServerActivity.mockResolvedValue({ items: [], total: 0, limit: 5, offset: 0 });
    mockApi.getMe.mockResolvedValue({
      user_id: "u1",
      username: "admin",
      roles: ["admin"],
    });
  });

  it("renders real /health daemon status strip, heading, and zero N+1 getServer calls", async () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(await screen.findByText("Docker Connected")).toBeInTheDocument();
    expect(screen.getByText("Database Ready")).toBeInTheDocument();
    expect(screen.getByText("v1.4.2")).toBeInTheDocument();
    expect(screen.getByText(/Panel up 1h 5m/i)).toBeInTheDocument();

    expect(mockApi.getServer).not.toHaveBeenCalled();
  });

  it("renders Docker Offline critical banner when /health reports docker: false", async () => {
    mockApi.health.mockResolvedValue({ ...mockHealth, docker: false });
    renderPage();

    expect(await screen.findByText("Docker Offline")).toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/Docker engine is offline/i);
  });

  it("renders honest 4-card KPI strip with real backup size, schedules, Server CPU, Shared CPU, and consistent free RAM", async () => {
    renderPage();

    const fleetRegion = screen.getByRole("region", { name: "Fleet and Players" });
    expect(within(fleetRegion).getByText("1 / 3")).toBeInTheDocument();
    expect(await within(fleetRegion).findByText("1 health warn")).toBeInTheDocument();
    expect(within(fleetRegion).getByRole("link", { name: "1 Online" })).toHaveAttribute(
      "href",
      "/servers?status=running",
    );
    expect(within(fleetRegion).getByRole("link", { name: "1 Offline" })).toHaveAttribute(
      "href",
      "/servers?status=stopped",
    );
    expect(within(fleetRegion).getByRole("link", { name: "1 Attention" })).toHaveAttribute(
      "href",
      "/servers?status=attention",
    );

    const computeRegion = screen.getByRole("region", { name: "Compute and Tickrate" });
    expect(await within(computeRegion).findByText("34.5%")).toBeInTheDocument();
    expect(within(computeRegion).getByText("19.8 TPS")).toBeInTheDocument();
    expect(within(computeRegion).getByText("Server CPU (1 active)")).toBeInTheDocument();
    expect(screen.queryByText(/Host CPU/i)).not.toBeInTheDocument();

    const memRegion = screen.getByRole("region", { name: "Memory and Capacity" });
    expect(within(memRegion).getByText("2.4 GB")).toBeInTheDocument();
    expect(within(memRegion).getByText("/ 4.0 GB")).toBeInTheDocument();
    expect(within(memRegion).getByText("8 GB free")).toBeInTheDocument();

    const budgetRegion = screen.getByRole("region", { name: "Host Resource Budget" });
    expect(within(budgetRegion).getByText("8 GB free")).toBeInTheDocument();
    expect(within(budgetRegion).getByText("Shared CPU (6 cores)")).toBeInTheDocument();

    const backupRegion = screen.getByRole("region", { name: "Backups and Schedules" });
    expect(await within(backupRegion).findByText("1.5 GB")).toBeInTheDocument();
    expect(within(backupRegion).getByText("1 saved")).toBeInTheDocument();
    expect(within(backupRegion).getByText("2 scheduled")).toBeInTheDocument();
    expect(screen.queryByText("0.5 GB")).not.toBeInTheDocument();
  });

  it("navigates attention banner to single crashed server console or filtered servers page for multiple", () => {
    renderPage();
    const consoleLink = screen.getByRole("link", { name: "Open Console" });
    expect(consoleLink).toHaveAttribute("href", "/servers/srv-3/console");

    vi.mocked(useServersList).mockReturnValue({
      data: [
        mockServers[0],
        mockServers[2],
        { ...mockServers[1], server_id: "srv-4", name: "Broken Four", status: "broken" },
      ],
      isLoading: false,
      error: null,
      refetch: refetchServersMock,
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    const inspectLink = screen.getByRole("link", { name: "Inspect Servers" });
    expect(inspectLink).toHaveAttribute("href", "/servers?status=attention");
  });

  it("hides Create, Import, Start All, and per-server power buttons for viewer role", async () => {
    mockApi.getMe.mockResolvedValue({
      user_id: "viewer-1",
      username: "viewer",
      roles: ["viewer"],
      permissions: ["server:read"],
    });

    renderPage(makeQueryClient(false));
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "New Server" })).not.toBeInTheDocument();
    });
    expect(screen.queryByRole("link", { name: "Import" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start All" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restart" })).not.toBeInTheDocument();
  });

  it("renders StartingMonitorBanner when a server is starting", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: [{ ...mockServers[1], status: "starting" }],
      isLoading: false,
      error: null,
      refetch: refetchServersMock,
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    const banner = screen.getByLabelText("Starting monitor");
    expect(banner).toHaveTextContent(/Stopped Server/i);
    expect(screen.getByRole("button", { name: /Check now/i })).toBeInTheDocument();
  });

  it("supports ErrorState with Retry and 0-server EmptyState with both Create and Import CTAs", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("Backend unreachable"),
      refetch: refetchServersMock,
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    expect(screen.getByText("Backend unreachable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Try Again/i }));
    expect(refetchServersMock).toHaveBeenCalledTimes(1);
    expect(refetchBudgetMock).toHaveBeenCalledTimes(1);

    vi.mocked(useServersList).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
      refetch: refetchServersMock,
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    expect(screen.getByText("Launch your first Minecraft server")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create Server" })).toHaveAttribute(
      "href",
      "/servers/create",
    );
    expect(screen.getByRole("link", { name: "Import Existing Server" })).toHaveAttribute(
      "href",
      "/servers/import",
    );
  });

  it("preserves stretched links, copies full join address with toast, locks only clicked server on busy, supports Restart/Retry, and Start All confirmation", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const serversWithFailedProv: ServerResponse[] = [
      ...mockServers,
      {
        ...mockServers[1],
        server_id: "srv-4",
        name: "Failed Provision",
        status: "provisioning_failed",
        provisioning_retryable: true,
        provisioning_error: "Container pull failed",
        port: 25568,
      },
    ];

    vi.mocked(useServersList).mockReturnValue({
      data: serversWithFailedProv,
      isLoading: false,
      error: null,
      refetch: refetchServersMock,
    } as unknown as ReturnType<typeof useServersList>);

    // Keep start pending (never calls onSettled) so we verify per-server busyServerIds lock!
    startMutateMock.mockImplementation(() => undefined);

    renderPage();

    // Stretched link & ServerIcon render
    const onlineLink = screen.getByRole("link", { name: "Online Server" });
    expect(onlineLink).toHaveAttribute("href", "/servers/srv-1/console");
    expect(onlineLink.className).toContain("after:absolute");
    expect(onlineLink.className).toContain("after:inset-0");

    // Full join address copy + toast
    const copyBtn = screen.getByRole("button", { name: "Copy join address localhost:25565" });
    fireEvent.click(copyBtn);
    expect(writeText).toHaveBeenCalledWith("localhost:25565");
    expect(useToastStore.getState().toasts.some((t) => t.title === "Address copied")).toBe(true);

    // Restart click
    fireEvent.click(screen.getByRole("button", { name: "Restart" }));
    expect(restartMutateMock).toHaveBeenCalledWith("srv-1", expect.any(Object));

    // Retry provisioning click
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retryMutateMock).toHaveBeenCalledWith("srv-4", expect.any(Object));
    expect(screen.getByText("Container pull failed")).toBeInTheDocument();

    // Per-server busy lock: click Start on srv-2 -> srv-3's Start stays enabled!
    const stoppedCard = screen.getByRole("link", { name: "Stopped Server" }).closest(".group") as HTMLElement;
    const crashedCard = screen.getByRole("link", { name: "Crashed Server" }).closest(".group") as HTMLElement;
    fireEvent.click(within(stoppedCard).getByRole("button", { name: "Start" }));
    expect(within(stoppedCard).getByRole("button", { name: "Starting..." })).toBeDisabled();
    expect(within(crashedCard).getByRole("button", { name: "Start" })).not.toBeDisabled();

    // Safe Start All confirmation dialog
    fireEvent.click(screen.getByRole("button", { name: "Start All" }));
    expect(screen.getByText(/Start 2 servers\?/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start All Servers" }));
    expect(startMutateMock).toHaveBeenCalledTimes(3);
  });

  it("locks Stop ConfirmDialog controls while stopServer.isPending is true", () => {
    vi.mocked(useStopServer).mockReturnValue({
      mutate: stopMutateMock,
      isPending: true,
    } as unknown as ReturnType<typeof useStopServer>);

    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(screen.getByRole("button", { name: "Stopping..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("filters servers by search text, status pills including crashed under Offline, and clears filters", () => {
    renderPage();

    const searchInput = screen.getByPlaceholderText("Search name, port, loader...");
    fireEvent.change(searchInput, { target: { value: "paper" } });
    expect(screen.getByText("Stopped Server")).toBeInTheDocument();
    expect(screen.queryByText("Online Server")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByText("Online Server")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Offline (2)" }));
    expect(screen.getByText("Stopped Server")).toBeInTheDocument();
    expect(screen.getByText("Crashed Server")).toBeInTheDocument();
    expect(screen.queryByText("Online Server")).not.toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: "nonexistent-node" } });
    expect(screen.getByText("No servers match your current filter.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("Online Server")).toBeInTheDocument();
  });

  it("renders no fake daemon logs in Activity & Tasks and jumps Quick Console cleanly", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "Activity & Tasks" })).toBeInTheDocument();
    expect(screen.queryByText(/ONX Manager v0\.1\.0/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/var\/run\/docker\.sock/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\[SYS\]/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\[DOCKER\]/i)).not.toBeInTheDocument();

    const select = screen.getByRole("combobox", { name: "Select server console" });
    fireEvent.change(select, { target: { value: "srv-2" } });
    fireEvent.click(screen.getByRole("button", { name: /Open Console/i }));
    expect(screen.getByTestId("attached-console-route")).toBeInTheDocument();
  });

  it("ignores orphaned critical health entries for deleted servers and keeps left fleet panel unstretched", async () => {
    vi.mocked(useServersList).mockReturnValue({
      data: [mockServers[0]], // only srv-1 exists and is healthy/running
      isLoading: false,
      error: null,
      refetch: refetchServersMock,
    } as unknown as ReturnType<typeof useServersList>);

    mockApi.getHealthDashboard.mockResolvedValue({
      total_servers: 8,
      healthy: 1,
      warning: 0,
      critical: 7,
      broken: 0,
      unknown: 0,
      pending: 0,
      servers: [
        {
          server_id: "srv-1",
          status: "healthy",
          trend: "stable",
          contributing_factors: [],
          last_updated: "2026-11-24T00:00:00Z",
        },
        {
          server_id: "ghost-srv-1",
          status: "critical",
          trend: "declining",
          contributing_factors: ["Critical: crash=UNKNOWN_RUNTIME_FAILURE"],
          last_updated: "2026-09-15T00:00:00Z",
        },
      ],
    });

    renderPage();

    const fleetRegion = await screen.findByRole("region", { name: "Fleet and Players" });
    expect(within(fleetRegion).queryByText(/health warn/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    // Left Servers panel does not force h-full stretch
    const serversHeading = screen.getByRole("heading", { name: "Servers" });
    const serversCard = serversHeading.closest(".rounded-xl.border.bg-surface-card");
    expect(serversCard?.className).not.toContain("h-full");
  });
});
