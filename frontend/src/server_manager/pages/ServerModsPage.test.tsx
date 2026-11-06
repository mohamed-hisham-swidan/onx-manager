import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerModsPage } from "./ServerModsPage";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import { toast } from "@/stores/toastStore";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

const mockMods = [
  {
    plugin_id: "mod-1",
    server_id: "srv-mc-100",
    name: "Sodium",
    mod_id: "sodium",
    version: "0.5.8",
    description: "Modern rendering engine",
    author: "JellySquid",
    status: "enabled",
    loader: "fabric",
    is_disabled_on_disk: false,
    warning: "Client-only mod detected — may fail or be ignored on dedicated server",
    dependencies: [],
    installed_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    filename: "sodium-fabric-0.5.8.jar",
  },
  {
    plugin_id: "mod-2",
    server_id: "srv-mc-100",
    name: "JEI",
    mod_id: "jei",
    version: "15.2.0.27",
    description: "Just Enough Items",
    author: "mezz",
    status: "disabled",
    loader: "forge",
    is_disabled_on_disk: true,
    warning: null,
    dependencies: [],
    installed_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    filename: "jei-1.20.1-forge.jar.disabled",
  },
  {
    plugin_id: "mod-3",
    server_id: "srv-mc-100",
    name: "Cloth Config",
    mod_id: "cloth-config",
    version: "13.0.121",
    description: "Configuration library",
    author: "shedaniel",
    status: "enabled",
    loader: "neoforge",
    is_disabled_on_disk: false,
    warning: null,
    dependencies: [],
    installed_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    filename: "cloth-config-neoforge.jar",
  },
];

let mockModsData = mockMods;
let mockIsLoading = false;
let mockError: Error | null = null;
const mockUploadMutate = vi.fn();
const mockToggleMutate = vi.fn();
const mockUninstallMutate = vi.fn();

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(() => ({
    data: [{ server_id: "srv-mc-100", name: "Modded Server" }],
  })),
}));

