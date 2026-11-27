import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/services/api";
import type {
  CompatibilityMatrixPayload,
  InstallPlanPayload,
  MatrixEntryItem,
  ModpackInspectResponse,
  ServerP55SettingsResponse,
  ServerUpgradeListResponse,
  ServerUpgradeResponse,
} from "@/server_manager/types";
import { ServerP55SettingsCard } from "./ServerP55SettingsCard";
import { ModpackInstallWizardModal } from "./ModpackInstallWizardModal";
import { SafeUpgradeWizardModal } from "./SafeUpgradeWizardModal";
import { UpgradePinnedBanner } from "./UpgradePinnedBanner";
import { ServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { useOperationStore } from "@/operations/stores/operationStore";

const mockApi = {
  getCurseForgeIntegrationStatus: vi.fn(),
  setCurseForgeIntegrationKey: vi.fn(),
  deleteCurseForgeIntegrationKey: vi.fn(),
  listLecEntries: vi.fn(),
  prewarmLecEntry: vi.fn(),
  gcLecEntries: vi.fn(),
  getServerP55Settings: vi.fn(),
  updateServerP55Settings: vi.fn(),
  inspectModpack: vi.fn(),
  installModpack: vi.fn(),
  getOperation: vi.fn(),
  listServerUpgrades: vi.fn(),
  getServerUpgrade: vi.fn(),
  planServerUpgrade: vi.fn(),
  resolveUpgradeManualUpload: vi.fn(),
  prepareServerUpgradeTest: vi.fn(),
  applyServerUpgrade: vi.fn(),
  confirmServerUpgrade: vi.fn(),
  rollbackServerUpgrade: vi.fn(),
  stopBranchRun: vi.fn(),
  destroyBranchRun: vi.fn(),
  deleteServerBranch: vi.fn(),
  getServerExposure: vi.fn(),
};

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    createAuthenticatedApi: () => mockApi,
  };
});

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
  useToastStore: vi.fn(() => ({ toasts: [], dismiss: vi.fn() })),
}));

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={makeClient()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function resetApi() {
  for (const fn of Object.values(mockApi)) fn.mockReset();
}

const P55_SETTINGS: ServerP55SettingsResponse = {
  server_id: "srv-p55",
  health_gate_boot_timeout_seconds: 300,
  install_optional_server_files: true,
  allow_experimental_paper_builds: false,
  download_host_allowlist: [],
  default_allowed_hosts: ["cdn.modrinth.com", "edge.forgecdn.net"],
};

const PLAN: InstallPlanPayload = {
  source: "modrinth",
  project_id: "test-pack",
  version_id: "v1",
  version_label: "Test Pack 1.0",
  index_sha256: "index123",
  mc_version: "1.21.4",
  loader_id: "fabric",
  loader_version: "0.16.9",
  files: [
    {
      path: "mods/example-mod.jar",
      sha1: "sha1file",
      sha512: "sha512file",
      sha256: "sha256file",
      size: 2048,
      downloads: ["https://cdn.modrinth.com/example-mod.jar"],
      env_server: "required",
      optional: false,
      origin: "modrinth",
      project_id: "example",
      version_id: "v2",
      source_layer: "index",
      curseforge_project_id: null,
      curseforge_file_id: null,
    },
  ],
  overrides: [
    {
      path: "config/example.toml",
      archive_path: "overrides/config/example.toml",
      source_layer: "overrides",
      classification: "routed_cas",
      sha256: "sha256override",
      sha512: "sha512override",
      sha1: "sha1override",
      size: 512,
    },
  ],
  manual_blockers: [],
  skipped_client_files: ["mods/sodium.jar"],
  skipped_optional_files: [],
  skipped_client_override_jars: [],
  discarded_paths: [],
  warnings: [],
};

const INSPECTION: ModpackInspectResponse = {
  server_id: "srv-p55",
  staged_pack_id: "staged-pack-1",
  source: "modrinth",
  mc_version: "1.21.4",
  loader_id: "fabric",
  loader_version: "0.16.9",
  has_unresolved_blockers: false,
  plan: PLAN,
};

const MANUAL_BLOCKER = {
  path: "mods/manual.jar",
  filename: "manual.jar",
  project_id: 4242,
  file_id: 77,
  webpage_url: "https://www.curseforge.com/minecraft/mc-mods/manual/files/77",
  expected_size: 4096,
  expected_sha1: "manualsha1",
  expected_sha512: "manualsha512",
  required: true,
  reason: "downloadUrl: null",
  blocker_type: "manual_download_required",
  resolved: false,
  resolved_sha256: null,
};

const BLOCKED_INSPECTION: ModpackInspectResponse = {
  ...INSPECTION,
  has_unresolved_blockers: true,
  plan: { ...PLAN, manual_blockers: [MANUAL_BLOCKER] },
};

const UPGRADE_BASE: ServerUpgradeResponse = {
  id: "upgrade-1",
  server_id: "srv-p55",
  kind: "upgrade",
  mode: "simple",
  status: "planned",
  source_mc: "1.20.4",
  target_mc: "1.21.4",
  source_loader_id: "fabric",
  source_loader_version: "0.15.0",
  target_loader_id: "fabric",
  target_loader_version: "0.16.9",
  target_lec_key: null,
  upgrade_branch: null,
  operation_id: null,
  journal_id: null,
  previous_main_sha: null,
  target_main_sha: null,
  pre_upgrade_backup_id: null,
  class_c_snapshot_id: null,
  data_template_id: null,
  plan: null,
  matrix: null,
  manual_blockers: null,
  pinned_until_confirm: false,
  health_gate_passed: false,
  reminder_72h_overdue: false,
  error_code: null,
  error_message: null,
  confirmed_at: null,
  rolled_back_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const WARNING_ENTRY: MatrixEntryItem = {
  path: "mods/UnresolvedLib.jar",
  status: "warning: unresolved_carried",
  origin: "modrinth",
  source_sha256: "srcwarning",
  source_sha512: null,
  source_project_id: "unresolved",
  source_version_id: "v1",
  target_sha256: null,
  target_sha512: null,
  target_sha1: null,
  target_size: null,
  target_project_id: null,
  target_version_id: null,
  target_version_number: null,
  download_url: null,
  required_by: [],
  detail: "Could not resolve against target loader",
  manual_blocker: null,
  excluded_by_operator: false,
  is_blocker: false,
};

const BROKEN_ENTRY: MatrixEntryItem = {
  path: "mods/BrokenMod.jar",
  status: "blocker: no_target_build",
  origin: "modrinth",
  source_sha256: "srcbroken",
  source_sha512: null,
  source_project_id: "broken",
  source_version_id: "v1",
  target_sha256: null,
  target_sha512: null,
  target_sha1: null,
  target_size: null,
  target_project_id: null,
  target_version_id: null,
  target_version_number: null,
  download_url: null,
  required_by: [],
  detail: "No build for MC 1.21.4",
  manual_blocker: null,
  excluded_by_operator: false,
  is_blocker: true,
};

const MANUAL_ENTRY: MatrixEntryItem = {
  ...BROKEN_ENTRY,
  path: "mods/manual.jar",
  status: "blocker: manual_download_required",
  manual_blocker: MANUAL_BLOCKER,
  detail: "Manual download required",
};

const BLOCKED_MATRIX: CompatibilityMatrixPayload = {
  source_mc: "1.20.4",
  target_mc: "1.21.4",
  source_loader: { id: "fabric", version: "0.15.0" },
  target_loader: { id: "fabric", version: "0.16.9" },
  entries: [WARNING_ENTRY, BROKEN_ENTRY, MANUAL_ENTRY],
  bfs_depth_reached: 2,
  bfs_projects_resolved: 8,
  excluded_paths: [],
  has_blockers: true,
  blockers_count: 2,
  warnings_count: 1,
};

const CLEAN_MATRIX: CompatibilityMatrixPayload = {
  ...BLOCKED_MATRIX,
  entries: [WARNING_ENTRY, BROKEN_ENTRY].map((entry) => ({
    ...entry,
    is_blocker: false,
    status: entry.path === "mods/BrokenMod.jar" ? "remove" : entry.status,
  })),
  has_blockers: false,
  blockers_count: 0,
};

describe("ServerP55SettingsCard", () => {
  beforeEach(resetApi);

  it("loads settings, validates the 300–900s bound with safe empty-input typing, edits toggles and custom hosts, then saves", async () => {
    const user = userEvent.setup();
    mockApi.getServerP55Settings.mockResolvedValue(P55_SETTINGS);
    mockApi.updateServerP55Settings.mockResolvedValue({
      ...P55_SETTINGS,
      health_gate_boot_timeout_seconds: 600,
      install_optional_server_files: false,
      allow_experimental_paper_builds: true,
      download_host_allowlist: ["mirror.example.com"],
    });

    renderWithProviders(<ServerP55SettingsCard serverId="srv-p55" />);

    const timeout = (await screen.findByLabelText(
      "Health Gate Boot Timeout",
    )) as HTMLInputElement;
    expect(timeout.value).toBe("300");
    // Default hosts sit inside a collapsed disclosure by default
    expect(screen.queryByText("cdn.modrinth.com")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /View 2 default hosts/i }));
    expect(screen.getByText("cdn.modrinth.com")).toBeInTheDocument();

    // Clearing the field mid-typing must NOT snap to 0 or flash an error
    await user.clear(timeout);
    expect(timeout.value).toBe("");
    expect(screen.queryByText("Must be between 300 and 900 seconds.")).not.toBeInTheDocument();

    await user.type(timeout, "120");
    expect(
      screen.getByText("Must be between 300 and 900 seconds."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("save-p55-settings-btn")).toBeDisabled();

    await user.clear(timeout);
    await user.type(timeout, "600");

    await user.click(
      screen.getByRole("switch", { name: "Install Optional Server Files" }),
    );
    await user.click(
      screen.getByRole("switch", { name: "Allow Experimental Paper Builds" }),
    );

    await user.type(
      screen.getByPlaceholderText("mirror.example.com"),
      "mirror.example.com",
    );
    await user.click(screen.getByRole("button", { name: "Add Host" }));
    expect(screen.getByText("mirror.example.com")).toBeInTheDocument();

    await user.click(screen.getByTestId("save-p55-settings-btn"));
    await waitFor(() =>
      expect(mockApi.updateServerP55Settings).toHaveBeenCalledWith(
        "srv-p55",
        expect.objectContaining({
          health_gate_boot_timeout_seconds: 600,
          install_optional_server_files: false,
          allow_experimental_paper_builds: true,
          download_host_allowlist: ["mirror.example.com"],
        }),
      ),
    );
  });

  it("rejects scheme, port, wildcard, and IP-literal hostnames client-side", async () => {
    const user = userEvent.setup();
    mockApi.getServerP55Settings.mockResolvedValue(P55_SETTINGS);

    renderWithProviders(<ServerP55SettingsCard serverId="srv-p55" />);

    const input = await screen.findByPlaceholderText("mirror.example.com");
    await user.type(input, "https://mirror.example.com:8080");
    await user.click(screen.getByRole("button", { name: "Add Host" }));

    expect(
      screen.getByText(
        "Enter a lowercase domain hostname only (no scheme, port, wildcard, or IP literal).",
      ),
    ).toBeInTheDocument();
    expect(mockApi.updateServerP55Settings).not.toHaveBeenCalled();
  });

  it("gates optional server files to modded loaders and Paper builds to Paper/Purpur", async () => {
    mockApi.getServerP55Settings.mockResolvedValue(P55_SETTINGS);
    const { unmount } = renderWithProviders(
      <ServerP55SettingsCard serverId="srv-p55" serverType="fabric" />,
    );
    expect(
      await screen.findByRole("switch", { name: "Install Optional Server Files" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("switch", { name: "Allow Experimental Paper Builds" }),
    ).not.toBeInTheDocument();
    unmount();

    mockApi.getServerP55Settings.mockResolvedValue(P55_SETTINGS);
    renderWithProviders(<ServerP55SettingsCard serverId="srv-p55" serverType="paper" />);
    expect(
      await screen.findByRole("switch", { name: "Allow Experimental Paper Builds" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("switch", { name: "Install Optional Server Files" }),
    ).not.toBeInTheDocument();
  });
});

describe("ModpackInstallWizardModal", () => {
  beforeEach(resetApi);

  it("inspects an .mrpack preview before writing, then installs", async () => {
    const user = userEvent.setup();
    mockApi.inspectModpack.mockResolvedValue(INSPECTION);
    mockApi.installModpack.mockResolvedValue({
      server_id: "srv-p55",
      upgrade_id: "upgrade-1",
      status: "applied",
      mc_version: "1.21.4",
      loader_id: "fabric",
      loader_version: "0.16.9",
      lec_key: "fabric/1.21.4/0.16.9/1.0.1",
      files_installed: 1,
      base_overrides_count: 1,
      commit_sha: "commit-sha-1",
      operation_id: null,
    });

    renderWithProviders(
      <ModpackInstallWizardModal serverId="srv-p55" isOpen onClose={vi.fn()} />,
    );

    await user.upload(
      screen.getByTestId("modpack-file-input"),
      new File(["archive"], "pack.mrpack", { type: "application/zip" }),
    );
    await user.click(screen.getByTestId("inspect-modpack-btn"));

    await waitFor(() =>
      expect(mockApi.inspectModpack).toHaveBeenCalledWith(
        "srv-p55",
        expect.any(File),
        expect.objectContaining({
          format: "auto",
          install_optional_server_files: true,
        }),
      ),
    );
    expect(await screen.findByText("Test Pack 1.0")).toBeInTheDocument();
    expect(screen.getByText("1.21.4")).toBeInTheDocument();
    expect(screen.getAllByText("mods/example-mod.jar").length).toBeGreaterThan(0);
    expect(screen.getAllByText("mods/sodium.jar").length).toBeGreaterThan(0);

    await user.click(screen.getByTestId("confirm-install-modpack-btn"));
    await waitFor(() =>
      expect(mockApi.installModpack).toHaveBeenCalledWith("srv-p55", {
        staged_pack_id: "staged-pack-1",
        build_lec: false,
        async_mode: false,
      }),
    );
    expect(
      await screen.findByText("Modpack installed successfully"),
    ).toBeInTheDocument();
    expect(screen.getByText("1 server files installed, 1 base overrides committed.")).toBeInTheDocument();
  });

  it("renders the CurseForge API key callout with a deep link on 409", async () => {
    const user = userEvent.setup();
    mockApi.inspectModpack.mockRejectedValue(
      new ApiError(
        409,
        "CURSEFORGE_API_KEY_MISSING",
        "CurseForge API key is not configured",
      ),
    );

    renderWithProviders(
      <ModpackInstallWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        initialFormat="curseforge"
      />,
    );

    await user.upload(
      screen.getByTestId("modpack-file-input"),
      new File(["archive"], "pack.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByTestId("inspect-modpack-btn"));

    expect(
      await screen.findByTestId("curseforge-key-missing-alert"),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", {
      name: /Configure CurseForge API Key in Panel Settings/i,
    });
    expect(link).toHaveAttribute("href", "/settings?tab=integrations");
  });

  it("disables install until a manual-download blocker is uploaded and verified", async () => {
    const user = userEvent.setup();
    mockApi.inspectModpack.mockResolvedValue(BLOCKED_INSPECTION);
    mockApi.resolveUpgradeManualUpload.mockResolvedValue({
      ...UPGRADE_BASE,
      status: "planned",
      manual_blockers: [{ ...MANUAL_BLOCKER, resolved: true, resolved_sha256: "resolvedhash" }],
    });
    mockApi.installModpack.mockResolvedValue({
      ...UPGRADE_BASE,
      status: "applied",
      files_installed: 2,
      base_overrides_count: 0,
    });

    renderWithProviders(
      <ModpackInstallWizardModal serverId="srv-p55" isOpen onClose={vi.fn()} />,
    );

    await user.upload(
      screen.getByTestId("modpack-file-input"),
      new File(["archive"], "pack.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByTestId("inspect-modpack-btn"));

    expect(await screen.findByTestId("modpack-manual-blockers")).toBeInTheDocument();
    expect(screen.getByTestId("confirm-install-modpack-btn")).toBeDisabled();
    expect(
      screen.getByText("Resolve all manual download blockers above to enable installation"),
    ).toBeInTheDocument();

    await user.upload(
      screen.getByTestId("manual-upload-input-77"),
      new File(["manual"], "manual.jar", { type: "application/java-archive" }),
    );

    await waitFor(() =>
      expect(mockApi.resolveUpgradeManualUpload).toHaveBeenCalledWith(
        "srv-p55",
        "staged-pack-1",
        expect.any(File),
        { file_id: 77, path: "mods/manual.jar" },
      ),
    );
    expect(await screen.findByText("Verified")).toBeInTheDocument();
    expect(screen.getByTestId("confirm-install-modpack-btn")).toBeEnabled();
  });

  it("refreshes manual blockers when install returns 409 MANUAL_DOWNLOAD_REQUIRED", async () => {
    const user = userEvent.setup();
    mockApi.inspectModpack.mockResolvedValue(INSPECTION);
    mockApi.installModpack.mockRejectedValue(
      new ApiError(409, "MANUAL_DOWNLOAD_REQUIRED", "Manual download required"),
    );
    mockApi.getServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      manual_blockers: [MANUAL_BLOCKER],
      status: "awaiting_manual_uploads",
    });

    renderWithProviders(
      <ModpackInstallWizardModal serverId="srv-p55" isOpen onClose={vi.fn()} />,
    );

    await user.upload(
      screen.getByTestId("modpack-file-input"),
      new File(["archive"], "pack.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByTestId("inspect-modpack-btn"));
    await screen.findByText("Test Pack 1.0");

    await user.click(screen.getByTestId("confirm-install-modpack-btn"));
    await waitFor(() =>
      expect(mockApi.getServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "staged-pack-1",
      ),
    );
    expect(await screen.findByTestId("modpack-manual-blockers")).toBeInTheDocument();
    expect(
      screen.getByText(
        "CurseForge requires a manual download. Upload the newly blocked file below to continue.",
      ),
    ).toBeInTheDocument();
  });

  it("renders skipped path notes in a collapsed neutral disclosure instead of a warning banner", async () => {
    const user = userEvent.setup();
    mockApi.inspectModpack.mockResolvedValue({
      ...INSPECTION,
      plan: {
        ...PLAN,
        warnings: [
          "skipped_path:config/fancymenu/README.md",
          "skipped_path:config/fancymenu/assets/bg.png",
        ],
      },
    });

    renderWithProviders(
      <ModpackInstallWizardModal serverId="srv-p55" isOpen onClose={vi.fn()} />,
    );

    await user.upload(
      screen.getByTestId("modpack-file-input"),
      new File(["archive"], "pack.mrpack", { type: "application/zip" }),
    );
    await user.click(screen.getByTestId("inspect-modpack-btn"));

    const details = await screen.findByTestId("modpack-skipped-paths-details");
    expect(details).toBeInTheDocument();
    expect(details).not.toHaveAttribute("open");
    expect(screen.queryByText("Inspection warnings")).not.toBeInTheDocument();
    expect(
      screen.getByText("Skipped non-server paths & notes (2)"),
    ).toBeInTheDocument();
  });

  it("opens operation drawer and shows live progress, current file, and logs in background mode", async () => {
    const user = userEvent.setup();
    useOperationStore.setState({
      operations: {},
      activeDrawerId: null,
      logs: {},
      gapDetectedOperations: {},
    });
    mockApi.inspectModpack.mockResolvedValue(INSPECTION);
    mockApi.installModpack.mockResolvedValue({
      server_id: "srv-p55",
      upgrade_id: "staged-pack-1",
      status: "installing",
      mc_version: "1.21.4",
      loader_id: "fabric",
      loader_version: "0.16.9",
      lec_key: null,
      files_installed: 0,
      base_overrides_count: 0,
      commit_sha: null,
      operation_id: "op-bg-1",
    });
    mockApi.getOperation.mockResolvedValue({
      id: "op-bg-1",
      type: "MODPACK_INSTALL",
      target_type: "server",
      target_id: "srv-p55",
      actor_id: "local-admin",
      status: "RUNNING",
      idempotency_key: null,
      current_step_id: "INSTALL_MODPACK",
      last_event_seq: 1,
      failure_code: null,
      error_message: null,
      cancellation_requested: false,
      timeout_seconds: 600,
      created_at: "2026-01-01T00:00:00Z",
      started_at: "2026-01-01T00:00:00Z",
      finished_at: null,
      elapsed_ms: 1200,
      steps: [
        {
          id: "step-1",
          step_id: "INSTALL_MODPACK",
          sequence: 1,
          status: "IN_PROGRESS",
          progress: 45,
          elapsed_ms: 1200,
          message_key: "Downloading modpack files (1/2)...",
          safe_to_retry: false,
          context: { current_file: "mods/example-mod.jar", total: 2 },
          started_at: "2026-01-01T00:00:00Z",
          completed_at: null,
        },
      ],
      metadata: {},
    });
    useOperationStore
      .getState()
      .appendLog("op-bg-1", "info", "Downloading [1/2]: mods/example-mod.jar");

    renderWithProviders(
      <ModpackInstallWizardModal serverId="srv-p55" isOpen onClose={vi.fn()} />,
    );

    await user.upload(
      screen.getByTestId("modpack-file-input"),
      new File(["archive"], "pack.mrpack", { type: "application/zip" }),
    );
    await user.click(screen.getByTestId("inspect-modpack-btn"));
    await screen.findByText("Test Pack 1.0");

    await user.click(screen.getByTestId("modpack-async-checkbox"));
    await user.click(screen.getByTestId("confirm-install-modpack-btn"));

    await waitFor(() =>
      expect(mockApi.installModpack).toHaveBeenCalledWith("srv-p55", {
        staged_pack_id: "staged-pack-1",
        build_lec: false,
        async_mode: true,
      }),
    );

    expect(useOperationStore.getState().activeDrawerId).toBe("op-bg-1");
    const progress = await screen.findByTestId("modpack-live-progress");
    expect(progress).toHaveTextContent("Downloading modpack files (1/2)...");
    expect(progress).toHaveTextContent("RUNNING · 45%");
    expect(progress).toHaveTextContent("Downloading: mods/example-mod.jar");
    expect(screen.getByTestId("modpack-live-logs")).toHaveTextContent(
      "Downloading [1/2]: mods/example-mod.jar",
    );
    expect(
      screen.queryByText(/Modpack installed successfully/i),
    ).not.toBeInTheDocument();
  });

  it("displays operation error banner when background modpack install fails", async () => {
    const user = userEvent.setup();
    useOperationStore.setState({
      operations: {},
      activeDrawerId: null,
      logs: {},
      gapDetectedOperations: {},
    });
    mockApi.inspectModpack.mockResolvedValue(INSPECTION);
    mockApi.installModpack.mockResolvedValue({
      server_id: "srv-p55",
      upgrade_id: "staged-pack-1",
      status: "installing",
      mc_version: "1.21.4",
      loader_id: "fabric",
      loader_version: "0.16.9",
      lec_key: null,
      files_installed: 0,
      base_overrides_count: 0,
      commit_sha: null,
      operation_id: "op-bg-fail",
    });
    mockApi.getOperation.mockResolvedValue({
      id: "op-bg-fail",
      type: "MODPACK_INSTALL",
      target_type: "server",
      target_id: "srv-p55",
      actor_id: "local-admin",
      status: "FAILED",
      idempotency_key: null,
      current_step_id: "INSTALL_MODPACK",
      last_event_seq: 2,
      failure_code: "INFRASTRUCTURE_ERROR",
      error_message: "Download failed: HTTP 0 — Download timed out",
      cancellation_requested: false,
      timeout_seconds: 600,
      created_at: "2026-01-01T00:00:00Z",
      started_at: "2026-01-01T00:00:00Z",
      finished_at: "2026-01-01T00:00:10Z",
      elapsed_ms: 10000,
      steps: [],
      metadata: {},
    });

    renderWithProviders(
      <ModpackInstallWizardModal serverId="srv-p55" isOpen onClose={vi.fn()} />,
    );

    await user.upload(
      screen.getByTestId("modpack-file-input"),
      new File(["archive"], "pack.mrpack", { type: "application/zip" }),
    );
    await user.click(screen.getByTestId("inspect-modpack-btn"));
    await screen.findByText("Test Pack 1.0");

    await user.click(screen.getByTestId("modpack-async-checkbox"));
    await user.click(screen.getByTestId("confirm-install-modpack-btn"));

    expect(
      await screen.findByText("Download failed: HTTP 0 — Download timed out"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("confirm-install-modpack-btn")).toBeEnabled();
  });
});

describe("SafeUpgradeWizardModal", () => {
  beforeEach(resetApi);

  it("plans a matrix, excludes a blocker, re-evaluates, and applies in Simple mode", async () => {
    const user = userEvent.setup();
    mockApi.planServerUpgrade
      .mockResolvedValueOnce({ ...UPGRADE_BASE, matrix: BLOCKED_MATRIX, status: "blocked" })
      .mockResolvedValueOnce({ ...UPGRADE_BASE, matrix: CLEAN_MATRIX, status: "planned" });
    mockApi.applyServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      status: "active_pinned",
      health_gate_passed: true,
      pinned_until_confirm: true,
      pre_upgrade_backup_id: "backup-1",
      class_c_snapshot_id: "snapshot-1",
      target_mc: "1.21.4",
    });

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="simple"
        serverType="fabric"
        currentMc="1.20.4"
      />,
    );

    const targetMc = screen.getByLabelText("Target Minecraft");
    await user.clear(targetMc);
    await user.type(targetMc, "1.21.4");
    await user.click(screen.getByTestId("plan-upgrade-btn"));

    expect(
      await screen.findByTestId("upgrade-compatibility-matrix"),
    ).toBeInTheDocument();
    expect(screen.getByText("No Compatible Build")).toBeInTheDocument();
    expect(screen.getByText("Manual Upload Required")).toBeInTheDocument();
    expect(
      screen.getByText("Custom / Untracked (Carried)"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("continue-upgrade-btn")).toBeDisabled();

    await user.click(screen.getByTestId("exclude-entry-mods/BrokenMod.jar"));
    await user.click(screen.getByRole("button", { name: "Re-evaluate Matrix" }));
    await waitFor(() =>
      expect(mockApi.planServerUpgrade).toHaveBeenLastCalledWith(
        "srv-p55",
        expect.objectContaining({
          excluded_paths: ["mods/BrokenMod.jar"],
        }),
      ),
    );

    expect(await screen.findByTestId("continue-upgrade-btn")).toBeEnabled();
    await user.click(await screen.findByTestId("continue-upgrade-btn"));

    expect(
      screen.queryByTestId("prepare-upgrade-test-btn"),
    ).not.toBeInTheDocument();
    const apply = screen.getByTestId("apply-upgrade-live-btn");
    expect(apply).toHaveTextContent("Apply Change Version");
    await user.click(apply);

    await waitFor(() =>
      expect(mockApi.applyServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "upgrade-1",
        {
          resolved_conflicts: {},
          async_mode: true,
          verify_public_network: false,
        },
      ),
    );
    expect(
      await screen.findByText(
        "Health Gate Passed — Upgrade Active & Rollback Snapshot Pinned",
      ),
    ).toBeInTheDocument();
  });

  it("prepares an isolated branch test and applies in Advanced mode", async () => {
    const user = userEvent.setup();
    mockApi.planServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      mode: "advanced",
      matrix: CLEAN_MATRIX,
      status: "planned",
    });
    mockApi.prepareServerUpgradeTest.mockResolvedValue({
      upgrade: {
        ...UPGRADE_BASE,
        status: "testing",
        upgrade_branch: "upgrade-1.21.4",
        data_template_id: "dt-clone-1",
      },
      runtime: {
        runtime_id: "runtime-1",
        server_id: "srv-p55",
        branch_name: "upgrade-1.21.4",
        commit_sha: "sha-test",
        container_name: "onx-srv-p55-upgrade-test",
        container_id: "container-1",
        port_set: { game_port: 25570, rcon_port: 25575, query_port: 25580 },
        data_template_id: "dt-clone-1",
        allow_public_test_join: false,
        uncommitted_changes_warning: false,
        memory_max_mb: 4096,
        cpu_cores: 4,
      },
    });
    mockApi.applyServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      status: "active_pinned",
      health_gate_passed: true,
      pinned_until_confirm: true,
      target_mc: "1.21.4",
    });

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="advanced"
        serverType="fabric"
        currentMc="1.20.4"
      />,
    );

    const targetMc = screen.getByLabelText("Target Minecraft");
    await user.clear(targetMc);
    await user.type(targetMc, "1.21.4");
    await user.click(screen.getByTestId("plan-upgrade-btn"));
    await screen.findByTestId("upgrade-compatibility-matrix");
    await user.click(await screen.findByTestId("continue-upgrade-btn"));

    const prepare = screen.getByTestId("prepare-upgrade-test-btn");
    expect(prepare).toHaveTextContent(
      "Prepare upgrade-1.21.4 Branch & Start Test",
    );
    await user.click(prepare);

    await waitFor(() =>
      expect(mockApi.prepareServerUpgradeTest).toHaveBeenCalledWith(
        "srv-p55",
        "upgrade-1",
        { resolved_conflicts: {}, start_test: true },
      ),
    );
    expect(
      await screen.findByText("Branch: upgrade-1.21.4"),
    ).toBeInTheDocument();
    expect(screen.getByText("onx-srv-p55-upgrade-test")).toBeInTheDocument();
    expect(
      screen.getByText("game 25570 · rcon 25575 · query 25580"),
    ).toBeInTheDocument();

    await user.click(screen.getByTestId("apply-upgrade-live-btn"));
    await waitFor(() =>
      expect(mockApi.applyServerUpgrade).toHaveBeenCalledTimes(1),
    );
    expect(
      await screen.findByText(
        "Health Gate Passed — Upgrade Active & Rollback Snapshot Pinned",
      ),
    ).toBeInTheDocument();
  });

  it("hydrates active run on open, supports Start Fresh, downgrade warning, Keep Current, branch handoff, and Discard Test", async () => {
    const user = userEvent.setup();
    const setBranch = vi.fn();
    const onClose = vi.fn();

    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [],
      active_upgrade: {
        ...UPGRADE_BASE,
        mode: "advanced",
        status: "testing",
        target_mc: "1.21.4",
        upgrade_branch: "upgrade-1.21.4",
        matrix: CLEAN_MATRIX,
      },
      banner_active: false,
      reminder_72h_overdue: false,
    });
    mockApi.stopBranchRun.mockResolvedValue({});
    mockApi.destroyBranchRun.mockResolvedValue({});
    mockApi.deleteServerBranch.mockResolvedValue({});

    renderWithProviders(
      <ServerBranchContext.Provider
        value={{
          branch: "main",
          setBranch,
          gitBacked: true,
          serverMode: "advanced",
        }}
      >
        <SafeUpgradeWizardModal
          serverId="srv-p55"
          isOpen
          onClose={onClose}
          serverMode="advanced"
          serverType="fabric"
          currentMc="1.21.4"
        />
      </ServerBranchContext.Provider>,
    );

    // 1. Auto-hydrates testing branch step & allows Switch to Branch & Inspect
    const switchBtn = await screen.findByTestId("switch-to-upgrade-branch-btn");
    await user.click(switchBtn);
    expect(setBranch).toHaveBeenCalledWith("upgrade-1.21.4");
    expect(onClose).toHaveBeenCalled();

    // 2. Discard Test stops/destroys runtime & deletes branch, resetting to Step 1
    await user.click(screen.getByTestId("discard-upgrade-test-btn"));
    await waitFor(() => {
      expect(mockApi.stopBranchRun).toHaveBeenCalledWith("srv-p55", "upgrade-1.21.4", {});
      expect(mockApi.destroyBranchRun).toHaveBeenCalledWith("srv-p55", "upgrade-1.21.4", {});
      expect(mockApi.deleteServerBranch).toHaveBeenCalledWith("srv-p55", "upgrade-1.21.4");
    });

    // 3. Downgrade warning shown on Step 1 when target MC < current MC (1.21.4 -> 1.20.4)
    const targetMcInput = await screen.findByLabelText("Target Minecraft");
    await user.clear(targetMcInput);
    await user.type(targetMcInput, "1.20.4");
    expect(await screen.findByTestId("downgrade-advisory-banner")).toBeInTheDocument();

    // 4. Keep Current toggle sends keep_paths in planServerUpgrade
    mockApi.planServerUpgrade
      .mockResolvedValueOnce({ ...UPGRADE_BASE, matrix: BLOCKED_MATRIX, status: "blocked" })
      .mockResolvedValueOnce({
        ...UPGRADE_BASE,
        matrix: { ...CLEAN_MATRIX, kept_paths: ["mods/BrokenMod.jar"] },
        status: "planned",
      });
    await user.click(screen.getByTestId("plan-upgrade-btn"));
    await screen.findByTestId("upgrade-compatibility-matrix");
    await user.click(screen.getByTestId("keep-entry-mods/BrokenMod.jar"));
    await user.click(screen.getByRole("button", { name: "Re-evaluate Matrix" }));
    await waitFor(() =>
      expect(mockApi.planServerUpgrade).toHaveBeenLastCalledWith(
        "srv-p55",
        expect.objectContaining({
          keep_paths: ["mods/BrokenMod.jar"],
        }),
      ),
    );

    // 5. Start Fresh resets hydrated/active run cleanly back to Step 1
    await user.click(screen.getByTestId("start-fresh-upgrade-btn"));
    expect(screen.getByTestId("plan-upgrade-btn")).toBeInTheDocument();
  });

  it("resolves a manual_download_required blocker via upload", async () => {
    const user = userEvent.setup();
    mockApi.planServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      matrix: BLOCKED_MATRIX,
      status: "awaiting_manual_uploads",
    });
    mockApi.resolveUpgradeManualUpload.mockResolvedValue({
      ...UPGRADE_BASE,
      status: "planned",
      matrix: CLEAN_MATRIX,
    });

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="simple"
        serverType="fabric"
        currentMc="1.20.4"
      />,
    );

    const targetMc = screen.getByLabelText("Target Minecraft");
    await user.clear(targetMc);
    await user.type(targetMc, "1.21.4");
    await user.click(screen.getByTestId("plan-upgrade-btn"));
    await screen.findByTestId("upgrade-compatibility-matrix");

    await user.upload(
      screen.getByTestId("upgrade-manual-upload-77"),
      new File(["manual"], "manual.jar", { type: "application/java-archive" }),
    );
    await waitFor(() =>
      expect(mockApi.resolveUpgradeManualUpload).toHaveBeenCalledWith(
        "srv-p55",
        "upgrade-1",
        expect.any(File),
        { file_id: 77, path: "mods/manual.jar" },
      ),
    );
    expect(await screen.findByTestId("continue-upgrade-btn")).toBeEnabled();
  });

  it("renders the automatic triad rollback alert on 502 HEALTH_GATE_FAILED", async () => {
    const user = userEvent.setup();
    mockApi.planServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      matrix: CLEAN_MATRIX,
      status: "planned",
    });
    mockApi.applyServerUpgrade.mockRejectedValue(
      new ApiError(
        502,
        "HEALTH_GATE_FAILED",
        "Health gate failed after 4 steps; automatic triad rollback restored the server",
      ),
    );

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="simple"
        serverType="fabric"
        currentMc="1.20.4"
      />,
    );

    const targetMc = screen.getByLabelText("Target Minecraft");
    await user.clear(targetMc);
    await user.type(targetMc, "1.21.4");
    await user.click(screen.getByTestId("plan-upgrade-btn"));
    await screen.findByTestId("upgrade-compatibility-matrix");
    await user.click(await screen.findByTestId("continue-upgrade-btn"));
    await user.click(screen.getByTestId("apply-upgrade-live-btn"));

    expect(
      await screen.findByTestId("upgrade-auto-rollback-alert"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Automatic Triad Rollback Restored Pre-Upgrade Server/),
    ).toBeInTheDocument();
    expect(screen.getByText(/HEALTH_GATE_FAILED/)).toBeInTheDocument();
  });
});

