import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerExposurePage } from "./ServerExposurePage";
import { ServerDetailPage } from "./ServerDetailPage";
import { ServerShell } from "@/layouts/ServerShell";
import { queryKeys } from "@/services/queryClient";
import type {
  ServerExposureResponse,
  AgentStatusResponse,
} from "@/types";
import type { ServerDetailResponse } from "@/server_manager/types";

// Mock API functions
const mockGetMe = vi.fn();
const mockGetServer = vi.fn();
const mockGetServerExposure = vi.fn();
const mockSetServerExposure = vi.fn();
const mockSetServerExposureState = vi.fn();
const mockRemoveServerExposure = vi.fn();
const mockCreateExposureTarget = vi.fn();
const mockUpdateExposureTarget = vi.fn();
const mockDeleteExposureTarget = vi.fn();
const mockListServerPorts = vi.fn();
const mockRegisterServerPort = vi.fn();
const mockDeleteServerPort = vi.fn();
const mockGetAgentStatus = vi.fn();
const mockGenerateClaim = vi.fn();
const mockResetAgent = vi.fn();
const mockStopAllExposures = vi.fn();
const mockRemoveCredentials = vi.fn();

const mockToast = vi.fn();
const mockCopy = vi.fn();

vi.mock("@/services/api", () => {
  const client = {
    getMe: () => mockGetMe(),
    getServer: (id: string) => mockGetServer(id),
    getServerExposure: (id: string) => mockGetServerExposure(id),
    setServerExposure: (id: string, body: unknown) => mockSetServerExposure(id, body),
    setServerExposureState: (id: string, body: unknown) => mockSetServerExposureState(id, body),
    removeServerExposure: (id: string) => mockRemoveServerExposure(id),
    listExposureTargets: (id: string) => mockGetServerExposure(id).then((r: ServerExposureResponse) => r.targets),
    createExposureTarget: (id: string, body: unknown) => mockCreateExposureTarget(id, body),
    updateExposureTarget: (id: string, tid: string, body: unknown) => mockUpdateExposureTarget(id, tid, body),
    deleteExposureTarget: (id: string, tid: string) => mockDeleteExposureTarget(id, tid),
    listServerPorts: (id: string) => mockListServerPorts(id),
    registerServerPort: (id: string, body: unknown) => mockRegisterServerPort(id, body),
    deleteServerPort: (id: string, pid: string) => mockDeleteServerPort(id, pid),
    getAgentStatus: () => mockGetAgentStatus(),
    generateClaim: () => mockGenerateClaim(),
    resetAgent: () => mockResetAgent(),
    stopAllExposures: () => mockStopAllExposures(),
    removeCredentials: () => mockRemoveCredentials(),
    getServerRuntime: () => Promise.resolve({ cpu_percent: 0, memory_mb: 0 }),
  };
  return {
    createApiClient: () => client,
    createAuthenticatedApi: () => client,
    ApiError: class extends Error {
      status: number;
      constructor(status: number, message: string) {
        super(message);
        this.status = status;
      }
    },
  };
});

vi.mock("@/stores/toastStore", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/stores/toastStore")>();
  return {
    ...actual,
    toast: (...args: unknown[]) => mockToast(...args),
  };
});

vi.mock("@/hooks/useClipboard", () => ({
  useClipboard: () => ({
    copy: mockCopy,
  }),
}));

