import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CreateServerPage } from "./CreateServerPage";
import { ApiError } from "@/services/api";

const listSoftwareMock = vi.fn();
const listSoftwareVersionsMock = vi.fn();
const getAvailablePortMock = vi.fn();
const listServersMock = vi.fn().mockResolvedValue([]);
const searchMarketplaceGlobalMock = vi.fn().mockResolvedValue({
  items: [],
  total_hits: 0,
  offset: 0,
  limit: 12,
});
const installFromMarketplaceMock = vi.fn().mockResolvedValue({
  plugin_id: "pl-1",
  version: "1.0.0",
  filename: "pl-1.jar",
  source: "modrinth",
  notice: "",
  notice_kind: "",
});
const healthMock = vi.fn().mockResolvedValue({ docker: true });
const getSetupStatusMock = vi.fn().mockResolvedValue({ advanced_mode_enabled: false });
const mutateAsyncMock = vi.fn().mockResolvedValue({ server_id: "new-srv" });
const createServerBranchMock = vi.fn().mockResolvedValue({ name: "setup-initial-addons" });
const createServerCommitMock = vi.fn().mockResolvedValue({ commit_id: "c1" });
const mergeServerCommitsMock = vi.fn().mockResolvedValue({ commit_id: "m1" });
const deleteServerBranchMock = vi.fn().mockResolvedValue({ status: "deleted" });

vi.mock("@/services/api", async () => {
  const actual = await importActualHelper();
  return {
    ...actual,
    createAuthenticatedApi: () => ({
      listSoftware: listSoftwareMock,
      listSoftwareVersions: listSoftwareVersionsMock,
      getAvailablePort: getAvailablePortMock,
      listServers: listServersMock,
      searchMarketplaceGlobal: searchMarketplaceGlobalMock,
      installFromMarketplace: installFromMarketplaceMock,
      createServerBranch: createServerBranchMock,
      createServerCommit: createServerCommitMock,
      mergeServerCommits: mergeServerCommitsMock,
      deleteServerBranch: deleteServerBranchMock,
      health: healthMock,
      getSetupStatus: getSetupStatusMock,
    }),
  };
});

async function importActualHelper() {
  return await vi.importActual<typeof import("@/services/api")>("@/services/api");
}

vi.mock("@/server_manager/hooks/useServers", () => ({
  useCreateServer: vi.fn(() => ({ mutateAsync: mutateAsyncMock, isPending: false })),
}));

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CreateServerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CreateServerPage version step", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "vanilla", name: "Vanilla", description: "Official" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue([]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
    getSetupStatusMock.mockResolvedValue({ advanced_mode_enabled: false });
  });

  it("shows a distinct error message when the versions fetch fails", async () => {
    listSoftwareVersionsMock.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Vanilla/i }));

    expect(
      await screen.findByText(/Failed to load versions — try again/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("No versions available.")).not.toBeInTheDocument();
  });

  it("shows the empty message only when versions are genuinely empty", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Vanilla/i }));

    expect(await screen.findByText("No versions available.")).toBeInTheDocument();
    expect(screen.queryByText(/Failed to load versions/i)).not.toBeInTheDocument();
  });

  it("shows the NEW software's versions even when a previous fetch resolves late", async () => {
    listSoftwareMock.mockResolvedValue([
      { type: "vanilla", name: "Vanilla", description: "Official" },
      { type: "paper", name: "Paper", description: "Optimized" },
    ]);
    let resolveVanilla: (v: string[]) => void = () => {};
    listSoftwareVersionsMock.mockImplementation((softwareType: string) => {
      if (softwareType === "vanilla") {
        return new Promise((resolve) => {
          resolveVanilla = (v) => resolve(v);
        });
      }
      return Promise.resolve(["1.21.4", "1.21.1"]);
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Vanilla/i }));
    // vanilla fetch is still pending; go back and pick a different software
    await user.click(await screen.findByRole("button", { name: "Back" }));
    await user.click(await screen.findByRole("button", { name: /Paper/i }));

    await screen.findByText("1.21.4");
    // now the stale vanilla response resolves late — it must NOT stick the UI in "Loading..."
    resolveVanilla(["1.21.4", "1.21.1"]);

    await waitFor(() => {
      expect(screen.queryByText("Loading versions...")).not.toBeInTheDocument();
    });
    expect(screen.getByText("1.21.4")).toBeInTheDocument();
  });
});