describe("UpgradePinnedBanner", () => {
  beforeEach(resetApi);

  const activeUpgrade: ServerUpgradeResponse = {
    ...UPGRADE_BASE,
    status: "active_pinned",
    pinned_until_confirm: true,
    health_gate_passed: true,
    reminder_72h_overdue: true,
    pre_upgrade_backup_id: "backup-pinned-1",
    class_c_snapshot_id: "snapshot-pinned-1",
  };

  const activeList: ServerUpgradeListResponse = {
    server_id: "srv-p55",
    items: [activeUpgrade],
    active_upgrade: activeUpgrade,
    banner_active: true,
    reminder_72h_overdue: true,
  };

  it("renders the pinned banner with target and 72h overdue badge", async () => {
    mockApi.listServerUpgrades.mockResolvedValue(activeList);

    renderWithProviders(<UpgradePinnedBanner serverId="srv-p55" />);

    expect(await screen.findByTestId("upgrade-pinned-banner")).toBeInTheDocument();
    expect(
      screen.getByText("Upgrade Active — Pre-Upgrade Rollback Snapshot is Pinned"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/MC 1.21.4 \(fabric 0.16.9\)/),
    ).toBeInTheDocument();
    expect(screen.getByText("backup-pinned-1")).toBeInTheDocument();
    expect(screen.getByText("snapshot-pinned-1")).toBeInTheDocument();
    expect(screen.getByTestId("upgrade-72h-overdue-badge")).toHaveTextContent(
      /Pinned > 72h/,
    );
  });

  it("confirms the upgrade and unpins the rollback backup", async () => {
    const user = userEvent.setup();
    mockApi.listServerUpgrades.mockResolvedValue(activeList);
    mockApi.confirmServerUpgrade.mockResolvedValue({
      ...activeUpgrade,
      status: "confirmed",
      pinned_until_confirm: false,
      reminder_72h_overdue: false,
    });

    renderWithProviders(<UpgradePinnedBanner serverId="srv-p55" />);

    await screen.findByTestId("upgrade-pinned-banner");
    await user.click(screen.getByTestId("banner-confirm-upgrade-btn"));
    await waitFor(() =>
      expect(mockApi.confirmServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "upgrade-1",
      ),
    );
  });

  it("performs an emergency rollback with an operator reason", async () => {
    const user = userEvent.setup();
    mockApi.listServerUpgrades.mockResolvedValue(activeList);
    mockApi.rollbackServerUpgrade.mockResolvedValue({
      ...activeUpgrade,
      status: "rolled_back",
      rolled_back_at: "2026-01-02T00:00:00Z",
    });

    renderWithProviders(<UpgradePinnedBanner serverId="srv-p55" />);

    await screen.findByTestId("upgrade-pinned-banner");
    await user.click(screen.getByTestId("banner-emergency-rollback-btn"));
    expect(
      screen.getByText(/will be restored/i),
    ).toBeInTheDocument();
    await user.click(screen.getByTestId("confirm-emergency-rollback-btn"));

    await waitFor(() =>
      expect(mockApi.rollbackServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "upgrade-1",
        { reason: "operator emergency rollback" },
      ),
    );
  });

  it("renders nothing when the upgrade API is not mocked by an older page test", () => {
    const partialApi = { ...mockApi, listServerUpgrades: undefined };
    const original = mockApi.listServerUpgrades;
    (mockApi as unknown as Record<string, unknown>).listServerUpgrades = undefined;
    const { container } = renderWithProviders(<UpgradePinnedBanner serverId="srv-p55" />);
    expect(container).toBeEmptyDOMElement();
    (mockApi as unknown as Record<string, unknown>).listServerUpgrades = original;
    expect(partialApi.listServerUpgrades).toBeUndefined();
  });

  it("renders Resume and branch switcher actions for active non-pinned runs", async () => {
    const user = userEvent.setup();
    const setBranch = vi.fn();
    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [],
      active_upgrade: {
        ...UPGRADE_BASE,
        status: "testing",
        mode: "advanced",
        upgrade_branch: "upgrade-1.21.4",
      },
      banner_active: false,
      reminder_72h_overdue: false,
    });

    const { rerender } = renderWithProviders(
      <ServerBranchContext.Provider
        value={{
          branch: "main",
          setBranch,
          gitBacked: true,
          serverMode: "advanced",
        }}
      >
        <UpgradePinnedBanner serverId="srv-p55" />
      </ServerBranchContext.Provider>,
    );

    expect(await screen.findByText("Change Version in Progress")).toBeInTheDocument();
    expect(screen.getByTestId("banner-resume-upgrade-btn")).toHaveTextContent("Resume");
    await user.click(screen.getByTestId("banner-switch-branch-btn"));
    expect(setBranch).toHaveBeenCalledWith("upgrade-1.21.4");

    rerender(
      <QueryClientProvider client={makeClient()}>
        <MemoryRouter>
          <ServerBranchContext.Provider
            value={{
              branch: "upgrade-1.21.4",
              setBranch,
              gitBacked: true,
              serverMode: "advanced",
            }}
          >
            <UpgradePinnedBanner serverId="srv-p55" />
          </ServerBranchContext.Provider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const backBtn = await screen.findByTestId("banner-back-to-main-btn");
    await user.click(backBtn);
    expect(setBranch).toHaveBeenCalledWith("main");
  });

  it("supports direct Apply to Live and Discard actions right on the staging/testing banner", async () => {
    const user = userEvent.setup();
    const setBranch = vi.fn();
    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [],
      active_upgrade: {
        ...UPGRADE_BASE,
        id: "upg-live-test",
        status: "testing",
        mode: "advanced",
        upgrade_branch: "upgrade-1.21.4",
      },
      banner_active: false,
      reminder_72h_overdue: false,
    });
    mockApi.applyServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      id: "upg-live-test",
      status: "active_pinned",
      pinned_until_confirm: true,
    });
    mockApi.rollbackServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      id: "upg-live-test",
      status: "rolled_back",
    });

    renderWithProviders(
      <ServerBranchContext.Provider
        value={{
          branch: "upgrade-1.21.4",
          setBranch,
          gitBacked: true,
          serverMode: "advanced",
        }}
      >
        <UpgradePinnedBanner serverId="srv-p55" />
      </ServerBranchContext.Provider>,
    );

    expect(
      await screen.findByText(/Test container running on upgrade-1\.21\.4/i),
    ).toBeInTheDocument();

    // Direct Apply to Live confirmation flow
    await user.click(screen.getByTestId("banner-apply-live-btn"));
    await user.click(screen.getByTestId("confirm-banner-apply-live-btn"));
    await waitFor(() =>
      expect(mockApi.applyServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "upg-live-test",
        { resolved_conflicts: {}, async_mode: false },
      ),
    );
    expect(setBranch).toHaveBeenCalledWith("main");

    // Direct Discard confirmation flow (cleans up branch + abandons upgrade row)
    await user.click(screen.getByTestId("banner-discard-upgrade-btn"));
    await user.click(screen.getByTestId("confirm-discard-upgrade-btn"));
    await waitFor(() =>
      expect(mockApi.rollbackServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "upg-live-test",
        { reason: "operator discarded upgrade plan" },
      ),
    );
  });
});

