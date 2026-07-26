import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

vi.mock("@/server_manager/components/InstallPluginDialog", () => ({
  InstallPluginDialog: vi.fn(() => <div data-testid="install-plugin-dialog">InstallPlugin</div>),
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

describe("PluginListPage", () => {
  beforeEach(() => {
    mockPluginsData = mockPlugins;
    mockIsLoading = false;
    mockError = null;
  });

  it("renders title", () => {
    renderPage();
    expect(screen.getByText("Plugins")).toBeInTheDocument();
  });

  it("shows empty state when no server selected", () => {
    renderPage();
    expect(screen.getByText("Select a server")).toBeInTheDocument();
  });
});