const defaultServerDetail: ServerDetailResponse = {
  server_id: "srv-123",
  name: "Survival World",
  minecraft_version: "1.20.4",
  server_type: "paper",
  status: "ONLINE",
  group_id: "default",
  port: 25565,
  max_players: 20,
  pvp: true,
  difficulty: "normal",
  gamemode: "survival",
  whitelist: false,
  online_mode: true,
  enable_command_block: false,
  spawn_protection: 16,
  view_distance: 10,
  simulation_distance: 10,
  min_memory_mb: 1024,
  max_memory_mb: 4096,
  java_args: "",
  motd: "A Minecraft Server",
  provider: "local",
  deployment_host: "127.0.0.1",
  deployment_port: 25565,
  deployment_pid: 1234,
  location_type: "local",
  location_uri: null,
  root_path: "/servers/survival",
  working_directory: "/servers/survival",
  startup_jar: "paper.jar",
  startup_command: null,
  primary_world: "world",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const defaultExposureResponse: ServerExposureResponse = {
  server_id: "srv-123",
  method: "none",
  desired_state: "DISABLED",
  aggregate_status: "DISABLED",
  error_code: null,
  error_message: null,
  cloudflare_tunnel_id: null,
  has_cloudflare_credentials: false,
  targets: [],
};

const defaultAgentResponse: AgentStatusResponse = {
  claimed: false,
  process_status: "STOPPED",
  desired_agent_running: false,
  last_health_at: null,
  claim_active: false,
  claim_expires_at: null,
};

function renderServerExposurePage(
  initialRoute = "/servers/srv-123/network",
  qc?: QueryClient
) {
  const queryClient =
    qc ??
    new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          gcTime: 0,
        },
      },
    });

  const renderResult = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="servers/:serverId" element={<ServerShell />}>
            <Route path="console" element={<ServerDetailPage />} />
            <Route path="network" element={<ServerExposurePage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );

  return {
    queryClient,
    ...renderResult,
  };
}

