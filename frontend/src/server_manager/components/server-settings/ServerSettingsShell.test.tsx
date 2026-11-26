import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerSettingsPage } from "@/server_manager/pages/ServerSettingsPage";
import { ServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import type { ServerDetailResponse } from "@/server_manager/types";

const { mockApi, mockToast, mockPerms, mockUpdateMutateAsync, mockUseServerDetail } = vi.hoisted(() => ({
  mockApi: {
    getMe: vi.fn(),
    getServer: vi.fn(),
    getServerBranches: vi.fn(),
    getBranchRuntime: vi.fn(),
    getServerP55Settings: vi.fn(),
    updateServerP55Settings: vi.fn(),
    uploadServerFile: vi.fn(),
    restartServer: vi.fn(),
    discardPendingSettings: vi.fn(),
  },
  mockToast: vi.fn(),
  mockUpdateMutateAsync: vi.fn(),
  mockUseServerDetail: vi.fn(),
  mockPerms: {
    canCreate: true,
    canImport: true,
    canDelete: true,
    canManageVersioning: true,
    canPower: vi.fn(() => true),
    canConsole: vi.fn(() => true),
    canWrite: vi.fn(() => true),
    canFiles: vi.fn(() => true),
    canManagePlugins: vi.fn(() => true),
    canViewExposure: vi.fn(() => true),
  },
}));

vi.mock("@/services/api", () => ({
  ApiError: class extends Error {
    status: number;
    code?: string;
    constructor(status: number, message: string, code?: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
  createAuthenticatedApi: () => mockApi,
}));

vi.mock("@/stores/toastStore", () => ({
  toast: mockToast,
}));

vi.mock("@/server_manager/components/servers/serversUtils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/server_manager/components/servers/serversUtils")>();
  return {
    ...actual,
    useFleetPermissions: () => mockPerms,
  };
});

vi.mock("@/server_manager/hooks/useHostResources", () => ({
  useHostResources: () => ({
    data: {
      total_ram_mb: 16384,
      os_reserve_ram_mb: 2048,
      allocatable_ram_mb: 14336,
      allocated_ram_mb: 2048,
      available_ram_mb: 12288,
      total_cpus: 8,
      reserved_cpus: 2,
      allocatable_cpus: 6,
      allocated_cpus: 2,
      available_cpus: 4,
      profile: "local",
      allocations: [],
    },
  }),
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServerDetail: (...args: unknown[]) => mockUseServerDetail(...args),
  useUpdateServer: () => ({
    mutateAsync: mockUpdateMutateAsync,
    isPending: false,
  }),
  useDeleteServer: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}));

const baseServer: ServerDetailResponse = {
  server_id: "srv-1",
  name: "Studio SMP",
  server_type: "paper",
  minecraft_version: "1.21.4",
  status: "stopped",
  mode: "simple",
  group_id: "default",
  port: 25565,
  motd: "Welcome to Studio",
  max_players: 20,
  gamemode: "survival",
  difficulty: "normal",
  min_memory_mb: 1024,
  max_memory_mb: 2048,
  cpu_cores: 2,
  cpu_affinity: "",
  java_args: "",
  startup_timeout_seconds: 120,
  spawn_protection: 16,
  pvp: true,
  enable_command_block: false,
  online_mode: true,
  whitelist: false,
  view_distance: 10,
  simulation_distance: 10,
  raw_properties: {
    "allow-flight": "false",
    "spawn-monsters": "true",
    "spawn-animals": "true",
    "spawn-npcs": "true",
    "allow-nether": "true",
    hardcore: "false",
    "force-gamemode": "false",
    "enforce-secure-profile": "false",
    "generate-structures": "true",
    "sync-chunk-writes": "true",
    "rcon.port": "25575",
    "enable-rcon": "true",
  },
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
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderPage(options?: {
  server?: ServerDetailResponse;
  branchCtx?: { branch: string; setBranch: (b: string) => void; gitBacked: boolean } | null;
}) {
  const srv = options?.server ?? baseServer;
  mockUseServerDetail.mockReturnValue({
    data: srv,
    isLoading: false,
    error: null,
  });
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const inner = (
    <Routes>
      <Route path="/servers/:serverId/settings" element={<ServerSettingsPage />} />
    </Routes>
  );
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/servers/${srv.server_id}/settings`]}>
        {options?.branchCtx ? (
          <ServerBranchContext.Provider value={options.branchCtx}>
            {inner}
          </ServerBranchContext.Provider>
        ) : (
          inner
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerSettingsPage Overhaul & ServerSettingsShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPerms.canWrite.mockReturnValue(true);
    mockPerms.canPower.mockReturnValue(true);
    mockPerms.canDelete = true;
    mockPerms.canManageVersioning = true;
    mockUpdateMutateAsync.mockResolvedValue({});
    mockApi.getServerBranches.mockResolvedValue([]);
    mockApi.getBranchRuntime.mockResolvedValue(null);
    mockApi.getServerP55Settings.mockResolvedValue({
      health_gate_boot_timeout_seconds: 300,
      install_optional_server_files: true,
      allow_experimental_paper_builds: false,
      download_host_allowlist: [],
      default_allowed_hosts: ["cdn.modrinth.com"],
    });
  });

  it("navigates across all 6 tabs via click and ArrowDown/ArrowUp keyboard navigation", async () => {
    renderPage();

    expect(screen.getByTestId("server-settings-tab-general")).toBeInTheDocument();
    expect(screen.queryByTestId("sticky-server-save-bar")).not.toBeInTheDocument();

    const generalTab = document.getElementById("server-settings-tab-general")!;
    fireEvent.keyDown(generalTab, { key: "ArrowDown" });
    expect(screen.getByTestId("server-settings-tab-resources")).toBeInTheDocument();

    const resourcesTab = document.getElementById("server-settings-tab-resources")!;
    fireEvent.keyDown(resourcesTab, { key: "ArrowDown" });
    expect(screen.getByTestId("server-settings-tab-gameplay")).toBeInTheDocument();

    fireEvent.click(document.getElementById("server-settings-tab-rules")!);
    expect(screen.getByTestId("server-settings-tab-rules")).toBeInTheDocument();

    fireEvent.click(document.getElementById("server-settings-tab-lifecycle")!);
    expect(await screen.findByTestId("server-p55-settings-card")).toBeInTheDocument();
    expect(screen.getByTestId("server-mode-conversion-card")).toBeInTheDocument();

    fireEvent.click(document.getElementById("server-settings-tab-danger")!);
    expect(screen.getByTestId("server-danger-zone")).toBeInTheDocument();

    const dangerTab = document.getElementById("server-settings-tab-danger")!;
    fireEvent.keyDown(dangerTab, { key: "ArrowUp" });
    expect(screen.getByTestId("server-settings-tab-lifecycle")).toBeInTheDocument();
  });

  it("strictly separates Gameplay & World (6 controls) from Rules & Security (14 switches)", () => {
    renderPage();

    fireEvent.click(document.getElementById("server-settings-tab-gameplay")!);
    const gameplayTab = screen.getByTestId("server-settings-tab-gameplay");
    expect(within(gameplayTab).getByRole("radiogroup", { name: "Default Gamemode" })).toBeInTheDocument();
    expect(within(gameplayTab).getByRole("radiogroup", { name: "Difficulty" })).toBeInTheDocument();
    expect(within(gameplayTab).getByLabelText("Max Players")).toBeInTheDocument();
    expect(within(gameplayTab).getByLabelText("View Distance")).toBeInTheDocument();
    expect(within(gameplayTab).getByLabelText("Simulation Distance")).toBeInTheDocument();
    expect(within(gameplayTab).getByLabelText("Spawn Protection")).toBeInTheDocument();
    // Spawn protection slider and stepper both capped at 256
    expect(within(gameplayTab).getByLabelText("Spawn Protection slider")).toHaveAttribute("max", "256");
    expect(within(gameplayTab).getByLabelText("Spawn Protection")).toHaveAttribute("max", "256");
    // Zero rules switches in Gameplay & World
    expect(within(gameplayTab).queryAllByRole("switch")).toHaveLength(0);

    fireEvent.click(document.getElementById("server-settings-tab-rules")!);
    const rulesTab = screen.getByTestId("server-settings-tab-rules");
    expect(within(rulesTab).getAllByRole("switch")).toHaveLength(14);
    expect(within(rulesTab).queryByText("ENABLED")).not.toBeInTheDocument();
    expect(within(rulesTab).queryByText("DISABLED")).not.toBeInTheDocument();
  });

  it("performs true row-level cross-section search (pvp -> only PvP; timeout -> both timeouts)", () => {
    renderPage();

    const searchInputs = screen.getAllByPlaceholderText("Search settings...");
    fireEvent.change(searchInputs[0], { target: { value: "pvp" } });

    const results = screen.getByTestId("server-settings-search-results");
    expect(within(results).getByRole("switch", { name: "PvP" })).toBeInTheDocument();
    expect(within(results).queryByRole("switch", { name: "Whitelist" })).not.toBeInTheDocument();
    expect(within(results).queryByLabelText("Game Port")).not.toBeInTheDocument();

    fireEvent.change(searchInputs[0], { target: { value: "timeout" } });
    expect(screen.getByTestId("search-result-startup-timeout")).toBeInTheDocument();
    expect(screen.getByTestId("search-result-p55-health-timeout")).toBeInTheDocument();

    fireEvent.change(searchInputs[0], { target: { value: "zzzz-no-match" } });
    expect(screen.getByTestId("search-empty-state")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear Search" }));
    expect(screen.getByTestId("server-settings-tab-general")).toBeInTheDocument();
  });

  it("validates FORBIDDEN_JVM_HOOK_FLAGS, applies Aikar flags, edits Startup Timeout, and clamps on Enter submit", async () => {
    renderPage();

    fireEvent.click(document.getElementById("server-settings-tab-resources")!);
    fireEvent.click(screen.getByTestId("toggle-advanced-jvm"));

    const jvmTextarea = screen.getByLabelText("Custom JVM Arguments");
    fireEvent.change(jvmTextarea, { target: { value: "-javaagent:/tmp/bad.jar" } });
    expect(screen.getByText(/Disallowed JVM flag: -javaagent:/i)).toBeInTheDocument();

    const saveBar = screen.getByTestId("sticky-server-save-bar");
    expect(within(saveBar).getByRole("button", { name: /^save$/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Apply Aikar's Flags" }));
    expect((jvmTextarea as HTMLTextAreaElement).value).toContain("-XX:+UseG1GC");

    const timeoutInput = screen.getByLabelText("Server Startup Timeout");
    fireEvent.change(timeoutInput, { target: { value: "9999" } });
    fireEvent.submit(screen.getByTestId("server-settings-form"));

    await waitFor(() => expect(mockUpdateMutateAsync).toHaveBeenCalledTimes(1));
    const call = mockUpdateMutateAsync.mock.calls[0][0];
    expect(call.body.startup_timeout_seconds).toBe(1800);
    expect(call.body.java_args).toContain("-XX:+UseG1GC");
    // Class-D non-port keys must be stripped from customProperties
    expect(call.body.properties["rcon.port"]).toBeUndefined();
    expect(call.body.properties["enable-rcon"]).toBeUndefined();
  });

  it("auto-resyncs on background poll when clean, without clobbering dirty user edits", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    mockUseServerDetail.mockReturnValue({
      data: baseServer,
      isLoading: false,
      error: null,
    });

    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1/settings"]}>
          <Routes>
            <Route path="/servers/:serverId/settings" element={<ServerSettingsPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const nameInput = screen.getByLabelText("Server Name") as HTMLInputElement;
    expect(nameInput.value).toBe("Studio SMP");

    // Server updates externally while clean -> form auto-syncs
    mockUseServerDetail.mockReturnValue({
      data: { ...baseServer, name: "Polled Name" },
      isLoading: false,
      error: null,
    });
    rerender(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1/settings"]}>
          <Routes>
            <Route path="/servers/:serverId/settings" element={<ServerSettingsPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect((screen.getByLabelText("Server Name") as HTMLInputElement).value).toBe("Polled Name");
    expect(screen.queryByTestId("sticky-server-save-bar")).not.toBeInTheDocument();

    // User edits form -> dirty -> external poll must NOT clobber
    fireEvent.change(screen.getByLabelText("Server Name"), { target: { value: "User Editing" } });
    mockUseServerDetail.mockReturnValue({
      data: { ...baseServer, name: "Another Poll" },
      isLoading: false,
      error: null,
    });
    rerender(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1/settings"]}>
          <Routes>
            <Route path="/servers/:serverId/settings" element={<ServerSettingsPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect((screen.getByLabelText("Server Name") as HTMLInputElement).value).toBe("User Editing");
  });

  it("validates PNG server icon upload and calls uploadServerFile", async () => {
    const user = userEvent.setup();
    mockApi.uploadServerFile.mockResolvedValue({ name: "server-icon.png" });
    renderPage();

    const fileInput = screen.getByLabelText("Upload PNG server icon") as HTMLInputElement;
    const pngFile = new File(["pngbytes"], "my-logo.png", { type: "image/png" });
    await user.upload(fileInput, pngFile);

    await waitFor(() =>
      expect(mockApi.uploadServerFile).toHaveBeenCalledWith(
        "srv-1",
        "",
        expect.objectContaining({ name: "server-icon.png" }),
        undefined,
      ),
    );
  });

  it("enforces RBAC read-only gating for viewer role", () => {
    mockPerms.canWrite.mockReturnValue(false);
    mockPerms.canDelete = false;
    mockPerms.canManageVersioning = false;

    renderPage();
    expect(screen.getByTestId("settings-readonly-pill")).toHaveTextContent("Read-only access");
    expect(screen.getByLabelText("Server Name")).toBeDisabled();
    expect(screen.getByLabelText("Game Port")).toBeDisabled();
  });

  it("gates locked worktrees and forwards ?branch= in Edit server.properties link on working branches", async () => {
    mockApi.getServerBranches.mockResolvedValue([
      {
        id: "br-1",
        server_id: "srv-1",
        name: "feat-x",
        head_commit_id: "a".repeat(40),
        created_at: "2026-01-01T00:00:00Z",
        is_protected: false,
        worktree_path: "/tmp/wt/feat-x",
        worktree_locked: true,
      },
    ]);
    mockApi.getBranchRuntime.mockResolvedValue({
      server_id: "srv-1",
      branch_name: "feat-x",
      runtime_id: "rt-1",
      runtime_status: "running",
      container_provisioned: true,
      port_set: null,
    });

    renderPage({
      server: { ...baseServer, mode: "advanced" },
      branchCtx: { branch: "feat-x", setBranch: vi.fn(), gitBacked: true },
    });

    expect(await screen.findByTestId("worktree-locked-banner")).toBeInTheDocument();
    expect(screen.getByLabelText("MOTD")).toBeDisabled();
    expect(screen.getByTestId("edit-server-properties-link")).toHaveAttribute(
      "href",
      "/servers/srv-1/files?file=server.properties&branch=feat-x",
    );
  });

  it("uses concise 'Queue for Restart' label on Advanced main branch", () => {
    renderPage({
      server: { ...baseServer, mode: "advanced" },
      branchCtx: { branch: "main", setBranch: vi.fn(), gitBacked: true },
    });

    fireEvent.change(screen.getByLabelText("MOTD"), { target: { value: "Changed MOTD" } });
    expect(screen.getByRole("button", { name: "Queue for Restart" })).toBeInTheDocument();
  });

  it("clears rawDrafts when clicking CPU, Startup Timeout, and Max Players quick chips and keeps sticky save bar visible on lifecycle tab", () => {
    renderPage();

    fireEvent.click(document.getElementById("server-settings-tab-resources")!);
    const cpuInput = screen.getByLabelText("CPU Core Limit") as HTMLInputElement;
    fireEvent.change(cpuInput, { target: { value: "99" } });
    expect(cpuInput.value).toBe("99");
    fireEvent.click(screen.getByRole("button", { name: "2 Cores" }));
    expect(cpuInput.value).toBe("2");

    const timeoutInput = screen.getByLabelText("Server Startup Timeout") as HTMLInputElement;
    fireEvent.change(timeoutInput, { target: { value: "777" } });
    expect(timeoutInput.value).toBe("777");
    fireEvent.click(screen.getByRole("button", { name: "60s" }));
    expect(timeoutInput.value).toBe("60");

    fireEvent.click(document.getElementById("server-settings-tab-gameplay")!);
    const maxPlayersInput = screen.getByLabelText("Max Players") as HTMLInputElement;
    fireEvent.change(maxPlayersInput, { target: { value: "88" } });
    expect(maxPlayersInput.value).toBe("88");
    fireEvent.click(screen.getByRole("button", { name: "50" }));
    expect(maxPlayersInput.value).toBe("50");

    // Sticky save bar remains visible when switching to lifecycle / danger tabs
    fireEvent.click(document.getElementById("server-settings-tab-lifecycle")!);
    expect(screen.getByTestId("sticky-server-save-bar")).toBeInTheDocument();
    fireEvent.click(document.getElementById("server-settings-tab-danger")!);
    expect(screen.getByTestId("sticky-server-save-bar")).toBeInTheDocument();
  });

  it("renders unsaved changes notification at the top with Save and Undo All choices", async () => {
    renderPage();

    const nameInput = screen.getByLabelText("Server Name") as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "Edited SMP" } });

    const saveBar = screen.getByTestId("sticky-server-save-bar");
    expect(saveBar).toHaveClass("sticky", "top-16");
    expect(saveBar).not.toHaveClass("bottom-4");

    // Notification bar is placed before the tab content in the panel (top, not bottom)
    const tabContent = screen.getByTestId("server-settings-tab-general");
    expect(
      saveBar.compareDocumentPosition(tabContent) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    const undoAllBtn = within(saveBar).getByRole("button", { name: "Undo All" });
    const saveBtn = within(saveBar).getByRole("button", { name: "Save" });
    expect(undoAllBtn).toBeInTheDocument();
    expect(saveBtn).toBeInTheDocument();

    // Clicking Undo All reverts the edit and hides the notification bar
    fireEvent.click(undoAllBtn);
    expect(nameInput.value).toBe("Studio SMP");
    expect(screen.queryByTestId("sticky-server-save-bar")).not.toBeInTheDocument();

    // Editing again and clicking Save triggers mutation
    fireEvent.change(nameInput, { target: { value: "Saved SMP" } });
    fireEvent.click(
      within(screen.getByTestId("sticky-server-save-bar")).getByRole("button", {
        name: "Save",
      }),
    );
    await waitFor(() => expect(mockUpdateMutateAsync).toHaveBeenCalledTimes(1));
    expect(mockUpdateMutateAsync.mock.calls[0][0].body.name).toBe("Saved SMP");
  });
});
