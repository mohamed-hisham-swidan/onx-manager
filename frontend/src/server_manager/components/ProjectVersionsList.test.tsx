import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
});