describe("CreateServerPage Forge modern/legacy chooser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "forge", name: "Forge", description: "Mod loader" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue([
      "1.21.1",
      "1.20.4",
      "1.17.1",
      "1.16.5",
      "1.12.2",
      "1.8.9",
    ]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
  });

  it("offers a modern/legacy toggle when Forge is selected (defaults to modern)", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Forge/i }));

    expect(await screen.findByRole("button", { name: /Modern Forge \(1\.17\+\)/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Legacy Forge \(< 1\.17\)/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("filters the version grid by the selected edition", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Forge/i }));

    // default modern: shows 1.17+ versions only
    expect(await screen.findByText("1.21.1")).toBeInTheDocument();
    expect(screen.getByText("1.17.1")).toBeInTheDocument();
    expect(screen.queryByText("1.16.5")).not.toBeInTheDocument();
    expect(screen.queryByText("1.12.2")).not.toBeInTheDocument();

    // switch to legacy: shows < 1.17 versions only
    await user.click(await screen.findByRole("button", { name: /Legacy Forge \(< 1\.17\)/i }));
    expect(screen.queryByText("1.21.1")).not.toBeInTheDocument();
    expect(screen.queryByText("1.17.1")).not.toBeInTheDocument();
    expect(screen.getByText("1.16.5")).toBeInTheDocument();
    expect(screen.getByText("1.8.9")).toBeInTheDocument();
  });

  it("shows the flow description for the active edition", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Forge/i }));

    expect(await screen.findByText(/forge-installer\.jar and configures run\.sh/i)).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: /Legacy Forge \(< 1\.17\)/i }));
    expect(screen.getByText(/forge-\{version\}-universal\.jar directly/i)).toBeInTheDocument();
  });

  it("shows the Forge Edition row on the review step when a legacy version is chosen", async () => {
    listSoftwareVersionsMock.mockResolvedValue(["1.21.1", "1.16.5"]);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Forge/i }));
    await user.click(await screen.findByRole("button", { name: /Legacy Forge \(< 1\.17\)/i }));
    await user.click(await screen.findByRole("button", { name: "1.16.5" }));

    const nameInput = await screen.findByPlaceholderText("Server");
    await user.clear(nameInput);
    await user.type(nameInput, "Legacy Forge Server");
    await user.click(await screen.findByRole("button", { name: /^Next$/i }));
    await user.click(await screen.findByRole("button", { name: /^Next$/i }));
    await user.click(await screen.findByRole("button", { name: /^Next$/i }));

    expect(await screen.findByText("Forge Edition")).toBeInTheDocument();
    expect(screen.getByText("Legacy Forge (< 1.17)")).toBeInTheDocument();
  });
});

describe("CreateServerPage NeoForge flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "neoforge", name: "NeoForge", description: "Modern mod loader" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue([
      "1.21.1",
      "1.20.4",
      "1.20.1",
    ]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
  });

  it("shows all NeoForge Minecraft versions and allows selection", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /NeoForge/i }));

    expect(await screen.findByText("1.21.1")).toBeInTheDocument();
    expect(screen.getByText("1.20.4")).toBeInTheDocument();
    expect(screen.getByText("1.20.1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Modern Forge/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Legacy Forge/i })).not.toBeInTheDocument();

    await user.click(screen.getByText("1.21.1"));
    expect(await screen.findByText("Server Configuration")).toBeInTheDocument();
  });
});

