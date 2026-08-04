import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PluginMarketplacePage } from "./PluginMarketplacePage";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useSearchParams: () => [new URLSearchParams("server=srv-1")],
  };
});

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({
    data: [{ server_id: "srv-1", name: "Test Server" }],
  })),
}));

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

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  useMarketplaceSearch: vi.fn(() => ({ data: mockResults, isLoading: false, isError: false, error: null })),
  useProjectVersions: vi.fn(() => ({ data: mockVersions, isLoading: false, isError: false, error: null })),
  useInstallFromMarketplace: vi.fn(() => ({ mutate: vi.fn(), isPending: false, reset: vi.fn() })),
}));

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/plugins/marketplace?server=srv-1"]}>
        <PluginMarketplacePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PluginMarketplacePage", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
  });

  it("renders page header", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Plugin Marketplace" })).toBeInTheDocument();
  });

  it("shows back button to plugins page", () => {
    renderPage();
    fireEvent.click(screen.getByText("Back to Plugins"));
    expect(mockNavigate).toHaveBeenCalledWith("/plugins");
  });

  it("searches and renders results", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Search plugins"), { target: { value: "essentials" } });
    fireEvent.click(screen.getByText("Search"));
    expect(screen.getByText("EssentialsX")).toBeInTheDocument();
  });

  it("opens versions view when install is clicked", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Search plugins"), { target: { value: "essentials" } });
    fireEvent.click(screen.getByText("Search"));
    fireEvent.click(screen.getAllByText("Install")[0]);
    expect(screen.getByText("2.21.0")).toBeInTheDocument();
  });
});