describe("SafeUpgradeWizardModal — Purpur default & inline error surfacing", () => {
  beforeEach(resetApi);

  it("defaults purpur servers to purpur and shows a loader-switch note when switching to paper", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="advanced"
        serverType="purpur"
        currentMc="1.21.11"
      />,
    );

    const loaderSelect = screen.getByLabelText("Target Loader") as HTMLSelectElement;
    expect(loaderSelect.value).toBe("purpur");
    expect(screen.queryByTestId("loader-switch-note")).not.toBeInTheDocument();

    await user.selectOptions(loaderSelect, "paper");
    expect(screen.getByTestId("loader-switch-note")).toHaveTextContent(
      /Switching loader: Purpur → Paper/i,
    );
  });

  it("surfaces persistent inline errors with recovery hints on Prepare Test and Apply failures", async () => {
    const user = userEvent.setup();
    mockApi.planServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      mode: "advanced",
      target_loader_id: "purpur",
      target_loader_version: "latest",
      matrix: CLEAN_MATRIX,
      status: "planned",
    });
    mockApi.prepareServerUpgradeTest.mockRejectedValue(
      new ApiError(409, "CONFLICT", "No changes to commit"),
    );
    mockApi.applyServerUpgrade.mockRejectedValue(
      new ApiError(500, "INTERNAL_ERROR", "Purpur build download failed"),
    );

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="advanced"
        serverType="purpur"
        currentMc="1.21.4"
      />,
    );

    await user.click(screen.getByTestId("plan-upgrade-btn"));
    await screen.findByTestId("upgrade-compatibility-matrix");
    await user.click(await screen.findByTestId("continue-upgrade-btn"));

    await user.click(screen.getByTestId("prepare-upgrade-test-btn"));
    const prepareBanner = await screen.findByTestId("upgrade-error-banner");
    expect(prepareBanner).toHaveTextContent("No changes to commit");
    expect(prepareBanner).toHaveTextContent(/Start Fresh/i);

    await user.click(screen.getByTestId("apply-upgrade-live-btn"));
    const banners = await screen.findAllByTestId("upgrade-error-banner");
    expect(
      banners.some((b) =>
        b.textContent?.includes("Purpur build download failed"),
      ),
    ).toBe(true);
  });

  it("shows accurate confirmation recovery guidance (not config-conflict text) for retained .prev errors", async () => {
    const user = userEvent.setup();
    mockApi.planServerUpgrade.mockResolvedValue({
      ...UPGRADE_BASE,
      mode: "simple",
      target_loader_id: "purpur",
      target_loader_version: "latest",
      matrix: CLEAN_MATRIX,
      status: "planned",
    });
    mockApi.applyServerUpgrade.mockRejectedValue(
      new ApiError(
        409,
        "CONFLICT",
        "A previous tree retained until confirmation blocks this refresh: journal j-1, path /data/srv.prev, requested policy until_confirm",
      ),
    );

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="simple"
        serverType="purpur"
        currentMc="1.21.11"
      />,
    );

    await user.click(screen.getByTestId("plan-upgrade-btn"));
    await screen.findByTestId("upgrade-compatibility-matrix");
    await user.click(await screen.findByTestId("continue-upgrade-btn"));
    await user.click(screen.getByTestId("apply-upgrade-live-btn"));

    const banner = await screen.findByTestId("upgrade-error-banner");
    expect(banner).toHaveTextContent(/previous version change is still waiting for confirmation/i);
    expect(banner).not.toHaveTextContent(/conflicting config files/i);
  });

  it("renders as a non-blocking docked side panel, defaults async apply to true, and shows inline confirm/rollback buttons when pinned", async () => {
    const user = userEvent.setup();
    const pinnedUpgrade: ServerUpgradeResponse = {
      ...UPGRADE_BASE,
      id: "pinned-prev-1",
      status: "active_pinned",
      pinned_until_confirm: true,
    };
    const currentPlan: ServerUpgradeResponse = {
      ...UPGRADE_BASE,
      id: "current-plan-1",
      mode: "simple",
      target_loader_id: "purpur",
      target_loader_version: "latest",
      matrix: CLEAN_MATRIX,
      status: "planned",
    };

    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [currentPlan, pinnedUpgrade],
      active_upgrade: currentPlan,
      banner_active: true,
      reminder_72h_overdue: false,
    });
    mockApi.planServerUpgrade.mockResolvedValue(currentPlan);
    mockApi.applyServerUpgrade.mockRejectedValue(
      new ApiError(
        409,
        "CONFLICT",
        "A previous tree retained until confirmation blocks this refresh: journal j-prev, path /data/srv.prev, requested policy until_confirm",
      ),
    );
    mockApi.confirmServerUpgrade.mockResolvedValue({
      ...pinnedUpgrade,
      status: "confirmed",
      pinned_until_confirm: false,
    });

    const { container } = renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="simple"
        serverType="purpur"
        currentMc="1.21.11"
      />,
    );

    const panel = await screen.findByTestId("change-version-side-panel");
    expect(panel).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain("inset-0");

    await user.click(await screen.findByTestId("continue-upgrade-btn"));
    const asyncCheckbox = screen.getByTestId(
      "upgrade-async-checkbox",
    ) as HTMLInputElement;
    expect(asyncCheckbox.checked).toBe(true);

    await user.click(screen.getByTestId("apply-upgrade-live-btn"));

    const confirmPrevBtn = await screen.findByTestId(
      "inline-confirm-prev-upgrade-btn",
    );
    expect(
      screen.getByTestId("inline-rollback-prev-upgrade-btn"),
    ).toBeInTheDocument();
    await user.click(confirmPrevBtn);
    await waitFor(() =>
      expect(mockApi.confirmServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "pinned-prev-1",
      ),
    );
  });

  it("surfaces SERVER_UPGRADE active operation conflict with View Live Progress handoff and uses floating card classes", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    useOperationStore.setState({ activeDrawerId: null, operations: {} });

    const currentPlan: ServerUpgradeResponse = {
      ...UPGRADE_BASE,
      id: "plan-conflict-1",
      mode: "simple",
      status: "planned",
      target_mc: "1.21.11",
      target_loader_id: "purpur",
      target_loader_version: "latest",
      matrix: CLEAN_MATRIX,
    };

    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [currentPlan],
      active_upgrade: currentPlan,
      banner_active: false,
      reminder_72h_overdue: false,
    });
    mockApi.applyServerUpgrade.mockRejectedValue(
      new ApiError(
        409,
        "OPERATION_CONCURRENCY_CONFLICT",
        "Mutating operation 'SERVER_UPGRADE' is already active on server 'srv-p55'",
        { operation_id: "op-live-conflict-1", active_operation_type: "SERVER_UPGRADE" },
      ),
    );

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={onClose}
        serverMode="simple"
        serverType="purpur"
        currentMc="1.21.11"
      />,
    );

    const panel = await screen.findByTestId("change-version-side-panel");
    expect(panel.className).toContain("lg:w-[460px]");
    expect(panel.className).toContain("lg:right-4");
    expect(panel.className).toContain("lg:h-fit");

    await user.click(await screen.findByTestId("continue-upgrade-btn"));
    await user.click(screen.getByTestId("apply-upgrade-live-btn"));

    const banner = await screen.findByTestId("upgrade-error-banner");
    expect(banner).toHaveTextContent(
      "A version change operation is already running in the background for this server.",
    );
    expect(banner).not.toHaveTextContent("Resolve the conflicting config files above");

    const viewBtn = await screen.findByTestId("view-conflict-operation-btn");
    await user.click(viewBtn);
    expect(useOperationStore.getState().activeDrawerId).toBe("op-live-conflict-1");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("prevents double-click during apply, renders live step progress, and hands off on View Live Logs", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    useOperationStore.setState({ activeDrawerId: null, operations: {} });

    const currentPlan: ServerUpgradeResponse = {
      ...UPGRADE_BASE,
      id: "plan-bg-1",
      mode: "simple",
      status: "planned",
      target_mc: "1.21.11",
      target_loader_id: "purpur",
      target_loader_version: "latest",
      matrix: CLEAN_MATRIX,
    };

    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [currentPlan],
      active_upgrade: currentPlan,
      banner_active: false,
      reminder_72h_overdue: false,
    });
    let resolveApply!: (val: ServerUpgradeResponse) => void;
    mockApi.applyServerUpgrade.mockImplementation(
      () =>
        new Promise<ServerUpgradeResponse>((res) => {
          resolveApply = res;
        }),
    );
    mockApi.getOperation.mockResolvedValue({
      id: "op-bg-123",
      type: "SERVER_UPGRADE",
      target_type: "server",
      target_id: "srv-p55",
      actor_id: "usr-1",
      status: "RUNNING",
      idempotency_key: null,
      current_step_id: "HEALTH_GATE",
      last_event_seq: 4,
      failure_code: null,
      error_message: null,
      cancellation_requested: false,
      timeout_seconds: 1800,
      created_at: "2026-11-25T11:35:00Z",
      started_at: "2026-11-25T11:35:01Z",
      finished_at: null,
      elapsed_ms: 12300,
      steps: [
        {
          id: "s1",
          step_id: "PREPARE_AND_DOWNLOAD",
          sequence: 1,
          status: "COMPLETED",
          progress: 1,
          elapsed_ms: 2100,
          message_key: "Preparing backup & downloading target artifacts",
          safe_to_retry: false,
          context: {},
          started_at: "2026-11-25T11:35:01Z",
          completed_at: "2026-11-25T11:35:03Z",
        },
        {
          id: "s4",
          step_id: "HEALTH_GATE",
          sequence: 4,
          status: "IN_PROGRESS",
          progress: 0.5,
          elapsed_ms: 10200,
          message_key: "Booting server & running 4-step Health Gate",
          safe_to_retry: false,
          context: {},
          started_at: "2026-11-25T11:35:03Z",
          completed_at: null,
        },
      ],
      metadata: {},
    });

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={onClose}
        serverMode="simple"
        serverType="purpur"
        currentMc="1.21.11"
      />,
    );

    await user.click(await screen.findByTestId("continue-upgrade-btn"));
    const applyBtn = screen.getByTestId("apply-upgrade-live-btn");
    await user.click(applyBtn);
    expect(applyBtn).toBeDisabled();
    // Second click must not trigger duplicate apply calls
    await user.click(applyBtn);
    expect(mockApi.applyServerUpgrade).toHaveBeenCalledTimes(1);

    resolveApply({
      ...currentPlan,
      status: "applying",
      operation_id: "op-bg-123",
    });

    const liveCard = await screen.findByTestId("upgrade-live-progress-card");
    expect(liveCard).toBeInTheDocument();
    expect(
      await screen.findByText(/Booting server & running 5-check Health Gate/),
    ).toBeInTheDocument();

    await user.click(await screen.findByTestId("open-operation-drawer-btn"));
    expect(useOperationStore.getState().activeDrawerId).toBe("op-bg-123");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("keeps rolled-back outcome summary visible inside Change Version and UpgradePinnedBanner instead of vanishing silently", async () => {
    const rolledBackUpgrade: ServerUpgradeResponse = {
      ...UPGRADE_BASE,
      id: "upg-rb-outcome-1",
      mode: "simple",
      status: "rolled_back",
      source_mc: "1.21.4",
      source_loader_id: "purpur",
      target_mc: "1.21.11",
      target_loader_id: "purpur",
      error_code: "nbt_data_version",
      error_message:
        "Health Gate (nbt_data_version) failed: expected >= 4671 for MC 1.21.11. Automatically rolled back to purpur 1.21.4.",
    };

    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [rolledBackUpgrade],
      active_upgrade: null,
      banner_active: false,
      reminder_72h_overdue: false,
    });

    renderWithProviders(
      <>
        <UpgradePinnedBanner serverId="srv-p55" />
        <SafeUpgradeWizardModal
          serverId="srv-p55"
          isOpen
          onClose={vi.fn()}
          serverMode="simple"
          serverType="purpur"
          currentMc="1.21.4"
        />
      </>,
    );

    const outcomeBanner = await screen.findByTestId("upgrade-outcome-banner");
    expect(outcomeBanner).toHaveTextContent("Rolled Back Automatically");
    expect(outcomeBanner).toHaveTextContent(/nbt_data_version/);
    expect(outcomeBanner).toHaveTextContent(/restored to purpur 1\.21\.4 safely/i);
    expect(screen.getByTestId("outcome-banner-dismiss-btn")).toBeInTheDocument();
    expect(screen.getByTestId("outcome-banner-retry-btn")).toBeInTheDocument();

    const alertCard = await screen.findByTestId("upgrade-auto-rollback-alert");
    expect(alertCard).toHaveTextContent("Rolled Back Automatically");
    expect(alertCard).toHaveTextContent(/nbt_data_version/);
    expect(screen.getByTestId("outcome-dismiss-btn")).toBeInTheDocument();
    expect(screen.getByTestId("outcome-try-again-btn")).toBeInTheDocument();
  });

  it("invalidates upgrades, server detail, and branches when applying operation finishes in UpgradePinnedBanner", async () => {
    const applyingUpgrade: ServerUpgradeResponse = {
      ...UPGRADE_BASE,
      id: "upg-applying-sync-1",
      mode: "simple",
      status: "applying",
      operation_id: "op-sync-finish-1",
    };
    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [applyingUpgrade],
      active_upgrade: applyingUpgrade,
      banner_active: false,
      reminder_72h_overdue: false,
    });
    mockApi.getOperation.mockResolvedValue({
      id: "op-sync-finish-1",
      type: "SERVER_UPGRADE",
      target_type: "server",
      target_id: "srv-p55",
      actor_id: "local-admin",
      status: "COMPLETED",
      idempotency_key: null,
      current_step_id: "FINALIZE",
      last_event_seq: 6,
      failure_code: null,
      error_message: null,
      cancellation_requested: false,
      timeout_seconds: 600,
      created_at: "2026-11-25T12:00:00Z",
      started_at: "2026-11-25T12:00:00Z",
      finished_at: "2026-11-25T12:00:10Z",
      elapsed_ms: 10000,
      steps: [],
      metadata: {},
    });

    renderWithProviders(<UpgradePinnedBanner serverId="srv-p55" />);

    await waitFor(() => {
      expect(mockApi.getOperation).toHaveBeenCalledWith("op-sync-finish-1");
    });
    await waitFor(() => {
      expect(mockApi.listServerUpgrades.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("auto-enables External Network Verification when public exposure is active and forwards verify_public_network", async () => {
    const user = userEvent.setup();
    const plannedUpgrade: ServerUpgradeResponse = {
      ...UPGRADE_BASE,
      id: "upg-net-1",
      mode: "simple",
      status: "planned",
      target_mc: "1.21.11",
      target_loader_id: "purpur",
      target_loader_version: "latest",
      matrix: CLEAN_MATRIX,
    };
    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [plannedUpgrade],
      active_upgrade: plannedUpgrade,
      banner_active: false,
      reminder_72h_overdue: false,
    });
    mockApi.getServerExposure.mockResolvedValue({
      server_id: "srv-p55",
      branch_name: "main",
      method: "playit",
      desired_state: "ENABLED",
      aggregate_status: "ACTIVE",
      targets: [
        {
          id: "t1",
          service_type: "java",
          protocol: "tcp",
          local_port: 25565,
          public_address: "demo.joinmc.link:25565",
          status: "ACTIVE",
        },
      ],
    });
    mockApi.applyServerUpgrade.mockResolvedValue({
      ...plannedUpgrade,
      status: "active_pinned",
      pinned_until_confirm: true,
      health_gate_passed: true,
      matrix: {
        ...CLEAN_MATRIX,
        health_gate_checks: [
          { id: "startup_log", label: "Container Boot & Ready Signal", status: "passed", detail: "Done in 18.2s" },
          { id: "local_slp", label: "Local Server Ping (SLP)", status: "passed", detail: "Purpur 1.21.11 · 4ms" },
          { id: "rcon_flush", label: "RCON World Flush", status: "skipped", detail: "RCON disabled in server.properties" },
          { id: "world_nbt", label: "World Save Integrity (NBT)", status: "passed", detail: "DataVersion 4671" },
          { id: "network_reachability", label: "Public Network / Tunnel Probe", status: "warned", detail: "Local server 1.21.11 is healthy, but public address demo.joinmc.link:25565 was unreachable after 3 attempts" },
        ],
        health_gate_warnings: [
          "Local server 1.21.11 is healthy, but public address demo.joinmc.link:25565 was unreachable after 3 attempts",
        ],
      },
    });

    renderWithProviders(
      <SafeUpgradeWizardModal
        serverId="srv-p55"
        isOpen
        onClose={vi.fn()}
        serverMode="simple"
        serverType="purpur"
        currentMc="1.21.4"
      />,
    );

    await user.click(await screen.findByTestId("continue-upgrade-btn"));
    const toggle = (await screen.findByTestId(
      "verify-public-network-toggle",
    )) as HTMLInputElement;
    await waitFor(() => expect(toggle.checked).toBe(true));
    expect(screen.getByTestId("external-network-active-pill")).toHaveTextContent(
      "Active: playit",
    );

    await user.click(screen.getByTestId("apply-upgrade-live-btn"));

    await waitFor(() =>
      expect(mockApi.applyServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "upg-net-1",
        {
          resolved_conflicts: {},
          async_mode: true,
          verify_public_network: true,
        },
      ),
    );

    expect(
      await screen.findByTestId("wizard-health-warning-banner"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("health-gate-checklist")).toBeInTheDocument();
    expect(
      screen.getByTestId("health-gate-check-network_reachability"),
    ).toHaveAttribute("data-status", "warned");
    expect(screen.getByTestId("confirm-upgrade-unpin-btn")).toBeInTheDocument();
    expect(screen.getByTestId("wizard-rollback-pinned-btn")).toBeInTheDocument();
  });

  it("renders public network warning cleanly in UpgradePinnedBanner when active_pinned has warnings", async () => {
    const warnedPinned: ServerUpgradeResponse = {
      ...UPGRADE_BASE,
      id: "upg-warn-banner-1",
      mode: "simple",
      status: "active_pinned",
      pinned_until_confirm: true,
      health_gate_passed: true,
      target_mc: "1.21.11",
      matrix: {
        ...CLEAN_MATRIX,
        health_gate_warnings: [
          "Local server 1.21.11 is healthy, but public address demo.joinmc.link:25565 was unreachable after 3 attempts",
        ],
      },
    };
    mockApi.listServerUpgrades.mockResolvedValue({
      server_id: "srv-p55",
      items: [warnedPinned],
      active_upgrade: warnedPinned,
      banner_active: true,
      reminder_72h_overdue: false,
    });

    renderWithProviders(<UpgradePinnedBanner serverId="srv-p55" />);

    expect(
      await screen.findByTestId("banner-network-warning-pill"),
    ).toHaveTextContent("Public Network Warning");
    expect(screen.getByTestId("banner-health-warning")).toHaveTextContent(
      "demo.joinmc.link:25565",
    );
    expect(screen.getByTestId("banner-confirm-upgrade-btn")).toBeInTheDocument();
    expect(
      screen.getByTestId("banner-emergency-rollback-btn"),
    ).toBeInTheDocument();
  });
});
