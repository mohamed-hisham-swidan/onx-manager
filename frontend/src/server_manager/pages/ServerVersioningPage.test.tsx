import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ServerVersioningPage } from "./ServerVersioningPage";
import type { GitHubConnectionStatusResponse } from "@/server_manager/types";
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
  getGitHubStatus: vi.fn(),
  generateGitHubDeployKey: vi.fn(),
  connectGitHub: vi.fn(),
  rotateGitHubCredentials: vi.fn(),
  disconnectGitHub: vi.fn(),
  fetchGitHubSync: vi.fn(),
  pushGitHubBranch: vi.fn(),
  listGitHubWebhookDeliveries: vi.fn(),
  redeliverGitHubWebhook: vi.fn(),
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

function buildGitHubStatus(
  overrides: Partial<GitHubConnectionStatusResponse> = {},
): GitHubConnectionStatusResponse {
  return {
    server_id: "srv-vers-1",
    connected: true,
    remote_url: "https://github.com/owner/repo.git",
    auth_method: "pat",
    credential_hint: "…abcd",
    deploy_public_key: null,
    webhook_enabled: true,
    webhook_path: "/api/v1/webhooks/github/srv-vers-1",
    sync_status: "synced",
    needs_reauth: false,
    last_error_code: null,
    last_error_message: null,
    last_fetch_at: "2026-09-14T10:00:00Z",
    last_push_at: "2026-09-14T10:05:00Z",
    remote_default_branch: "main",
    remote_head_sha: "cccc3333dddd4444",
    branches: [
      {
        branch: "main",
        status: "synced",
        local_sha: "aaaa1111bbbb2222",
        remote_sha: "aaaa1111bbbb2222",
        ahead_count: 0,
        behind_count: 0,
      },
      {
        branch: "feat-trial",
        status: "ahead",
        local_sha: "eeee5555ffff6666",
        remote_sha: null,
        ahead_count: 2,
        behind_count: 0,
      },
    ],
    created_at: "2026-09-14T09:00:00Z",
    updated_at: "2026-09-14T10:05:00Z",
    generated_webhook_secret: null,
    ...overrides,
  };
}

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
    vi.mocked(mockApi.getGitHubStatus).mockResolvedValue(
      buildGitHubStatus({
        connected: false,
        remote_url: null,
        auth_method: null,
        credential_hint: null,
        webhook_enabled: false,
        webhook_path: null,
        sync_status: "disconnected",
        branches: [],
      }),
    );
    vi.mocked(mockApi.listGitHubWebhookDeliveries).mockResolvedValue([]);
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

    expect(await screen.findByText("Versions & Isolated Testing")).toBeInTheDocument();
    expect(await screen.findByText(/Instant storage cloning: available/i)).toBeInTheDocument();
    expect(screen.getByTitle(/copy-on-write \/ Btrfs \/ ZFS/i)).toBeInTheDocument();
    expect(await screen.findByText("Initial baseline configuration")).toBeInTheDocument();
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
    const rollbackBtn = await screen.findByRole("button", { name: "Rollback" });
    await waitFor(() => expect(rollbackBtn).toBeEnabled());
    await user.click(rollbackBtn);
    await waitFor(() => expect(mockApi.rollbackRefresh).toHaveBeenCalledWith("srv-vers-1", expect.objectContaining({ journal_id: "j1", reason: "operator_requested" })));
  });

  it("clicking Confirm Upgrade calls confirmUpgrade", async () => {
    const user = userEvent.setup();
    renderPage();
    const confirmBtn = await screen.findByRole("button", { name: "Confirm Upgrade" });
    await waitFor(() => expect(confirmBtn).toBeEnabled());
    await user.click(confirmBtn);
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
    const branchSelect = await screen.findByDisplayValue("main");
    fireEvent.change(branchSelect, { target: { value: "feat-trial" } });
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

  it("renders the disconnected GitHub sync panel and opens the connect modal", async () => {
    renderPage();

    const panel = await screen.findByTestId("github-sync-panel");
    expect(within(panel).getByTestId("github-sync-status-badge")).toHaveTextContent(
      "Not Connected",
    );
    fireEvent.click(within(panel).getByRole("button", { name: "Connect GitHub" }));

    expect(
      await screen.findByRole("dialog", { name: "Connect GitHub Repository" }),
    ).toBeInTheDocument();
  });

  it("renders connected GitHub sync state, 1:1 branch indicator, and toolbar pill on branch switch", async () => {
    vi.mocked(mockApi.getGitHubStatus).mockResolvedValue(buildGitHubStatus());

    renderPage();

    const strip = await screen.findByTestId("github-branch-sync-strip");
    const panel = screen.getByTestId("github-sync-panel");
    expect(within(panel).getByTestId("github-sync-status-badge")).toHaveTextContent(
      "Synced",
    );
    expect(
      within(panel).getByText("https://github.com/owner/repo.git"),
    ).toBeInTheDocument();

    expect(strip).toHaveTextContent("Selected Branch (1:1 Sync)");
    expect(strip).toHaveTextContent("main");
    expect(strip).toHaveTextContent("Local aaaa1111");
    expect(screen.getByTestId("branch-github-sync-pill")).toHaveTextContent(
      "GitHub: Synced",
    );

    await switchToTrialBranch();

    await waitFor(() =>
      expect(screen.getByTestId("branch-github-sync-pill")).toHaveTextContent(
        "GitHub: 2 ahead",
      ),
    );
  });

  it("clicking Fetch Now calls fetchGitHubSync and shows success feedback", async () => {
    vi.mocked(mockApi.getGitHubStatus).mockResolvedValue(buildGitHubStatus());
    vi.mocked(mockApi.fetchGitHubSync).mockResolvedValue({
      server_id: "srv-vers-1",
      sync_status: "synced",
      trigger: "manual",
      main_fast_forwarded: true,
      previous_main_sha: "aaaa1111bbbb2222",
      main_sha: "bbbb2222cccc3333",
      remote_default_branch: "main",
      remote_head_sha: "bbbb2222cccc3333",
      branches: [],
      fetched_at: "2026-09-14T10:10:00Z",
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Fetch Now" }));

    await waitFor(() =>
      expect(mockApi.fetchGitHubSync).toHaveBeenCalledWith("srv-vers-1"),
    );
    expect(
      await screen.findByText("Fetched from GitHub and fast-forwarded 'main'."),
    ).toBeInTheDocument();
  });

  it("clicking Push main calls pushGitHubBranch without a force key", async () => {
    vi.mocked(mockApi.getGitHubStatus).mockResolvedValue(buildGitHubStatus());
    vi.mocked(mockApi.pushGitHubBranch).mockResolvedValue({
      server_id: "srv-vers-1",
      branch_name: "main",
      commit_sha: "abcdef1234567890",
      remote_url: "https://github.com/owner/repo.git",
      sync_status: "synced",
      branches: [],
      pushed_at: "2026-09-14T10:15:00Z",
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Push main" }));

    await waitFor(() =>
      expect(mockApi.pushGitHubBranch).toHaveBeenCalledWith("srv-vers-1", {
        branch_name: "main",
      }),
    );
    expect(mockApi.pushGitHubBranch.mock.calls[0][1]).toEqual({
      branch_name: "main",
    });
    expect(
      await screen.findByText(
        "Pushed branch 'main' (abcdef12) to GitHub.",
      ),
    ).toBeInTheDocument();
  });

  it("renders the non-fast-forward main conflict alert with short SHAs", async () => {
    vi.mocked(mockApi.getGitHubStatus).mockResolvedValue(buildGitHubStatus());
    vi.mocked(mockApi.pushGitHubBranch).mockRejectedValue(
      Object.assign(new Error("Non-fast-forward update rejected"), {
        code: "GITHUB_NON_FAST_FORWARD_MAIN",
        status: 409,
        detail: {
          local_sha: "aaaa1111bbbb2222",
          remote_sha: "cccc3333dddd4444",
        },
      }),
    );

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Push main" }));

    const alert = await screen.findByTestId("github-nff-conflict-alert");
    expect(alert).toHaveTextContent("Local: aaaa1111");
    expect(alert).toHaveTextContent("Remote: cccc3333");
    expect(alert).toHaveTextContent("Force-push is disabled to protect server history.");
  });

  it("renders the reauth banner whose CTA opens the rotate credentials modal", async () => {
    vi.mocked(mockApi.getGitHubStatus).mockResolvedValue(buildGitHubStatus());
    vi.mocked(mockApi.pushGitHubBranch).mockRejectedValue(
      Object.assign(new Error("GitHub authentication failed"), {
        code: "GITHUB_AUTH_FAILED",
        status: 409,
        detail: { needs_reauth: true },
      }),
    );

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Push main" }));

    const banner = await screen.findByTestId("github-reauth-banner");
    expect(banner).toHaveTextContent("GitHub authentication failed");
    fireEvent.click(
      within(banner).getByRole("button", {
        name: "Reconnect / Rotate Credentials",
      }),
    );

    expect(
      await screen.findByRole("dialog", {
        name: "Rotate GitHub Credentials & Webhook",
      }),
    ).toBeInTheDocument();
  });

  it("renders the plain .jar push rejection alert with forbidden paths", async () => {
    vi.mocked(mockApi.getGitHubStatus).mockResolvedValue(buildGitHubStatus());
    vi.mocked(mockApi.pushGitHubBranch).mockRejectedValue(
      Object.assign(new Error("Push rejected"), {
        code: "GITHUB_PUSH_REJECTED",
        status: 409,
        detail: {
          branch: "main",
          reason: "plain_jar_blob_forbidden",
          forbidden_paths: ["plugins/Test.jar"],
        },
      }),
    );

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Push main" }));

    const alert = await screen.findByTestId("github-push-rejected-alert");
    expect(alert).toHaveTextContent(
      "Push rejected: plain .jar binaries cannot be pushed to GitHub.",
    );
    expect(alert).toHaveTextContent("plugins/Test.jar");
  });

  it("opens disconnect and webhook deliveries modals, preserving local history feedback", async () => {
    vi.mocked(mockApi.getGitHubStatus).mockResolvedValue(buildGitHubStatus());
    vi.mocked(mockApi.disconnectGitHub).mockResolvedValue({
      server_id: "srv-vers-1",
      disconnected: true,
      remote_url: "https://github.com/owner/repo.git",
      local_history_preserved: true,
      purged_deliveries: 0,
    });

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Webhook Deliveries" }));
    const deliveriesDialog = await screen.findByRole("dialog", {
      name: "GitHub Webhook Deliveries",
    });
    expect(deliveriesDialog).toBeInTheDocument();
    fireEvent.click(
      within(deliveriesDialog).getByRole("button", { name: "Close" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    const disconnectDialog = await screen.findByRole("dialog", {
      name: "Disconnect GitHub Repository",
    });
    expect(
      within(disconnectDialog).getByText(/Local Git history is preserved/i),
    ).toBeInTheDocument();

    fireEvent.click(
      within(disconnectDialog).getByRole("button", {
        name: "Disconnect GitHub",
      }),
    );

    await waitFor(() =>
      expect(mockApi.disconnectGitHub).toHaveBeenCalledWith(
        "srv-vers-1",
        false,
      ),
    );
    expect(
      await screen.findByText(
        "Disconnected from GitHub (local Git history preserved).",
      ),
    ).toBeInTheDocument();
  });
});
