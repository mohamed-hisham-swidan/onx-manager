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
  MARKETPLACE_PAGE_SIZE: 20,
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

  it("does not show a Game Versions row in the Information sidebar", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        game_versions: ["1.17", "1.17.1", "1.18", "1.18.1", "1.18.2"],
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();
    expect(screen.queryByText("Game Versions")).not.toBeInTheDocument();
  });

  it("renders the sidebar Loaders as icon-tagged pills, not comma text", () => {
    renderDetailPage();
    const dl = screen.getByText("Loaders").closest("dl");
    expect(dl).not.toBeNull();
    expect(dl?.querySelector('span[class*="rounded-full"]')?.textContent).toBe("Paper");
    expect(screen.queryByText("paper, spigot")).not.toBeInTheDocument();
    const pills = dl?.querySelectorAll('span[class*="rounded-full"]');
    expect(pills?.length).toBe(2);
    expect(pills?.[0]?.querySelector("svg")).not.toBeNull();
    expect(pills?.[1]?.querySelector("svg")).not.toBeNull();
  });

  it("makes platform pills search the marketplace by that platform", () => {
    renderDetailPage();
    const paper = screen.getByRole("link", { name: "Paper" });
    expect(paper).toHaveAttribute("href", "/marketplace?type=plugin&loader=paper");
    const spigot = screen.getByRole("link", { name: "Spigot" });
    expect(spigot).toHaveAttribute("href", "/marketplace?type=plugin&loader=spigot");
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

  it("renders markdown image syntax as a real img element", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        body: "![Screenshot](https://cdn.modrinth.com/essentials/screenshot.png)",
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();
    const img = screen.getByRole("img", { name: "Screenshot" });
    expect(img).toHaveAttribute("src", "https://cdn.modrinth.com/essentials/screenshot.png");
    expect(img).toHaveAttribute("loading", "lazy");
  });

  it("renders GitHub-flavored markdown (tables + task lists) as real markup", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        body: "- [x] Features\n- [ ] Coming soon\n\n| A | B |\n|---|---|\n| 1 | 2 |",
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(screen.getByText("Features")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    expect(table).toHaveClass("border-collapse");
    expect(table.closest("div")).toHaveClass("overflow-x-auto", "rounded-lg", "border");
    expect(screen.getAllByRole("columnheader")[0]).toHaveClass("uppercase", "font-bold");
  });

  it("renders styled tables for raw-HTML table bodies", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        body: "<table><thead><tr><th>Command</th><th>Desc</th></tr></thead><tbody><tr><td>/veinminer blocks</td><td>Edit</td></tr></tbody></table>",
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();
    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    expect(screen.getByText("/veinminer blocks")).toBeInTheDocument();
  });

  it("escapes raw HTML in the body instead of executing it", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        body: "<script>alert(1)</script><img src=x onerror=alert(1)>",
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();
    expect(document.querySelector("script")).not.toBeInTheDocument();
    expect(document.querySelector("img[onerror]")).not.toBeInTheDocument();
    expect(screen.queryByText("alert(1)")).not.toBeInTheDocument();
  });

  it("blocks javascript: URLs in markdown links", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        body: "[click me](javascript:alert(1))",
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();
    expect(
      screen.getByText("click me", { selector: "a" }),
    ).toBeInTheDocument();
    expect(
      document.querySelector("a[href^='javascript:']"),
    ).not.toBeInTheDocument();
  });
});