describe("CreateServerPage Configuration step", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "paper", name: "Paper", description: "High performance server" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue(["1.21.1"]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
  });

  it("supports RAM presets including 512 MB to 128 GB, 512 MB steppers, and free numeric typing", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    expect(await screen.findByText("Server Configuration")).toBeInTheDocument();

    // Presets exist
    expect(screen.getByRole("button", { name: "32 GB" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "64 GB" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "128 GB" })).toBeInTheDocument();

    // Click 32 GB preset
    await user.click(screen.getByRole("button", { name: "32 GB" }));
    const minRamInput = screen.getByPlaceholderText("1024") as HTMLInputElement;
    const maxRamInput = screen.getByPlaceholderText("2048") as HTMLInputElement;
    expect(minRamInput.value).toBe("16384");
    expect(maxRamInput.value).toBe("32768");

    // Click 512 MB preset
    const preset512 = screen.getByRole("button", { name: "512 MB" });
    await user.click(preset512);
    expect(minRamInput.value).toBe("512");
    expect(maxRamInput.value).toBe("512");

    // Click +512 stepper button on Max RAM
    const increaseMaxRam = screen.getByRole("button", { name: /Increase Max RAM by 512 MB/i });
    await user.click(increaseMaxRam);
    expect(maxRamInput.value).toBe("1024");

    // Click -512 stepper button on Max RAM
    const decreaseMaxRam = screen.getByRole("button", { name: /Decrease Max RAM by 512 MB/i });
    await user.click(decreaseMaxRam);
    expect(maxRamInput.value).toBe("512");

    // Clear and type freely without snapping to default
    await user.clear(minRamInput);
    expect(minRamInput.value).toBe("");
    await user.type(minRamInput, "768");
    expect(minRamInput.value).toBe("768");

    // Clear and type port freely
    const portInput = screen.getByPlaceholderText("25565") as HTMLInputElement;
    await user.clear(portInput);
    expect(portInput.value).toBe("");
    await user.type(portInput, "25570");
    expect(portInput.value).toBe("25570");
  });

  it("disables Docker option when docker daemon is not available", async () => {
    healthMock.mockResolvedValue({ docker: false });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    expect(await screen.findByText("Runtime Provider")).toBeInTheDocument();
    const dockerBtn = screen.getByRole("button", { name: /Docker Container/i });
    expect(dockerBtn).toBeDisabled();
    expect(screen.getByText("Docker daemon not detected")).toBeInTheDocument();
    expect(screen.getByTestId("docker-provider-card")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Host Process/i })).not.toBeInTheDocument();
  });

  it("allows selecting Docker Container when available and forwards provider on create", async () => {
    healthMock.mockResolvedValue({ docker: true });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    expect(await screen.findByText("Runtime Provider")).toBeInTheDocument();
    const dockerBtn = screen.getByRole("button", { name: /Docker Container/i });
    expect(dockerBtn).not.toBeDisabled();
    await user.click(dockerBtn);

    const nameInput = screen.getByPlaceholderText("Server");
    await user.clear(nameInput);
    await user.type(nameInput, "Dockerized Server");

    // Next to Properties
    await user.click(screen.getByRole("button", { name: "Next" }));
    // Next to Plugins
    await user.click(screen.getByRole("button", { name: "Next" }));
    // Next to Review
    await user.click(screen.getByRole("button", { name: "Next" }));

    // Review step shows Runtime Provider as Docker Container
    expect(await screen.findByText("Review & Create")).toBeInTheDocument();
    expect(screen.getByText("Docker Container")).toBeInTheDocument();
    expect(screen.getByText("Mode")).toBeInTheDocument();
    expect(screen.getByText("Simple")).toBeInTheDocument();

    // Click Create Server
    await user.click(screen.getByRole("button", { name: "Create Server" }));

    expect(mutateAsyncMock).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Dockerized Server",
        provider: "docker",
        mode: "simple",
      })
    );
  });

  it("removes Host Process and sends provider docker by default", async () => {
    healthMock.mockResolvedValue({ docker: true });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    expect(await screen.findByText("Runtime Provider")).toBeInTheDocument();
    const dockerCard = screen.getByTestId("docker-provider-card");
    expect(dockerCard).not.toBeDisabled();
    expect(screen.queryByRole("button", { name: /Host Process/i })).not.toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText("Server");
    await user.clear(nameInput);
    await user.type(nameInput, "Docker Only Server");

    // Next to Properties
    await user.click(screen.getByRole("button", { name: "Next" }));
    // Next to Plugins
    await user.click(screen.getByRole("button", { name: "Next" }));
    // Next to Review
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Review & Create")).toBeInTheDocument();
    expect(screen.getByText("Docker Container")).toBeInTheDocument();
    expect(screen.queryByText("Host Process")).not.toBeInTheDocument();
    expect(screen.getByText("Mode")).toBeInTheDocument();
    expect(screen.getByText("Simple")).toBeInTheDocument();

    // Click Create Server without toggling the provider
    await user.click(screen.getByRole("button", { name: "Create Server" }));

    expect(mutateAsyncMock).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Docker Only Server",
        provider: "docker",
        mode: "simple",
      })
    );
  });

  it("renders Simple mode chooser and does not render Advanced mode in Configuration step", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    expect(await screen.findByText("Server Configuration")).toBeInTheDocument();
    expect(screen.getByText("Server Mode")).toBeInTheDocument();
    expect(screen.getByTestId("server-mode-simple")).toBeInTheDocument();
    expect(screen.queryByTestId("server-mode-advanced")).not.toBeInTheDocument();
  });
});

