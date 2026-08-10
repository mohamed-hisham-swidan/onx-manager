import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerShell } from "./ServerShell";

// Mock WebSocket hooks used in ServerDetailPage
vi.mock("@/hooks/useWebSocket", () => ({
  subscribeChannels: vi.fn(),
  unsubscribeChannels: vi.fn(),
}));

// Mock ServerDetailPage dependencies if needed
const mockServer = {
  server_id: "srv-123",
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
  root_path: null,
  startup_jar: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServerDetail: vi.fn(() => ({
    data: mockServer,
    isLoading: false,
    error: null,
  })),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
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
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerShell", () => {
  it("renders top bar, contextual server sidebar, and active route content", () => {
    renderServerShell("/servers/srv-123/console");

    expect(screen.getByText("MC Server Manager")).toBeInTheDocument();
    expect(screen.getByText("Back to Servers")).toBeInTheDocument();
    expect(screen.getByText("Server Management")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Console" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Files" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mods" })).toBeInTheDocument();

    expect(screen.getByTestId("console-page")).toBeInTheDocument();
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

  it("navigates back to /servers when clicking back arrow link", async () => {
    const user = userEvent.setup();
    renderServerShell("/servers/srv-123/console");

    await user.click(screen.getByText("Back to Servers"));
    expect(screen.getByTestId("servers-page")).toBeInTheDocument();
  });
});
