import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/services/api";
import { ServerDetailPage } from "./ServerDetailPage";

function NavigateButton({ to, label }: { to: string; label: string }) {
  const navigate = useNavigate();
  return <button onClick={() => navigate(to)}>{label}</button>;
}

const { subscribeChannelsMock, unsubscribeChannelsMock } = vi.hoisted(() => ({
  subscribeChannelsMock: vi.fn(),
  unsubscribeChannelsMock: vi.fn(),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  subscribeChannels: subscribeChannelsMock,
  unsubscribeChannels: unsubscribeChannelsMock,
}));

const mockServer = {
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
  root_path: null,
  startup_jar: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

let mockData: typeof mockServer | null = mockServer;
let mockIsLoading = false;
let mockError: Error | null = null;

let mockRuntimeData: any = null;
let mockMetricsData: any = null;

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
}));

vi.mock("@/server_manager/hooks/useServerMetrics", () => ({
  useServerMetrics: vi.fn(() => ({
    data: mockMetricsData,
  })),
}));

vi.mock("@/server_manager/components/ServerConfigEditor", () => ({
  ServerConfigEditor: () => <div data-testid="config-editor">ConfigEditor</div>,
}));

vi.mock("@/server_manager/components/ServerConsole", () => ({
  ServerConsole: () => <div data-testid="server-console">Console</div>,
}));

vi.mock("@/server_manager/components/Sparkline", () => ({
  Sparkline: () => <div data-testid="sparkline">Sparkline</div>,
}));

vi.mock("@/hooks/useClipboard", () => ({
  useClipboard: () => ({ copy: vi.fn() }),
}));

function renderPage(serverId = "srv-1") {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/servers/${serverId}`]}>
        <Routes>
          <Route path="/servers/:serverId" element={<ServerDetailPage />} />
          <Route path="/servers" element={<div data-testid="servers-list">Servers</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerDetailPage", () => {
  beforeEach(() => {
    mockData = mockServer;
    mockIsLoading = false;
    mockError = null;
    mockRuntimeData = null;
    mockMetricsData = null;
    subscribeChannelsMock.mockClear();
    unsubscribeChannelsMock.mockClear();
  });

  it("shows loading skeletons", () => {
    mockIsLoading = true;
    const { container } = renderPage();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows server name and status in header", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Test Server" })).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
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

  it("shows all info fields correctly in the collapsible section", async () => {
    const user = userEvent.setup();
    renderPage();
    const expandBtn = screen.getByText("Server Info & Configuration");
    await user.click(expandBtn);
    expect(screen.getByText("1.20.4")).toBeInTheDocument();
    expect(screen.getByText("25565")).toBeInTheDocument();
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Network")).toBeInTheDocument();
    expect(screen.getByText("Zone ID")).toBeInTheDocument();
  });

  it("renders a cleaned MOTD", async () => {
    const user = userEvent.setup();
    mockData = { ...mockServer, motd: "\u00a7bWelcome\u00a7r &6to &ethe server" };
    renderPage();
    await user.click(screen.getByText("Server Info & Configuration"));
    expect(screen.getByText("Welcome to the server")).toBeInTheDocument();
  });

  it("shows a placeholder MOTD when empty", async () => {
    const user = userEvent.setup();
    mockData = { ...mockServer, motd: "" };
    renderPage();
    await user.click(screen.getByText("Server Info & Configuration"));
    const motdRow = screen.getByText("MOTD").parentElement!;
    expect(motdRow.querySelector("dd")!.textContent).toBe("—");
  });

  it("shows Start button when stopped", () => {
    mockData = { ...mockServer, status: "stopped" };
    renderPage();
    expect(screen.getByText("Start")).toBeInTheDocument();
  });

  it("shows Stop and Restart buttons when running", () => {
    renderPage();
    expect(screen.getByText("Stop")).toBeInTheDocument();
    expect(screen.getByText("Restart")).toBeInTheDocument();
  });

  it("opens delete confirmation dialog", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("Delete"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Delete server?")).toBeInTheDocument();
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
});
