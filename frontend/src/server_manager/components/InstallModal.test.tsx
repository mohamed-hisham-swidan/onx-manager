import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { InstallModal } from "./InstallModal";
import type { PluginSearchResultResponse } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

let mockServers: ServerResponse[] = [];
let mockIsPending = false;
let mockInstalledPlugins: Array<{ name: string; filename: string; version?: string; size_bytes: number; external_project_id?: string | null }> | undefined = undefined;
let mockVersionList = [
  {
    version_id: "v1",
    project_id: "test-plugin",
    name: "1.0.0",
    version_number: "1.0.0",
    game_versions: ["1.21"],
    loaders: ["paper"],
    files: [{ url: "https://example.com/p.jar", filename: "p.jar", size_bytes: 1024, sha1: "", sha512: "", primary: true }],
    dependencies: [] as string[],
    required_dependencies: [] as string[],
    date_published: "2026-01-01T00:00:00Z",
  },
];
const mockInstallMutate = vi.fn();
const mockGetServerBranches = vi.fn();
const mockGetMarketplaceProject = vi.fn();
let mockSelectedVersionOverride: unknown = undefined;

const mockProject: PluginSearchResultResponse = {
  project_id: "test-plugin",
  slug: "test-plugin",
  title: "Test Plugin",
  description: "A test plugin description",
  author: "TestAuthor",
  project_types: ["plugin"],
  downloads: 500,
  follows: 20,
  icon_url: "",
  latest_version_id: "v1",
  categories: ["admin"],
  loaders: ["paper"],
  client_side: "unsupported",
  server_side: "required",
  date_modified: "2026-01-01T00:00:00Z",
  color: null,
};

const mockVersions = {
  project_id: "test-plugin",
  versions: [
    {
      version_id: "v1",
      project_id: "test-plugin",
      name: "1.0.0",
      version_number: "1.0.0",
      game_versions: ["1.21"],
      loaders: ["paper"],
      files: [{ url: "https://example.com/p.jar", filename: "p.jar", size_bytes: 1024, sha1: "", sha512: "", primary: true }],
      dependencies: [],
      date_published: "2026-01-01T00:00:00Z",
    },
  ],
  selected: {
    version_id: "v1",
    project_id: "test-plugin",
    name: "1.0.0",
    version_number: "1.0.0",
    game_versions: ["1.21"],
    loaders: ["paper"],
    files: [{ url: "https://example.com/p.jar", filename: "p.jar", size_bytes: 1024, sha1: "", sha512: "", primary: true }],
    dependencies: [],
    date_published: "2026-01-01T00:00:00Z",
  },
  notice: "",
  notice_kind: "",
};

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: () => ({ data: mockServers }),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  useProjectVersions: () => ({
    data: {
      ...mockVersions,
      versions: mockVersionList,
      selected:
        mockSelectedVersionOverride !== undefined
          ? mockSelectedVersionOverride
          : (mockVersionList[0] ?? null),
    },
    isLoading: false,
    isError: false,
    error: null,
  }),
  usePluginsList: () => ({
    data: mockInstalledPlugins,
  }),
  useInstallFromMarketplace: () => ({
    mutate: mockInstallMutate,
    isPending: mockIsPending,
  }),
}));

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...actual,
    createAuthenticatedApi: () => ({
      getServerBranches: (...args: unknown[]) => mockGetServerBranches(...args),
      getMarketplaceProject: (...args: unknown[]) => mockGetMarketplaceProject(...args),
    }),
  };
});

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

vi.mock("@/stores/lastUsedServerStore", () => ({
  useLastUsedServerStore: <T,>(selector: (state: { lastUsedServerId: string; setLastUsedServer: () => void }) => T): T =>
    selector({
      lastUsedServerId: "srv-paper",
      setLastUsedServer: vi.fn(),
    }),
}));

vi.mock("@/stores/marketplaceSourceStore", () => ({
  useMarketplaceSourceStore: <T,>(selector: (state: { source: string }) => T): T =>
    selector({
      source: "modrinth",
    }),
}));

