import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ServerVersioningPage } from "./ServerVersioningPage";
const mockApi = {
  getServerBranches: vi.fn(),
  createServerBranch: vi.fn(),
  getServerCommits: vi.fn(),
  createServerCommit: vi.fn(),
  runIsolatedTest: vi.fn(),
  getTestStatus: vi.fn(),
  promoteTestCommit: vi.fn(),
  discardTest: vi.fn(),
  getBotSettings: vi.fn(),
  updateBotSettings: vi.fn(),
  getPreflightStatus: vi.fn(),
};

vi.mock("@/services/api", () => ({
  createApiClient: () => mockApi,
  createAuthenticatedApi: () => mockApi,
}));

const mockBranches = [
  {
    id: "b-main",
    server_id: "srv-vers-1",
    name: "main",
    head_commit_id: "c-111",
    created_at: "2026-09-14T10:00:00Z",
  },
  {
    id: "b-trial",
    server_id: "srv-vers-1",
    name: "feat-trial",
    head_commit_id: null,
    created_at: "2026-09-14T11:00:00Z",
  },
];

const mockCommits = [
  {
    id: "c-111222333",
    server_id: "srv-vers-1",
    branch_id: "b-main",
    parent_commit_id: null,
    author_id: "admin",
    message: "Initial baseline configuration",
    manifest: {
      server_type: "paper",
      minecraft_version: "1.21.1",
      configs: { "server.properties": "online-mode=true\n" },
      mods: [{ filename: "plugins/EssentialsX.jar", sha256: "abc", source: "custom" }],
      env_vars: {},
      java_args: "-Xmx4G",
    },
    world_snapshot_id: "snap-1",
    created_at: "2026-09-14T10:05:00Z",
  },
];

const mockPreflight = {
  reflink_supported: true,
  available_ram_mb: 16384,
  available_cores: 8,
  min_required_ram_mb: 4096,
  min_required_cores: 2,
  passed: true,
  error: null,
};

const mockBotSettings = {
  server_id: "srv-vers-1",
  bot_count: 10,
  duration_minutes: 15,
  bot_tech: "auto",
  placement_mode: "sidecar",
  effective_bot_count: 10,
  effective_duration_minutes: 15,
  effective_bot_tech: "fakeplayer_next",
  effective_placement_mode: "sidecar",
};

