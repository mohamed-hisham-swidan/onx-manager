import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/services/api";
import type {
  CompatibilityMatrixPayload,
  InstallPlanPayload,
  LecEntryResponse,
  MatrixEntryItem,
  ModpackInspectResponse,
  ServerP55SettingsResponse,
  ServerUpgradeListResponse,
  ServerUpgradeResponse,
} from "@/server_manager/types";
import { PanelP55IntegrationsSection } from "./PanelP55IntegrationsSection";
import { ServerP55SettingsCard } from "./ServerP55SettingsCard";
import { ModpackInstallWizardModal } from "./ModpackInstallWizardModal";
import { SafeUpgradeWizardModal } from "./SafeUpgradeWizardModal";
import { UpgradePinnedBanner } from "./UpgradePinnedBanner";

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
  listServerUpgrades: vi.fn(),
  getServerUpgrade: vi.fn(),
  planServerUpgrade: vi.fn(),
  resolveUpgradeManualUpload: vi.fn(),
  prepareServerUpgradeTest: vi.fn(),
  applyServerUpgrade: vi.fn(),
  confirmServerUpgrade: vi.fn(),
  rollbackServerUpgrade: vi.fn(),
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

const NOT_CONFIGURED = { configured: false, source: "none" as const, hint: null };
const CONFIGURED_PANEL = {
  configured: true,
  source: "panel" as const,
  hint: "***...9f2a",
};

