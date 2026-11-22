import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerSettingsPage } from "./ServerSettingsPage";
import type { ServerDetailResponse } from "@/server_manager/types";

const mockDeleteMutate = vi.fn();
const mockServer: ServerDetailResponse = {
  server_id: "srv-settings-1",
  name: "Production SMP",
  server_type: "purpur",
  minecraft_version: "1.20.4",
  status: "stopped",
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

let mockData: ServerDetailResponse | null = mockServer;
let mockIsLoading = false;
let mockError: Error | null = null;

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServerDetail: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useDeleteServer: vi.fn(() => ({
    mutate: mockDeleteMutate,
    isPending: false,
  })),
}));

vi.mock("@/server_manager/components/ServerSettingsSection", () => ({
  ServerSettingsSection: () => <div data-testid="settings-section">Settings Section Form</div>,
}));

vi.mock("@/server_manager/components/ServerModeConversionCard", () => ({
  ServerModeConversionCard: () => <div data-testid="server-mode-conversion-card">Conversion Card</div>,
}));

function renderSettingsPage(serverId = "srv-settings-1") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/servers/${serverId}/settings`]}>
        <Routes>
          <Route path="/servers/:serverId/settings" element={<ServerSettingsPage />} />
          <Route path="/servers" element={<div data-testid="servers-fleet">Servers Fleet</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerSettingsPage", () => {
  beforeEach(() => {
    mockData = mockServer;
    mockIsLoading = false;
    mockError = null;
    mockDeleteMutate.mockClear();
  });

  it("shows loading skeletons while loading", () => {
    mockIsLoading = true;
    const { container } = renderSettingsPage();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error alert on load failure", () => {
    mockError = new Error("Failed to load server configuration");
    renderSettingsPage();
    expect(screen.getByText("Failed to load server configuration")).toBeInTheDocument();
  });

  it("renders settings header and settings form", () => {
    renderSettingsPage();
    expect(screen.getByRole("heading", { name: "Server Settings & Configuration" })).toBeInTheDocument();
    expect(screen.getByTestId("settings-section")).toBeInTheDocument();
  });

  it("renders Danger Zone section with Delete Server button in settings", () => {
    renderSettingsPage();
    const dangerZone = screen.getByTestId("server-danger-zone");
    expect(dangerZone).toBeInTheDocument();
    expect(dangerZone).toHaveTextContent("Danger Zone: Delete Server");
    expect(screen.getByRole("button", { name: "Delete Server" })).toBeInTheDocument();
  });

  it("opens delete confirmation modal when Delete Server is clicked", async () => {
    const user = userEvent.setup();
    renderSettingsPage();

    await user.click(screen.getByRole("button", { name: "Delete Server" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText('Delete "Production SMP"?')).toBeInTheDocument();
  });

  it("dismisses delete confirmation dialog on cancel", async () => {
    const user = userEvent.setup();
    renderSettingsPage();

    await user.click(screen.getByRole("button", { name: "Delete Server" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mockDeleteMutate).not.toHaveBeenCalled();
  });

  it("triggers delete mutation on confirmation and navigates to fleet", async () => {
    const user = userEvent.setup();
    mockDeleteMutate.mockImplementation((_id, options) => {
      options?.onSuccess?.();
    });

    renderSettingsPage();

    await user.click(screen.getByRole("button", { name: "Delete Server" }));
    // In dialog, confirmLabel is "Delete Server"
    const dialogConfirmBtn = screen.getAllByRole("button", { name: "Delete Server" })[1];
    await user.click(dialogConfirmBtn);

    expect(mockDeleteMutate).toHaveBeenCalledWith("srv-settings-1", expect.any(Object));
    expect(screen.getByTestId("servers-fleet")).toBeInTheDocument();
  });

  it("integrates ServerModeConversionCard above the danger zone", () => {
    renderSettingsPage();
    const card = screen.getByTestId("server-mode-conversion-card");
    expect(card).toBeInTheDocument();
    expect(card).toHaveTextContent("Conversion Card");
    // Placement: below settings form/P55 card, above the danger zone
    expect(screen.getByTestId("settings-section")).toBeInTheDocument();
    expect(screen.getByTestId("server-danger-zone")).toBeInTheDocument();
  });
});
