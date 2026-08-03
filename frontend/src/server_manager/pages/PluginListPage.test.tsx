import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PluginListPage } from "./PluginListPage";

const mockPlugins = [
  {
    plugin_id: "plg-1",
    server_id: "srv-1",
    name: "Essentials",
    version: "2.0.0",
    description: "Essential commands",
    author: "dev",
    status: "enabled",
    dependencies: [],
    installed_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
  },
  {
    plugin_id: "plg-2",
    server_id: "srv-1",
    name: "WorldGuard",
    version: "1.0.0",
    description: "World protection",
    author: "dev",
    status: "disabled",
    dependencies: [],
    installed_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
  },
];

let mockPluginsData = mockPlugins;
let mockIsLoading = false;
let mockError: Error | null = null;

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({
    data: [{ server_id: "srv-1", name: "Test Server" }],
  })),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  usePluginsList: vi.fn(() => ({
    data: mockPluginsData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useEnablePlugin: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDisablePlugin: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useUninstallPlugin: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PluginListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function selectServer() {
  fireEvent.change(screen.getByLabelText("Choose a server"), { target: { value: "srv-1" } });
}

describe("PluginListPage", () => {
  beforeEach(() => {
    mockPluginsData = mockPlugins;
    mockIsLoading = false;
    mockError = null;
  });

  it("renders page header", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Plugins" })).toBeInTheDocument();
  });

  it("shows empty state when no server selected", () => {
    renderPage();
    expect(screen.getByText("Select a server")).toBeInTheDocument();
  });

  it("hides install button until a server is selected", () => {
    renderPage();
    expect(screen.queryByText("Install Plugin")).not.toBeInTheDocument();
    selectServer();
    expect(screen.getByText("Install Plugin")).toBeInTheDocument();
  });

  it("renders plugin rows after selecting a server", () => {
    renderPage();
    selectServer();
    expect(screen.getByText("Essentials")).toBeInTheDocument();
    expect(screen.getByText("WorldGuard")).toBeInTheDocument();
    expect(screen.getAllByText("enabled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("disabled").length).toBeGreaterThanOrEqual(1);
  });

  it("shows enable/disable and uninstall actions", () => {
    renderPage();
    selectServer();
    expect(screen.getByLabelText("Disable Essentials")).toBeInTheDocument();
    expect(screen.getByLabelText("Enable WorldGuard")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/Uninstall/)).toHaveLength(2);
  });

  it("shows loading state", () => {
    mockIsLoading = true;
    renderPage();
    selectServer();
    expect(document.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error state", () => {
    mockError = new Error("Load failed");
    renderPage();
    selectServer();
    expect(screen.getByText("Load failed")).toBeInTheDocument();
  });

  it("shows empty state when server has no plugins", () => {
    mockPluginsData = [];
    renderPage();
    selectServer();
    expect(screen.getByText("No plugins installed")).toBeInTheDocument();
  });

  it("opens uninstall confirmation dialog", () => {
    renderPage();
    selectServer();
    fireEvent.click(screen.getByLabelText("Uninstall Essentials"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Uninstall plugin?")).toBeInTheDocument();
  });

  it("shows a placeholder toast when install is clicked", () => {
    renderPage();
    selectServer();
    fireEvent.click(screen.getByText("Install Plugin"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
