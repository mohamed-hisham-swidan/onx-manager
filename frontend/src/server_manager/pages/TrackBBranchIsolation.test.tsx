import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerShell } from "@/layouts/ServerShell";
import { ServerDetailPage } from "./ServerDetailPage";
import { PluginListPage } from "./PluginListPage";
import { ServerSettingsPage } from "./ServerSettingsPage";
import { ServerExposurePage } from "./ServerExposurePage";
import { ServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import type { ServerBranch, ServerDetailResponse } from "@/server_manager/types";
import type { PluginResponse, ServerExposureResponse } from "@/types";

const mockApi = vi.hoisted(() => ({
  getMe: vi.fn(),
  getSetupStatus: vi.fn(),
  getServer: vi.fn(),
  getServerBranches: vi.fn(),
  getBranchRuntime: vi.fn(),
  startBranchRun: vi.fn(),
  stopBranchRun: vi.fn(),
  destroyBranchRun: vi.fn(),
  listDataTemplates: vi.fn(),
  getServerConsole: vi.fn(),
  sendServerCommand: vi.fn(),
  getServerCrashReports: vi.fn(),
  listPlugins: vi.fn(),
  enablePlugin: vi.fn(),
  disablePlugin: vi.fn(),
  uninstallPlugin: vi.fn(),
  createServerCommit: vi.fn(),
  createServerBranch: vi.fn(),
  updateServer: vi.fn(),
  restartServer: vi.fn(),
  discardPendingSettings: vi.fn(),
  getServerExposure: vi.fn(),
  getAgentStatus: vi.fn(),
  listServerPorts: vi.fn(),
  setServerExposure: vi.fn(),
  setServerExposureState: vi.fn(),
}));

const mainPowerMocks = vi.hoisted(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  restart: vi.fn(),
}));

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    createAuthenticatedApi: () => mockApi,
  };
});

vi.mock("@/hooks/useWebSocket", () => ({
  subscribeChannels: vi.fn(),
  unsubscribeChannels: vi.fn(),
  useConsoleStream: vi.fn(),
}));

vi.mock("@/server_manager/hooks/useServers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/server_manager/hooks/useServers")>();
  return {
    ...actual,
    useServersList: vi.fn(() => ({
      data: [{ server_id: "srv-1", name: "Adv Server", status: "running", port: 25565, mode: "advanced" }],
    })),
    useStartServer: vi.fn(() => ({ mutate: mainPowerMocks.start, isPending: false })),
    useStopServer: vi.fn(() => ({ mutate: mainPowerMocks.stop, isPending: false })),
    useRestartServer: vi.fn(() => ({ mutate: mainPowerMocks.restart, isPending: false })),
  };
});

vi.mock("@/server_manager/hooks/useServerMetrics", () => ({
  useServerMetrics: vi.fn(() => ({ data: [] })),
}));

vi.mock("@/stores/toastStore", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/stores/toastStore")>();
  return {
    ...actual,
    toast: vi.fn(),
  };
});

vi.mock("@/server_manager/components/ServerSettingsSection", () => ({
  ServerSettingsSection: ({ branch }: { branch?: string }) => (
    <div data-testid="mock-settings-section">Settings form for {branch ?? "main"}</div>
  ),
}));

vi.mock("@/server_manager/components/p55/ServerP55SettingsCard", () => ({
  ServerP55SettingsCard: () => <div data-testid="mock-p55-settings" />,
}));

vi.mock("@/server_manager/components/ServerModeConversionCard", () => ({
  ServerModeConversionCard: () => <div data-testid="mock-conversion-card" />,
}));

