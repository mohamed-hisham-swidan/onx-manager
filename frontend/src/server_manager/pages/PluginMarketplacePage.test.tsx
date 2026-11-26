import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PluginMarketplacePage } from "./PluginMarketplacePage";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockResults = [
  {
    project_id: "essentialsx",
    slug: "essentialsx",
    title: "EssentialsX",
    description: "Essential commands",
    author: "Essentials Team",
    project_types: ["plugin"],
    downloads: 1200000,
    follows: 100,
    icon_url: "",
    latest_version_id: "v1",
    categories: ["management"],
    loaders: ["paper"],
    client_side: "unsupported",
    server_side: "required",
    date_modified: new Date(Date.now() - 86400000).toISOString(),
    color: null,
  },
];

const mockSearchResults = {
  items: mockResults,
  total_hits: mockResults.length,
  offset: 0,
  limit: 20,
};

const mockVersions = {
  project_id: "essentialsx",
  versions: [
    {
      version_id: "v1",
      project_id: "essentialsx",
      name: "EssentialsX 2.21.0",
      version_number: "2.21.0",
      game_versions: ["1.21", "1.21.1"],
      loaders: ["paper", "spigot"],
      files: [{ url: "https://example.com/x.jar", filename: "x.jar", size_bytes: 2048, sha1: "", sha512: "", primary: true }],
      dependencies: [],
      date_published: "2025-01-01T00:00:00Z",
    },
    {
      version_id: "v2",
      project_id: "essentialsx",
      name: "EssentialsX 2.20.0",
      version_number: "2.20.0",
      game_versions: ["1.20.4"],
      loaders: ["paper"],
      files: [{ url: "https://example.com/y.jar", filename: "y.jar", size_bytes: 2048, sha1: "", sha512: "", primary: true }],
      dependencies: [],
      date_published: "2024-01-01T00:00:00Z",
    },
  ],
  selected: {
    version_id: "v1",
    project_id: "essentialsx",
    name: "EssentialsX 2.21.0",
    version_number: "2.21.0",
    game_versions: ["1.21", "1.21.1"],
    loaders: ["paper", "spigot"],
    files: [{ url: "https://example.com/x.jar", filename: "x.jar", size_bytes: 2048, sha1: "", sha512: "", primary: true }],
    dependencies: [],
    date_published: "2025-01-01T00:00:00Z",
  },
  notice: "",
  notice_kind: "",
};

let mockServers: unknown[] = [];
let mockInstallCallbacks: { onSuccess?: (r: unknown) => void; onError?: (e: unknown) => void } = {};
const mockInstallMutate = vi.fn((_body: unknown, opts: unknown) => {
  mockInstallCallbacks = (opts ?? {}) as typeof mockInstallCallbacks;
});

interface SearchMock {
  data: unknown;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch?: () => void;
}

const { useMarketplaceSearch, useMarketplaceSearchGlobal, usePluginsList, useMinecraftVersions } = vi.hoisted(() => {
  const empty: SearchMock = { data: null, isLoading: false, isError: false, error: null, refetch: vi.fn() };
  return {
    useMarketplaceSearch: vi.fn<
      (serverId: string, query: string, options?: { enabled?: boolean; projectType?: string; offset?: number; loader?: string; sort?: string; gameVersion?: string; compatibleOnly?: boolean }) => SearchMock
    >(() => empty),
    useMarketplaceSearchGlobal: vi.fn<
      (query: string, options?: { enabled?: boolean; projectType?: string; offset?: number; loader?: string; sort?: string; gameVersion?: string }) => SearchMock
    >(() => empty),
    usePluginsList: vi.fn(() => ({ data: undefined as unknown })),
    useMinecraftVersions: vi.fn(() => ({ data: undefined as string[] | undefined })),
  };
});

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({ data: mockServers })),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  MARKETPLACE_PAGE_SIZE: 20,
  useMarketplaceSearch,
  useMarketplaceSearchGlobal,
  usePluginsList,
  useMinecraftVersions,
  useProjectVersions: vi.fn(() => ({ data: mockVersions, isLoading: false, isError: false, error: null })),
  useInstallFromMarketplace: vi.fn(() => ({ mutate: mockInstallMutate, isPending: false, reset: vi.fn() })),
}));