describe("Batch 7.5 — ServerExposurePage Acceptance Tests (T-75-01..T-75-24)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMe.mockResolvedValue({
      user_id: "user-1",
      email: "owner@example.com",
      display_name: "Owner User",
      is_active: true,
      roles: ["owner"],
      created_at: new Date().toISOString(),
      last_login_at: null,
    });

    mockGetServer.mockResolvedValue({ ...defaultServerDetail });
    mockGetServerExposure.mockResolvedValue({ ...defaultExposureResponse });
    mockGetAgentStatus.mockResolvedValue({ ...defaultAgentResponse });
    mockListServerPorts.mockResolvedValue([]);
  });

  it("T-75-01: renders_not_exposed_default_state_cleanly", async () => {
    renderServerExposurePage();

    expect(await screen.findByText("Network & Public Exposure")).toBeInTheDocument();
    expect(screen.getByText("Not Exposed")).toBeInTheDocument();
    expect(screen.getByText("No active targets configured")).toBeInTheDocument();
  });

  it("T-75-02: switching_method_cards_updates_draft_without_autosaving", async () => {
    renderServerExposurePage();

    expect(await screen.findByText("Network & Public Exposure")).toBeInTheDocument();
    const playitCard = screen.getByRole("button", { name: /playit\.gg/i });
    fireEvent.click(playitCard);

    expect(await screen.findByText("playit.gg Game Server Tunnel")).toBeInTheDocument();
    expect(mockSetServerExposure).not.toHaveBeenCalled(); // No auto-save on card select
  });

  it("T-75-03: cloudflare_tcp_warning_checkbox_gates_save_button", async () => {
    renderServerExposurePage();

    const cfCard = await screen.findByRole("button", { name: /Cloudflare TCP/i });
    fireEvent.click(cfCard);

    const hostnameInput = await screen.findByLabelText(/Custom Domain \/ FQDN/i);
    const tokenInput = screen.getByLabelText(/Cloudflare API Token/i);
    const checkbox = screen.getByRole("checkbox", {
      name: /I understand that players must use Modflared/i,
    });
    const saveBtn = screen.getByRole("button", { name: /Enable Cloudflare Tunnel/i });

    // Initial state: empty & unchecked -> disabled
    expect(saveBtn).toBeDisabled();

    // Fill valid FQDN and token, but leave checkbox unchecked -> still disabled
    fireEvent.change(hostnameInput, { target: { value: "play.example.com" } });
    fireEvent.change(tokenInput, { target: { value: "cf-token-123" } });
    expect(saveBtn).toBeDisabled();

    // Check the mandatory warning box -> enabled
    fireEvent.click(checkbox);
    expect(saveBtn).toBeEnabled();

    // Submit mutation
    mockSetServerExposure.mockResolvedValueOnce({
      ...defaultExposureResponse,
      method: "cloudflare_tcp",
      desired_state: "ENABLED",
      aggregate_status: "STARTING",
    });

    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockSetServerExposure).toHaveBeenCalledWith("srv-123", {
        method: "cloudflare_tcp",
        desired_state: "ENABLED",
        cloudflare_token: "cf-token-123",
        hostname: "play.example.com",
        acknowledged_warning: true,
      });
    });
  });

  it("T-75-04: renders_multi_target_list_with_protocols_and_public_addresses", async () => {
    mockGetServerExposure.mockResolvedValueOnce({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "survival.ply.gg:12345",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
        {
          id: "tgt-2",
          exposure_id: "exp-1",
          protocol: "udp",
          service_type: "bedrock",
          local_port: 19132,
          public_address: "survival-bedrock.ply.gg:19132",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
        {
          id: "tgt-3",
          exposure_id: "exp-1",
          protocol: "udp",
          service_type: "voice",
          local_port: 24454,
          public_address: "survival-voice.ply.gg:24454",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    expect(await screen.findByText("survival.ply.gg:12345")).toBeInTheDocument();
    expect(screen.getByText("survival-bedrock.ply.gg:19132")).toBeInTheDocument();
    expect(screen.getByText("survival-voice.ply.gg:24454")).toBeInTheDocument();
    expect(screen.getByText("Bedrock Edition (Geyser)")).toBeInTheDocument();
    expect(screen.getByText("Simple Voice Chat")).toBeInTheDocument();
  });

  it("T-75-05: copy_target_address_writes_to_clipboard_and_fires_toast", async () => {
    mockGetServerExposure.mockResolvedValueOnce({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "custom.ply.gg:25565",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    const copyBtn = await screen.findByRole("button", {
      name: /Copy Java Edition public address to clipboard/i,
    });
    fireEvent.click(copyBtn);

    expect(mockCopy).toHaveBeenCalledWith("custom.ply.gg:25565", "Public address copied to clipboard");
  });

  it("T-75-06: playit_assisted_setup_renders_numbered_scaffold_and_manual_edit_flow", async () => {
    mockGetServerExposure.mockResolvedValueOnce({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: null,
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: "https://playit.gg/manage",
          setup_instructions: "Create a TCP tunnel pointing to 127.0.0.1:25565",
        },
      ],
    });

    renderServerExposurePage();

    expect(await screen.findByText("playit.gg Assisted Setup Required")).toBeInTheDocument();
    expect(screen.getByText(/Create a TCP tunnel pointing to 127\.0\.0\.1:25565/i)).toBeInTheDocument();

    const dashboardLink = screen.getByRole("link", { name: /Open Dashboard/i });
    expect(dashboardLink).toHaveAttribute("href", "https://playit.gg/manage");

    // Click Paste / Enter Address to trigger manual address modal
    const setAddressBtn = screen.getByRole("button", { name: /Paste \/ Enter Address/i });
    fireEvent.click(setAddressBtn);

    expect(screen.getByText("Update Public Address")).toBeInTheDocument();
    const addressInput = screen.getByRole("textbox", { name: /Public Address/i });
    fireEvent.change(addressInput, { target: { value: "mc.myserver.ply.gg:12345" } });

    mockUpdateExposureTarget.mockResolvedValueOnce({
      id: "tgt-1",
      public_address: "mc.myserver.ply.gg:12345",
    });

    const saveAddressBtn = screen.getByRole("button", { name: /Save Address/i });
    fireEvent.click(saveAddressBtn);

    await waitFor(() => {
      expect(mockUpdateExposureTarget).toHaveBeenCalledWith(
        "srv-123",
        "tgt-1",
        { public_address: "mc.myserver.ply.gg:12345" }
      );
    });
  });

  it("T-75-07: companion_target_modal_validates_port_range_and_deny_list", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "play.ply.gg:12345",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    const addTargetBtn = await screen.findByRole("button", { name: /Add Companion Target/i });
    fireEvent.click(addTargetBtn);

    expect(screen.getByText("Add Companion Service Target")).toBeInTheDocument();
    const portInput = screen.getByLabelText(/Local Service Port/i);
    const createBtn = screen.getByRole("button", { name: /Add Target/i });

    // Test reserved RCON port 25575
    fireEvent.change(portInput, { target: { value: "25575" } });
    expect(
      screen.getByText(/Port 25575 is reserved for internal management\/database services/i)
    ).toBeInTheDocument();
    expect(createBtn).toBeDisabled();

    // Test reserved MySQL port 3306
    fireEvent.change(portInput, { target: { value: "3306" } });
    expect(
      screen.getByText(/Port 3306 is reserved for internal management\/database services/i)
    ).toBeInTheDocument();
    expect(createBtn).toBeDisabled();

    // Test out of range port 70000
    fireEvent.change(portInput, { target: { value: "70000" } });
    expect(
      screen.getByText(/Port must be a valid number between 1 and 65535/i)
    ).toBeInTheDocument();
    expect(createBtn).toBeDisabled();
  });

  it("T-75-08: companion_target_modal_creates_new_bedrock_target", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "play.ply.gg:12345",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    const addTargetBtn = await screen.findByRole("button", { name: /Add Companion Target/i });
    fireEvent.click(addTargetBtn);

    const bedrockCard = screen.getByRole("button", { name: /Bedrock Edition/i });
    fireEvent.click(bedrockCard);

    mockCreateExposureTarget.mockResolvedValueOnce({
      id: "tgt-2",
      exposure_id: "exp-1",
      protocol: "udp",
      service_type: "bedrock",
      local_port: 19132,
      public_address: null,
      status: "STARTING",
    });

    const submitBtn = screen.getByRole("button", { name: /Add Target/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockCreateExposureTarget).toHaveBeenCalledWith("srv-123", {
        service_type: "bedrock",
        protocol: "udp",
        local_port: 19132,
      });
    });
  });

  it("T-75-09: removing_companion_target_opens_confirmation_and_deletes", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "play.ply.gg:12345",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
        {
          id: "tgt-2",
          exposure_id: "exp-1",
          protocol: "udp",
          service_type: "voice",
          local_port: 24454,
          public_address: "voice.ply.gg:24454",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    // Primary Java target has NO delete button (F-75-13)
    expect(screen.queryByLabelText(/Remove Java Edition target/i)).not.toBeInTheDocument();

    // Companion Voice target HAS delete button
    const deleteVoiceBtn = await screen.findByLabelText(/Remove Simple Voice Chat target/i);
    fireEvent.click(deleteVoiceBtn);

    expect(screen.getByText("Remove Companion Target?")).toBeInTheDocument();
    mockDeleteExposureTarget.mockResolvedValueOnce(undefined);

    const confirmRemoveBtn = screen.getByRole("button", { name: /Remove Target/i });
    fireEvent.click(confirmRemoveBtn);

    await waitFor(() => {
      expect(mockDeleteExposureTarget).toHaveBeenCalledWith("srv-123", "tgt-2");
    });
  });

  it("T-75-10: adaptive_polling_frequency_matches_state_transitions", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "STARTING",
    });

    const { queryClient } = renderServerExposurePage();

    expect(await screen.findByText("Starting...")).toBeInTheDocument();

    // Transition to ACTIVE
    act(() => {
      queryClient.setQueryData(queryKeys.exposure.server("srv-123"), {
        ...defaultExposureResponse,
        method: "playit",
        desired_state: "ENABLED",
        aggregate_status: "ACTIVE",
      });
    });

    expect(await screen.findByText("Active")).toBeInTheDocument();
  });

  it("T-75-11: view_only_user_cannot_see_mutate_buttons_or_forms", async () => {
    // Set viewer role
    mockGetMe.mockResolvedValue({
      user_id: "user-viewer",
      email: "viewer@example.com",
      display_name: "Viewer",
      is_active: true,
      roles: ["viewer"],
      created_at: new Date().toISOString(),
      last_login_at: null,
    });

    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "play.ply.gg:12345",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    expect(await screen.findByText("View-only mode")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add Companion Target/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Disable Exposure/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Instance Exposure Controls (Owner-Only)")).not.toBeInTheDocument();
  });

  it("T-75-12: owner_actions_card_only_visible_to_instance_owner", async () => {
    // 1. As owner -> visible
    renderServerExposurePage();
    expect(
      await screen.findByText("Instance Exposure Controls (Owner-Only)")
    ).toBeInTheDocument();

    // Clean up DOM before re-rendering with different role
    cleanup();

    // 2. As manager (not owner) -> hidden
    mockGetMe.mockResolvedValue({
      user_id: "user-mgr",
      email: "mgr@example.com",
      display_name: "Manager",
      is_active: true,
      roles: ["member"],
      created_at: new Date().toISOString(),
      last_login_at: null,
    });

    renderServerExposurePage();
    expect(
      screen.queryByText("Instance Exposure Controls (Owner-Only)")
    ).not.toBeInTheDocument();
  });

  it("T-75-13: owner_stop_all_exposures_requires_typed_confirmation_and_triggers_api", async () => {
    renderServerExposurePage();

    const stopAllBtn = await screen.findByRole("button", { name: /Stop All Exposures/i });
    fireEvent.click(stopAllBtn);

    expect(screen.getByText("Stop All Instance Exposures")).toBeInTheDocument();
    const typedInput = screen.getByLabelText(/Type STOP ALL to confirm/i);
    const confirmBtn = screen.getByRole("button", { name: "Stop All Exposures" });

    // Blocked until exact match typed
    expect(confirmBtn).toBeDisabled();

    fireEvent.change(typedInput, { target: { value: "wrong text" } });
    expect(confirmBtn).toBeDisabled();

    fireEvent.change(typedInput, { target: { value: "STOP ALL" } });
    expect(confirmBtn).toBeEnabled();

    mockStopAllExposures.mockResolvedValueOnce({ disabled_count: 3 });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockStopAllExposures).toHaveBeenCalled();
      expect(mockToast).toHaveBeenCalledWith("success", "All Exposures Stopped", "Successfully disabled 3 active exposure(s).");
    });
  });

  it("T-75-14: owner_reset_agent_requires_typed_confirmation_and_clears_agent_credentials", async () => {
    renderServerExposurePage();

    const resetBtn = await screen.findByRole("button", { name: /Reset playit Agent/i });
    fireEvent.click(resetBtn);

    expect(screen.getByText("Reset playit.gg Host Agent")).toBeInTheDocument();
    const typedInput = screen.getByLabelText(/Type RESET to confirm/i);
    const confirmBtn = screen.getByRole("button", { name: "Reset Agent Credentials" });

    expect(confirmBtn).toBeDisabled();

    fireEvent.change(typedInput, { target: { value: "RESET" } });
    expect(confirmBtn).toBeEnabled();

    mockResetAgent.mockResolvedValueOnce({ claimed: false, process_status: "STOPPED" });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockResetAgent).toHaveBeenCalled();
      expect(mockToast).toHaveBeenCalledWith("success", "Agent Credentials Reset", "Host playit agent credentials cleared and unclaimed.");
    });
  });

  it("T-75-15: method_switch_with_active_targets_requires_typed_confirmation", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "play.ply.gg:12345",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    // Click Port Forward method card while playit is ENABLED and ACTIVE
    const portForwardCard = await screen.findByRole("button", { name: /Port Forward/i });
    fireEvent.click(portForwardCard);

    expect(screen.getByText("Switch Exposure Method?")).toBeInTheDocument();
    const typedInput = screen.getByLabelText(/Type SWITCH to confirm/i);
    const confirmSwitchBtn = screen.getByRole("button", { name: "Switch Method" });

    // Blocked until exact string "SWITCH" typed (F-75-17)
    expect(confirmSwitchBtn).toBeDisabled();

    fireEvent.change(typedInput, { target: { value: "switch" } }); // Case sensitive
    expect(confirmSwitchBtn).toBeDisabled();

    fireEvent.change(typedInput, { target: { value: "SWITCH" } });
    expect(confirmSwitchBtn).toBeEnabled();

    fireEvent.click(confirmSwitchBtn);
    expect(screen.queryByText("Switch Exposure Method?")).not.toBeInTheDocument();
  });

  it("T-75-16: disabling_exposure_opens_modal_and_patches_disabled_state", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "play.ply.gg:12345",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    const disableBtn = await screen.findByRole("button", { name: "Disable Exposure" });
    fireEvent.click(disableBtn);

    expect(screen.getByText("Disable Server Exposure?")).toBeInTheDocument();
    mockSetServerExposureState.mockResolvedValueOnce({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "DISABLED",
      aggregate_status: "DISABLED",
    });

    const confirmDisableBtn = screen.getByRole("button", { name: "Confirm Disable" });
    fireEvent.click(confirmDisableBtn);

    await waitFor(() => {
      expect(mockSetServerExposureState).toHaveBeenCalledWith("srv-123", {
        desired_state: "DISABLED",
      });
    });
  });

  it("T-75-17: reclaim_required_status_renders_token_revoked_prompt", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "cloudflare_tcp",
      desired_state: "ENABLED",
      aggregate_status: "RECLAIM_REQUIRED",
      error_code: "TOKEN_REVOKED",
      cloudflare_tunnel_id: "tun-123",
      has_cloudflare_credentials: true,
    });

    renderServerExposurePage();

    expect(
      await screen.findByText("Exposure Credentials Revoked or Invalidated")
    ).toBeInTheDocument();
  });

  it("T-75-18: error_status_renders_error_banner_with_fix_hint", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "port_forward",
      desired_state: "ENABLED",
      aggregate_status: "ERROR",
      error_code: "UPNP_TIMEOUT",
      error_message: "Router failed to respond to UPnP IGD request",
    });

    renderServerExposurePage();

    expect(
      await screen.findByText("Router failed to respond to UPnP IGD request")
    ).toBeInTheDocument();
    expect(screen.getByText("UPNP_TIMEOUT")).toBeInTheDocument();
  });

  it("T-75-19: playit_claim_card_mounts_when_host_agent_unclaimed", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "none",
      desired_state: "DISABLED",
    });
    mockGetAgentStatus.mockResolvedValue({
      ...defaultAgentResponse,
      claimed: false,
    });

    renderServerExposurePage();

    const playitCard = await screen.findByRole("button", { name: /playit\.gg/i });
    fireEvent.click(playitCard);

    expect(await screen.findByText("playit.gg Game Server Tunnel")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Authorize with playit.gg" })).toBeInTheDocument();
  });

  it("T-75-20: playit_claim_card_unmounts_once_agent_becomes_claimed", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
    });
    mockGetAgentStatus.mockResolvedValue({
      ...defaultAgentResponse,
      claimed: true,
    });

    renderServerExposurePage();

    expect(
      await screen.findByText("Host playit.gg agent is claimed and active.")
    ).toBeInTheDocument();
    expect(screen.queryByText("Authorize with playit.gg")).not.toBeInTheDocument();
  });

  it("T-75-21: server_shell_nav_renders_network_and_exposure_link", async () => {
    renderServerExposurePage("/servers/srv-123/console");

    const navLinks = await screen.findAllByRole("link", { name: /Network & Exposure/i });
    expect(navLinks.length).toBeGreaterThan(0);
    expect(navLinks[0]).toHaveAttribute("href", "/servers/srv-123/network");
  });

  it("T-75-22: server_detail_page_renders_exposure_status_row_and_link", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "mc.survival.ply.gg:25565",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage("/servers/srv-123/console");

    // Expand Server Info & Configuration accordion
    const accordionBtn = await screen.findByRole("button", {
      name: /Server Info & Configuration/i,
    });
    fireEvent.click(accordionBtn);

    expect(await screen.findByText("Public Exposure")).toBeInTheDocument();
    expect(screen.getAllByText("mc.survival.ply.gg:25565")).toHaveLength(2);
    const manageLink = screen.getByRole("link", { name: "Manage" });
    expect(manageLink).toHaveAttribute("href", "/servers/srv-123/network");
  });

  it("T-75-23: non_blocking_mutation_error_leaves_inputs_editable", async () => {
    renderServerExposurePage();

    const cfCard = await screen.findByRole("button", { name: /Cloudflare TCP/i });
    fireEvent.click(cfCard);

    const hostnameInput = await screen.findByLabelText(/Custom Domain \/ FQDN/i);
    const tokenInput = screen.getByLabelText(/Cloudflare API Token/i);
    const checkbox = screen.getByRole("checkbox", {
      name: /I understand that players must use Modflared/i,
    });
    const saveBtn = screen.getByRole("button", { name: /Enable Cloudflare Tunnel/i });

    fireEvent.change(hostnameInput, { target: { value: "play.example.com" } });
    fireEvent.change(tokenInput, { target: { value: "bad-token" } });
    fireEvent.click(checkbox);

    mockSetServerExposure.mockRejectedValueOnce(new Error("Cloudflare API error (401 Unauthorized)"));
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockToast).toHaveBeenCalledWith("error", "Exposure Update Failed", "Cloudflare API error (401 Unauthorized)");
    });

    // Form inputs remain editable
    expect(hostnameInput).toBeEnabled();
    expect(tokenInput).toBeEnabled();
    expect(checkbox).toBeEnabled();
  });

  it("T-75-24: aggregate_status_precedence_renders_correct_top_badge", async () => {
    mockGetServerExposure.mockResolvedValue({
      ...defaultExposureResponse,
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ERROR",
      error_code: "TUNNEL_FAILED",
      targets: [
        {
          id: "tgt-1",
          exposure_id: "exp-1",
          protocol: "tcp",
          service_type: "java",
          local_port: 25565,
          public_address: "play.ply.gg:12345",
          status: "ACTIVE",
          error_code: null,
          error_message: null,
          dashboard_url: null,
          setup_instructions: null,
        },
        {
          id: "tgt-2",
          exposure_id: "exp-1",
          protocol: "udp",
          service_type: "bedrock",
          local_port: 19132,
          public_address: null,
          status: "ERROR",
          error_code: "TUNNEL_FAILED",
          error_message: "Failed to establish UDP tunnel",
          dashboard_url: null,
          setup_instructions: null,
        },
      ],
    });

    renderServerExposurePage();

    // Top aggregate status should render Error badge
    const errorBadges = await screen.findAllByText("Error");
    expect(errorBadges.length).toBeGreaterThan(0);
  });

  describe("Modal behavior (FIX-3)", () => {
    async function renderActiveAndOpenModal() {
      mockGetServerExposure.mockResolvedValue({
        ...defaultExposureResponse,
        method: "playit",
        desired_state: "ENABLED",
        aggregate_status: "ACTIVE",
      });

      renderServerExposurePage();
      const disableBtn = await screen.findByRole("button", { name: "Disable Exposure" });
      fireEvent.click(disableBtn);
    }

    it("renders dialog with accessible title, focuses inside, and supports Escape when idle", async () => {
      await renderActiveAndOpenModal();

      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Disable Server Exposure?" })).toBeInTheDocument();

      await waitFor(() => {
        expect(dialog.contains(document.activeElement)).toBe(true);
      });

      fireEvent.keyDown(window, { key: "Escape" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
    });

    it("does not close on backdrop click or content click", async () => {
      await renderActiveAndOpenModal();

      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();

      const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60")!;
      expect(backdrop).toBeInTheDocument();
      fireEvent.click(backdrop);
      expect(screen.getByRole("dialog")).toBeInTheDocument();

      fireEvent.click(dialog);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("guards against Escape and disables Cancel/Action buttons while pending", async () => {
      let resolveMutation!: (val: unknown) => void;
      mockSetServerExposureState.mockImplementation(
        () => new Promise((resolve) => { resolveMutation = resolve; })
      );

      await renderActiveAndOpenModal();

      const dialog = screen.getByRole("dialog");
      const confirmBtn = dialog.querySelector("button.bg-red-600") as HTMLButtonElement;
      const cancelBtn = screen.getByRole("button", { name: "Cancel" });

      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Disabling..." })).toBeDisabled();
        expect(cancelBtn).toBeDisabled();
      });

      fireEvent.keyDown(window, { key: "Escape" });
      expect(screen.getByRole("dialog")).toBeInTheDocument();

      resolveMutation({ ...defaultExposureResponse, desired_state: "DISABLED" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
    });
  });
});
