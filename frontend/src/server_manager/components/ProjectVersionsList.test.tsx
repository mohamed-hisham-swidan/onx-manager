import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProjectVersionsList } from "./ProjectVersionsList";
import { useMarketplaceProjectVersions } from "@/server_manager/hooks/usePlugins";
import { useServersList } from "@/server_manager/hooks/useServers";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import type { PluginVersionResponse, PluginVersionsResponse } from "@/types";
import type { ServerResponse } from "@/server_manager/types";

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  MARKETPLACE_PAGE_SIZE: 20,
  useMarketplaceProjectVersions: vi.fn(),
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
}));

const mockVersions: PluginVersionResponse[] = [
  {
    version_id: "v-1",
    project_id: "proj-1",
    name: "1.0.0",
    version_number: "1.0.0",
    game_versions: ["1.20"],
    loaders: ["paper"],
    files: [
      {
        url: "https://example.com/file1.jar",
        filename: "plugin-1.0.0.jar",
        size_bytes: 1048576,
        sha1: "abc",
        sha512: "",
        primary: true,
      },
    ],
    dependencies: [],
    date_published: "2024-01-01T00:00:00Z",
  },
  {
    version_id: "v-2",
    project_id: "proj-1",
    name: "2.0.0",
    version_number: "2.0.0",
    game_versions: ["1.21"],
    loaders: ["paper"],
    files: [
      {
        url: "https://example.com/file2.jar",
        filename: "plugin-2.0.0.jar",
        size_bytes: 2097152,
        sha1: "def",
        sha512: "",
        primary: true,
      },
    ],
    dependencies: [],
    date_published: "2024-06-01T00:00:00Z",
  },
];

const mockServers: ServerResponse[] = [
  {
    server_id: "srv-1",
    name: "Survival Server",
    server_type: "paper",
    minecraft_version: "1.21",
    status: "RUNNING",
    group_id: "default",
    port: 25565,
    motd: "A Minecraft Server",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
  },
];