function renderPage(initialEntry: string | { pathname: string; state?: unknown } = "/marketplace") {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <PluginMarketplacePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function serverFixture(overrides: Record<string, string>) {
  return {
    server_id: "srv-1",
    name: "Paper Server 1",
    server_type: "paper",
    minecraft_version: "1.21.1",
    status: "running",
    group_id: "",
    port: 25565,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "easy",
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";

describe("PluginMarketplacePage & InstallModal", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockInstallMutate.mockClear();
    mockInstallCallbacks = {};
    useMarketplaceSearch.mockReturnValue({ data: null, isLoading: false, isError: false, error: null, refetch: vi.fn() });
    useMarketplaceSearchGlobal.mockReturnValue({ data: null, isLoading: false, isError: false, error: null, refetch: vi.fn() });
    usePluginsList.mockReturnValue({ data: undefined });
    useMinecraftVersions.mockReturnValue({ data: undefined });
    mockServers = [
      serverFixture({ server_id: "srv-1", name: "Paper Server 1", server_type: "paper", minecraft_version: "1.21.1" }),
      serverFixture({ server_id: "srv-2", name: "Paper Server 2", server_type: "paper", minecraft_version: "1.20.4" }),
      serverFixture({ server_id: "srv-3", name: "Fabric Server", server_type: "fabric", minecraft_version: "1.20.4" }),
    ];
    useLastUsedServerStore.setState({ lastUsedServerId: "" });
    useMarketplaceSourceStore.setState({ source: "modrinth" });
    localStorage.removeItem("onx_last_used_server");
    localStorage.removeItem("onx_marketplace_source");
    localStorage.removeItem("onx_marketplace_view_mode");
  });

  it("renders page header", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Marketplace" })).toBeInTheDocument();
  });

  it("renders marketplace results as project cards with schema fields", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockSearchResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");

    expect(screen.getByTestId("project-card-list")).toBeInTheDocument();
    const card = screen.getByTestId("project-card-essentialsx");
    expect(card).toBeInTheDocument();
    expect(within(card).getByText("Paper")).toBeInTheDocument();
    expect(within(card).getByText("Server-side")).toBeInTheDocument();
  });

  it("renders Modrinth marketplace and hides CurseForge source switch", () => {
    renderPage();
    expect(screen.queryByRole("button", { name: /CurseForge/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Modrinth/i })).not.toBeInTheDocument();
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith(
      "",
      expect.objectContaining({ enabled: true, projectType: "plugin", offset: 0 }),
    );
  });

  it("disables global search hook when serverId is present in query parameters", () => {
    renderPage("/marketplace?serverId=srv-1");
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith("", expect.objectContaining({
      enabled: false,
    }));
    expect(useMarketplaceSearch).toHaveBeenLastCalledWith("srv-1", "", expect.objectContaining({
      enabled: true,
      compatibleOnly: true,
    }));
  });

  it("switches Discover type from Plugins to Mods and passes projectType to search hook", () => {
    renderPage();
    const discoverGroup = screen.getByRole("group", { name: /discover type/i });
    expect(discoverGroup).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mods" }));

    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith(
      "",
      expect.objectContaining({
        enabled: true,
        projectType: "mod",
        offset: 0,
      }),
    );
  });

  it("opens InstallModal on Install button click from search results", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockSearchResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Paper Server 1")).toBeInTheDocument();
  });

  it("opens InstallModal automatically when entering with location.state.selectedProject", () => {
    renderPage({
      pathname: "/marketplace",
      state: { selectedProject: mockResults[0] },
    });

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("EssentialsX")).toBeInTheDocument();
  });

  it("opens InstallModal with two clean pickers and resolved build summary (no raw version list)", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockSearchResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    expect(screen.queryByTestId("version-list")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Game Version" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Platform / Loader" })).toBeInTheDocument();
    expect(screen.getByTestId("install-resolved-summary")).toHaveTextContent("2.21.0");
  });

  it("hard excludes incompatible servers (e.g. Fabric server excluded for plugins)", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockSearchResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    fireEvent.click(screen.getByText("Change Server"));

    expect(screen.getByText("Paper Server 1")).toBeInTheDocument();
    expect(screen.getByText("Paper Server 2")).toBeInTheDocument();
    expect(screen.queryByText("Fabric Server")).not.toBeInTheDocument();
  });

  it("resets version selection when target server is changed", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockSearchResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    fireEvent.click(screen.getByText("Change Server"));
    fireEvent.click(screen.getByText("Paper Server 2"));

    expect(screen.getByText("Paper Server 2")).toBeInTheDocument();
  });

  it("renders clear empty state when no compatible servers exist", () => {
    mockServers = [
      serverFixture({ server_id: "srv-3", name: "Fabric Server", server_type: "fabric", minecraft_version: "1.20.4" }),
    ];
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockSearchResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    expect(screen.getByText("No compatible servers available")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Install Now/i })).toBeDisabled();
  });

  it("executes installation and updates last used server on success", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockSearchResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    fireEvent.click(screen.getByRole("button", { name: /Install Now/i }));

    expect(mockInstallMutate).toHaveBeenCalledWith(
      { project_id: "essentialsx", version_id: "v1" },
      expect.any(Object),
    );

    act(() => mockInstallCallbacks.onSuccess?.({ version: "2.21.0" }));
    expect(useLastUsedServerStore.getState().lastUsedServerId).toBe("srv-1");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("passes page offset to the search hook when navigating pagination", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: { items: mockResults, total_hits: 25, offset: 0, limit: 20 }, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");

    fireEvent.click(screen.getByRole("button", { name: "Page 2" }));

    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith(
      "",
      expect.objectContaining({
        enabled: true,
        projectType: "plugin",
        offset: 20,
      }),
    );
  });

  it("fetches the page offset from the URL page param on initial load", () => {
    renderPage("/marketplace?page=2");

    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith(
      "",
      expect.objectContaining({
        enabled: true,
        projectType: "plugin",
        offset: 20,
      }),
    );
  });

  it("resets pagination to the first page when a new search is submitted", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: { items: mockResults, total_hits: 25, offset: 0, limit: 20 }, isLoading: false, isError: false, error: null });
    renderPage("/marketplace?page=2");

    const input = screen.getByRole("textbox", { name: /Search plugins/i });
    fireEvent.change(input, { target: { value: "essentials" } });
    fireEvent.submit(input.closest("form")!);

    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith(
      "essentials",
      expect.objectContaining({
        enabled: true,
        projectType: "plugin",
        offset: 0,
      }),
    );
  });

  it("passes a ?loader= platform filter to the search and shows a removable tag", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: { items: mockResults, total_hits: 1, offset: 0, limit: 20 }, isLoading: false, isError: false, error: null });
    renderPage("/marketplace?loader=fabric");

    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith(
      "",
      expect.objectContaining({
        enabled: true,
        projectType: "plugin",
        offset: 0,
        loader: "fabric",
      }),
    );
    const tag = screen.getByTestId("loader-filter-tag");
    expect(tag).toHaveTextContent("Fabric");

    useMarketplaceSearchGlobal.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Remove Fabric platform filter" }));
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith(
      "",
      expect.objectContaining({
        enabled: true,
        projectType: "plugin",
        offset: 0,
      }),
    );
    expect(useMarketplaceSearchGlobal.mock.lastCall?.[1]?.loader).toBeUndefined();
    expect(screen.queryByTestId("loader-filter-tag")).not.toBeInTheDocument();
  });

  it("allows toggling between cards grid view and compact list view", () => {
    useMarketplaceSearchGlobal.mockReturnValue({
      data: mockSearchResults,
      isLoading: false,
      isError: false,
      error: null,
    });
    renderPage("/marketplace");

    const list = screen.getByTestId("project-card-list");
    expect(list.className).toContain("grid");

    fireEvent.click(screen.getByRole("button", { name: /compact list view/i }));
    expect(list.className).toContain("space-y-3");

    fireEvent.click(screen.getByRole("button", { name: /grid card view/i }));
    expect(list.className).toContain("grid");
  });

  it("debounces live search input and threads sort, MC version, and compatible-only toggle", () => {
    vi.useFakeTimers();
    try {
      renderPage("/marketplace?serverId=srv-1");

      fireEvent.change(screen.getByRole("combobox", { name: /Sort results/i }), {
        target: { value: "downloads" },
      });
      fireEvent.change(screen.getByRole("combobox", { name: /Filter by Minecraft version/i }), {
        target: { value: "1.21.1" },
      });
      fireEvent.click(screen.getByTestId("compatible-only-toggle"));

      expect(useMarketplaceSearch).toHaveBeenLastCalledWith(
        "srv-1",
        "",
        expect.objectContaining({
          sort: "downloads",
          gameVersion: "1.21.1",
        }),
      );
      expect(useMarketplaceSearch.mock.lastCall?.[2]?.compatibleOnly).toBeUndefined();

      const input = screen.getByRole("textbox", { name: /Search plugins/i });
      fireEvent.change(input, { target: { value: "luckperms" } });
      act(() => {
        vi.advanceTimersByTime(360);
      });

      expect(useMarketplaceSearch).toHaveBeenLastCalledWith(
        "srv-1",
        "luckperms",
        expect.objectContaining({
          sort: "downloads",
          gameVersion: "1.21.1",
        }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("navigates Back to server section and marks installed addons on cards", () => {
    useMarketplaceSearch.mockReturnValue({ data: mockSearchResults, isLoading: false, isError: false, error: null });
    usePluginsList.mockReturnValue({
      data: [{ name: "EssentialsX", filename: "EssentialsX.jar", size_bytes: 1024 }],
    });
    renderPage("/marketplace?serverId=srv-3&type=mod&branch=dev");

    expect(screen.getByText("Installed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Back to Fabric Server/i }));
    expect(mockNavigate).toHaveBeenCalledWith("/servers/srv-3/mods?branch=dev");
  });

  it("renders ErrorState with Retry button on search failure", () => {
    const refetch = vi.fn();
    useMarketplaceSearchGlobal.mockReturnValue({
      data: null,
      isLoading: false,
      isError: true,
      error: new Error("Modrinth timeout"),
      refetch,
    });
    renderPage("/marketplace");

    expect(screen.getByText("Modrinth timeout")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Try Again/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("includes 26.x and 1.21.11 MC versions by default and prefers live Mojang release list when loaded", () => {
    renderPage("/marketplace");
    expect(screen.getByRole("option", { name: "MC 26.3" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "MC 1.21.11" })).toBeInTheDocument();

    useMinecraftVersions.mockReturnValue({ data: ["26.4", "26.3", "26.2", "1.21.11"] });
    renderPage("/marketplace");
    expect(screen.getAllByRole("option", { name: "MC 26.4" }).length).toBeGreaterThan(0);

    const mcSelects = screen.getAllByRole("combobox", { name: /Filter by Minecraft version/i });
    fireEvent.change(mcSelects[mcSelects.length - 1], { target: { value: "26.3" } });
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith(
      "",
      expect.objectContaining({
        gameVersion: "26.3",
      }),
    );
  });

  it("locks projectType and hides Plugins|Mods toggle when rendered in-shell", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1/plugins/marketplace"]}>
          <Routes>
            <Route
              path="/servers/:serverId/plugins/marketplace"
              element={<PluginMarketplacePage lockedProjectType="plugin" />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.queryByRole("group", { name: "Discover type" })).not.toBeInTheDocument();
    expect(useMarketplaceSearch).toHaveBeenCalledWith(
      "srv-1",
      "",
      expect.objectContaining({ projectType: "plugin" }),
    );
  });

  it("navigates to in-shell project detail route when clicking a card inside ServerShell", () => {
    useMarketplaceSearch.mockReturnValue({
      data: mockSearchResults,
      isLoading: false,
      isError: false,
      error: null,
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1/plugins/marketplace?branch=dev"]}>
          <Routes>
            <Route
              path="/servers/:serverId/plugins/marketplace"
              element={<PluginMarketplacePage lockedProjectType="plugin" />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByTestId("project-card-essentialsx"));
    expect(mockNavigate).toHaveBeenCalledWith(
      "/servers/srv-1/plugins/marketplace/essentialsx?branch=dev",
    );
  });
});