const baseServer: ServerDetailResponse = {
  server_id: "srv-1",
  name: "Adv Server",
  server_type: "paper",
  minecraft_version: "1.20.4",
  status: "running",
  mode: "advanced",
  group_id: "default",
  port: 25565,
  motd: "Main Server",
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
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

const branches: ServerBranch[] = [
  {
    id: "b-main",
    server_id: "srv-1",
    name: "main",
    head_commit_id: "a".repeat(40),
    created_at: "2024-01-01T00:00:00Z",
    is_protected: true,
    worktree_path: "/tmp/wt/main",
    worktree_locked: false,
  },
  {
    id: "b-feat",
    server_id: "srv-1",
    name: "feat-a",
    head_commit_id: "b".repeat(40),
    created_at: "2024-01-01T00:00:00Z",
    is_protected: false,
    worktree_path: "/tmp/wt/feat-a",
    worktree_locked: false,
  },
];

function makeQC() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

describe("Track B Multi-Tab Branch Isolation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockApi.getMe.mockResolvedValue({ user_id: "u1", roles: ["owner"] });
    mockApi.getSetupStatus.mockResolvedValue({ deployment_mode: "vps", password_configured: true });
    mockApi.getServer.mockResolvedValue(baseServer);
    mockApi.getServerBranches.mockResolvedValue(branches);
    mockApi.getServerConsole.mockResolvedValue({ lines: ["[INFO] Done (1.2s)! For help, type \"help\""] });
    mockApi.getServerCrashReports.mockResolvedValue([]);
    mockApi.listDataTemplates.mockResolvedValue([
      {
        id: "tpl-1",
        server_id: "srv-1",
        name: "Survival Snapshot",
        description: "",
        source_branch_name: "main",
        source_commit_sha: null,
        file_count: 10,
        total_bytes: 1024,
        status: "ready",
        operation_id: null,
      },
    ]);
    mockApi.getAgentStatus.mockResolvedValue({
      claimed: false,
      process_status: "stopped",
      desired_agent_running: false,
      last_health_at: null,
      claim_active: false,
      claim_expires_at: null,
    });
    mockApi.listServerPorts.mockResolvedValue([]);
    mockApi.getServerExposure.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "main",
      method: "none",
      desired_state: "DISABLED",
      aggregate_status: "DISABLED",
      error_code: null,
      error_message: null,
      cloudflare_tunnel_id: null,
      has_cloudflare_credentials: false,
      targets: [],
    } satisfies ServerExposureResponse);
  });

  it("ServerShell scopes Sidebar links and Start/Stop power buttons to the active branch without touching main", async () => {
    const user = userEvent.setup();
    mockApi.getBranchRuntime.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "feat-a",
      runtime_id: "rt-1",
      runtime_status: "stopped",
      container_provisioned: false,
      port_set: null,
    });
    mockApi.startBranchRun.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "feat-a",
      runtime_id: "rt-1",
      runtime_status: "running",
    });

    const qc = makeQC();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1/console?branch=feat-a"]}>
          <Routes>
            <Route path="/servers/:serverId" element={<ServerShell />}>
              <Route path="console" element={<div data-testid="outlet-console">OK</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const startBtn = await screen.findByRole("button", { name: /^Start$/i });
    await waitFor(() => expect(screen.getByTestId("branch-unprovisioned-badge")).toBeInTheDocument());

    const pluginsLink = screen.getByRole("link", { name: "Plugins" });
    expect(pluginsLink).toHaveAttribute("href", "/servers/srv-1/plugins?branch=feat-a");

    await user.click(startBtn);
    await waitFor(() => expect(mockApi.startBranchRun).toHaveBeenCalledWith("srv-1", "feat-a"));
    expect(mainPowerMocks.start).not.toHaveBeenCalled();
  });

  it("ServerDetailPage renders unprovisioned state and destroy flow for non-main branches", async () => {
    const user = userEvent.setup();
    mockApi.getBranchRuntime.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "feat-a",
      runtime_id: null,
      runtime_status: "stopped",
      container_provisioned: false,
      port_set: null,
    });
    mockApi.startBranchRun.mockResolvedValue({});

    const qc = makeQC();
    const { unmount } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1/console?branch=feat-a"]}>
          <ServerBranchContext.Provider
            value={{ branch: "feat-a", setBranch: vi.fn(), gitBacked: true }}
          >
            <Routes>
              <Route path="/servers/:serverId/console" element={<ServerDetailPage />} />
            </Routes>
          </ServerBranchContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const unprov = await screen.findByTestId("branch-container-unprovisioned-state");
    expect(unprov).toHaveTextContent(/No container created for branch .feat-a. yet/);
    await user.selectOptions(screen.getByTestId("branch-console-template-select"), "tpl-1");
    await user.click(screen.getByTestId("branch-console-create-start-btn"));
    await waitFor(() =>
      expect(mockApi.startBranchRun).toHaveBeenCalledWith("srv-1", "feat-a", {
        data_template_id: "tpl-1",
      }),
    );
    unmount();

    mockApi.getBranchRuntime.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "feat-a",
      runtime_id: "rt-1",
      runtime_status: "stopped",
      container_provisioned: true,
      port_set: { game_port: 25665, rcon_port: 25675, query_port: 25685, plugin_ports: {} },
    });
    mockApi.destroyBranchRun.mockResolvedValue({ destroyed: true });

    render(
      <QueryClientProvider client={makeQC()}>
        <MemoryRouter initialEntries={["/servers/srv-1/console?branch=feat-a"]}>
          <ServerBranchContext.Provider
            value={{ branch: "feat-a", setBranch: vi.fn(), gitBacked: true }}
          >
            <Routes>
              <Route path="/servers/:serverId/console" element={<ServerDetailPage />} />
            </Routes>
          </ServerBranchContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const destroyBtn = await screen.findByTestId("branch-console-destroy-btn");
    await user.click(destroyBtn);
    const dialog = await screen.findByRole("dialog");
    const confirmBtn = within(dialog).getByRole("button", { name: /^Destroy Container$/i });
    await user.click(confirmBtn);
    await waitFor(() => expect(mockApi.destroyBranchRun).toHaveBeenCalledWith("srv-1", "feat-a"));
  });

  it("PluginListPage protects main and surfaces uncommitted lockfile commit action on working branches", async () => {
    const user = userEvent.setup();
    const branchPlugins: PluginResponse[] = [
      {
        plugin_id: "bp-1",
        server_id: "srv-1",
        name: "Spark",
        version: "1.10.0",
        description: "Profiler",
        author: "lucko",
        status: "enabled",
        dependencies: [],
        installed_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        source: "modrinth",
        checksum: "abcdef1234567890",
        branch_name: "feat-a",
        is_committed: false,
      },
    ];
    mockApi.listPlugins.mockResolvedValue(branchPlugins);
    mockApi.createServerCommit.mockResolvedValue({ id: "commit-1" });

    const { unmount } = render(
      <QueryClientProvider client={makeQC()}>
        <MemoryRouter initialEntries={["/servers/srv-1/plugins"]}>
          <ServerBranchContext.Provider
            value={{ branch: "main", setBranch: vi.fn(), gitBacked: true }}
          >
            <Routes>
              <Route path="/servers/:serverId/plugins" element={<PluginListPage />} />
            </Routes>
          </ServerBranchContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("plugins-main-protected-banner")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Install Plugin/i })).toBeDisabled();
    unmount();

    render(
      <QueryClientProvider client={makeQC()}>
        <MemoryRouter initialEntries={["/servers/srv-1/plugins?branch=feat-a"]}>
          <ServerBranchContext.Provider
            value={{ branch: "feat-a", setBranch: vi.fn(), gitBacked: true }}
          >
            <Routes>
              <Route path="/servers/:serverId/plugins" element={<PluginListPage />} />
            </Routes>
          </ServerBranchContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("plugins-uncommitted-banner")).toBeInTheDocument();
    expect(screen.getByTestId("plugin-commit-badge-bp-1")).toHaveTextContent("Uncommitted");
    await user.click(screen.getByTestId("plugins-commit-btn"));
    await waitFor(() =>
      expect(mockApi.createServerCommit).toHaveBeenCalledWith("srv-1", {
        branch_name: "feat-a",
        message: "Update branch plugins lockfile",
      }),
    );
  });

  it("ServerSettingsPage splits branch vs server-wide sections and discards pending settings on main", async () => {
    const user = userEvent.setup();
    mockApi.getServer.mockResolvedValue({
      ...baseServer,
      pending_settings_branch: {
        branch_name: "settings/20261123",
        status: "pending",
        error_message: null,
      },
    });
    mockApi.discardPendingSettings.mockResolvedValue({ discarded: true });

    render(
      <QueryClientProvider client={makeQC()}>
        <MemoryRouter initialEntries={["/servers/srv-1/settings"]}>
          <ServerBranchContext.Provider
            value={{ branch: "main", setBranch: vi.fn(), gitBacked: true }}
          >
            <Routes>
              <Route path="/servers/:serverId/settings" element={<ServerSettingsPage />} />
            </Routes>
          </ServerBranchContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("pending-settings-banner")).toBeInTheDocument();
    expect(screen.getByTestId("branch-scoped-settings-section")).toBeInTheDocument();
    expect(screen.getByTestId("server-wide-settings-section")).toHaveTextContent(
      "Applies to the entire server (all branches)",
    );

    await user.click(screen.getByTestId("pending-settings-discard-btn"));
    await waitFor(() => expect(mockApi.discardPendingSettings).toHaveBeenCalledWith("srv-1"));
  });

  it("ServerExposurePage displays branch Host Port Set, CGNAT warning, and SRV helper", async () => {
    mockApi.getServerExposure.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "feat-a",
      branch_runtime_status: "running",
      allocated_game_port: 25665,
      allocated_port_set: { game_port: 25665, rcon_port: 25675, query_port: 25685 },
      method: "port_forward",
      desired_state: "ENABLED",
      aggregate_status: "ERROR",
      error_code: "CGNAT_DETECTED",
      error_message: "CGNAT IP 100.64.10.2 detected",
      upnp_status: "CGNAT_DETECTED",
      detected_wan_ip: "100.64.10.2",
      srv_record_enabled: true,
      srv_record_hint: "_minecraft._tcp.play.example.com. 300 IN SRV 0 5 25665 play.example.com.",
      cloudflare_tunnel_id: null,
      has_cloudflare_credentials: false,
      targets: [],
    });

    render(
      <QueryClientProvider client={makeQC()}>
        <MemoryRouter initialEntries={["/servers/srv-1/network?branch=feat-a"]}>
          <ServerBranchContext.Provider
            value={{ branch: "feat-a", setBranch: vi.fn(), gitBacked: true }}
          >
            <Routes>
              <Route path="/servers/:serverId/network" element={<ServerExposurePage />} />
            </Routes>
          </ServerBranchContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("exposure-branch-badge")).toHaveTextContent("Branch: feat-a");
    expect(screen.getByTestId("branch-exposure-port-set-banner")).toHaveTextContent("Game 25665");
    expect(screen.getByTestId("server-cgnat-detected-banner")).toHaveTextContent("100.64.10.2");
    expect(screen.getByTestId("server-srv-record-helper")).toHaveTextContent("_minecraft._tcp.play.example.com");
  });
});
