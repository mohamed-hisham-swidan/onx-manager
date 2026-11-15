import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ServerVersioningPage } from "./ServerVersioningPage";
const mockApi = {
  getServerBranches: vi.fn(),
  createServerBranch: vi.fn(),
  getServerCommits: vi.fn(),
  createServerCommit: vi.fn(),
  getServerTestRuns: vi.fn(),
  runIsolatedTest: vi.fn(),
  getTestStatus: vi.fn(),
  promoteTestCommit: vi.fn(),
  discardTest: vi.fn(),
  getBotSettings: vi.fn(),
  updateBotSettings: vi.fn(),
  getPreflightStatus: vi.fn(),
  getServerTags: vi.fn().mockResolvedValue([]),
  getLiveChanges: vi.fn().mockResolvedValue(null),
  getBranchProtection: vi.fn().mockResolvedValue({ is_protected: false, policy: null }),
  getTestDefinitions: vi.fn().mockResolvedValue([]),
  getMaterializations: vi.fn().mockResolvedValue([]),
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
    vi.mocked(mockApi.getServerTestRuns).mockResolvedValue([]);
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

    expect(screen.getByText(/Instant storage cloning: available/i)).toBeInTheDocument();
    expect(screen.getByTitle(/copy-on-write \/ Btrfs \/ ZFS/i)).toBeInTheDocument();
    expect(screen.getByText("Initial baseline configuration")).toBeInTheDocument();
    expect(screen.getByText("c-111222")).toBeInTheDocument();
  });

  it("renders disabled P3 preview controls with Coming soon tooltips", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument();
    });

    const liveRefresh = screen.getByRole("button", { name: "Live Refresh (Coming soon)" });
    const rollback = screen.getByRole("button", { name: "Rollback (Coming soon)" });
    const confirmUpgrade = screen.getByRole("button", { name: "Confirm Upgrade (Coming soon)" });

    for (const control of [liveRefresh, rollback, confirmUpgrade]) {
      expect(control).toBeDisabled();
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).toHaveTextContent("Coming soon");
    }

    expect(liveRefresh).toHaveAttribute("title", "P3 Live Refresh is coming soon");
    expect(rollback).toHaveAttribute("title", "P3 Rollback is coming soon");
    expect(confirmUpgrade).toHaveAttribute("title", "P3 Confirm Upgrade is coming soon");
  });

  it("displays warning state when instant storage cloning is unavailable", async () => {
    vi.mocked(mockApi.getPreflightStatus).mockResolvedValue({
      ...mockPreflight,
      reflink_supported: false,
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/Instant storage cloning: unavailable/i)).toBeInTheDocument();
    });
  });

  it("opens create branch dialog and creates a new branch", async () => {
    vi.mocked(mockApi.createServerBranch).mockResolvedValue({ success: true });

    renderPage();

    await waitFor(() => {
      expect(screen.getAllByText("New Branch")[0]).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByText("New Branch")[0]);

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

  it("renders dark theme classes on empty state panels when branch has no commits", async () => {
    vi.mocked(mockApi.getServerCommits).mockResolvedValue([]);
    renderPage();

    await waitFor(() => {
      expect(
        screen.getByText(/No snapshot commits yet on branch/i)
      ).toBeInTheDocument();
    });

    // Verify empty state container has dark:bg-gray-800 and not dark:bg-gray-850
    const emptyCommitMsg = screen.getByText(/No snapshot commits yet on branch/i);
    const commitPanel = emptyCommitMsg.closest(".rounded-xl");
    expect(commitPanel).not.toBeNull();
    expect(commitPanel).toHaveClass("dark:bg-gray-800");
    expect(commitPanel?.className).not.toContain("gray-850");

    // Verify isolated test runs empty state container has dark:bg-gray-800 and not dark:bg-gray-850
    const emptyTestMsg = screen.getByText(/No isolated test runs active or recorded/i);
    const testPanel = emptyTestMsg.closest(".rounded-xl");
    expect(testPanel).not.toBeNull();
    expect(testPanel).toHaveClass("dark:bg-gray-800");
    expect(testPanel?.className).not.toContain("gray-850");
  });

  it("displays recorded test runs and opens console logs modal", async () => {
    const mockRuns = [
      {
        id: "test-run-123456",
        server_id: "srv-vers-1",
        commit_id: "c-111222333",
        status: "PASSED",
        bot_count: 10,
        bot_tech: "mineflayer",
        duration_minutes: 15,
        placement_mode: "sidecar",
        ephemeral_port: 25566,
        failure_reason: null,
        log_output: "[STARTUP] Spawning test container\n[TEST] 10/10 bots joined\n[DONE] Verification passed",
        created_at: "2026-09-15T10:00:00Z",
      },
    ];
    vi.mocked(mockApi.getServerTestRuns).mockResolvedValue(mockRuns);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("1 runs recorded")).toBeInTheDocument();
      expect(screen.getByText("ID: test-run")).toBeInTheDocument();
      expect(screen.getByText("PASSED")).toBeInTheDocument();
    });

    const logsBtn = screen.getByRole("button", { name: "Logs" });
    fireEvent.click(logsBtn);

    expect(screen.getByText(/Test Run Console Output/i)).toBeInTheDocument();
    expect(screen.getByText(/10\/10 bots joined/i)).toBeInTheDocument();

    const closeButtons = screen.getAllByRole("button", { name: "Close" });
    fireEvent.click(closeButtons[0]);
    expect(screen.queryByText(/Test Run Console Output/i)).not.toBeInTheDocument();
  });

  it("allows force promoting a failed test run with mandatory bypass reason", async () => {
    const mockFailedRuns = [
      {
        id: "test-fail-999999",
        server_id: "srv-vers-1",
        commit_id: "c-111222333",
        status: "FAILED",
        bot_count: 5,
        bot_tech: "fakeplayer_next",
        duration_minutes: 10,
        placement_mode: "sidecar",
        ephemeral_port: 25567,
        failure_reason: "Handshake timed out",
        log_output: "Handshake error",
        created_at: "2026-09-15T10:05:00Z",
      },
    ];
    vi.mocked(mockApi.getServerTestRuns).mockResolvedValue(mockFailedRuns);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("FAILED")).toBeInTheDocument();
      expect(screen.getByText(/Handshake timed out/i)).toBeInTheDocument();
    });

    const forceBtn = screen.getByRole("button", { name: /Force Promote/i });
    expect(forceBtn).toBeInTheDocument();
    fireEvent.click(forceBtn);

    expect(screen.getByText("Force Promotion Override")).toBeInTheDocument();
    expect(screen.getByText(/server:version:promote:force/i)).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: "Confirm Force Promotion" });
    expect(confirmBtn).toBeDisabled();

    const reasonInput = screen.getByLabelText(/Bypass Reason/i);
    fireEvent.change(reasonInput, { target: { value: "Manually verified in local client" } });
    expect(confirmBtn).not.toBeDisabled();

    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockApi.promoteTestCommit).toHaveBeenCalledWith("srv-vers-1", "test-fail-999999", {
        keep_world_changes: false,
        force: true,
        force_reason: "Manually verified in local client",
      });
    });
  });

  it("renders 3-step visual workflow guide banner collapsed by default and allows expanding and collapsing", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("3-Step Safe Testing & Promotion Workflow")).toBeInTheDocument();
    });

    // Collapsed by default: steps not visible
    expect(screen.queryByText("Step 1: Snapshot World (Commit)")).not.toBeInTheDocument();
    const expandBtn = screen.getByRole("button", { name: /Expand Guide/i });
    expect(expandBtn).toBeInTheDocument();

    // Toggle expand: steps are visible as documentation
    fireEvent.click(expandBtn);
    expect(screen.getByText("Step 1: Snapshot World (Commit)")).toBeInTheDocument();
    expect(screen.getByText("Step 2: Isolate (Branch / Worktree)")).toBeInTheDocument();
    expect(screen.getByText("Step 3: Automated Bot Dry-Run (Verify)")).toBeInTheDocument();

    // No duplicate action buttons inside guide
    expect(screen.queryByRole("button", { name: "Create Snapshot" })).not.toBeInTheDocument();

    // Toggle collapse
    const collapseBtn = screen.getByRole("button", { name: /Collapse Guide/i });
    fireEvent.click(collapseBtn);
    expect(screen.queryByText("Step 1: Snapshot World (Commit)")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Expand Guide/i })).toBeInTheDocument();
  });

  it("groups secondary commit actions in More commit actions menu while keeping primary test action visible", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Initial baseline configuration")).toBeInTheDocument();
    });

    // Primary action visible
    expect(screen.getByRole("button", { name: "Run Isolated Test" })).toBeInTheDocument();

    // Secondary actions initially not in DOM
    expect(screen.queryByRole("button", { name: "Tag" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Inspect Manifest" })).not.toBeInTheDocument();

    // Open More commit actions menu
    const moreBtn = screen.getByRole("button", { name: "More commit actions" });
    fireEvent.click(moreBtn);

    // Secondary actions now visible
    expect(screen.getByRole("button", { name: "Tag" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect Manifest" })).toBeInTheDocument();
  });

  it("displays live summary badge counts, re-run button, and allows re-running test from run list", async () => {
    const mockRuns = [
      {
        id: "test-run-passed-1",
        server_id: "srv-vers-1",
        commit_id: "c-111222333",
        status: "PASSED",
        bot_count: 10,
        bot_tech: "fakeplayer_next",
        duration_minutes: 15,
        placement_mode: "sidecar",
        ephemeral_port: 25566,
        failure_reason: null,
        log_output: "All ok",
        created_at: "2026-09-15T10:00:00Z",
      },
      {
        id: "test-run-active-2",
        server_id: "srv-vers-1",
        commit_id: "c-111222333",
        status: "RUNNING",
        bot_count: 5,
        bot_tech: "auto",
        duration_minutes: 10,
        placement_mode: "sidecar",
        ephemeral_port: 25568,
        failure_reason: null,
        log_output: "Running swarm",
        created_at: "2026-09-15T10:10:00Z",
      },
    ];
    vi.mocked(mockApi.getServerTestRuns).mockResolvedValue(mockRuns);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("1 Passed")).toBeInTheDocument();
      expect(screen.getByText("1 Running / Pending")).toBeInTheDocument();
    });

    // Cancel Run button for active run
    expect(screen.getByRole("button", { name: /Cancel Run/i })).toBeInTheDocument();

    // Re-run button for test run
    const reRunBtns = screen.getAllByRole("button", { name: /Re-run/i });
    expect(reRunBtns.length).toBeGreaterThan(0);
    fireEvent.click(reRunBtns[0]);

    // Opens Launch Isolated Bot Test modal
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: "Launch Isolated Bot Test" })).toBeInTheDocument();
    });
  });
});
