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
  selected: null,
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
      (serverId: string, query: string, options?: { enabled?: boolean }) => SearchMock
    >(() => empty),
    useMarketplaceSearchGlobal: vi.fn<
      (query: string, options?: { enabled?: boolean }) => SearchMock
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

function renderPage(initialEntry = "/marketplace") {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <PluginMarketplacePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function searchAndOpenProject() {
  fireEvent.change(screen.getByLabelText("Search plugins"), { target: { value: "essentials" } });
  fireEvent.click(screen.getByText("Search"));
  fireEvent.click(screen.getAllByText("Install")[0]);
}

function chooseVersion() {
  fireEvent.click(screen.getAllByText("Install")[0]);
}

function serverFixture(overrides: Record<string, string>) {
  return {
    server_id: "srv-1",
    name: "Paper Server",
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

describe("PluginMarketplacePage", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockInstallMutate.mockClear();
    mockInstallCallbacks = {};
    useMarketplaceSearch.mockReturnValue({ data: null, isLoading: false, isError: false, error: null });
    useMarketplaceSearchGlobal.mockReturnValue({ data: null, isLoading: false, isError: false, error: null });
    mockServers = [
      serverFixture({ server_id: "srv-1", name: "Paper Server", server_type: "paper", minecraft_version: "1.21.1" }),
      serverFixture({ server_id: "srv-2", name: "Fabric Server", server_type: "fabric", minecraft_version: "1.20.4" }),
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
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith("", { enabled: true });

    fireEvent.click(screen.getByRole("button", { name: /CurseForge/i }));
    expect(useMarketplaceSourceStore.getState().source).toBe("curseforge");
    expect(screen.getByText("CurseForge Integration Coming Soon")).toBeInTheDocument();
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith("", { enabled: false });

    fireEvent.click(screen.getByRole("button", { name: /Switch to Modrinth/i }));
    expect(useMarketplaceSourceStore.getState().source).toBe("modrinth");
    expect(useMarketplaceSearchGlobal).toHaveBeenLastCalledWith("", { enabled: true });
  });

  it("searches the global marketplace with no server in the URL", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    fireEvent.change(screen.getByLabelText("Search plugins"), { target: { value: "essentials" } });
    fireEvent.click(screen.getByText("Search"));
    expect(useMarketplaceSearchGlobal).toHaveBeenCalledWith("essentials", { enabled: true });
    expect(screen.getByText("EssentialsX")).toBeInTheDocument();
  });

  it("keeps server-scoped search when a server is deep-linked", () => {
    useMarketplaceSearch.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace?server=srv-1");
    fireEvent.change(screen.getByLabelText("Search plugins"), { target: { value: "essentials" } });
    fireEvent.click(screen.getByText("Search"));
    expect(useMarketplaceSearch).toHaveBeenCalledWith("srv-1", "essentials", { enabled: true });
    expect(screen.getByText("EssentialsX")).toBeInTheDocument();
  });

  it("shows the version list without requiring a server and without a recommended badge", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    searchAndOpenProject();
    expect(screen.getByText("2.21.0")).toBeInTheDocument();
    expect(screen.getByText("2.20.0")).toBeInTheDocument();
    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
  });

  it("shows the server picker with compatibility markers after a version is chosen", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    searchAndOpenProject();
    chooseVersion();
    expect(screen.getByText("Paper Server")).toBeInTheDocument();
    expect(screen.getByText("Fabric Server")).toBeInTheDocument();
    expect(screen.getByText("Compatible")).toBeInTheDocument();
    expect(screen.getByText("May not work")).toBeInTheDocument();
    expect(
      screen.getByText(/runs fabric 1\.20\.4/),
    ).toBeInTheDocument();
  });

  it("pre-selects the last used server in the picker", () => {
    useLastUsedServerStore.setState({ lastUsedServerId: "srv-2" });
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    searchAndOpenProject();
    chooseVersion();
    expect(screen.getByRole("radio", { name: /Fabric Server/ })).toBeChecked();
  });

  it("disables install and shows an empty state when there are no servers", () => {
    mockServers = [];
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    searchAndOpenProject();
    chooseVersion();
    expect(screen.getByText("No servers available")).toBeInTheDocument();
    expect(screen.getByText("Continue")).toBeDisabled();
  });

  it("installs into a selected server and records it as last used", () => {
    useMarketplaceSearchGlobal.mockReturnValue({ data: mockResults, isLoading: false, isError: false, error: null });
    renderPage("/marketplace");
    searchAndOpenProject();
    chooseVersion();
    fireEvent.click(screen.getByText("Continue"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Install"));
    expect(mockInstallMutate).toHaveBeenCalledWith(
      { project_id: "essentialsx", version_id: "v1" },
      expect.any(Object),
    );
    act(() => mockInstallCallbacks.onSuccess?.({ version: "2.21.0" }));
    expect(useLastUsedServerStore.getState().lastUsedServerId).toBe("srv-1");
  });
});