const LEC_ENTRY: LecEntryResponse = {
  lec_key: "fabric/1.21.1/0.16.9/1.0.1",
  loader_id: "fabric",
  mc_version: "1.21.1",
  loader_version: "0.16.9",
  installer_version: "1.0.1",
  java_major: 21,
  status: "ready",
  size_bytes: 52_428_800,
  file_count: 37,
  complete_manifest_sha256: "abc123",
  ready_on_disk: true,
  last_used_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

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

describe("PanelP55IntegrationsSection — CurseForge & Host LEC", () => {
  beforeEach(resetApi);

  it("stores a panel CurseForge key, clears plaintext, and shows masked status", async () => {
    const user = userEvent.setup();
    mockApi.getCurseForgeIntegrationStatus
      .mockResolvedValueOnce(NOT_CONFIGURED)
      .mockResolvedValue(CONFIGURED_PANEL);
    mockApi.setCurseForgeIntegrationKey.mockResolvedValue(CONFIGURED_PANEL);
    mockApi.listLecEntries.mockResolvedValue([]);

    const { container } = renderWithProviders(<PanelP55IntegrationsSection />);

    expect(await screen.findByText("Not Configured")).toBeInTheDocument();
    const key = "$2a$10$secret-key-9f2a";
    const input = screen.getByTestId("curseforge-api-key-input");
    await user.type(input, key);
    await user.click(screen.getByTestId("save-curseforge-key-btn"));

    await waitFor(() =>
      expect(mockApi.setCurseForgeIntegrationKey).toHaveBeenCalledWith({
        api_key: key,
      }),
    );
    await waitFor(() => expect(input).toHaveValue(""));
    expect(container.textContent ?? "").not.toContain("secret-key-9f2a");
    expect(
      await screen.findByText("Configured (Panel Encrypted Store)"),
    ).toBeInTheDocument();
    expect(screen.getByText("***...9f2a")).toBeInTheDocument();
  });

  it("deletes a stored panel key", async () => {
    const user = userEvent.setup();
    mockApi.getCurseForgeIntegrationStatus
      .mockResolvedValueOnce(CONFIGURED_PANEL)
      .mockResolvedValue(NOT_CONFIGURED);
    mockApi.deleteCurseForgeIntegrationKey.mockResolvedValue(NOT_CONFIGURED);
    mockApi.listLecEntries.mockResolvedValue([]);

    renderWithProviders(<PanelP55IntegrationsSection />);

    expect(
      await screen.findByText("Configured (Panel Encrypted Store)"),
    ).toBeInTheDocument();
    await user.click(screen.getByTestId("delete-curseforge-key-btn"));
    await waitFor(() =>
      expect(mockApi.deleteCurseForgeIntegrationKey).toHaveBeenCalledTimes(1),
    );
    expect(await screen.findByText("Not Configured")).toBeInTheDocument();
  });

  it("lists LEC entries, pre-warms an entry, and prunes the cache with a freed-byte summary", async () => {
    const user = userEvent.setup();
    mockApi.getCurseForgeIntegrationStatus.mockResolvedValue(NOT_CONFIGURED);
    mockApi.listLecEntries.mockResolvedValue([LEC_ENTRY]);
    mockApi.prewarmLecEntry.mockResolvedValue({
      lec_key: "fabric/1.21.1/0.16.9/1.0.1",
      status: "ready",
      file_count: 37,
      total_bytes: 52_428_800,
      java_major: 21,
      unix_args_relpath: "args/unix.args",
      operation_id: "op-lec-1",
    });
    mockApi.gcLecEntries.mockResolvedValue({
      pruned_lec_keys: ["fabric/old/1.0/0.1"],
      pruned_cas_digests: ["digest1", "digest2"],
      freed_bytes: 1_572_864,
    });

    renderWithProviders(<PanelP55IntegrationsSection />);

    expect(
      await screen.findByText("fabric/1.21.1/0.16.9/1.0.1"),
    ).toBeInTheDocument();
    expect(screen.getByText("Verified (.onx-complete.json)")).toBeInTheDocument();
    expect(screen.getByText("Java 21")).toBeInTheDocument();

    await user.click(screen.getByTestId("lec-prewarm-btn"));
    await waitFor(() =>
      expect(mockApi.prewarmLecEntry).toHaveBeenCalledWith(
        expect.objectContaining({
          loader_id: "fabric",
          mc_version: "1.21.1",
          loader_version: "0.16.9",
          installer_version: "1.0.1",
        }),
      ),
    );
    expect(await screen.findByText("Open Operation Drawer")).toBeInTheDocument();

    await user.click(screen.getByTestId("lec-gc-btn"));
    await waitFor(() =>
      expect(mockApi.gcLecEntries).toHaveBeenCalledWith({ min_age_days: 7 }),
    );
    expect(
      await screen.findByText(/2 CAS blobs pruned/i),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("lec-gc-btn").parentElement?.textContent ?? "",
    ).toContain("1.50 MB freed");
  });
});

describe("ServerP55SettingsCard", () => {
  beforeEach(resetApi);

  it("loads settings, validates the 300–900s bound, edits toggles and custom hosts, then saves", async () => {
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
    expect(screen.getByText("cdn.modrinth.com")).toBeInTheDocument();

    await user.clear(timeout);
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
    expect(
      await screen.findByText("Modpack & upgrade settings saved."),
    ).toBeInTheDocument();
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
    expect(await screen.findByText("Verified in CAS")).toBeInTheDocument();
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
    expect(screen.getByText("blocker: no_target_build")).toBeInTheDocument();
    expect(screen.getByText("blocker: manual_download_required")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Unresolved (Carried Forward — Does Not Block Test/Upgrade)",
      ),
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
    await user.click(screen.getByTestId("continue-upgrade-btn"));

    expect(
      screen.queryByTestId("prepare-upgrade-test-btn"),
    ).not.toBeInTheDocument();
    const apply = screen.getByTestId("apply-upgrade-live-btn");
    expect(apply).toHaveTextContent("Apply 1-Click Safe Upgrade");
    await user.click(apply);

    await waitFor(() =>
      expect(mockApi.applyServerUpgrade).toHaveBeenCalledWith(
        "srv-p55",
        "upgrade-1",
        { resolved_conflicts: {}, async_mode: false },
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
        upgrade_branch: "upgrade/1.21.4",
        data_template_id: "dt-clone-1",
      },
      runtime: {
        runtime_id: "runtime-1",
        server_id: "srv-p55",
        branch_name: "upgrade/1.21.4",
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
    await user.click(screen.getByTestId("continue-upgrade-btn"));

    const prepare = screen.getByTestId("prepare-upgrade-test-btn");
    expect(prepare).toHaveTextContent(
      "Prepare upgrade/1.21.4 Branch & Start Isolated Test",
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
      await screen.findByText("Branch: upgrade/1.21.4"),
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
    await user.click(screen.getByTestId("continue-upgrade-btn"));
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
      screen.getByText(/restored atomically/i),
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
});
