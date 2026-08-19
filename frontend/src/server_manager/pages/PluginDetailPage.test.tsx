import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PluginDetailPage } from "./PluginDetailPage";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockProject = {
  project_id: "essentialsx",
  slug: "essentialsx",
  title: "EssentialsX",
  description: "Essential plugin suite",
  body: "Long description of EssentialsX body",
  author: "Essentials Team",
  project_types: ["plugin"],
  loaders: ["paper", "spigot"],
  game_versions: ["1.21"],
  downloads: 5000000,
  follows: 1200,
  icon_url: "https://example.com/icon.png",
  wiki_url: "https://example.com/wiki",
  source_url: "https://example.com/source",
  client_side: "optional",
  server_side: "required",
};

interface ProjectMock {
  data: typeof mockProject | null;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
}

const { useMarketplaceProject, useMarketplaceProjectVersions, useServersList } = vi.hoisted(() => ({
  useMarketplaceProject: vi.fn<
    (projectId: string, options?: { enabled?: boolean }) => ProjectMock
  >(() => ({ data: null, isLoading: false, isError: false, error: null })),
  useMarketplaceProjectVersions: vi.fn(() => ({
    data: {
      project_id: "essentialsx",
      versions: [],
      selected: null,
      notice: "",
      notice_kind: "",
      total: 0,
    },
    isLoading: false,
    error: null,
  })),
  useServersList: vi.fn(() => ({
    data: [],
    isLoading: false,
    error: null,
  })),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  useMarketplaceProject,
  useMarketplaceProjectVersions,
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList,
}));

function renderDetailPage(projectId = "essentialsx") {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/marketplace/${projectId}`]}>
        <Routes>
          <Route path="/marketplace/:projectId" element={<PluginDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PluginDetailPage", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    useMarketplaceSourceStore.setState({ source: "modrinth" });
    useMarketplaceProject.mockReturnValue({
      data: mockProject,
      isLoading: false,
      isError: false,
      error: null,
    });
  });

  it("renders project details, tabs, and compatibility card", () => {
    renderDetailPage();
    expect(screen.getByRole("heading", { name: "EssentialsX" })).toBeInTheDocument();
    expect(screen.getAllByText("Essentials Team")[0]).toBeInTheDocument();
    expect(screen.getByText("5.0M")).toBeInTheDocument();
    expect(screen.getByText("Wiki")).toHaveAttribute("href", "https://example.com/wiki");
    expect(screen.getByText("Source Code")).toHaveAttribute("href", "https://example.com/source");

    // Detail tabs present
    expect(screen.getByTestId("detail-tabs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Description" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Changelog/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Versions" })).toBeInTheDocument();

    // Default tab is Description -> About section rendered
    expect(screen.getByTestId("about-section")).toBeInTheDocument();
    expect(screen.getByText("Long description of EssentialsX body")).toBeInTheDocument();

    // Compatibility card rendered
    expect(screen.getByTestId("compatibility-card")).toBeInTheDocument();
    expect(screen.getByText("Client and server")).toBeInTheDocument();
  });

  it("switches to Versions tab when clicked", () => {
    renderDetailPage();
    const versionsTab = screen.getByRole("button", { name: "Versions" });
    fireEvent.click(versionsTab);

    // About section hidden, Versions list container rendered
    expect(screen.queryByTestId("about-section")).not.toBeInTheDocument();
    expect(screen.getByTestId("no-versions-state")).toBeInTheDocument();
  });

  it("navigates back to marketplace with install state when Install button is clicked", () => {
    renderDetailPage();
    const installBtn = screen.getByRole("button", { name: /Install/i });
    fireEvent.click(installBtn);

    expect(mockNavigate).toHaveBeenCalledWith("/marketplace", {
      state: {
        selectedProject: {
          project_id: "essentialsx",
          slug: "essentialsx",
          title: "EssentialsX",
          description: "Essential plugin suite",
          author: "Essentials Team",
          project_types: ["plugin"],
          downloads: 5000000,
          follows: 1200,
          icon_url: "https://example.com/icon.png",
          latest_version_id: "",
          categories: [],
          loaders: ["paper", "spigot"],
          client_side: "optional",
          server_side: "required",
          date_modified: "",
          color: null,
        },
      },
    });
  });

  it("shows coming soon state when source is CurseForge", () => {
    useMarketplaceSourceStore.setState({ source: "curseforge" });
    renderDetailPage();
    expect(screen.getByText("CurseForge Integration Coming Soon")).toBeInTheDocument();
  });

  it("shows error state when fetch fails", () => {
    useMarketplaceProject.mockReturnValue({
      data: null,
      isLoading: false,
      isError: true,
      error: new Error("Network error"),
    });
    renderDetailPage();
    expect(screen.getByText("Network error")).toBeInTheDocument();
  });
});