describe("CreateServerPage error handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "paper", name: "Paper", description: "High performance server" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue(["1.21.1"]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
    healthMock.mockResolvedValue({ docker: true });
  });

  it("maps INFRASTRUCTURE_ERROR timeout to user-friendly download timeout message", async () => {
    const errorUrl = "https://fill-data.papermc.io/v1/objects/123/paper.jar";
    mutateAsyncMock.mockRejectedValue(
      new ApiError(503, "INFRASTRUCTURE_ERROR", `Download timed out for ${errorUrl}`, {
        url: errorUrl,
        timeout_seconds: 30,
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    const errNameInput = screen.getByPlaceholderText("Server");
    await user.clear(errNameInput);
    await user.type(errNameInput, "Paper Test");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Create Server" }));

    expect(
      await screen.findByText(
        "Failed to download server software (paper 1.21.1): the download timed out. " +
          "Please check your network connection or try again.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/fill-data\.papermc\.io/)).not.toBeInTheDocument();
  });

  it("maps INFRASTRUCTURE_ERROR download failed to remote server error message", async () => {
    const errorUrl = "https://fill-data.papermc.io/v1/objects/123/paper.jar";
    mutateAsyncMock.mockRejectedValue(
      new ApiError(503, "INFRASTRUCTURE_ERROR", `Download failed for ${errorUrl}`, {
        url: errorUrl,
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    const dlErrInput = screen.getByPlaceholderText("Server");
    await user.clear(dlErrInput);
    await user.type(dlErrInput, "Paper Test");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Create Server" }));

    expect(
      await screen.findByText(
        "Failed to download server software (paper 1.21.1). The remote download server " +
          "returned an error. Please try again later or select another version.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/fill-data\.papermc\.io/)).not.toBeInTheDocument();
  });
});

describe("CreateServerPage advanced mode flag gating", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "vanilla", name: "Vanilla", description: "Official" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue(["1.20.4"]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
  });

  it("calls getSetupStatus once on mount and shows Advanced card when advanced_mode_enabled is true", async () => {
    getSetupStatusMock.mockResolvedValue({ advanced_mode_enabled: true });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Vanilla/i }));
    await user.click(await screen.findByRole("button", { name: "1.20.4" }));

    expect(await screen.findByTestId("server-mode-advanced")).toBeInTheDocument();
    expect(getSetupStatusMock).toHaveBeenCalledTimes(1);
  });

  it("does not show Advanced card when advanced_mode_enabled is false", async () => {
    getSetupStatusMock.mockResolvedValue({ advanced_mode_enabled: false });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Vanilla/i }));
    await user.click(await screen.findByRole("button", { name: "1.20.4" }));

    expect(await screen.findByTestId("server-mode-simple")).toBeInTheDocument();
    expect(screen.queryByTestId("server-mode-advanced")).not.toBeInTheDocument();
  });

  it("does not show Advanced card when advanced_mode_enabled is omitted from status", async () => {
    getSetupStatusMock.mockResolvedValue({ initialized: true, access_mode: "LOCAL" });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Vanilla/i }));
    await user.click(await screen.findByRole("button", { name: "1.20.4" }));

    expect(await screen.findByTestId("server-mode-simple")).toBeInTheDocument();
    expect(screen.queryByTestId("server-mode-advanced")).not.toBeInTheDocument();
  });

  it("does not show Advanced card when getSetupStatus rejects and wizard still works", async () => {
    getSetupStatusMock.mockRejectedValue(new Error("Network failure"));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Vanilla/i }));
    await user.click(await screen.findByRole("button", { name: "1.20.4" }));

    expect(await screen.findByTestId("server-mode-simple")).toBeInTheDocument();
    expect(screen.queryByTestId("server-mode-advanced")).not.toBeInTheDocument();

    const fallbackInput = screen.getByPlaceholderText("Server");
    await user.clear(fallbackInput);
    await user.type(fallbackInput, "Test Server");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Game Properties")).toBeInTheDocument();
  });
});

