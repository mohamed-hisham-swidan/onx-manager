import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PluginDetailPage } from "./PluginDetailPage";

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

const {
  useMarketplaceProject,
  useMarketplaceProjectVersions,
  useProjectVersionsGlobal,
  useProjectVersions,
  useInstallFromMarketplace,
  usePluginsList,
  useServersList,
} = vi.hoisted(() => ({
  useMarketplaceProject: vi.fn<
    (projectId: string, options?: { enabled?: boolean }) => ProjectMock & { refetch?: () => void }
  >(() => ({ data: null, isLoading: false, isError: false, error: null, refetch: vi.fn() })),
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
    refetch: vi.fn(),
  })),
  useProjectVersionsGlobal: vi.fn(() => ({
    data: {
      project_id: "essentialsx",
      versions: [
        {
          version_id: "v-1",
          project_id: "essentialsx",
          name: "2.21.0",
          version_number: "2.21.0",
          game_versions: ["1.21"],
          loaders: ["paper"],
          files: [],
          dependencies: [],
          changelog: "## Highlights\n- Performance fix",
          date_published: "2026-01-01T00:00:00Z",
        },
      ],
      selected: null,
      notice: "",
      notice_kind: "",
      total: 1,
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
  useProjectVersions: vi.fn(() => ({
    data: {
      project_id: "essentialsx",
      versions: [
        {
          version_id: "v-1",
          project_id: "essentialsx",
          name: "2.21.0",
          version_number: "2.21.0",
          game_versions: ["1.21"],
          loaders: ["paper"],
          files: [{ url: "https://example.com/p.jar", filename: "p.jar", size_bytes: 1024, sha1: "", sha512: "", primary: true }],
          dependencies: [],
          required_dependencies: [],
          date_published: "2026-01-01T00:00:00Z",
        },
      ],
      selected: null,
      notice: "",
      notice_kind: "",
      total: 1,
    },
    isLoading: false,
    isError: false,
    error: null,
  })),
  useInstallFromMarketplace: vi.fn(() => ({
    mutate: vi.fn(),
    isPending: false,
  })),
  usePluginsList: vi.fn(() => ({ data: undefined })),
  useServersList: vi.fn<
    () => {
      data: Array<{ server_id: string; name: string; server_type: string; minecraft_version: string }>;
      isLoading: boolean;
      error: unknown;
    }
  >(() => ({
    data: [],
    isLoading: false,
    error: null,
  })),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  MARKETPLACE_PAGE_SIZE: 20,
  useMarketplaceProject,
  useMarketplaceProjectVersions,
  useProjectVersionsGlobal,
  useProjectVersions,
  useInstallFromMarketplace,
  usePluginsList,
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList,
}));

function renderDetailPage(
  initialEntry = "/marketplace/essentialsx",
  lockedProjectType?: "plugin" | "mod",
) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/marketplace/:projectId" element={<PluginDetailPage />} />
          <Route
            path="/servers/:serverId/plugins/marketplace/:projectId"
            element={<PluginDetailPage lockedProjectType={lockedProjectType ?? "plugin"} />}
          />
          <Route
            path="/servers/:serverId/mods/marketplace/:projectId"
            element={<PluginDetailPage lockedProjectType={lockedProjectType ?? "mod"} />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PluginDetailPage", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    useMarketplaceProject.mockReturnValue({
      data: mockProject,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
  });

  it("renders project details, tabs, and compatibility card", () => {
    renderDetailPage();
    expect(screen.getByRole("heading", { name: "EssentialsX" })).toBeInTheDocument();
    expect(screen.getAllByText("Essentials Team")[0]).toBeInTheDocument();
    expect(screen.getByText("5.0M")).toBeInTheDocument();
    expect(screen.getByText("Wiki")).toHaveAttribute("href", "https://example.com/wiki");
    expect(screen.getByText("Source Code")).toHaveAttribute("href", "https://example.com/source");

    // Detail tabs present (Description, enabled Changelog, Versions)
    expect(screen.getByTestId("detail-tabs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Description" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Changelog" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Versions" })).toBeInTheDocument();

    // Real followers stat rendered (1.2k)
    expect(screen.getByText("1.2k")).toBeInTheDocument();

    // Default tab is Description -> clean README card without duplicate About box
    expect(screen.getByTestId("description-section")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "About" })).not.toBeInTheDocument();
    expect(screen.getByTestId("hero-summary")).toHaveTextContent("Essential plugin suite");
    expect(screen.getByText("Long description of EssentialsX body")).toBeInTheDocument();

    // Compatibility card rendered
    expect(screen.getByTestId("compatibility-card")).toBeInTheDocument();
    expect(screen.getByText("Client and server")).toBeInTheDocument();
  });

  it("does not duplicate Game Versions or Loaders rows in the Details sidebar", () => {
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
    expect(screen.queryByText("Loaders")).not.toBeInTheDocument();
  });

  it("makes platform pills search the marketplace by that platform", () => {
    renderDetailPage();
    const paper = screen.getByRole("link", { name: "Paper" });
    expect(paper).toHaveAttribute("href", "/marketplace?type=plugin&loader=paper");
    const spigot = screen.getByRole("link", { name: "Spigot" });
    expect(spigot).toHaveAttribute("href", "/marketplace?type=plugin&loader=spigot");
  });

  it("switches to Changelog and Versions tabs when clicked", () => {
    renderDetailPage();

    fireEvent.click(screen.getByRole("button", { name: "Changelog" }));
    expect(screen.getByTestId("project-changelog-list")).toBeInTheDocument();
    expect(screen.getByText("Performance fix")).toBeInTheDocument();

    const versionsTab = screen.getByRole("button", { name: "Versions" });
    fireEvent.click(versionsTab);

    expect(screen.queryByTestId("description-section")).not.toBeInTheDocument();
    expect(screen.getByTestId("no-versions-state")).toBeInTheDocument();
  });

  it("opens InstallModal directly on page when Install button is clicked", () => {
    useServersList.mockReturnValue({
      data: [
        {
          server_id: "srv-paper",
          name: "Paper 1",
          server_type: "paper",
          minecraft_version: "1.21",
        },
      ],
      isLoading: false,
      error: null,
    });
    renderDetailPage("/marketplace/essentialsx?serverId=srv-paper&branch=dev");
    const installBtn = screen.getByRole("button", { name: /Install/i });
    fireEvent.click(installBtn);

    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Paper 1")).toBeInTheDocument();
  });

  it("renders dedicated 404 not-found state without retry and retryable ErrorState for transient errors", async () => {
    const { ApiError } = await import("@/services/api");
    const refetch = vi.fn();
    useMarketplaceProject.mockReturnValue({
      data: null,
      isLoading: false,
      isError: true,
      error: new ApiError(404, "Not found", "NOT_FOUND"),
      refetch,
    });
    renderDetailPage();
    expect(screen.getByText(/Project Not Found/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry/i })).not.toBeInTheDocument();
  });

  it("shows error state with Retry button when fetch fails", () => {
    const refetch = vi.fn();
    useMarketplaceProject.mockReturnValue({
      data: null,
      isLoading: false,
      isError: true,
      error: new Error("Network error"),
      refetch,
    });
    renderDetailPage();
    expect(screen.getByText("Network error")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Try Again/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
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

  it("renders inline code without backticks, styled details disclosures, and center alignment", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        body:
          "<div align=\"center\">\n\n| Command | Permission |\n|---|---|\n| /veinminer blocks | `veinminer.blocks` |\n\n</div>\n\n" +
          "<details><summary>General Settings</summary>\n\nEnable vein mining globally.\n\n</details>",
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();

    const markdownRoot = document.querySelector(".onx-markdown");
    expect(markdownRoot).not.toBeNull();
    expect(markdownRoot).toHaveClass("prose-code:before:content-none", "prose-code:after:content-none");

    const codeEl = screen.getByText("veinminer.blocks");
    expect(codeEl.tagName.toLowerCase()).toBe("code");
    expect(codeEl).toHaveClass("font-mono", "bg-surface-muted");

    const summary = screen.getByText("General Settings");
    expect(summary.tagName.toLowerCase()).toBe("summary");
    expect(summary.closest("details")).toHaveClass("rounded-lg", "border");
    expect(document.querySelector('[align="center"]')).not.toBeNull();
  });

  it("renders dual Plugin and Mod badges and Details type when loaders span both families", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        title: "Emotecraft",
        project_types: ["mod"],
        loaders: ["fabric", "forge", "paper"],
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();

    expect(screen.getByTestId("project-type-badge-plugin")).toHaveTextContent("plugin");
    expect(screen.getByTestId("project-type-badge-mod")).toHaveTextContent("mod");
    expect(screen.getByTestId("detail-type-value")).toHaveTextContent("Plugin · Mod");
  });

  it("stays inside ServerShell on in-shell marketplace detail route and returns inside shell", () => {
    useServersList.mockReturnValue({
      data: [
        {
          server_id: "srv-paper",
          name: "Paper 1",
          server_type: "paper",
          minecraft_version: "1.21",
        },
      ],
      isLoading: false,
      error: null,
    });
    renderDetailPage("/servers/srv-paper/plugins/marketplace/essentialsx?branch=dev", "plugin");

    const backLink = screen.getByRole("link", { name: /Back to Marketplace/i });
    expect(backLink).toHaveAttribute(
      "href",
      "/servers/srv-paper/plugins/marketplace?branch=dev",
    );

    const paperPill = screen.getByRole("link", { name: "Paper" });
    expect(paperPill).toHaveAttribute(
      "href",
      "/servers/srv-paper/plugins/marketplace?branch=dev&loader=paper",
    );
  });

  it("renders raw HTML external markdown images with lazy loading, no-referrer, and fallback on error", () => {
    useMarketplaceProject.mockReturnValue({
      data: {
        ...mockProject,
        body: '<p align="center"><img src="//cdn.modrinth.com/emote/wheel.png" alt="Emote Wheel" width="400"></p>',
      },
      isLoading: false,
      isError: false,
      error: null,
    });
    renderDetailPage();

    const img = screen.getByRole("img", { name: "Emote Wheel" });
    expect(img).toHaveAttribute("src", "https://cdn.modrinth.com/emote/wheel.png");
    expect(img).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img).toHaveClass("rounded-lg", "max-w-full");

    fireEvent.error(img);
    expect(screen.getByTestId("markdown-image-fallback")).toHaveTextContent("Emote Wheel");
  });
});
