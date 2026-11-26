import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerSettingsPage } from "./ServerSettingsPage";
import type { ServerDetailResponse } from "@/server_manager/types";

const mockDeleteMutate = vi.fn();
const mockUpdateMutateAsync = vi.fn();
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
  useUpdateServer: vi.fn(() => ({
    mutateAsync: mockUpdateMutateAsync,
    isPending: false,
  })),
  useDeleteServer: vi.fn(() => ({
    mutate: mockDeleteMutate,
    isPending: false,
  })),
}));

vi.mock("@/server_manager/components/ServerModeConversionCard", () => ({
  ServerModeConversionCard: () => <div data-testid="server-mode-conversion-card">Conversion Card</div>,
}));

vi.mock("@/server_manager/components/p55/ServerP55SettingsCard", () => ({
  ServerP55SettingsCard: () => <div data-testid="server-p55-settings-card">P55 Card</div>,
}));

function renderSettingsPage(serverId = "srv-settings-1") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
    mockUpdateMutateAsync.mockClear();
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

  it("renders General tab by default inside the 2-column settings shell", () => {
    renderSettingsPage();
    expect(screen.getByRole("heading", { name: "General" })).toBeInTheDocument();
    expect(screen.getByTestId("server-settings-form")).toBeInTheDocument();
  });

  it("renders Danger Zone tab with Delete Server button and opens confirmation modal", async () => {
    const user = userEvent.setup();
    renderSettingsPage();

    await user.click(document.getElementById("server-settings-tab-danger")!);
    const dangerZone = screen.getByTestId("server-danger-zone");
    expect(dangerZone).toBeInTheDocument();
    expect(dangerZone).toHaveTextContent("Delete Server");

    await user.click(screen.getByRole("button", { name: "Delete Server" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText('Delete "Production SMP"?')).toBeInTheDocument();
  });

  it("dismisses delete confirmation dialog on cancel", async () => {
    const user = userEvent.setup();
    renderSettingsPage();

    await user.click(document.getElementById("server-settings-tab-danger")!);
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

    await user.click(document.getElementById("server-settings-tab-danger")!);
    await user.click(screen.getByRole("button", { name: "Delete Server" }));
    const dialogConfirmBtn = screen.getAllByRole("button", { name: "Delete Server" })[1];
    await user.click(dialogConfirmBtn);

    expect(mockDeleteMutate).toHaveBeenCalledWith("srv-settings-1", expect.any(Object));
    expect(screen.getByTestId("servers-fleet")).toBeInTheDocument();
  });

  it("renders Upgrades & Mode tab with P55 settings and ServerModeConversionCard", async () => {
    const user = userEvent.setup();
    renderSettingsPage();

    await user.click(document.getElementById("server-settings-tab-lifecycle")!);
    expect(screen.getByTestId("server-version-loader-card")).toBeInTheDocument();
    expect(screen.getByTestId("open-change-version-btn")).toHaveTextContent("Change Version");
    expect(screen.getByTestId("server-p55-settings-card")).toBeInTheDocument();
    expect(screen.getByTestId("server-mode-conversion-card")).toBeInTheDocument();
  });

  it("opens Upgrades & Mode and the Change Version drawer from ?tab=lifecycle&action=change-version", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter
          initialEntries={["/servers/srv-settings-1/settings?tab=lifecycle&action=change-version"]}
        >
          <Routes>
            <Route path="/servers/:serverId/settings" element={<ServerSettingsPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("server-settings-tab-lifecycle")).toBeInTheDocument();
    expect(await screen.findByRole("complementary", { name: "Change Version" })).toBeInTheDocument();
  });
});