describe("CreateServerPage Install Modpack creation mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "vanilla", name: "Vanilla", description: "Official" },
      { type: "paper", name: "Paper", description: "High performance" },
      { type: "fabric", name: "Fabric", description: "Lightweight mod loader" },
      { type: "neoforge", name: "NeoForge", description: "Modern mod loader" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue(["1.21.1"]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
    healthMock.mockResolvedValue({ docker: true });
    getSetupStatusMock.mockResolvedValue({ advanced_mode_enabled: false });
    mutateAsyncMock.mockResolvedValue({ server_id: "srv-modpack-1" });
  });

  it("filters loaders to modded servers and opens the modpack installer upon creation", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByRole("button", { name: /Paper/i })).toBeInTheDocument();
    await user.click(screen.getByTestId("creation-mode-modpack"));

    expect(screen.queryByRole("button", { name: /^Vanilla/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Paper/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Fabric/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /NeoForge/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Fabric/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));
    const modpackNameInput = await screen.findByPlaceholderText("Server");
    await user.clear(modpackNameInput);
    await user.type(modpackNameInput, "Modpack Server");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Create Server" }));

    expect(await screen.findByTestId("open-modpack-installer-btn")).toBeInTheDocument();
    expect(
      await screen.findByRole("dialog", { name: "Install Modpack (.mrpack / CurseForge)" }),
    ).toBeInTheDocument();
  });
});

