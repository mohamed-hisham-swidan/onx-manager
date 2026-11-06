import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { ServerSettingsSection } from "./ServerSettingsSection";
import type { ServerDetailResponse } from "@/server_manager/types";

const mockMutateAsync = vi.fn().mockResolvedValue({});

vi.mock("@/server_manager/hooks/useServers", () => ({
  useUpdateServer: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

const baseMockServer: ServerDetailResponse = {
  server_id: "srv-settings-1",
  name: "My Survival World",
  server_type: "vanilla",
  minecraft_version: "1.21",
  status: "stopped",
  group_id: "default",
  port: 25565,
  motd: "A Great Minecraft Server",
  max_players: 20,
  gamemode: "survival",
  difficulty: "easy",
  min_memory_mb: 1024,
  max_memory_mb: 2048,
  cpu_cores: 2,
  cpu_affinity: "0-1",
  java_args: "-XX:+UseG1GC",
  spawn_protection: 16,
  pvp: true,
  enable_command_block: false,
  online_mode: true,
  whitelist: false,
  view_distance: 10,
  simulation_distance: 10,
  raw_properties: {
    "level-seed": "123456789",
    "generator-settings": "{}",
  },
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
  created_at: "2026-09-04T00:00:00Z",
  updated_at: "2026-09-04T00:00:00Z",
};

function renderSettings(server: ServerDetailResponse = baseMockServer) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ServerSettingsSection serverId={server.server_id} server={server} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ServerSettingsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all four cards", () => {
    renderSettings();

    expect(screen.getByText("General & Identity")).toBeInTheDocument();
    expect(screen.getByText("Resource Allocation (RAM & CPU)")).toBeInTheDocument();
    expect(screen.getByText("Gameplay & World Properties")).toBeInTheDocument();
    expect(screen.getByText("Advanced Configuration")).toBeInTheDocument();
  });

  it("displays running state advisory banner when status is running", () => {
    renderSettings({ ...baseMockServer, status: "running" });

    expect(screen.getByText("Server is Currently Running")).toBeInTheDocument();
    expect(
      screen.getByText(/require a server restart to be applied to the active process/i)
    ).toBeInTheDocument();
  });

  it("does not display running advisory banner when status is stopped", () => {
    renderSettings({ ...baseMockServer, status: "stopped" });

    expect(screen.queryByText("Server is Currently Running:")).not.toBeInTheDocument();
  });

  it("reflects server properties in boolean switches", () => {
    renderSettings();

    const pvpSwitch = screen.getByRole("switch", { name: "PvP" });
    const onlineModeSwitch = screen.getByRole("switch", { name: "Online Mode" });
    const whitelistSwitch = screen.getByRole("switch", { name: "Whitelist" });
    const commandBlockSwitch = screen.getByRole("switch", { name: "Command Blocks" });

    expect(pvpSwitch).toBeChecked();
    expect(onlineModeSwitch).toBeChecked();
    expect(whitelistSwitch).not.toBeChecked();
    expect(commandBlockSwitch).not.toBeChecked();
  });

  it("provides direct link to edit server.properties in File Manager without raw text lines in GUI", () => {
    renderSettings();

    expect(screen.queryByLabelText("Raw Properties")).not.toBeInTheDocument();

    const link = screen.getByRole("link", { name: /open server\.properties in file manager/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/servers/srv-settings-1/files?file=server.properties");
  });

  it("submits update payload on save button click", async () => {
    renderSettings();

    const nameInput = screen.getByLabelText("Server Name");
    fireEvent.change(nameInput, { target: { value: "Renamed Server" } });

    const saveButton = screen.getByRole("button", { name: /save changes/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledTimes(1);
    });

    const callArgs = mockMutateAsync.mock.calls[0][0];
    expect(callArgs.serverId).toBe("srv-settings-1");
    expect(callArgs.body.name).toBe("Renamed Server");
    expect(callArgs.body.cpu_cores).toBe(2);
    expect(callArgs.body.cpu_affinity).toBe("0-1");
    expect(callArgs.body.properties["level-seed"]).toBe("123456789");
    expect(callArgs.body.properties["server-port"]).toBe(25565);
  });

  it("disables save button and displays error when JVM flags contain prohibited characters", () => {
    renderSettings();

    const jvmInput = screen.getByPlaceholderText(/-XX:\+UseG1GC/i);
    fireEvent.change(jvmInput, { target: { value: "-Xmx1G;calc" } });

    expect(
      screen.getByText(/all flags must start with '-' and cannot contain prohibited shell characters/i)
    ).toBeInTheDocument();

    const saveButton = screen.getByRole("button", { name: /save changes/i });
    expect(saveButton).toBeDisabled();
  });

  it("filters sections by category tabs", () => {
    renderSettings();

    // Verify all 4 are present initially
    expect(screen.getByText("General & Identity")).toBeInTheDocument();
    expect(screen.getByText("Resource Allocation (RAM & CPU)")).toBeInTheDocument();
    expect(screen.getByText("Gameplay & World Properties")).toBeInTheDocument();
    expect(screen.getByText("Advanced Configuration")).toBeInTheDocument();

    // Click Resources & JVM
    fireEvent.click(screen.getByRole("tab", { name: /resources & jvm/i }));
    expect(screen.getByText("Resource Allocation (RAM & CPU)")).toBeInTheDocument();
    expect(screen.queryByText("General & Identity")).not.toBeInTheDocument();
    expect(screen.queryByText("Gameplay & World Properties")).not.toBeInTheDocument();
    expect(screen.queryByText("Advanced Configuration")).not.toBeInTheDocument();

    // Click All Settings
    fireEvent.click(screen.getByRole("tab", { name: /all settings/i }));
    expect(screen.getByText("General & Identity")).toBeInTheDocument();
    expect(screen.getByText("Resource Allocation (RAM & CPU)")).toBeInTheDocument();
    expect(screen.getByText("Gameplay & World Properties")).toBeInTheDocument();
    expect(screen.getByText("Advanced Configuration")).toBeInTheDocument();

    // Click Rules & Security (shows switches)
    fireEvent.click(screen.getByRole("tab", { name: /rules & security/i }));
    expect(screen.getByRole("switch", { name: "PvP" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Online Mode" })).toBeInTheDocument();
    expect(screen.queryByText("General & Identity")).not.toBeInTheDocument();
    expect(screen.queryByText("Resource Allocation (RAM & CPU)")).not.toBeInTheDocument();
  });

  it("filters settings using quick search bar", () => {
    renderSettings();

    const searchInput = screen.getByPlaceholderText(/search server settings/i);

    // Search for "whitelist"
    fireEvent.change(searchInput, { target: { value: "whitelist" } });
    expect(screen.getByRole("switch", { name: "Whitelist" })).toBeInTheDocument();
    expect(screen.queryByText("General & Identity")).not.toBeInTheDocument();
    expect(screen.queryByText("Resource Allocation (RAM & CPU)")).not.toBeInTheDocument();

    // Search for non-existent keyword
    fireEvent.change(searchInput, { target: { value: "nonexistentkeywordxyz" } });
    expect(screen.getByText("No settings found")).toBeInTheDocument();

    // Clear search
    fireEvent.click(screen.getByRole("button", { name: "Clear Search" }));
    expect(screen.getByText("General & Identity")).toBeInTheDocument();
    expect(screen.getByText("Resource Allocation (RAM & CPU)")).toBeInTheDocument();
  });

  it("tracks unsaved changes and reverts them via Reset to Saved button", () => {
    renderSettings();

    const resetButton = screen.getByRole("button", { name: /reset to saved/i });
    expect(resetButton).toBeDisabled();
    expect(screen.queryByText("Unsaved Changes")).not.toBeInTheDocument();

    const nameInput = screen.getByLabelText("Server Name") as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "Modified World Name" } });

    expect(nameInput.value).toBe("Modified World Name");
    expect(screen.getByText("Unsaved Changes")).toBeInTheDocument();
    expect(resetButton).not.toBeDisabled();

    // Click reset
    fireEvent.click(resetButton);

    expect(nameInput.value).toBe("My Survival World");
    expect(screen.queryByText("Unsaved Changes")).not.toBeInTheDocument();
    expect(resetButton).toBeDisabled();
  });

  it("updates RAM allocation and visual ratio bar when presets are clicked", () => {
    renderSettings();

    const minRamInput = screen.getByLabelText("Minimum Memory (MB)") as HTMLInputElement;
    const maxRamInput = screen.getByLabelText("Maximum Memory (MB)") as HTMLInputElement;

    // Initially 1024 / 2048
    expect(minRamInput.value).toBe("1024");
    expect(maxRamInput.value).toBe("2048");
    expect(screen.getByText("50% Heap Ratio")).toBeInTheDocument();

    // Click 4 GB preset (2048 / 4096)
    fireEvent.click(screen.getByRole("button", { name: "4 GB" }));
    expect(minRamInput.value).toBe("2048");
    expect(maxRamInput.value).toBe("4096");
    expect(screen.getByText("50% Heap Ratio")).toBeInTheDocument();

    // Click 1 GB preset (512 / 1024)
    fireEvent.click(screen.getByRole("button", { name: "1 GB" }));
    expect(minRamInput.value).toBe("512");
    expect(maxRamInput.value).toBe("1024");
  });
});
