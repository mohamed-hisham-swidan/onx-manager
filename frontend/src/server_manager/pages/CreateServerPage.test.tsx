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
const healthMock = vi.fn().mockResolvedValue({ docker: true });
const getSetupStatusMock = vi.fn().mockResolvedValue({ advanced_mode_enabled: false });
const mutateAsyncMock = vi.fn().mockResolvedValue({ server_id: "new-srv" });

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...actual,
    createAuthenticatedApi: () => ({
      listSoftware: listSoftwareMock,
      listSoftwareVersions: listSoftwareVersionsMock,
      getAvailablePort: getAvailablePortMock,
      health: healthMock,
      getSetupStatus: getSetupStatusMock,
    }),
  };
});

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

    await user.type(await screen.findByPlaceholderText("My Awesome Server"), "Legacy Forge Server");
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

    const nameInput = screen.getByPlaceholderText("My Awesome Server");
    await user.type(nameInput, "Dockerized Server");

    // Next to Properties
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

  it("omits provider or sends undefined when Host Process is selected", async () => {
    healthMock.mockResolvedValue({ docker: true });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Paper/i }));
    await user.click(await screen.findByRole("button", { name: "1.21.1" }));

    expect(await screen.findByText("Runtime Provider")).toBeInTheDocument();
    const dockerBtn = screen.getByRole("button", { name: /Docker Container/i });
    const hostBtn = screen.getByRole("button", { name: /Host Process/i });

    // Select Docker Container first, then switch back to Host Process
    await user.click(dockerBtn);
    await user.click(hostBtn);

    const nameInput = screen.getByPlaceholderText("My Awesome Server");
    await user.type(nameInput, "Host Process Server");

    // Next to Properties
    await user.click(screen.getByRole("button", { name: "Next" }));
    // Next to Review
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Review & Create")).toBeInTheDocument();
    expect(screen.getByText("Host Process")).toBeInTheDocument();
    expect(screen.getByText("Mode")).toBeInTheDocument();
    expect(screen.getByText("Simple")).toBeInTheDocument();

    // Click Create Server
    await user.click(screen.getByRole("button", { name: "Create Server" }));

    expect(mutateAsyncMock).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Host Process Server",
        provider: undefined,
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

    await user.type(screen.getByPlaceholderText("My Awesome Server"), "Paper Test");
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

    await user.type(screen.getByPlaceholderText("My Awesome Server"), "Paper Test");
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

    await user.type(screen.getByPlaceholderText("My Awesome Server"), "Test Server");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Game Properties")).toBeInTheDocument();
  });
});