describe("CreateServerPage sequential naming, stepper, and optional add-ons step", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSoftwareMock.mockResolvedValue([
      { type: "vanilla", name: "Vanilla", description: "Official" },
      { type: "paper", name: "Paper", description: "High performance" },
      { type: "fabric", name: "Fabric", description: "Lightweight mod loader" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue(["1.21.1"]);
    getAvailablePortMock.mockResolvedValue({ port: 25565 });
    healthMock.mockResolvedValue({ docker: true });
    getSetupStatusMock.mockResolvedValue({ advanced_mode_enabled: false });
    mutateAsyncMock.mockResolvedValue({ server_id: "srv-addons-1" });
    searchMarketplaceGlobalMock.mockResolvedValue({
      items: [
        {
          project_id: "pl-essentials",
          slug: "essentialsx",
          title: "EssentialsX",
          description: "Essential commands and utilities",
          author: "EssentialsTeam",
          project_types: ["plugin"],
          downloads: 500000,
          follows: 1200,
          icon_url: null,
          latest_version_id: "v1",
          categories: ["utility"],
          loaders: ["paper"],
          client_side: null,
          server_side: null,
          date_modified: "2026-01-01T00:00:00Z",
          color: null,
        },
      ],
      total_hits: 1,
      offset: 0,
      limit: 12,
    });
  });

  it("auto-generates 'Server 2' when 'Server' already exists", async () => {
    listServersMock.mockResolvedValue([{ name: "Server" }]);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Vanilla/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    const nameInput = (await screen.findByLabelText("Server Name")) as HTMLInputElement;
    expect(nameInput.value).toBe("Server 2");
  });

  it("auto-generates 'Server 3' when 'Server' and 'Server 2' already exist", async () => {
    listServersMock.mockResolvedValue([{ name: "Server" }, { name: "Server 2" }]);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    const nameInput = (await screen.findByLabelText("Server Name")) as HTMLInputElement;
    expect(nameInput.value).toBe("Server 3");
  });

  it("shows connected stepper with Plugins for Paper, Mods & Modpack for Fabric, and neither for Vanilla", async () => {
    const user = userEvent.setup();
    renderPage();

    const stepNav = screen.getByRole("navigation", { name: "Server creation steps" });
    expect(stepNav).not.toHaveTextContent("Plugins");
    expect(stepNav).not.toHaveTextContent("Mods & Modpack");

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    expect(screen.getByRole("navigation", { name: "Server creation steps" })).toHaveTextContent(
      "Plugins",
    );

    await user.click(await screen.findByRole("button", { name: "Back" }));
    await user.click(await screen.findByRole("button", { name: /Fabric/i }));
    expect(screen.getByRole("navigation", { name: "Server creation steps" })).toHaveTextContent(
      "Mods & Modpack",
    );
  });

  it("lets users browse and multi-select plugins on Paper and installs them after server creation", async () => {
    listServersMock.mockResolvedValue([]);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Browse Plugins (Optional)")).toBeInTheDocument();
    expect(searchMarketplaceGlobalMock).toHaveBeenCalledWith(
      "",
      "plugin",
      12,
      0,
      "paper",
      undefined,
      "1.21.1",
    );
    const card = await screen.findByTestId("addon-card-pl-essentials");
    await user.click(card);
    expect(screen.getByTestId("wizard-selected-addons")).toHaveTextContent("EssentialsX");

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Review & Create")).toBeInTheDocument();
    expect(screen.getByText("Selected Plugins")).toBeInTheDocument();
    expect(screen.getByText("1 (EssentialsX)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create Server" }));

    await waitFor(() => {
      expect(installFromMarketplaceMock).toHaveBeenCalledWith("srv-addons-1", {
        project_id: "pl-essentials",
        minecraft_version: "1.21.1",
      });
    });
    expect(await screen.findByText("Server Created")).toBeInTheDocument();
  });

  it("installs addons onto a staging branch and auto-merges into main when mode is advanced", async () => {
    listServersMock.mockResolvedValue([]);
    getSetupStatusMock.mockResolvedValue({ advanced_mode_enabled: true });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    const advCard = await screen.findByTestId("server-mode-advanced");
    await user.click(advCard);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Browse Plugins (Optional)")).toBeInTheDocument();
    await user.click(await screen.findByTestId("addon-card-pl-essentials"));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Create Server" }));

    await waitFor(() => {
      expect(createServerBranchMock).toHaveBeenCalledWith("srv-addons-1", {
        name: "setup-initial-addons",
      });
      expect(installFromMarketplaceMock).toHaveBeenCalledWith(
        "srv-addons-1",
        {
          project_id: "pl-essentials",
          minecraft_version: "1.21.1",
        },
        "setup-initial-addons",
      );
      expect(createServerCommitMock).toHaveBeenCalledWith(
        "srv-addons-1",
        expect.objectContaining({ branch_name: "setup-initial-addons" }),
      );
      expect(mergeServerCommitsMock).toHaveBeenCalledWith(
        "srv-addons-1",
        expect.objectContaining({
          target_branch_name: "main",
          source_branch_name: "setup-initial-addons",
          force: true,
          force_bypass_protection: true,
        }),
      );
      expect(deleteServerBranchMock).toHaveBeenCalledWith(
        "srv-addons-1",
        "setup-initial-addons",
      );
    });
    expect(await screen.findByText("Server Created")).toBeInTheDocument();
    expect(screen.queryByText(/Some optional add-ons could not be installed/i)).not.toBeInTheDocument();
  });

  it("defaults VersionStep to Main Versions and separates 26.x / snapshots into their own tab", async () => {
    listSoftwareVersionsMock.mockResolvedValue([
      "26.1-snapshot-1",
      "26.0",
      "1.21.4",
      "1.21.3",
      "1.21.2",
      "1.21.1",
      "1.20.4",
    ]);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    expect(await screen.findByRole("button", { name: "1.21.4" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1.21.1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1.20.4" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "1.21.2" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "26.0" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "26.1-snapshot-1" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Snapshots & 26\.x \(2\)/i }));
    expect(screen.getByRole("button", { name: "26.0" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "26.1-snapshot-1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "1.21.4" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /All Versions \(7\)/i }));
    expect(screen.getByRole("button", { name: "1.21.2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "26.0" })).toBeInTheDocument();
  });

  it("preserves spawn_protection = 0 instead of coercing to 16 and blocks Next when minRam > maxRam", async () => {
    listSoftwareVersionsMock.mockResolvedValue(["1.21.4"]);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.4" }));

    // Set minRam > maxRam -> Next should be disabled with inline validation
    const [minRamInput] = screen.getAllByRole("spinbutton").slice(2, 4);
    await user.clear(minRamInput);
    await user.type(minRamInput, "4096");
    expect(screen.getByText(/Minimum RAM \(4096 MB\) cannot exceed Maximum RAM/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    // Restore valid RAM via preset and proceed to properties
    await user.click(screen.getByRole("button", { name: "2 GB" }));
    await user.click(screen.getByRole("button", { name: "Next" }));

    await user.click(await screen.findByRole("button", { name: /Advanced Server Properties/i }));
    const spawnInput = await screen.findByLabelText("Spawn Protection Radius");
    await user.clear(spawnInput);
    await user.type(spawnInput, "0");

    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("button", { name: /Skip/ }));
    await user.click(await screen.findByRole("button", { name: "Create Server" }));

    await waitFor(() => {
      expect(mutateAsyncMock).toHaveBeenCalledWith(
        expect.objectContaining({
          spawn_protection: 0,
        }),
      );
    });
  });

  it("displays Review & Confirm summary with Java runtime, resources, properties, what-will-happen note, and Edit jump links", async () => {
    listServersMock.mockResolvedValue([]);
    listSoftwareMock.mockResolvedValue([
      { type: "purpur", name: "Purpur", description: "Feature-rich fork" },
    ]);
    listSoftwareVersionsMock.mockResolvedValue(["1.21.11"]);
    getAvailablePortMock.mockResolvedValue({ port: 25577 });

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Purpur/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.11" }));

    const nameInput = await screen.findByLabelText("Server Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Purpur Review Server");
    await user.click(screen.getByRole("button", { name: "4 GB" }));

    // Next -> Properties -> Next -> Plugins -> Skip -> Review
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("button", { name: /Skip/i }));

    const card = await screen.findByTestId("review-confirm-card");
    expect(card).toHaveTextContent("Purpur Review Server");
    expect(card).toHaveTextContent("Purpur");
    expect(card).toHaveTextContent("1.21.11");
    expect(card).toHaveTextContent("Java 21");
    expect(card).toHaveTextContent("2048 - 4096 MB");
    expect(card).toHaveTextContent("25577");
    expect(card).toHaveTextContent("survival");
    expect(card).toHaveTextContent("easy");
    expect(card).toHaveTextContent("10 chunks");
    expect(card).toHaveTextContent("16 blocks");

    const note = screen.getByTestId("review-what-happens-note");
    expect(note).toHaveTextContent(/Downloads Purpur 1\.21\.11, verifies checksum/i);

    // Quick Edit jump link navigates back to Configuration
    const editButtons = screen.getAllByRole("button", { name: /Edit/i });
    await user.click(editButtons[0]);
    expect(await screen.findByText("Server Configuration")).toBeInTheDocument();
  });
});
