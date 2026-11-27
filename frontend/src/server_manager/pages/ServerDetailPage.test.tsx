import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError, type MetricsSnapshot } from "@/services/api";
import type { RuntimeDiagnosticsResponse, ServerDetailResponse } from "@/server_manager/types";
import { ServerDetailPage } from "./ServerDetailPage";

function NavigateButton({ to, label }: { to: string; label: string }) {
  const navigate = useNavigate();
  return <button onClick={() => navigate(to)}>{label}</button>;
}

const { subscribeChannelsMock, unsubscribeChannelsMock, copyMock } = vi.hoisted(() => ({
  subscribeChannelsMock: vi.fn(),
  unsubscribeChannelsMock: vi.fn(),
  copyMock: vi.fn(),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  subscribeChannels: subscribeChannelsMock,
  unsubscribeChannels: unsubscribeChannelsMock,
}));

const mockServer: ServerDetailResponse = {
  server_id: "srv-1",
  name: "Test Server",
  server_type: "vanilla",
  minecraft_version: "1.20.4",
  status: "running",
  group_id: "default",
  port: 25565,
  motd: "Welcome!",
  max_players: 20,
  gamemode: "survival",
  difficulty: "normal",
  min_memory_mb: 1024,
  max_memory_mb: 2048,
  java_args: "-Xmx2G",
  spawn_protection: 16,
  pvp: true,
  enable_command_block: false,
  online_mode: true,
  whitelist: false,
  view_distance: 10,
  simulation_distance: 10,
  provider: null,
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
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

let mockData: ServerDetailResponse | null = mockServer;
let mockIsLoading = false;
let mockError: Error | null = null;

let mockRuntimeData: RuntimeDiagnosticsResponse | null = null;
let mockMetricsData: MetricsSnapshot[] | null = null;
let mockExposureData: { desired_state: string; aggregate_status: string; method?: string; targets?: Array<{ public_address: string | null }> } | null = null;

vi.mock("@/server_manager/hooks/useServerExposure", () => ({
  useServerExposure: vi.fn(() => ({
    exposure: mockExposureData,
    serverExposureQuery: { data: mockExposureData },
    agentStatusQuery: { data: null },
    portsQuery: { data: [] },
  })),
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServerDetail: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useServerRuntime: vi.fn(() => ({
    data: mockRuntimeData,
  })),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDeleteServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRetryProvisioningServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

vi.mock("@/server_manager/hooks/useServerMetrics", () => ({
  useServerMetrics: vi.fn(() => ({
    data: mockMetricsData,
  })),
}));

vi.mock("@/server_manager/components/ServerConsole", () => ({
  ServerConsole: () => <div data-testid="server-console">Console</div>,
}));

vi.mock("@/server_manager/components/Sparkline", () => ({
  Sparkline: () => <div data-testid="sparkline">Sparkline</div>,
}));

vi.mock("@/hooks/useClipboard", () => ({
  useClipboard: () => ({ copy: copyMock }),
}));

function SettingsRouteProbe() {
  const loc = useLocation();
  return <div data-testid="settings-route-target">{`${loc.pathname}${loc.search}`}</div>;
}

function renderPage(serverId = "srv-1") {
  const qc = new QueryClient();
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
  return {
    qc,
    ...render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[`/servers/${serverId}`]}>
          <Routes>
            <Route path="/servers/:serverId" element={<ServerDetailPage />} />
            <Route path="/servers/:serverId/settings" element={<SettingsRouteProbe />} />
            <Route path="/servers" element={<div data-testid="servers-list">Servers</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

describe("ServerDetailPage", () => {
  beforeEach(() => {
    mockData = mockServer;
    mockIsLoading = false;
    mockError = null;
    mockRuntimeData = null;
    mockMetricsData = null;
    mockExposureData = null;
    subscribeChannelsMock.mockClear();
    unsubscribeChannelsMock.mockClear();
  });

  it("shows loading skeletons", () => {
    mockIsLoading = true;
    const { container } = renderPage();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error message on transient error", () => {
    mockError = new Error("Failed to load");
    renderPage();
    expect(screen.getByText("Failed to load")).toBeInTheDocument();
  });

  it("shows not-found state when data is empty", () => {
    mockData = null;
    renderPage();
    expect(screen.getByText("Server not found")).toBeInTheDocument();
  });

  it("shows not-found state (not a generic error) on a 404 response", () => {
    mockError = new ApiError(404, "NOT_FOUND", "Request failed with status 404");
    renderPage();
    expect(screen.getByText("Server not found")).toBeInTheDocument();
    expect(screen.queryByText("Request failed with status 404")).not.toBeInTheDocument();
  });

  it("opens Diagnostics & Runtime Info drawer with server configuration and no Zone ID placeholder", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByTestId("open-diagnostics-drawer-btn"));
    const drawer = screen.getByTestId("server-diagnostics-drawer");
    expect(drawer).toBeInTheDocument();
    expect(drawer).toHaveTextContent("1.20.4");
    expect(drawer).toHaveTextContent("25565");
    expect(drawer).toHaveTextContent("Runtime & Process");
    expect(drawer).toHaveTextContent("Gameplay Snapshot");
    expect(drawer).not.toHaveTextContent("Zone ID");
    expect(drawer).not.toHaveTextContent("Coming Soon");
  });

  it("renders a cleaned MOTD inside Diagnostics drawer", async () => {
    const user = userEvent.setup();
    mockData = { ...mockServer, motd: "\u00a7bWelcome\u00a7r &6to &ethe server" };
    renderPage();
    await user.click(screen.getByTestId("open-diagnostics-drawer-btn"));
    expect(screen.getByText("Welcome to the server")).toBeInTheDocument();
  });

  it("shows a placeholder MOTD when empty inside Diagnostics drawer", async () => {
    const user = userEvent.setup();
    mockData = { ...mockServer, motd: "" };
    renderPage();
    await user.click(screen.getByTestId("open-diagnostics-drawer-btn"));
    const motdRow = screen.getByText("MOTD").parentElement!;
    expect(motdRow.querySelector("dd")!.textContent).toBe("—");
  });

  it("renders TPS Usage card with live metric value when running", () => {
    mockData = { ...mockServer, status: "running" };
    mockMetricsData = [
      {
        tps: 20.0,
        players: 3,
        ram_used_mb: 1024,
        cpu_percent: 10.0,
        timestamp: "2026-08-18T19:00:00Z",
      },
    ];
    renderPage();
    expect(screen.getByText("TPS & Tick Rate")).toBeInTheDocument();
    expect(screen.getByTestId("tps-usage-value")).toHaveTextContent("20.0 (100%)");
  });

  it("renders — for TPS Usage card when server is stopped despite metrics history", () => {
    mockData = { ...mockServer, status: "stopped" };
    mockMetricsData = [
      {
        tps: 20.0,
        players: 3,
        ram_used_mb: 1024,
        cpu_percent: 10.0,
        timestamp: "2026-08-18T19:00:00Z",
      },
    ];
    renderPage();
    expect(screen.getByTestId("tps-usage-value")).toHaveTextContent("—");
  });

  it("renders — for CPU and RAM Usage cards when server is stopped despite metrics history", () => {
    mockData = { ...mockServer, status: "stopped" };
    mockMetricsData = [
      {
        tps: 20.0,
        players: 3,
        ram_used_mb: 1024,
        cpu_percent: 10.0,
        timestamp: "2026-08-18T19:00:00Z",
      },
    ];
    renderPage();
    expect(screen.getAllByText("CPU Usage").length).toBeGreaterThan(0);
    expect(screen.queryByText("10.0%")).not.toBeInTheDocument();
    expect(screen.queryByText("1.0 GB (50.0%)")).not.toBeInTheDocument();
  });

  it("renders — for TPS Usage card when running but TPS is null (unknown)", () => {
    mockData = { ...mockServer, status: "running" };
    mockMetricsData = [
      {
        tps: null,
        players: 3,
        ram_used_mb: 1024,
        cpu_percent: 10.0,
        timestamp: "2026-08-18T19:00:00Z",
      },
    ];
    renderPage();
    expect(screen.getByTestId("tps-usage-value")).toHaveTextContent("—");
  });

  it("renders provisioning failure reason banner when status is provisioning_failed", () => {
    mockData = {
      ...mockServer,
      status: "provisioning_failed",
      provisioning_error: "Installer execution failed: installer exited with code 1",
    };
    renderPage();
    const banner = screen.getByTestId("provisioning-failed-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent("Server Installation Failed");
    expect(banner).toHaveTextContent("Installer execution failed: installer exited with code 1");
    expect(screen.getByTestId("detail-retry-provisioning-btn")).toBeInTheDocument();
  });

  it("renders address widget with public exposure address when exposure is active", () => {
    mockData = { ...mockServer, deployment_host: "127.0.0.1", deployment_port: 25565 };
    mockExposureData = {
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      method: "playit",
      targets: [{ public_address: "craft.ply.gg:54321" }],
    };
    renderPage();
    expect(screen.getByText("craft.ply.gg:54321")).toBeInTheDocument();
  });

  it("renders dedicated Server Port widget with copyable port value", () => {
    mockData = { ...mockServer, port: 25577 };
    renderPage();
    const portWidget = screen.getByTestId("server-port-widget");
    expect(portWidget).toBeInTheDocument();
    expect(portWidget).toHaveTextContent("Server Port");
    expect(portWidget).toHaveTextContent("25577");
  });

  it("always renders numeric port in server-port-widget and never leaks Docker 172.x bridge IP", async () => {
    const user = userEvent.setup();
    mockData = {
      ...mockServer,
      deployment_host: "172.18.0.5",
      deployment_port: 25565,
      port: 25565,
    };
    renderPage();
    const portWidget = screen.getByTestId("server-port-widget");
    expect(portWidget).toHaveTextContent("25565");
    expect(portWidget).not.toHaveTextContent("172.18.0.5");
    expect(screen.getByTestId("vitals-join-address")).toHaveTextContent("localhost:25565");
    const copyBtn = portWidget.querySelector("button");
    expect(copyBtn).not.toBeNull();
    await user.click(copyBtn!);
    expect(copyMock).toHaveBeenCalledWith("25565", expect.any(String));
  });

  it("hides Retry Provisioning button when provisioning_retryable is false", () => {
    mockData = {
      ...mockServer,
      status: "provisioning_failed",
      provisioning_error: "Unsupported Java version",
      provisioning_retryable: false,
    };
    renderPage();
    expect(screen.getByTestId("provisioning-failed-banner")).toBeInTheDocument();
    expect(screen.queryByTestId("detail-retry-provisioning-btn")).not.toBeInTheDocument();
  });

  it("renders uptime formatted when uptime_seconds > 0", () => {
    mockRuntimeData = {
      server_id: "srv-1",
      server_name: "Test Server",
      status: "running",
      alive: true,
      pid: 1234,
      provider: "local",
      uptime_seconds: 3665, // 1h 1m
      heartbeat_age_seconds: null,
      startup_duration_seconds: null,
      restart_count: 0,
      failure_code: null,
      failure_reason: null,
      last_logs: null,
      last_exception: null,
      last_verification_timestamp: null,
      supervised: true,
      runtime_handle: null,
      provider_status: null,
      last_crash_time: null,
      port: 25565,
      port_owner: null,
      tmux_session: null,
      jvm_command: null,
      owner_conflicts: [],
      validation_chain: [],
    };
    renderPage();
    expect(screen.getByText("1h 1m")).toBeInTheDocument();
  });

  it("subscribes to metrics:<serverId> on mount", () => {
    renderPage("srv-1");
    expect(subscribeChannelsMock).toHaveBeenCalledWith(["metrics:srv-1"]);
  });

  it("unsubscribes metrics:<serverId> on unmount", () => {
    const { unmount } = renderPage("srv-1");
    unmount();
    expect(unsubscribeChannelsMock).toHaveBeenCalledWith(["metrics:srv-1"]);
  });

  it("unsubscribes old and subscribes new metrics:<serverId> when the route param changes", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/servers/srv-1"]}>
          <Routes>
            <Route path="/servers/:serverId" element={<ServerDetailPage />} />
          </Routes>
          <NavigateButton to="/servers/srv-2" label="go srv-2" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(subscribeChannelsMock).toHaveBeenCalledWith(["metrics:srv-1"]);

    await user.click(screen.getByText("go srv-2"));
    expect(unsubscribeChannelsMock).toHaveBeenCalledWith(["metrics:srv-1"]);
    expect(subscribeChannelsMock).toHaveBeenCalledWith(["metrics:srv-2"]);
  });

  it("filters Docker bridge IP from join address while showing Internal Container IP in Diagnostics drawer", async () => {
    const user = userEvent.setup();
    mockData = {
      ...mockServer,
      provider: "docker",
      deployment_host: "172.17.0.3",
      deployment_port: 25569,
      port: 25569,
    };
    renderPage();
    expect(screen.getByTestId("vitals-join-address")).toHaveTextContent("localhost:25569");
    await user.click(screen.getByTestId("open-diagnostics-drawer-btn"));
    expect(screen.getByText("Internal Container IP")).toBeInTheDocument();
    expect(screen.getByText("172.17.0.3:25569")).toBeInTheDocument();
  });

  it("renders LAN Host in join address and Diagnostics drawer for host process server", async () => {
    const user = userEvent.setup();
    mockData = {
      ...mockServer,
      provider: "local",
      deployment_host: "192.168.1.253",
      deployment_port: 25565,
      port: 25565,
    };
    renderPage();
    expect(screen.getByTestId("vitals-join-address")).toHaveTextContent("192.168.1.253:25565");
    await user.click(screen.getByTestId("open-diagnostics-drawer-btn"));
    expect(screen.getByText("Host")).toBeInTheDocument();
  });

  it("renders page root with flex-1 min-h-0 for full-height viewport stretching", () => {
    const { container } = renderPage();
    const pageRoot = container.firstElementChild;
    expect(pageRoot?.className).toContain("flex-1");
    expect(pageRoot?.className).toContain("min-h-0");
  });

  it("hides Install Modpack action on non-modded servers and shows it on modded loaders", () => {
    mockData = { ...mockServer, server_type: "vanilla" };
    const { rerender, qc } = renderPage();
    expect(screen.queryByTestId("detail-open-modpack-wizard-btn")).not.toBeInTheDocument();
    expect(screen.getByTestId("detail-open-safe-upgrade-wizard-btn")).toBeInTheDocument();

    mockData = { ...mockServer, server_type: "fabric" };
    rerender(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1"]}>
          <Routes>
            <Route path="/servers/:serverId" element={<ServerDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("detail-open-modpack-wizard-btn")).toBeInTheDocument();
    expect(screen.getByTestId("detail-open-safe-upgrade-wizard-btn")).toBeInTheDocument();
  });

  it("navigates to Settings Change Version drawer when Change Version is clicked", async () => {
    const user = userEvent.setup();
    renderPage("srv-1");
    const btn = screen.getByTestId("detail-open-safe-upgrade-wizard-btn");
    expect(btn).toHaveTextContent("Change Version");
    await user.click(btn);
    expect(screen.getByTestId("settings-route-target")).toHaveTextContent(
      "/servers/srv-1/settings?tab=lifecycle&action=change-version",
    );
  });
});
