import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PluginListPage, parsePluginMetadata } from "./PluginListPage";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import type { PluginResponse } from "@/types";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockPlugins: PluginResponse[] = [
  {
    plugin_id: "plg-1",
    server_id: "srv-1",
    name: "Essentials",
    version: "2.0.0",
    description: "Essential commands",
    author: "dev",
    status: "enabled",
    dependencies: [],
    installed_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    source: "modrinth",
    filename: "Essentials-2.0.0.jar",
    external_url: "https://modrinth.com/plugin/essentials",
  },
  {
    plugin_id: "plg-2",
    server_id: "srv-1",
    name: "WorldGuard",
    version: "1.0.0",
    description: "World protection",
    author: "dev",
    status: "disabled",
    dependencies: [],
    installed_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    source: "detected",
    filename: "WorldGuard-1.0.0.jar",
  },
  {
    plugin_id: "plg-3",
    server_id: "srv-1",
    name: "ManualPlugin",
    version: "3.1.0",
    description: "",
    author: "",
    status: "installed",
    dependencies: [],
    installed_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    source: "manual",
    filename: null,
  },
];

let mockPluginsData: PluginResponse[] = mockPlugins;
let mockIsLoading = false;
let mockError: Error | null = null;

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({
    data: [{ server_id: "srv-1", name: "Test Server" }],
  })),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  usePluginsList: vi.fn(() => ({
    data: mockPluginsData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useEnablePlugin: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDisablePlugin: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useUninstallPlugin: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PluginListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function selectServer() {
  fireEvent.change(screen.getByLabelText("Choose a server"), { target: { value: "srv-1" } });
}

describe("PluginListPage", () => {
  beforeEach(() => {
    mockPluginsData = mockPlugins;
    mockIsLoading = false;
    mockError = null;
    useLastUsedServerStore.setState({ lastUsedServerId: "" });
    localStorage.removeItem("onx_last_used_server");
    localStorage.removeItem("onx_plugins_view_mode");
  });

  it("renders page header", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Plugins" })).toBeInTheDocument();
  });

  it("shows empty state when no server selected", () => {
    renderPage();
    expect(screen.getByText("Select a server")).toBeInTheDocument();
  });

  it("hides install button until a server is selected", () => {
    renderPage();
    expect(screen.queryByText("Install Plugin")).not.toBeInTheDocument();
    selectServer();
    expect(screen.getByText("Install Plugin")).toBeInTheDocument();
  });

  it("renders plugin rows after selecting a server", () => {
    renderPage();
    selectServer();
    expect(screen.getByText("Essentials")).toBeInTheDocument();
    expect(screen.getByText("WorldGuard")).toBeInTheDocument();
    expect(screen.getAllByText("enabled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("disabled").length).toBeGreaterThanOrEqual(1);
  });

  it("renders filename and marketplace badge for modrinth plugins", () => {
    renderPage();
    selectServer();
    expect(screen.getByText("Essentials-2.0.0.jar")).toBeInTheDocument();
    expect(screen.getByText("Marketplace")).toBeInTheDocument();
  });

  it("renders detected badge and filename for on-disk plugins", () => {
    renderPage();
    selectServer();
    expect(screen.getByText("Detected on disk")).toBeInTheDocument();
    expect(screen.getByText("WorldGuard-1.0.0.jar")).toBeInTheDocument();
  });

  it("renders manual badge for legacy manual rows", () => {
    renderPage();
    selectServer();
    expect(screen.getByText("ManualPlugin")).toBeInTheDocument();
    expect(screen.getByText("Manual")).toBeInTheDocument();
  });

  it("shows enable/disable and uninstall actions", () => {
    renderPage();
    selectServer();
    expect(screen.getByLabelText("Disable Essentials")).toBeInTheDocument();
    expect(screen.getByLabelText("Enable WorldGuard")).toBeInTheDocument();
    expect(screen.getByLabelText("Disable ManualPlugin")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/Uninstall/)).toHaveLength(3);
  });

  it("treats freshly installed plugins (status=installed, is_disabled_on_disk=false) as enabled by default", () => {
    mockPluginsData = [
      {
        plugin_id: "plg-new",
        server_id: "srv-1",
        name: "VeinMiner",
        version: "2.14.0",
        description: "",
        author: "Mirr",
        status: "installed",
        is_disabled_on_disk: false,
        dependencies: [],
        installed_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        source: "modrinth",
        filename: "veinminer.jar",
      },
    ];
    renderPage();
    selectServer();
    const toggle = screen.getByRole("switch", { name: "Disable VeinMiner" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("shows loading state", () => {
    mockIsLoading = true;
    renderPage();
    selectServer();
    expect(document.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error state", () => {
    mockError = new Error("Load failed");
    renderPage();
    selectServer();
    expect(screen.getByText("Load failed")).toBeInTheDocument();
  });

  it("shows empty state when server has no plugins", () => {
    mockPluginsData = [];
    renderPage();
    selectServer();
    expect(screen.getByText("No plugins installed")).toBeInTheDocument();
  });

  it("opens uninstall confirmation dialog with deferred-deletion copy", () => {
    renderPage();
    selectServer();
    fireEvent.click(screen.getByLabelText("Uninstall Essentials"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Uninstall plugin?")).toBeInTheDocument();
    expect(screen.getByText(/will be deleted from disk the next time this server restarts/)).toBeInTheDocument();
  });

  it("navigates to the marketplace when install is clicked", () => {
    renderPage();
    selectServer();
    mockNavigate.mockReset();
    fireEvent.click(screen.getByText("Install Plugin"));
    expect(mockNavigate).toHaveBeenCalledWith("/marketplace?server=srv-1");
  });

  it("starts empty when there is no last used server saved yet", () => {
    renderPage();
    expect(screen.getByLabelText("Choose a server")).toHaveValue("");
    expect(screen.getByText("Select a server")).toBeInTheDocument();
  });

  it("pre-fills the server select from the last used server", () => {
    useLastUsedServerStore.setState({ lastUsedServerId: "srv-1" });
    renderPage();
    expect(screen.getByLabelText("Choose a server")).toHaveValue("srv-1");
    expect(screen.getByText("Essentials")).toBeInTheDocument();
  });

  it("hides server select dropdown when route serverId is present", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/servers/srv-1/plugins"]}>
          <Routes>
            <Route path="/servers/:serverId/plugins" element={<PluginListPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.queryByLabelText("Choose a server")).not.toBeInTheDocument();
    expect(screen.getByText("Essentials")).toBeInTheDocument();
  });

  it("shows server select dropdown when route serverId is absent", () => {
    renderPage();
    expect(screen.getByLabelText("Choose a server")).toBeInTheDocument();
  });

  describe("parsePluginMetadata helper", () => {
    it("parses semver plugin name and jar filename into clean title and version", () => {
      const meta = parsePluginMetadata({
        plugin_id: "plg-via",
        server_id: "srv-1",
        name: "5.12.2",
        filename: "ViaVersion-5.12.2.jar",
        version: "5.12.2",
        description: "",
        author: "",
        status: "enabled",
        dependencies: [],
        installed_at: "",
        updated_at: "",
      });
      expect(meta.title).toBe("ViaVersion");
      expect(meta.version).toBe("5.12.2");
      expect(meta.author).toBe("Local .jar / Modrinth");
    });

    it("parses hyphenated package filename like veinminer-paper-2.12.3.jar", () => {
      const meta = parsePluginMetadata({
        plugin_id: "plg-vein",
        server_id: "srv-1",
        name: "veinminer-paper-2.12.3.jar",
        filename: "veinminer-paper-2.12.3.jar",
        version: "",
        description: "",
        author: "",
        status: "enabled",
        dependencies: [],
        installed_at: "",
        updated_at: "",
      });
      expect(meta.title).toBe("VeinMiner Paper");
      expect(meta.version).toBe("2.12.3");
      expect(meta.author).toBe("Local .jar / Modrinth");
      expect(meta.loaders).toContain("Paper");
    });

    it("preserves established human plugin names like WorldEdit and EssentialsX", () => {
      const meta = parsePluginMetadata({
        plugin_id: "plg-we",
        server_id: "srv-1",
        name: "WorldEdit",
        filename: "worldedit-bukkit-7.3.0.jar",
        version: "7.3.0",
        description: "",
        author: "EngineHub",
        status: "enabled",
        dependencies: [],
        installed_at: "",
        updated_at: "",
      });
      expect(meta.title).toBe("WorldEdit");
      expect(meta.version).toBe("7.3.0");
      expect(meta.author).toBe("EngineHub");
    });

    it("never displays a bare semver as the primary title", () => {
      const meta = parsePluginMetadata({
        plugin_id: "plg-bare",
        server_id: "srv-1",
        name: "1.2.3",
        filename: null,
        version: "1.2.3",
        description: "",
        author: "",
        status: "enabled",
        dependencies: [],
        installed_at: "",
        updated_at: "",
      });
      expect(meta.title).not.toBe("1.2.3");
      expect(meta.title).toBe("Plugin 1.2.3");
    });
  });

  describe("PluginListPage cards grid and metadata UI", () => {
    it("renders ViaVersion title instead of bare version when backend returns semver name", () => {
      mockPluginsData = [
        {
          plugin_id: "plg-via",
          server_id: "srv-1",
          name: "5.12.2",
          filename: "ViaVersion-5.12.2.jar",
          version: "5.12.2",
          description: "Allows newer clients to connect",
          author: "",
          status: "enabled",
          dependencies: [],
          installed_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
          source: "detected",
          external_url: "https://modrinth.com/plugin/viaversion",
        },
      ];
      renderPage();
      selectServer();

      expect(screen.getByText("ViaVersion")).toBeInTheDocument();
      expect(screen.getByText("5.12.2")).toBeInTheDocument();
      expect(screen.getByText("Local .jar / Modrinth")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Config" })).toBeInTheDocument();
    });

    it("allows toggling viewMode between Cards and List in PluginListPage", () => {
      renderPage();
      selectServer();

      expect(screen.getByRole("button", { name: /Grid card view/i })).toHaveAttribute("aria-pressed", "true");

      fireEvent.click(screen.getByRole("button", { name: /Compact list view/i }));
      expect(screen.getByRole("table")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /Grid card view/i }));
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
    });
  });
});
