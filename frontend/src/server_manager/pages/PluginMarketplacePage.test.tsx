import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
  },
];

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
}

const { useMarketplaceSearch, useMarketplaceSearchGlobal } = vi.hoisted(() => {
  const empty: SearchMock = { data: null, isLoading: false, isError: false, error: null };
  return {
    useMarketplaceSearch: vi.fn<
      (serverId: string, query: string, options?: { enabled?: boolean; projectType?: string }) => SearchMock
    >(() => empty),
    useMarketplaceSearchGlobal: vi.fn<
      (query: string, options?: { enabled?: boolean; projectType?: string }) => SearchMock
    >(() => empty),
  };
});

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({ data: mockServers })),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  useMarketplaceSearch,
  useMarketplaceSearchGlobal,
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
    useMarketplaceSearch.mockReturnValue({ data: null, isLoading: false, isError: false, error: null });
    useMarketplaceSearchGlobal.mockReturnValue({ data: null, isLoading: false, isError: false, error: null });
    mockServers = [
      serverFixture({ server_id: "srv-1", name: "Paper Server 1", server_type: "paper", minecraft_version: "1.21.1" }),
      serverFixture({ server_id: "srv-2", name: "Paper Server 2", server_type: "paper", minecraft_version: "1.20.4" }),
      serverFixture({ server_id: "srv-3", name: "Fabric Server", server_type: "fabric", minecraft_version: "1.20.4" }),
    ];
    useLastUsedServerStore.setState({ lastUsedServerId: "" });
    useMarketplaceSourceStore.setState({ source: "modrinth" });
    localStorage.removeItem("mcs_last_used_server");
    localStorage.removeItem("mcs_marketplace_source");
  });

  it("renders page header", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Plugin Marketplace" })).toBeInTheDocument();
  });

  it("switches to CurseForge source and renders coming soon state with disabled fetches", () => {
    renderPage();
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith("", { enabled: true, projectType: "plugin" });

    fireEvent.click(screen.getByRole("button", { name: /CurseForge/i }));
    expect(useMarketplaceSourceStore.getState().source).toBe("curseforge");
    expect(screen.getByText("CurseForge Integration Coming Soon")).toBeInTheDocument();
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith("", { enabled: false, projectType: "plugin" });

    fireEvent.click(screen.getByRole("button", { name: /Switch to Modrinth/i }));
    expect(useMarketplaceSourceStore.getState().source).toBe("modrinth");
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith("", { enabled: true, projectType: "plugin" });
  });

  it("changes Discover dropdown from Plugins to Mods and passes projectType to search hook", () => {
    renderPage();
    expect(screen.getByRole("combobox", { name: /discover type/i })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: /discover type/i }), {
      target: { value: "mod" },
    });

    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith("", {
      enabled: true,
      projectType: "mod",
    });
  });

  it("opens InstallModal on Install button click from search results", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
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

  it("starts with version dropdown collapsed and expands on click", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    expect(screen.queryByTestId("version-list")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("2.21.0"));
    expect(screen.getByTestId("version-list")).toBeInTheDocument();
  });

  it("hard excludes incompatible servers (e.g. Fabric server excluded for plugins)", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    fireEvent.click(screen.getByText("Change Server"));

    expect(screen.getByText("Paper Server 1")).toBeInTheDocument();
    expect(screen.getByText("Paper Server 2")).toBeInTheDocument();
    expect(screen.queryByText("Fabric Server")).not.toBeInTheDocument();
  });

  it("resets version selection when target server is changed", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
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
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));

    expect(screen.getByText("No compatible servers available")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Install Now/i })).toBeDisabled();
  });

  it("executes installation and updates last used server on success", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
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
});