function renderList(projectId = "proj-1", initialEntry = "/") {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ProjectVersionsList projectId={projectId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProjectVersionsList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useLastUsedServerStore.setState({ lastUsedServerId: "" });
    vi.mocked(useServersList).mockReturnValue({
      data: mockServers,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServersList>);
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: {
        project_id: "proj-1",
        versions: mockVersions,
        selected: null,
        notice: "",
        notice_kind: "",
        total: mockVersions.length,
      } as PluginVersionsResponse,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);
  });

  it("renders versions list with version numbers and file metadata", () => {
    renderList();

    expect(screen.getByText("1.0.0")).toBeInTheDocument();
    expect(screen.getByText("2.0.0")).toBeInTheDocument();
    expect(screen.getByText("plugin-1.0.0.jar (1.0 MB)")).toBeInTheDocument();
    expect(screen.getByText("plugin-2.0.0.jar (2.0 MB)")).toBeInTheDocument();
    // No recommended badge when lastUsedServerId is not set
    expect(screen.queryByTestId("recommended-badge")).not.toBeInTheDocument();
  });

  it("displays Recommended badge when matching last-used server resolves", () => {
    useLastUsedServerStore.setState({ lastUsedServerId: "srv-1" });
    renderList();

    const badge = screen.getByTestId("recommended-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Recommended");

    // Version 2.0.0 (matching 1.21 paper) should be recommended
    const card2 = screen.getByTestId("version-card-v-2");
    expect(card2).toContainElement(badge);
  });

  it("shows no Recommended badge when server does not match any version", () => {
    const incompatibleServer: ServerResponse = {
      ...mockServers[0],
      server_id: "srv-2",
      server_type: "fabric",
      minecraft_version: "1.19",
    };
    vi.mocked(useServersList).mockReturnValue({
      data: [incompatibleServer],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServersList>);
    useLastUsedServerStore.setState({ lastUsedServerId: "srv-2" });

    renderList();
    expect(screen.queryByTestId("recommended-badge")).not.toBeInTheDocument();
  });

  it("shows empty state when versions array is empty", () => {
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: {
        project_id: "proj-1",
        versions: [],
        selected: null,
        notice: "",
        notice_kind: "",
        total: 0,
      } as PluginVersionsResponse,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);

    renderList();
    expect(screen.getByTestId("no-versions-state")).toBeInTheDocument();
  });

  it("shows loading skeleton when fetching", () => {
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);

    renderList();
    expect(screen.getByTestId("project-versions-loading")).toBeInTheDocument();
  });

  it("passes the page offset to the versions hook via the URL page param", () => {
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: {
        project_id: "proj-1",
        versions: mockVersions,
        selected: null,
        notice: "",
        notice_kind: "",
        total: 25,
      } as PluginVersionsResponse,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);

    renderList("proj-1", "/?page=2");

    expect(vi.mocked(useMarketplaceProjectVersions)).toHaveBeenLastCalledWith("proj-1", { offset: 20 });
  });

  it("renders pagination when more than one page of versions exists", () => {
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: {
        project_id: "proj-1",
        versions: mockVersions,
        selected: null,
        notice: "",
        notice_kind: "",
        total: 25,
      } as PluginVersionsResponse,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);

    renderList("proj-1", "/?page=2");

    expect(screen.getByRole("button", { name: "Page 2", current: "page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("normalizes an out-of-range page param to the last page", async () => {
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: {
        project_id: "proj-1",
        versions: mockVersions,
        selected: null,
        notice: "",
        notice_kind: "",
        total: 25,
      } as PluginVersionsResponse,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);

    renderList("proj-1", "/?page=99");

    await waitFor(() => {
      expect(vi.mocked(useMarketplaceProjectVersions)).toHaveBeenLastCalledWith("proj-1", { offset: 20 });
    });
  });

  it("groups many raw game_versions into accurate contiguous release pills and collapses snapshots", () => {
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: {
        project_id: "proj-1",
        versions: [
          {
            ...mockVersions[1],
            version_id: "v-wide",
            version_number: "3.0.0",
            game_versions: [
              "1.21",
              "1.21.1",
              "1.21.2",
              "1.21.3",
              "1.21.4",
              "26.1-snapshot-1",
              "24w14potato",
            ],
          },
        ],
        selected: null,
        notice: "",
        notice_kind: "",
        total: 1,
      } as PluginVersionsResponse,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);

    renderList();

    expect(screen.getByText("1.21–1.21.4")).toBeInTheDocument();
    expect(screen.queryByText("1.21.2")).not.toBeInTheDocument();
    expect(screen.queryByText("24w14potato")).not.toBeInTheDocument();
    expect(screen.getByText("+2 snapshots")).toBeInTheDocument();
  });

  it("filters versions by platform, game version, channel, snapshot toggle (OFF by default), and toggles Notes & Install", () => {
    const onInstallVersion = vi.fn();
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: {
        project_id: "proj-1",
        versions: [
          {
            ...mockVersions[0],
            version_id: "v-paper",
            version_number: "1.0.0",
            version_type: "release",
            game_versions: ["1.21.1"],
            loaders: ["paper"],
            changelog: "## Changes\n- Fixed crash",
          },
          {
            ...mockVersions[0],
            version_id: "v-fabric",
            version_number: "2.0.0-beta.1",
            version_type: "beta",
            game_versions: ["1.21.4"],
            loaders: ["fabric"],
            changelog: null,
          },
          {
            ...mockVersions[0],
            version_id: "v-snap",
            version_number: "3.0.0-alpha.1",
            version_type: "alpha",
            game_versions: ["26.1-snapshot-1"],
            loaders: ["fabric"],
            changelog: null,
          },
        ],
        selected: null,
        notice: "",
        notice_kind: "",
        total: 3,
      } as PluginVersionsResponse,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);

    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ProjectVersionsList projectId="proj-1" onInstallVersion={onInstallVersion} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // Show snapshots is OFF by default, so snapshot-only v-snap is hidden initially
    expect(screen.getByTestId("versions-filter-bar")).toBeInTheDocument();
    expect(screen.getByTestId("versions-snapshots-toggle")).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByTestId("version-card-v-snap")).not.toBeInTheDocument();
    expect(screen.getByTestId("channel-badge-v-paper")).toHaveTextContent("Release");
    expect(screen.getByTestId("channel-badge-v-fabric")).toHaveTextContent("Beta");

    // Toggle snapshots ON -> snapshot-only version appears
    fireEvent.click(screen.getByTestId("versions-snapshots-toggle"));
    expect(screen.getByTestId("version-card-v-snap")).toBeInTheDocument();
    expect(screen.getByTestId("channel-badge-v-snap")).toHaveTextContent("Alpha");

    // Filter by Platform = Fabric
    fireEvent.change(screen.getByRole("combobox", { name: "Filter by platform" }), {
      target: { value: "fabric" },
    });
    expect(screen.queryByTestId("version-card-v-paper")).not.toBeInTheDocument();
    expect(screen.getByTestId("version-card-v-fabric")).toBeInTheDocument();

    // Filter by Channel = Beta
    fireEvent.click(screen.getByRole("button", { name: "Beta" }));
    expect(screen.queryByTestId("version-card-v-snap")).not.toBeInTheDocument();
    expect(screen.getByTestId("version-card-v-fabric")).toBeInTheDocument();

    // Reset filters
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByTestId("version-card-v-paper")).toBeInTheDocument();
    expect(screen.queryByTestId("version-card-v-snap")).not.toBeInTheDocument();

    // Filter by Game Version = 1.21.1
    fireEvent.change(screen.getByRole("combobox", { name: "Filter by game version" }), {
      target: { value: "1.21.1" },
    });
    expect(screen.getByTestId("version-card-v-paper")).toBeInTheDocument();
    expect(screen.queryByTestId("version-card-v-fabric")).not.toBeInTheDocument();

    // Notes toggle & Install button
    fireEvent.click(screen.getByRole("button", { name: "Notes" }));
    expect(screen.getByTestId("version-notes-v-paper")).toHaveTextContent("Fixed crash");

    fireEvent.click(screen.getByRole("button", { name: "Install version 1.0.0" }));
    expect(onInstallVersion).toHaveBeenCalledWith(expect.objectContaining({ version_id: "v-paper" }));
  });

  it("renders ErrorState with Retry button when versions query fails", () => {
    const refetch = vi.fn();
    vi.mocked(useMarketplaceProjectVersions).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("Failed loading versions"),
      refetch,
    } as unknown as ReturnType<typeof useMarketplaceProjectVersions>);

    renderList();
    expect(screen.getByText("Failed loading versions")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Try Again/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
