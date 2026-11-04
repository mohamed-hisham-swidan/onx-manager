import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerShell } from "./ServerShell";
import { useServerDetail } from "@/server_manager/hooks/useServers";

// Mock WebSocket hooks used in ServerDetailPage
vi.mock("@/hooks/useWebSocket", () => ({
  subscribeChannels: vi.fn(),
  unsubscribeChannels: vi.fn(),
}));

// Mock ServerDetailPage dependencies if needed
const mockServer = {
  server_id: "srv-123",
  name: "Test Server",
  server_type: "fabric",
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
  root_path: null,
  startup_jar: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

const mockStopMutate = vi.fn();

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServerDetail: vi.fn(() => ({
    data: mockServer,
    isLoading: false,
    error: null,
  })),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: mockStopMutate, isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDeleteServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

vi.mock("@/server_manager/components/ServerConfigEditor", () => ({
  ServerConfigEditor: () => <div data-testid="config-editor">ConfigEditor</div>,
}));

vi.mock("@/server_manager/components/ServerConsole", () => ({
  ServerConsole: () => <div data-testid="server-console">Console</div>,
}));

vi.mock("@/server_manager/components/ServerMetricsCharts", () => ({
  ServerMetricsCharts: () => <div data-testid="metrics-charts">Metrics</div>,
}));

function renderServerShell(initialPath = "/servers/srv-123/console") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/servers" element={<div data-testid="servers-page">Servers List</div>} />
          <Route path="/servers/:serverId" element={<ServerShell />}>
            <Route path="console" element={<div data-testid="console-page">Console Content</div>} />
            <Route path="files" element={<div data-testid="files-page">Files Content</div>} />
            <Route path="mods" element={<div data-testid="mods-page">Mods Content</div>} />
            <Route path="plugins" element={<div data-testid="plugins-page">Plugins Content</div>} />
            <Route path="settings" element={<div data-testid="settings-page">Settings Content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerShell", () => {
  beforeEach(() => {
    mockStopMutate.mockClear();
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, server_type: "fabric" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);
  });

  it("renders top bar, contextual server sidebar with Mods for fabric server", () => {
    renderServerShell("/servers/srv-123/console");

    expect(screen.getByText("onx-manager")).toBeInTheDocument();
    expect(screen.getByText("Back to Servers")).toBeInTheDocument();
    expect(screen.getByText("Server Management")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Console" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Files" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mods" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Plugins" })).not.toBeInTheDocument();

    expect(screen.getByTestId("console-page")).toBeInTheDocument();
  });

  it("renders Plugins link (and not Mods) for paper server", () => {
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, server_type: "paper" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    expect(screen.getByRole("link", { name: "Plugins" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Mods" })).not.toBeInTheDocument();
  });

  it("renders both Mods and Plugins links for hybrid (mohist) server", () => {
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, server_type: "mohist" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    expect(screen.getByRole("link", { name: "Mods" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plugins" })).toBeInTheDocument();
  });

  it("renders neither Mods nor Plugins for vanilla server", () => {
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, server_type: "vanilla" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    expect(screen.queryByRole("link", { name: "Mods" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Plugins" })).not.toBeInTheDocument();
  });

  it("defaults to rendering both Mods and Plugins for unknown server type", () => {
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, server_type: "custom_loader" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    expect(screen.getByRole("link", { name: "Mods" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Plugins" })).toBeInTheDocument();
  });

  it("navigates to Files when clicking Files link", async () => {
    const user = userEvent.setup();
    renderServerShell("/servers/srv-123/console");

    await user.click(screen.getByRole("link", { name: "Files" }));
    expect(screen.getByTestId("files-page")).toBeInTheDocument();
  });

  it("navigates to Mods when clicking Mods link", async () => {
    const user = userEvent.setup();
    renderServerShell("/servers/srv-123/console");

    await user.click(screen.getByRole("link", { name: "Mods" }));
    expect(screen.getByTestId("mods-page")).toBeInTheDocument();
  });

  it("navigates to Settings when clicking Settings link", async () => {
    const user = userEvent.setup();
    renderServerShell("/servers/srv-123/console");

    await user.click(screen.getByRole("link", { name: "Settings" }));
    expect(screen.getByTestId("settings-page")).toBeInTheDocument();
  });

  it("navigates back to /servers when clicking back arrow link", async () => {
    const user = userEvent.setup();
    renderServerShell("/servers/srv-123/console");

    await user.click(screen.getByText("Back to Servers"));
    expect(screen.getByTestId("servers-page")).toBeInTheDocument();
  });

  it("renders consistent breadcrumb navigation across server sections", async () => {
    const user = userEvent.setup();
    renderServerShell("/servers/srv-123/console");

    // Breadcrumb on Console
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(breadcrumb).toBeInTheDocument();
    expect(breadcrumb).toHaveTextContent("Test Server");
    expect(breadcrumb).toHaveTextContent("Console");

    // Navigate to Files and verify breadcrumb updates to Files
    await user.click(screen.getByRole("link", { name: "Files" }));
    expect(breadcrumb).toHaveTextContent("Files");

    // Navigate to Settings and verify breadcrumb updates to Settings
    await user.click(screen.getByRole("link", { name: "Settings" }));
    expect(breadcrumb).toHaveTextContent("Settings");
  });

  it("renders nested breadcrumb navigation for files path and subdirectories", () => {
    renderServerShell("/servers/srv-123/files?path=mods/worldedit");
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(breadcrumb).toBeInTheDocument();
    expect(breadcrumb).toHaveTextContent("Test Server");
    expect(breadcrumb).toHaveTextContent("Files");
    expect(breadcrumb).toHaveTextContent("mods");
    expect(breadcrumb).toHaveTextContent("worldedit");
  });

  it("renders nested breadcrumb navigation when editing a file in a subdirectory", () => {
    renderServerShell("/servers/srv-123/files?file=mods/worldedit/config.yml");
    const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(breadcrumb).toBeInTheDocument();
    expect(breadcrumb).toHaveTextContent("Test Server");
    expect(breadcrumb).toHaveTextContent("Files");
    expect(breadcrumb).toHaveTextContent("mods");
    expect(breadcrumb).toHaveTextContent("worldedit");
    expect(breadcrumb).toHaveTextContent("config.yml");

    const modsLink = screen.getByRole("link", { name: "mods" });
    expect(modsLink).toHaveAttribute("href", "/servers/srv-123/files?path=mods");
  });

  it("renders Server Identity Strip with name heading, status, and provider badge", () => {
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, provider: "docker" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    expect(screen.getByRole("heading", { name: "Test Server" })).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
    const badge = screen.getByTestId("server-provider-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Container");
  });

  it("renders File / Host provider badge when provider is local_process", () => {
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, provider: "local_process" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    const badge = screen.getByTestId("server-provider-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("File / Host");
  });

  it("shows Start button when server is stopped", () => {
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, status: "stopped" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    expect(screen.getByRole("button", { name: "Start" })).toBeInTheDocument();
  });

  it("shows Stop and Restart buttons when server is running and calls stop mutation on confirm", async () => {
    const user = userEvent.setup();
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, status: "running" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    expect(screen.getByRole("button", { name: "Restart" })).toBeInTheDocument();
    const stopBtn = screen.getByRole("button", { name: "Stop" });
    expect(stopBtn).toBeInTheDocument();

    await user.click(stopBtn);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Stop Test Server?")).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: "Stop Server" });
    await user.click(confirmBtn);
    expect(mockStopMutate).toHaveBeenCalledWith("srv-123");
  });

  it("shows Stop button while status is STARTING", () => {
    vi.mocked(useServerDetail).mockReturnValue({
      data: { ...mockServer, status: "starting" },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServerDetail>);

    renderServerShell("/servers/srv-123/console");

    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restart" })).not.toBeInTheDocument();
  });
});
