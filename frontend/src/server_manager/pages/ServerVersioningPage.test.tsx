import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { ServerVersioningPage } from "./ServerVersioningPage";
import type {
  GitHubConnectionStatusResponse,
  ServerMode,
} from "@/server_manager/types";

const mockAuthState = {
  canViewVersioning: true,
  canVersioning: true,
};

vi.mock("@/hooks/useAuthPermissions", () => ({
  useAuthPermissions: () => ({
    canViewVersioning: () => mockAuthState.canViewVersioning,
    canVersioning: () => mockAuthState.canVersioning,
  }),
}));

const mockApi = {
  getServer: vi.fn(),
  getServerBranches: vi.fn(),
  createServerBranch: vi.fn(),
  deleteServerBranch: vi.fn(),
  archiveBranch: vi.fn(),
  getServerCommits: vi.fn(),
  createServerCommit: vi.fn(),
  diffCommits: vi.fn(),
  getBotSettings: vi.fn(),
  updateBotSettings: vi.fn(),
  getServerTags: vi.fn().mockResolvedValue([]),
  createTag: vi.fn(),
  getLiveChanges: vi.fn().mockResolvedValue({ changes: [], auto_commit: null }),
  getBranchProtection: vi.fn().mockResolvedValue({ is_protected: false, policy: null }),
  getRefreshState: vi.fn(),
  refreshServer: vi.fn(),
  rollbackRefresh: vi.fn(),
  confirmUpgrade: vi.fn(),
  releaseRefreshPins: vi.fn(),
  listClassCSnapshots: vi.fn().mockResolvedValue([]),
  createClassCSnapshot: vi.fn(),
  restoreClassCSnapshot: vi.fn(),
  deleteClassCSnapshot: vi.fn(),
  listDynamicClassC: vi.fn().mockResolvedValue([]),
  resetDynamicClassC: vi.fn(),
  listSecrets: vi.fn().mockResolvedValue([]),
  extractSecret: vi.fn(),
  deleteSecret: vi.fn(),
  mergeServerCommits: vi.fn(),
  listDataTemplates: vi.fn(),
  createDataTemplate: vi.fn(),
  deleteDataTemplate: vi.fn(),
  saveBranchDataTemplate: vi.fn(),
  allocateBranchPortSet: vi.fn(),
  setBranchPortSet: vi.fn(),
  getBranchRuntime: vi.fn(),
  startBranchRun: vi.fn(),
  stopBranchRun: vi.fn(),
  destroyBranchRun: vi.fn(),
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
    head_commit_id: "c-111222333",
    created_at: "2026-09-14T10:00:00Z",
    status: "active",
    is_protected: true,
  },
  {
    id: "b-trial",
    server_id: "srv-vers-1",
    name: "feat-trial",
    head_commit_id: "c-444555666",
    created_at: "2026-09-14T11:00:00Z",
    status: "active",
    is_protected: false,
    runtime_status: "running",
    container_provisioned: true,
    active_commit_sha: "abcdef1234567890",
    port_set: {
      game_port: 25610,
      rcon_port: 25611,
      query_port: 25612,
      plugin_ports: {},
    },
    worktree_locked: true,
  },
  {
    id: "b-cleanup",
    server_id: "srv-vers-1",
    name: "feat-cleanup",
    head_commit_id: "c-777888999",
    created_at: "2026-09-14T11:30:00Z",
    status: "active",
    is_protected: false,
    runtime_status: "stopped",
    container_provisioned: false,
    port_set: null,
    worktree_locked: false,
  },
];

