import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  discardTest: vi.fn(),
  getBotSettings: vi.fn(),
  updateBotSettings: vi.fn(),
  getPreflightStatus: vi.fn(),
  getServerTags: vi.fn().mockResolvedValue([]),
  getLiveChanges: vi.fn().mockResolvedValue(null),
  getBranchProtection: vi.fn().mockResolvedValue({ is_protected: false, policy: null }),
  getTestDefinitions: vi.fn().mockResolvedValue([]),
  getMaterializations: vi.fn().mockResolvedValue([]),
  getRefreshState: vi.fn().mockResolvedValue({ server_id: "srv-vers-1", active_journal: null, latest_journal: { journal_id: "j1", class_c_snapshot_id: "snap1", phase: "done" }, can_confirm_upgrade: true, can_rollback: true, previous_tree_retention: "until_health_gate" }),
  refreshServer: vi.fn().mockResolvedValue({ server_id: "srv-vers-1", journal_id: "j1", phase: "done", status: "ok" }),
  rollbackRefresh: vi.fn().mockResolvedValue({ server_id: "srv-vers-1", journal_id: "j1", phase: "rolled_back", status: "ok" }),
  confirmUpgrade: vi.fn().mockResolvedValue({ server_id: "srv-vers-1", journal_id: "j1", phase: "confirmed", status: "ok" }),
  releaseRefreshPins: vi.fn().mockResolvedValue({ server_id: "srv-vers-1", journal_id: "j1", phase: "done", status: "ok" }),
  listClassCSnapshots: vi.fn().mockResolvedValue([{ snapshot_id: "snap1", server_id: "srv-vers-1", created_at: "2024", manifest_sha256: "abcd", pinned: false, entry_count: 1, archive_size_bytes: 10 }]),
  listDynamicClassC: vi.fn().mockResolvedValue([{ server_id: "srv-vers-1", relpath: "whitelist.json", promoted_at: "2024", main_commit_sha: "sha" }]),
  listSecrets: vi.fn().mockResolvedValue([{ server_id: "srv-vers-1", key_name: "DB_PASSWORD", placeholder: "${ONX_SECRET_DB_PASSWORD}", kek_version: 1, created_at: "2024", updated_at: "2024" }]),
  mergeServerCommits: vi.fn().mockResolvedValue({ commit_id: "m1", server_id: "srv-vers-1", branch_name: "main", parent_commit_ids: [], warnings: ["lossy"] }),
  extractSecret: vi.fn().mockResolvedValue({ server_id: "srv-vers-1", branch: "dev", path: "config.yml", key_name: "DB_PASSWORD", placeholder: "${ONX_SECRET_DB_PASSWORD}", replaced_occurrences: 1, remaining_findings: [] }),
  listDataTemplates: vi.fn(),
  createDataTemplate: vi.fn(),
  deleteDataTemplate: vi.fn(),
  saveBranchDataTemplate: vi.fn(),
  allocateBranchPortSet: vi.fn(),
  setBranchPortSet: vi.fn(),
  getBranchRuntime: vi.fn(),
  startBranchRun: vi.fn(),
  stopBranchRun: vi.fn(),
  getBranchConsole: vi.fn(),
  sendBranchConsoleCommand: vi.fn(),
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
  previous_tree_retention: "until_health_gate",
};