vi.mock("@/server_manager/hooks/usePlugins", () => ({
  usePluginsList: vi.fn(() => ({
    data: mockModsData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useUploadPluginOrMod: vi.fn(() => ({
    mutate: mockUploadMutate,
    isPending: false,
  })),
  useToggleModState: vi.fn(() => ({
    mutate: mockToggleMutate,
    isPending: false,
  })),
  useUninstallPlugin: vi.fn(() => ({
    mutate: mockUninstallMutate,
    isPending: false,
  })),
}));

function renderServerModsPage(initialEntry = "/servers/srv-mc-100/mods") {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/servers/:serverId/mods" element={<ServerModsPage />} />
          <Route path="/mods" element={<ServerModsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerModsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockModsData = mockMods;
    mockIsLoading = false;
    mockError = null;
    useLastUsedServerStore.setState({ lastUsedServerId: "" });
  });

  it("renders the page header and upload zone", () => {
    renderServerModsPage();
    expect(screen.getByRole("heading", { name: "Mods" })).toBeInTheDocument();
    expect(screen.getByText("Browse Marketplace")).toBeInTheDocument();
    expect(
      screen.getByText("Drop custom .jar mod file here, or browse"),
    ).toBeInTheDocument();
  });

  it("renders mod table with mod name, mod ID, version, and filenames", () => {
    renderServerModsPage();
    expect(screen.getByText("Sodium")).toBeInTheDocument();
    expect(screen.getByText("sodium")).toBeInTheDocument();
    expect(screen.getByText("0.5.8")).toBeInTheDocument();
    expect(screen.getByText("JEI")).toBeInTheDocument();
    expect(screen.getByText("Cloth Config")).toBeInTheDocument();
  });

  it("renders loader badges correctly", () => {
    renderServerModsPage();
    const table = screen.getByRole("table");
    expect(table).toHaveTextContent("Fabric");
    expect(table).toHaveTextContent("Forge");
    expect(table).toHaveTextContent("NeoForge");
  });

  it("renders client-only warning badge when warning is present", () => {
    renderServerModsPage();
    const warningBadges = screen.getAllByText("Client-only");
    expect(warningBadges.length).toBe(1);
    expect(warningBadges[0].closest("span")).toHaveAttribute(
      "title",
      "Client-only mod detected — may fail or be ignored on dedicated server",
    );
  });

  it("handles status toggle clicks and invokes toggle mutation", () => {
    renderServerModsPage();
    const sodiumToggle = screen.getByRole("switch", { name: "Disable Sodium" });
    expect(sodiumToggle).toHaveAttribute("aria-checked", "true");

    fireEvent.click(sodiumToggle);
    expect(mockToggleMutate).toHaveBeenCalledWith(
      {
        mod_id: "sodium",
        plugin_id: "mod-1",
        enabled: false,
      },
      expect.any(Object),
    );
  });

  it("handles enabling a disabled mod", () => {
    renderServerModsPage();
    const jeiToggle = screen.getByRole("switch", { name: "Enable JEI" });
    expect(jeiToggle).toHaveAttribute("aria-checked", "false");

    fireEvent.click(jeiToggle);
    expect(mockToggleMutate).toHaveBeenCalledWith(
      {
        mod_id: "jei",
        plugin_id: "mod-2",
        enabled: true,
      },
      expect.any(Object),
    );
  });

  it("handles custom jar file upload via file input", () => {
    renderServerModsPage();
    const fileInput = screen.getByTestId("mod-file-input");
    const testFile = new File(["dummy content"], "iris-1.7.0.jar", { type: "application/java-archive" });

    fireEvent.change(fileInput, { target: { files: [testFile] } });
    expect(mockUploadMutate).toHaveBeenCalledWith(testFile, expect.any(Object));
  });

  it("rejects non-jar files on upload with toast error", () => {
    renderServerModsPage();
    const fileInput = screen.getByTestId("mod-file-input");
    const invalidFile = new File(["not a jar"], "malicious.exe", { type: "application/octet-stream" });

    fireEvent.change(fileInput, { target: { files: [invalidFile] } });
    expect(mockUploadMutate).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith("error", "Invalid file", "Only .jar mod files are supported.");
  });

  it("filters mods by search query", () => {
    renderServerModsPage();
    const searchInput = screen.getByPlaceholderText("Search mods by name, ID, or file...");
    fireEvent.change(searchInput, { target: { value: "Sodium" } });

    expect(screen.getByText("Sodium")).toBeInTheDocument();
    expect(screen.queryByText("JEI")).not.toBeInTheDocument();
    expect(screen.queryByText("Cloth Config")).not.toBeInTheDocument();
  });

  it("filters mods by loader selection", () => {
    renderServerModsPage();
    const loaderSelect = screen.getByLabelText("Loader:");
    fireEvent.change(loaderSelect, { target: { value: "forge" } });

    expect(screen.getByText("JEI")).toBeInTheDocument();
    expect(screen.queryByText("Sodium")).not.toBeInTheDocument();
    expect(screen.queryByText("Cloth Config")).not.toBeInTheDocument();
  });

  it("opens confirm dialog when clicking delete and triggers uninstall mutation on confirm", () => {
    renderServerModsPage();
    const deleteButton = screen.getByRole("button", { name: "Uninstall Sodium" });
    fireEvent.click(deleteButton);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Uninstall mod?")).toBeInTheDocument();

    const confirmButton = screen.getByRole("button", { name: "Uninstall" });
    fireEvent.click(confirmButton);

    expect(mockUninstallMutate).toHaveBeenCalledWith("mod-1", expect.any(Object));
  });

  it("renders empty state when no mods are installed", () => {
    mockModsData = [];
    renderServerModsPage();
    expect(screen.getByText("No mods found")).toBeInTheDocument();
    expect(
      screen.getByText("No mods are installed yet. Drop a .jar file in the upload zone above or browse the marketplace."),
    ).toBeInTheDocument();
  });

  it("renders server selector when no serverId in route", () => {
    renderServerModsPage("/mods");
    expect(screen.getByLabelText("Choose a server")).toBeInTheDocument();
  });

  it("provides an accessible name on the hidden file input element", () => {
    renderServerModsPage();
    const fileInput = screen.getByLabelText("Choose custom mod jar file");
    expect(fileInput).toBeInTheDocument();
    expect(fileInput).toHaveAttribute("type", "file");
  });
});