describe("InstallModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockIsPending = false;
    mockSelectedVersionOverride = undefined;
    mockInstalledPlugins = undefined;
    mockGetMarketplaceProject.mockRejectedValue(new Error("not mocked"));
    mockVersionList = [
      {
        version_id: "v1",
        project_id: "test-plugin",
        name: "1.0.0",
        version_number: "1.0.0",
        game_versions: ["1.21"],
        loaders: ["paper"],
        files: [{ url: "https://example.com/p.jar", filename: "p.jar", size_bytes: 1024, sha1: "", sha512: "", primary: true }],
        dependencies: [],
        required_dependencies: [],
        date_published: "2026-01-01T00:00:00Z",
      },
    ];
    mockServers = [
      {
        server_id: "srv-paper",
        name: "Paper Server 1",
        server_type: "paper",
        minecraft_version: "1.21.1",
      },
    ] as unknown as ServerResponse[];
  });

  it("does not render when isOpen is false", () => {
    render(
      <InstallModal
        isOpen={false}
        project={mockProject}
        onClose={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders role='dialog' with accessible name, acquires scroll lock, and releases on unmount", () => {
    document.body.style.overflow = "";
    const { unmount } = render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Install Test Plugin" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes on Escape key when idle", () => {
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape when install is pending", () => {
    mockIsPending = true;
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes when clicking backdrop when idle", () => {
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when clicking backdrop while install is pending", () => {
    mockIsPending = true;
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close when clicking inside dialog content", () => {
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Install Test Plugin" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog on open", async () => {
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Install Test Plugin" });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const activeEl = document.activeElement;
    expect(dialog.contains(activeEl)).toBe(true);
  });

  it("disables Install button and ignores close button when install is pending", async () => {
    mockIsPending = true;
    const onClose = vi.fn();
    render(
      <InstallModal
        isOpen={true}
        project={mockProject}
        onClose={onClose}
      />
    );

    const installBtn = screen.getByRole("button", { name: /Installing.../i });
    expect(installBtn).toBeDisabled();

    const closeBtn = screen.getByRole("button", { name: "Close modal" });
    fireEvent.click(closeBtn);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("prioritizes explicit serverId prop over lastUsedServerId and warns if requested server is incompatible", () => {
    mockInstalledPlugins = undefined;
    mockVersionList = [{ ...mockVersions.versions[0], required_dependencies: [] }];
    const srvPaper1 = {
      server_id: "srv-paper",
      name: "Paper 1",
      server_type: "paper",
      minecraft_version: "1.21.1",
      status: "stopped",
      port: 25565,
      motd: "",
      max_players: 20,
      gamemode: "survival",
      difficulty: "normal",
      created_at: "",
      updated_at: "",
    } as ServerResponse;
    const srvPaper2 = { ...srvPaper1, server_id: "srv-paper-2", name: "Paper 2" } as ServerResponse;
    const srvFabric = {
      ...srvPaper1,
      server_id: "srv-fabric",
      name: "Fabric 1",
      server_type: "fabric",
    } as ServerResponse;
    mockServers = [srvPaper1, srvPaper2, srvFabric];
    mockIsPending = false;

    const { rerender } = render(
      <InstallModal isOpen={true} project={mockProject} serverId="srv-paper-2" onClose={vi.fn()} />,
    );
    expect(screen.getByText("Paper 2")).toBeInTheDocument();

    rerender(
      <InstallModal isOpen={true} project={mockProject} serverId="srv-fabric" onClose={vi.fn()} />,
    );
    expect(screen.getByTestId("incompatible-server-notice")).toHaveTextContent(
      /Fabric 1.*fabric.*does not support plugins/i,
    );
  });

  it("fails closed while Advanced server branches are loading or errored, and allows Retry", async () => {
    mockInstalledPlugins = undefined;
    mockVersionList = [{ ...mockVersions.versions[0], required_dependencies: [] }];
    mockIsPending = false;
    mockServers = [
      {
        server_id: "srv-adv",
        name: "Advanced Paper",
        server_type: "paper",
        minecraft_version: "1.21.1",
        mode: "advanced",
        status: "stopped",
        port: 25565,
        motd: "",
        max_players: 20,
        gamemode: "survival",
        difficulty: "normal",
        created_at: "",
        updated_at: "",
      } as ServerResponse,
    ];

    let rejectBranches!: (e: Error) => void;
    mockGetServerBranches.mockImplementationOnce(
      () =>
        new Promise((_res, rej) => {
          rejectBranches = rej;
        }),
    );

    render(<InstallModal isOpen={true} project={mockProject} serverId="srv-adv" onClose={vi.fn()} />);

    expect(screen.getByTestId("install-modal-branches-loading")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Checking branches.../i })).toBeDisabled();

    await act(async () => {
      rejectBranches(new Error("git branch check failed"));
    });

    expect(screen.getByTestId("install-modal-branches-error")).toHaveTextContent("git branch check failed");
    expect(screen.getByRole("button", { name: /Install Now/i })).toBeDisabled();

    mockGetServerBranches.mockResolvedValueOnce([
      { name: "main", worktree_path: "/srv/main" },
      { name: "dev", worktree_path: "/srv/dev" },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));

    await waitFor(() => {
      expect(screen.getByTestId("install-modal-branch-select")).toHaveValue("dev");
    });
    expect(screen.getByRole("button", { name: /Install Now/i })).toBeEnabled();
  });

  it("shows already-installed notice, resolves dependency titles, marks installed deps, and supports 2-option sequential install", async () => {
    mockIsPending = false;
    mockServers = [
      {
        server_id: "srv-paper",
        name: "Paper 1",
        server_type: "paper",
        minecraft_version: "1.21.1",
        status: "stopped",
        port: 25565,
        motd: "",
        max_players: 20,
        gamemode: "survival",
        difficulty: "normal",
        created_at: "",
        updated_at: "",
      } as ServerResponse,
    ];
    mockInstalledPlugins = [
      { name: "Test Plugin", filename: "test-plugin-0.9.0.jar", version: "0.9.0", size_bytes: 1024 },
      { name: "Vault", external_project_id: "vault", filename: "Vault.jar", version: "1.7.3", size_bytes: 512 },
    ];
    mockVersionList = [
      {
        ...mockVersions.versions[0],
        required_dependencies: ["vault", "protocollib"],
      },
    ];
    mockGetMarketplaceProject.mockImplementation((id: string) => {
      if (id === "vault") return Promise.resolve({ project_id: "vault", slug: "vault", title: "Vault" });
      if (id === "protocollib") return Promise.resolve({ project_id: "protocollib", slug: "protocollib", title: "ProtocolLib" });
      return Promise.reject(new Error("not found"));
    });

    const installedOrder: string[] = [];
    mockInstallMutate.mockImplementation((body: { project_id: string }, opts?: { onSuccess?: (r: { version: string }) => void }) => {
      installedOrder.push(body.project_id);
      opts?.onSuccess?.({ version: "1.0.0" });
    });

    const onClose = vi.fn();
    render(<InstallModal isOpen={true} project={mockProject} onClose={onClose} />);

    expect(screen.getByTestId("already-installed-notice")).toHaveTextContent("0.9.0");
    expect(screen.getByTestId("install-modal-dependencies")).toHaveTextContent("2");

    await waitFor(() => {
      expect(screen.getByText("ProtocolLib")).toBeInTheDocument();
      expect(screen.getByText("Vault")).toBeInTheDocument();
    });
    expect(screen.getByTestId("dep-installed-vault")).toHaveTextContent("Installed");

    // 2-option action buttons shown when missing dependencies exist
    const withDepsBtn = screen.getByRole("button", { name: /Install with Dependencies/i });
    const onlyThisBtn = screen.getByRole("button", { name: /Install Only This/i });
    expect(withDepsBtn).toBeEnabled();
    expect(onlyThisBtn).toBeEnabled();

    await act(async () => {
      fireEvent.click(withDepsBtn);
    });

    // Vault was already installed, so only protocollib + main project should install sequentially
    expect(installedOrder).toEqual(["protocollib", "test-plugin"]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("excludes snapshots from Game Version picker, shows fallback & mismatch amber notices without blocking Install, and preserves initialVersionId", () => {
    mockServers = [
      {
        server_id: "srv-purpur",
        name: "Purpur Main",
        server_type: "purpur",
        minecraft_version: "1.21.11",
        status: "stopped",
        port: 25565,
        motd: "",
        max_players: 20,
        gamemode: "survival",
        difficulty: "normal",
        created_at: "",
        updated_at: "",
      } as ServerResponse,
    ];
    const paperCompat = {
      version_id: "v-paper-12111",
      project_id: "test-plugin",
      name: "2.0.0-paper",
      version_number: "2.0.0",
      version_type: "release",
      game_versions: ["1.21.11", "26.1-snapshot-1", "24w14potato"],
      loaders: ["paper"],
      files: [{ url: "https://example.com/p2.jar", filename: "plugin-2.0.0.jar", size_bytes: 2048, sha1: "", sha512: "", primary: true }],
      dependencies: [],
      required_dependencies: [],
      date_published: "2026-03-01T00:00:00Z",
    };
    const fabricOldBeta = {
      version_id: "v-fabric-1204",
      project_id: "test-plugin",
      name: "1.5.0-beta",
      version_number: "1.5.0-beta",
      version_type: "beta",
      game_versions: ["1.20.4"],
      loaders: ["fabric"],
      files: [{ url: "https://example.com/f1.jar", filename: "plugin-1.5.0-beta.jar", size_bytes: 4096, sha1: "", sha512: "", primary: true }],
      dependencies: [],
      required_dependencies: [],
      date_published: "2025-01-01T00:00:00Z",
    };
    mockVersionList = [paperCompat, fabricOldBeta];
    mockSelectedVersionOverride = paperCompat;

    render(<InstallModal isOpen={true} project={mockProject} serverId="srv-purpur" onClose={vi.fn()} />);

    // Clean release options only (snapshots strictly excluded)
    const gvSelect = screen.getByRole("combobox", { name: "Game Version" });
    const gvOptions = Array.from(gvSelect.querySelectorAll("option")).map((o) => o.textContent);
    expect(gvOptions).toEqual(["1.21.11", "1.20.4"]);
    expect(gvOptions).not.toContain("26.1-snapshot-1");
    expect(gvOptions).not.toContain("24w14potato");

    // Fallback notice shown when Paper build selected for Purpur server
    expect(screen.getByTestId("install-fallback-notice")).toHaveTextContent(
      "No Purpur-tagged build for MC 1.21.11 — using the Paper build, which Purpur supports.",
    );
    expect(screen.getByTestId("install-resolved-summary")).toHaveTextContent("plugin-2.0.0.jar");
    expect(screen.getByTestId("install-channel-pill")).toHaveTextContent("Release");

    // Manual mismatch selection: shows amber warning WITHOUT disabling Install
    fireEvent.change(gvSelect, { target: { value: "1.20.4" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Platform / Loader" }), {
      target: { value: "fabric" },
    });

    expect(screen.getByTestId("install-mismatch-warning")).toHaveTextContent(
      "Not officially listed for Purpur 1.21.11 — install at your own risk",
    );
    expect(screen.getByTestId("install-channel-pill")).toHaveTextContent("Beta");
    expect(screen.getByRole("button", { name: /Install Now/i })).toBeEnabled();
  });

  it("installs only the main project when Install Only This is clicked", () => {
    mockVersionList = [
      {
        ...mockVersions.versions[0],
        required_dependencies: ["vault"],
      },
    ];
    const onClose = vi.fn();
    render(<InstallModal isOpen={true} project={mockProject} onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: /Install Only This/i }));
    expect(mockInstallMutate).toHaveBeenCalledTimes(1);
    expect(mockInstallMutate).toHaveBeenCalledWith(
      { project_id: "test-plugin", version_id: "v1" },
      expect.any(Object),
    );
  });
});