const mockCommits = [
  {
    id: "c-111222333",
    server_id: "srv-vers-1",
    branch_id: "b-main",
    parent_commit_id: "c-000111222",
    parent_commit_ids: ["c-000111222"],
    author_id: "admin",
    message: "Initial baseline configuration",
    manifest: {
      server_type: "ServerType.PURPUR",
      minecraft_version: "1.21.1",
      configs: {},
      mods: [],
      env_vars: {},
      java_args: "-Xmx4G",
    },
    world_snapshot_id: null,
    created_at: "2026-09-14T10:05:00Z",
  },
  {
    id: "c-000111222",
    server_id: "srv-vers-1",
    branch_id: "b-other-branch",
    parent_commit_id: null,
    parent_commit_ids: [],
    author_id: "123e4567-e89b-12d3-a456-426614174000",
    message: "Merged ancestor commit",
    manifest: {
      server_type: "purpur",
      minecraft_version: "1.21.1",
      configs: {},
      mods: [],
      env_vars: {},
      java_args: "",
    },
    world_snapshot_id: null,
    created_at: "2026-09-14T09:05:00Z",
  },
];

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
  previous_tree_retention: "until_confirm",
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
    mockAuthState.canViewVersioning = true;
    mockAuthState.canVersioning = true;
    mockApi.getServer.mockResolvedValue({
      server_id: "srv-vers-1",
      name: "Purpur Main",
      server_type: "purpur",
      minecraft_version: "1.21.1",
      mode: "advanced",
    });
    mockApi.getServerBranches.mockResolvedValue(mockBranches);
    mockApi.getServerCommits.mockResolvedValue(mockCommits);
    mockApi.getBotSettings.mockResolvedValue(mockBotSettings);
    mockApi.listDataTemplates.mockResolvedValue([]);
    mockApi.getBranchRuntime.mockResolvedValue(null);
    mockApi.diffCommits.mockResolvedValue({
      from_commit_id: "main",
      to_commit_id: "feat-trial",
      has_changes: true,
      configs: { added: ["config/new.yml"], modified: ["server.properties"], removed: [] },
      mods: { added: [], removed: [], modified: [] },
      env_vars: { added: {}, removed: {}, modified: {} },
      server_type: null,
      minecraft_version: null,
      java_args: null,
    });
    mockApi.getRefreshState.mockResolvedValue({
      server_id: "srv-vers-1",
      active_journal: null,
      latest_journal: {
        journal_id: "j1",
        server_id: "srv-vers-1",
        phase: "COMPLETED",
        terminal: true,
        target_main_sha: "c-111222333",
        previous_main_sha: "c-000111222",
        class_c_snapshot_id: "snap1",
        previous_dir: "/tmp/prev",
        retention_policy: "until_confirm",
        retain_until: null,
        rollback_reason: null,
        error_detail: null,
        created_at: "2026-09-14T10:00:00Z",
        updated_at: "2026-09-14T10:01:00Z",
      },
      can_confirm_upgrade: true,
      can_rollback: true,
      previous_tree_retention: "until_confirm",
    });
    mockApi.refreshServer.mockResolvedValue({
      server_id: "srv-vers-1",
      journal_id: "j2",
      phase: "COMPLETED",
      status: "ok",
    });
    mockApi.rollbackRefresh.mockResolvedValue({
      server_id: "srv-vers-1",
      journal_id: "j1",
      phase: "ROLLED_BACK",
      status: "ok",
    });
    mockApi.confirmUpgrade.mockResolvedValue({
      server_id: "srv-vers-1",
      journal_id: "j1",
      phase: "UPGRADE_CONFIRMED",
      status: "ok",
    });
    mockApi.releaseRefreshPins.mockResolvedValue({
      server_id: "srv-vers-1",
      journal_id: "j1",
      phase: "ROLLED_BACK",
      status: "ok",
    });
    mockApi.deleteServerBranch.mockResolvedValue({ deleted: true });
    mockApi.mergeServerCommits.mockResolvedValue({
      commit_id: "m1",
      server_id: "srv-vers-1",
      branch_name: "main",
      parent_commit_ids: ["c-111222333", "c-444555666"],
      warnings: [],
    });
    mockApi.getBranchConsole.mockResolvedValue({
      server_id: "srv-vers-1",
      branch_name: "feat-trial",
      runtime_id: "rt-1",
      container_name: "onx-feat-trial",
      lines: ["[INFO] Branch container ready"],
    });
    mockApi.getGitHubStatus.mockResolvedValue(
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
    mockApi.listGitHubWebhookDeliveries.mockResolvedValue([]);
    mockApi.listClassCSnapshots.mockResolvedValue([
      {
        snapshot_id: "snap1",
        server_id: "srv-vers-1",
        created_at: "2026-09-14T10:00:00Z",
        manifest_sha256: "abcd1234",
        pinned: false,
        entry_count: 1,
        archive_size_bytes: 2048,
      },
    ]);
    mockApi.listDynamicClassC.mockResolvedValue([
      {
        server_id: "srv-vers-1",
        relpath: "whitelist.json",
        promoted_at: "2026-09-14T10:00:00Z",
        main_commit_sha: "c-111222333",
      },
    ]);
    mockApi.listSecrets.mockResolvedValue([
      {
        server_id: "srv-vers-1",
        key_name: "DB_PASSWORD",
        placeholder: "${ONX_SECRET_DB_PASSWORD}",
        kek_version: 1,
        created_at: "2026-09-14T10:00:00Z",
        updated_at: "2026-09-14T10:00:00Z",
      },
    ]);
    mockApi.extractSecret.mockResolvedValue({
      server_id: "srv-vers-1",
      branch: "feat-trial",
      path: "config.yml",
      key_name: "DB_PASSWORD",
      placeholder: "${ONX_SECRET_DB_PASSWORD}",
      replaced_occurrences: 1,
      remaining_findings: [],
    });
  });

  const renderPage = (
    initialUrl = "/servers/srv-vers-1/versioning",
    options?: { serverMode?: ServerMode; initialBranch?: string },
  ) => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const setBranch = vi.fn();
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[initialUrl]}>
          <ServerBranchContext.Provider
            value={{
              branch: options?.initialBranch ?? "main",
              setBranch,
              gitBacked: true,
              serverMode: options?.serverMode ?? "advanced",
            }}
          >
            <Routes>
              <Route
                path="/servers/:serverId/versioning"
                element={<ServerVersioningPage />}
              />
              <Route
                path="/servers/:serverId/settings"
                element={<div data-testid="settings-route">Settings</div>}
              />
              <Route
                path="/servers/:serverId/files"
                element={<div data-testid="files-route">Files</div>}
              />
              <Route
                path="/servers/:serverId/console"
                element={<div data-testid="console-route">Console</div>}
              />
            </Routes>
          </ServerBranchContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  };

  it("renders the clean 3-tab cockpit with branches & sandboxes visible immediately on landing", async () => {
    renderPage();

    expect(await screen.findByTestId("production-branch-card")).toBeInTheDocument();
    expect(screen.getByText("Versions & Sandboxes")).toBeInTheDocument();
    expect(screen.getByTestId("branch-card-feat-trial")).toBeInTheDocument();
    expect(screen.getByText("Game: 25610")).toBeInTheDocument();
    expect(screen.getByText("RCON: 25611")).toBeInTheDocument();
    expect(screen.queryByText(/3-Step Safe Testing/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Uncommitted Live Server Changes/i)).not.toBeInTheDocument();
  });

  it("enforces Simple Mode guard and fires zero versioning API calls", async () => {
    renderPage("/servers/srv-vers-1/versioning", { serverMode: "simple" });

    expect(
      await screen.findByTestId("versioning-simple-mode-guard"),
    ).toBeInTheDocument();
    expect(mockApi.getServerBranches).not.toHaveBeenCalled();
    expect(mockApi.getServerCommits).not.toHaveBeenCalled();
    expect(mockApi.getRefreshState).not.toHaveBeenCalled();
  });

  it("enforces RBAC v2 read-only mode when canVersioning is false", async () => {
    mockAuthState.canVersioning = false;
    renderPage();

    expect(
      await screen.findByTestId("versioning-readonly-badge"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New Branch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deploy main to Live" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Merge to main" })).not.toBeInTheDocument();
  });

  it("deploys main to live with until_confirm default and supports Undo Last Deploy", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Deploy main to Live" }));
    const deployDialog = await screen.findByRole("dialog", {
      name: "Deploy main to Live Server",
    });
    await user.click(within(deployDialog).getByRole("button", { name: "Deploy to Live" }));

    await waitFor(() => {
      expect(mockApi.refreshServer).toHaveBeenCalledWith("srv-vers-1", {
        retention_policy: "until_confirm",
      });
    });

    await user.click(screen.getByRole("button", { name: "Undo Last Deploy" }));
    const undoDialog = await screen.findByRole("dialog", {
      name: "Undo Last Live Deployment?",
    });
    await user.click(within(undoDialog).getByRole("button", { name: "Undo Last Deploy" }));
    await waitFor(() => {
      expect(mockApi.rollbackRefresh).toHaveBeenCalledWith("srv-vers-1", {
        journal_id: "j1",
        reason: "operator_requested",
      });
    });
  });

  it("shows all commits without stripping ancestor commits and formats ServerType.PURPUR cleanly", async () => {
    const user = userEvent.setup();
    renderPage("/servers/srv-vers-1/versioning?tab=snapshots");

    expect(await screen.findByText("Initial baseline configuration")).toBeInTheDocument();
    expect(screen.getByText("Merged ancestor commit")).toBeInTheDocument();
    expect(screen.queryByText(/ServerType\.PURPUR/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Purpur 1.21.1").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/123e4567-e89b/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Inspect Manifest" })).not.toBeInTheDocument();

    // Restore to Live on non-live ancestor commit passes target_main_sha + until_confirm
    await user.click(screen.getByRole("button", { name: "Restore to Live" }));
    const restoreDialog = await screen.findByRole("dialog", {
      name: "Restore Snapshot to Live Server",
    });
    await user.click(within(restoreDialog).getByRole("button", { name: "Restore to Live" }));

    await waitFor(() => {
      expect(mockApi.refreshServer).toHaveBeenCalledWith("srv-vers-1", {
        retention_policy: "until_confirm",
        target_main_sha: "c-000111222",
      });
    });
  });

  it("opens Test in Sandbox with commit_sha on non-main branches", async () => {
    const user = userEvent.setup();
    renderPage("/servers/srv-vers-1/versioning?tab=snapshots", {
      initialBranch: "feat-trial",
    });

    const testBtns = await screen.findAllByRole("button", { name: "Test in Sandbox" });
    await user.click(testBtns[0]);
    const dialog = await screen.findByRole("dialog", { name: "Start Branch Run" });
    expect(within(dialog).getByText(/Testing historical snapshot/i)).toBeInTheDocument();

    mockApi.startBranchRun.mockResolvedValueOnce({
      runtime_id: "rt-2",
      server_id: "srv-vers-1",
      branch_name: "feat-trial",
      commit_sha: "c-111222333",
      container_name: "onx-feat-trial",
      container_id: "c-2",
      port_set: { game_port: 25610, rcon_port: 25611 },
      data_template_id: null,
      allow_public_test_join: false,
      uncommitted_changes_warning: false,
      memory_max_mb: 2048,
      cpu_cores: 2,
    });
    await user.click(within(dialog).getByRole("button", { name: "Start Branch Run" }));

    await waitFor(() => {
      expect(mockApi.startBranchRun).toHaveBeenCalledWith(
        "srv-vers-1",
        "feat-trial",
        expect.objectContaining({ commit_sha: "c-111222333" }),
      );
    });
  });

  it("previews merge diff, renders structured conflicts, and prompts to deploy after merge", async () => {
    const user = userEvent.setup();
    renderPage();

    const mergeBtns = await screen.findAllByRole("button", { name: "Merge to main" });
    await user.click(mergeBtns[0]);
    const dialog = await screen.findByRole("dialog", { name: "Merge Branch" });

    await waitFor(() => {
      expect(mockApi.diffCommits).toHaveBeenCalledWith("srv-vers-1", "main", "feat-trial");
    });
    expect(within(dialog).getByText(/config files changed/i)).toBeInTheDocument();

    // First attempt: conflict + finding
    mockApi.mergeServerCommits.mockRejectedValueOnce(
      Object.assign(new Error("Merge conflict"), {
        detail: {
          conflicts: [{ path: "server.properties", key_path: "motd", base: "b", ours: "o", theirs: "t" }],
          findings: [{ path: "config.yml", pattern: "api_key", message: "Exposed secret" }],
        },
      }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Merge Branch" }));

    expect(await within(dialog).findByText(/Merge Conflicts Detected/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Secret Scan Blocked Merge/i)).toBeInTheDocument();

    // Second attempt: success -> offers Deploy main to Live Now
    await user.click(within(dialog).getByRole("button", { name: "Merge Branch" }));
    expect(
      await within(dialog).findByRole("button", { name: "Deploy main to Live Now" }),
    ).toBeInTheDocument();
  });

  it("supports Delete Branch from branch overflow menu while blocking active sandboxes", async () => {
    const user = userEvent.setup();
    renderPage();

    // Running sandbox branch disables Delete Branch
    await user.click(
      await screen.findByRole("button", { name: "More actions for feat-trial" }),
    );
    expect(screen.getByRole("button", { name: "Delete Branch" })).toBeDisabled();

    // Stopped branch allows Delete Branch
    await user.click(
      screen.getByRole("button", { name: "More actions for feat-cleanup" }),
    );
    await user.click(screen.getByRole("button", { name: "Delete Branch" }));

    const confirmDialog = await screen.findByRole("dialog", {
      name: 'Delete branch "feat-cleanup"?',
    });
    await user.click(within(confirmDialog).getByRole("button", { name: "Delete Branch" }));

    await waitFor(() => {
      expect(mockApi.deleteServerBranch).toHaveBeenCalledWith(
        "srv-vers-1",
        "feat-cleanup",
      );
    });
  });

  it("exposes Retention Policy, GitHub Sync, and formatted Vault in Sync & Vault tab", async () => {
    const user = userEvent.setup();
    mockApi.getGitHubStatus.mockResolvedValue(buildGitHubStatus());
    mockApi.updateBotSettings.mockResolvedValue({
      ...mockBotSettings,
      previous_tree_retention: "24h",
    });

    renderPage("/servers/srv-vers-1/versioning?tab=sync");

    expect(await screen.findByTestId("sync-and-vault-tab")).toBeInTheDocument();
    expect(await screen.findByText("https://github.com/owner/repo.git")).toBeInTheDocument();
    expect(await screen.findByText(/2\.0 KB/)).toBeInTheDocument();

    await user.click(screen.getByLabelText(/Keep for 24 hours/i));
    await user.click(screen.getByRole("button", { name: "Save Policy" }));

    await waitFor(() => {
      expect(mockApi.updateBotSettings).toHaveBeenCalledWith("srv-vers-1", {
        previous_tree_retention: "24h",
      });
    });

    await user.click(screen.getByRole("button", { name: /Secret Vault/i }));
    expect(await screen.findByText("${ONX_SECRET_DB_PASSWORD}")).toBeInTheDocument();
  });

  it("validates branch names client-side in CreateBranchModal", async () => {
    const user = userEvent.setup();
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "New Branch" }));
    const input = screen.getByLabelText("Branch Name");
    await user.type(input, "bad branch name");
    expect(
      screen.getByText(/Use 1–63 characters/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create Branch" })).toBeDisabled();

    await user.clear(input);
    await user.type(input, "feat-valid-1");
    mockApi.createServerBranch.mockResolvedValueOnce({ success: true });
    await user.click(screen.getByRole("button", { name: "Create Branch" }));

    await waitFor(() => {
      expect(mockApi.createServerBranch).toHaveBeenCalledWith("srv-vers-1", {
        name: "feat-valid-1",
      });
    });
  });
});