describe("ServerVersioningPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(mockApi.getServerBranches).mockResolvedValue(mockBranches);
    vi.mocked(mockApi.getServerCommits).mockResolvedValue(mockCommits);
    vi.mocked(mockApi.getBotSettings).mockResolvedValue(mockBotSettings);
    vi.mocked(mockApi.getPreflightStatus).mockResolvedValue(mockPreflight);
  });

  const renderPage = () =>
    render(
      <MemoryRouter initialEntries={["/servers/srv-vers-1/versioning"]}>
        <Routes>
          <Route path="/servers/:serverId/versioning" element={<ServerVersioningPage />} />
        </Routes>
      </MemoryRouter>
    );

  it("renders branches, preflight COW status, and commit timeline", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument();
    });

    expect(screen.getByText("Storage Copy-On-Write Capability")).toBeInTheDocument();
    expect(screen.getByText("Active (Reflink / Btrfs / ZFS)")).toBeInTheDocument();
    expect(screen.getByText("Initial baseline configuration")).toBeInTheDocument();
    expect(screen.getByText("c-111222")).toBeInTheDocument();
  });

  it("opens create branch dialog and creates a new branch", async () => {
    vi.mocked(mockApi.createServerBranch).mockResolvedValue({ success: true });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("New Branch")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("New Branch"));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Create New Branch")).toBeInTheDocument();

    const input = screen.getByLabelText("Branch Name");
    fireEvent.change(input, { target: { value: "feat-speed-test" } });

    fireEvent.click(screen.getByRole("button", { name: "Create Branch" }));

    await waitFor(() => {
      expect(mockApi.createServerBranch).toHaveBeenCalledWith("srv-vers-1", {
        name: "feat-speed-test",
      });
    });
  });

  it("opens create commit dialog and saves a snapshot commit", async () => {
    vi.mocked(mockApi.createServerCommit).mockResolvedValue({ success: true, commit_id: "c-new" });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Create Snapshot Commit")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Create Snapshot Commit"));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const input = screen.getByLabelText("Commit Message");
    fireEvent.change(input, { target: { value: "Pre-patch backup" } });

    fireEvent.click(screen.getByRole("button", { name: "Commit Snapshot" }));

    await waitFor(() => {
      expect(mockApi.createServerCommit).toHaveBeenCalledWith("srv-vers-1", {
        message: "Pre-patch backup",
        branch_name: "main",
      });
    });
  });

  it("opens TestRunModal, validates preflight, and launches isolated test", async () => {
    vi.mocked(mockApi.runIsolatedTest).mockResolvedValue({ test_id: "test-run-456" });
    vi.mocked(mockApi.getTestStatus).mockResolvedValue({
      id: "test-run-456",
      server_id: "srv-vers-1",
      commit_id: "c-111222333",
      node_id: "local",
      status: "RUNNING",
      ephemeral_port: 25570,
      log_output: "Server starting...",
      failure_reason: null,
      created_at: "2026-09-14T10:10:00Z",
      expires_at: null,
      bot_count: 10,
      duration_minutes: 15,
      placement_mode: "sidecar",
      bot_tech: "auto",
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Run Isolated Test")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Run Isolated Test"));

    expect(screen.getByText("Launch Isolated Bot Test")).toBeInTheDocument();
    expect(screen.getByLabelText("Verification Bot Count")).toHaveValue(10);

    // Unrestricted input test: enter custom scale
    fireEvent.change(screen.getByLabelText("Verification Bot Count"), {
      target: { value: "50" },
    });
    expect(screen.getByLabelText("Verification Bot Count")).toHaveValue(50);

    fireEvent.click(screen.getByRole("button", { name: "Launch Test Run" }));

    await waitFor(() => {
      expect(mockApi.runIsolatedTest).toHaveBeenCalledWith("srv-vers-1", {
        commit_id: "c-111222333",
        bot_count: 50,
        duration_minutes: 15,
        placement_mode: "sidecar",
        bot_tech: "auto",
      });
    });
  });

  it("promotes a passed test run with keep world changes toggle", async () => {
    vi.mocked(mockApi.promoteTestCommit).mockResolvedValue({ success: true });

    // Pre-populate with a passed test run
    renderPage();

    // Trigger test run addition to state via TestRunModal
    vi.mocked(mockApi.runIsolatedTest).mockResolvedValue({ test_id: "test-pass-99" });
    vi.mocked(mockApi.getTestStatus).mockResolvedValue({
      id: "test-pass-99",
      server_id: "srv-vers-1",
      commit_id: "c-111222333",
      node_id: "local",
      status: "PASSED",
      ephemeral_port: 25571,
      log_output: "[BOT-VERIFY] Complete",
      failure_reason: null,
      created_at: "2026-09-14T10:15:00Z",
      expires_at: null,
      bot_count: 10,
      duration_minutes: 15,
      placement_mode: "sidecar",
      bot_tech: "auto",
    });

    await waitFor(() => {
      expect(screen.getByText("Run Isolated Test")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Run Isolated Test"));
    fireEvent.click(screen.getByRole("button", { name: "Launch Test Run" }));

    await waitFor(() => {
      expect(screen.getByText("Promote to Live")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Promote to Live"));

    expect(screen.getByText("Promote Verified Commit")).toBeInTheDocument();
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Confirm Promotion" }));

    await waitFor(() => {
      expect(mockApi.promoteTestCommit).toHaveBeenCalledWith("srv-vers-1", "test-pass-99", {
        keep_world_changes: true,
      });
    });
  });
});