describe("ServerVersioningPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(mockApi.getServerBranches).mockResolvedValue(mockBranches);
    vi.mocked(mockApi.getServerCommits).mockResolvedValue(mockCommits);
    vi.mocked(mockApi.getBotSettings).mockResolvedValue(mockBotSettings);
    vi.mocked(mockApi.getPreflightStatus).mockResolvedValue(mockPreflight);
    vi.mocked(mockApi.getServerTestRuns).mockResolvedValue([]);
    vi.mocked(mockApi.listDataTemplates).mockResolvedValue([]);
    vi.mocked(mockApi.getBranchRuntime).mockResolvedValue(null);
    vi.mocked(mockApi.getBranchConsole).mockResolvedValue({
      server_id: "srv-vers-1",
      branch_name: "feat-trial",
      runtime_id: "rt-1",
      container_name: "onx-feat-trial",
      lines: ["[INFO] Branch container ready"],
    });
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

  it("renders active P3 controls", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: "Live Refresh" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rollback" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm Upgrade" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Class-C & Secret Vault" })).toBeInTheDocument();
    expect(screen.getByText("Merge Branch")).toBeInTheDocument();
  });

  it("clicking Live Refresh calls refreshServer", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Live Refresh" }));
    await waitFor(() => expect(mockApi.refreshServer).toHaveBeenCalledWith("srv-vers-1", expect.objectContaining({ retention_policy: "until_health_gate" })));
  });

  it("clicking Rollback calls rollbackRefresh when can_rollback", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Rollback" }));
    await waitFor(() => expect(mockApi.rollbackRefresh).toHaveBeenCalledWith("srv-vers-1", expect.objectContaining({ journal_id: "j1", reason: "operator_requested" })));
  });

  it("clicking Confirm Upgrade calls confirmUpgrade", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Confirm Upgrade" }));
    await waitFor(() => expect(mockApi.confirmUpgrade).toHaveBeenCalledWith("srv-vers-1", expect.objectContaining({ journal_id: "j1" })));
  });

  it("Merge Branch modal submits and shows warnings/conflicts", async () => {
    const user = userEvent.setup();
    mockApi.mergeServerCommits.mockRejectedValueOnce(Object.assign(new Error("conflict"), { detail: { conflicts: [{ path: "a", key_path: "k", base: "b", ours: "o", theirs: "t" }], findings: [{ x: 1 }] } }));
    renderPage();
    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());
    await user.click(screen.getByText("Merge Branch"));
    const modal = await screen.findByRole("dialog", { name: "Merge Branch" });
    expect(modal).toBeInTheDocument();
    // submit
    await user.click(screen.getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(mockApi.mergeServerCommits).toHaveBeenCalled());
    expect(screen.getByText(/a k b o t/)).toBeInTheDocument();
    expect(screen.getByText(/\{"x":1\}/)).toBeInTheDocument();
  });

  it("Previous Tree Retention Policy saves previous_tree_retention", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Verification Defaults" }));
    const select = await screen.findByLabelText("Previous Tree Retention Policy");
    await user.selectOptions(select, "24h");
    await user.click(screen.getByRole("button", { name: "Save Defaults" }));
    await waitFor(() => expect(mockApi.updateBotSettings).toHaveBeenCalledWith("srv-vers-1", expect.objectContaining({ previous_tree_retention: "24h" })));
  });

  it("Class-C & Secret Vault modal lists and extracts secret clearing password", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Class-C & Secret Vault" }));
    expect(await screen.findByText("snap1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dynamic Class-C" }));
    expect(await screen.findByRole("button", { name: "Reset to Class B (Track from main)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Secrets" }));
    expect(await screen.findByText(/\$\{ONX_SECRET_DB_PASSWORD\}/)).toBeInTheDocument();
    const pwd = screen.getByPlaceholderText("Secret Plaintext Value") as HTMLInputElement;
    await user.type(pwd, "secret");
    expect(pwd.value).toBe("secret");
    await user.click(screen.getByRole("button", { name: "Extract Secret" }));
    await waitFor(() => expect(pwd.value).toBe(""));
    expect(mockApi.extractSecret).toHaveBeenCalled();
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

  const switchToTrialBranch = async () => {
    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());
    fireEvent.change(screen.getByDisplayValue("main"), { target: { value: "feat-trial" } });
    return screen.findByTestId("branch-run-panel");
  };

  it("hides the Branch Run Panel on main and shows it after switching to feat-trial", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());
    expect(screen.queryByTestId("branch-run-panel")).not.toBeInTheDocument();

    const panel = await switchToTrialBranch();

    expect(panel).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Branch Run" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Branch Console" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Branch Activity" })).toBeInTheDocument();
  });

  it("shows the Spec K uncommitted changes warning after starting a branch run and refreshes runtime", async () => {
    mockApi.startBranchRun.mockResolvedValue({
      runtime_id: "rt-1",
      server_id: "srv-vers-1",
      branch_name: "feat-trial",
      commit_sha: "deadbeef12345678",
      container_name: "onx-feat-trial",
      container_id: "c-1",
      port_set: { game_port: 25610, rcon_port: 25611 },
      data_template_id: null,
      allow_public_test_join: false,
      uncommitted_changes_warning: true,
      memory_max_mb: 2048,
      cpu_cores: 2,
    });

    renderPage();
    await switchToTrialBranch();
    const callsBeforeStart = mockApi.getBranchRuntime.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Start Branch Run" }));
    const dialog = await screen.findByRole("dialog", { name: "Start Branch Run" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Start Branch Run" }));

    await waitFor(() => {
      expect(mockApi.startBranchRun).toHaveBeenCalledWith(
        "srv-vers-1",
        "feat-trial",
        expect.objectContaining({ allow_public_test_join: false }),
      );
    });

    const warning = await screen.findByTestId("uncommitted-changes-warning");
    expect(warning).toHaveTextContent("Uncommitted changes in worktree were not included");
    expect(warning).toHaveTextContent("deadbeef");
    await waitFor(() => {
      expect(mockApi.getBranchRuntime.mock.calls.length).toBeGreaterThan(callsBeforeStart);
    });
  });

  it("renders running status, pinned commit, worktree lock, and copyable port set", async () => {
    mockApi.getBranchRuntime.mockResolvedValue({
      server_id: "srv-vers-1",
      branch_name: "feat-trial",
      runtime_status: "running",
      runtime_id: "rt-1",
      active_commit_sha: "abcdef1234567890",
      data_template_id: null,
      allow_public_test_join: false,
      container_liveness: true,
      port_set: {
        game_port: 25610,
        rcon_port: 25611,
        query_port: 25612,
        plugin_ports: { dynmap: 25613 },
      },
      worktree_locked: true,
      worktree_lock_reason: "Active branch runtime",
    });

    renderPage();
    await switchToTrialBranch();

    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText("Commit abcdef12")).toBeInTheDocument();
    expect(screen.getByTestId("worktree-lock-badge")).toBeInTheDocument();
    expect(screen.getByText("Game: 25610")).toBeInTheDocument();
    expect(screen.getByText("RCON: 25611")).toBeInTheDocument();
    expect(screen.getByText("Query: 25612")).toBeInTheDocument();
    expect(screen.getByText("dynmap: 25613")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy join port" })).toBeInTheDocument();
  });

  it("opens the Data Templates modal from the P4 toolbar and lists templates", async () => {
    vi.mocked(mockApi.listDataTemplates).mockResolvedValue([
      {
        id: "tpl-1",
        server_id: "srv-vers-1",
        name: "seed-1",
        description: "Known good world",
        source_branch_name: null,
        source_commit_sha: null,
        file_count: 12,
        total_bytes: 1024,
        status: "ready",
        operation_id: null,
        created_at: "2026-09-14T10:00:00Z",
        updated_at: "2026-09-14T10:00:00Z",
      },
    ]);

    renderPage();
    await waitFor(() => expect(screen.getByText("Versions & Isolated Testing")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Data Templates" }));

    expect(await screen.findByRole("dialog", { name: "Data Templates" })).toBeInTheDocument();
    expect(await screen.findByText("seed-1")).toBeInTheDocument();
    expect(screen.getByText("12 files")).toBeInTheDocument();
  });

  it("opens the Branch Console & Activity modal scoped to feat-trial", async () => {
    mockApi.getBranchRuntime.mockResolvedValue({
      server_id: "srv-vers-1",
      branch_name: "feat-trial",
      runtime_status: "running",
      runtime_id: "rt-1",
      active_commit_sha: "abcdef1234567890",
      data_template_id: null,
      allow_public_test_join: false,
      container_liveness: true,
      port_set: null,
      worktree_locked: false,
      worktree_lock_reason: null,
    });

    renderPage();
    await switchToTrialBranch();
    await screen.findByText("Running");

    fireEvent.click(screen.getByRole("button", { name: "Branch Console" }));

    expect(
      await screen.findByRole("dialog", { name: "Branch Console & Activity" }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(mockApi.getBranchConsole).toHaveBeenCalledWith("srv-vers-1", "feat-trial", 200);
    });
    expect(await screen.findByTestId("branch-console-output")).toHaveTextContent(
      "[INFO] Branch container ready",
    );
  });
});
