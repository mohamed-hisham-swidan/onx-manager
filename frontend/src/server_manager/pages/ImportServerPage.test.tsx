import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ImportServerPage } from "./ImportServerPage";
import type { ScanResult } from "@/server_manager/types";

const mockScanDirectory = vi.fn();
const mockUploadImportZip = vi.fn();
const mockImportServer = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    scanDirectory: mockScanDirectory,
    uploadImportZip: mockUploadImportZip,
    importServer: mockImportServer,
  }),
}));

const sampleScanResult: ScanResult = {
  import_id: "0123456789abcdef",
  path: "/srv/minecraft/survival",
  name: "survival-world",
  server_type: "paper",
  minecraft_version: "1.20.4",
  eula_accepted: true,
  server_jar: "paper-1.20.4.jar",
  jar_size_bytes: 45000000,
  icon: null,
  ops: [],
  banned_players: [],
  whitelisted_players: [],
  properties: {
    port: 25565,
    motd: "A Great Minecraft Server",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    spawn_protection: 16,
    pvp: true,
    enable_command_block: false,
    online_mode: true,
    whitelist: false,
    view_distance: 10,
    simulation_distance: 10,
  },
  plugins: [],
  mods: [],
  worlds: [],
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ImportServerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ImportServerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders initial input step with upload mode active by default", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Import Server" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upload Server Archive" })).toBeInTheDocument();
    expect(screen.getByText(/Drag and drop your server \.zip archive here/i)).toBeInTheDocument();
  });

  it("completes zip archive upload scan and import flow successfully", async () => {
    mockUploadImportZip.mockResolvedValueOnce(sampleScanResult);
    mockImportServer.mockResolvedValueOnce({ server_id: "srv-imported-456" });

    const user = userEvent.setup();
    renderPage();

    const fileInput = screen.getByTestId("zip-file-input");
    const file = new File(["dummy zip bytes"], "my-server.zip", { type: "application/zip" });

    await user.upload(fileInput, file);

    expect(screen.getByText("my-server.zip")).toBeInTheDocument();
    const uploadBtn = screen.getByRole("button", { name: "Upload & Scan Server" });
    expect(uploadBtn).toBeEnabled();

    await user.click(uploadBtn);

    expect(mockUploadImportZip).toHaveBeenCalledWith(file, expect.any(Function));

    // Review step
    expect(await screen.findByRole("heading", { name: "Scan Results" })).toBeInTheDocument();
    expect(screen.getByText("survival-world")).toBeInTheDocument();

    const importBtn = screen.getByRole("button", { name: "Import Server" });
    await user.click(importBtn);

    expect(mockImportServer).toHaveBeenCalledWith(
      expect.objectContaining({
        import_id: "0123456789abcdef",
        name: "survival-world",
        server_type: "paper",
        minecraft_version: "1.20.4",
      }),
    );

    // Done step
    expect(await screen.findByRole("heading", { name: "Server Imported" })).toBeInTheDocument();
  });

  it("shows error when non-zip file is selected", () => {
    renderPage();

    const fileInput = screen.getByTestId("zip-file-input");
    const file = new File(["dummy"], "server.tar.gz", { type: "application/gzip" });

    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(screen.getByText("Please select a .zip archive")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload & Scan Server" })).not.toBeInTheDocument();
  });

  it("displays error message when upload scan fails", async () => {
    mockUploadImportZip.mockRejectedValueOnce(
      new Error("Uploaded archive exceeds the maximum allowed size")
    );

    const user = userEvent.setup();
    renderPage();

    const fileInput = screen.getByTestId("zip-file-input");
    const file = new File(["dummy zip bytes"], "huge-server.zip", { type: "application/zip" });
    await user.upload(fileInput, file);

    const uploadBtn = screen.getByRole("button", { name: "Upload & Scan Server" });
    await user.click(uploadBtn);

    expect(
      await screen.findByText("Uploaded archive exceeds the maximum allowed size"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Scan Results" })).not.toBeInTheDocument();
  });

  it("displays error message when import submission fails", async () => {
    mockUploadImportZip.mockResolvedValueOnce(sampleScanResult);
    mockImportServer.mockRejectedValueOnce(new Error("Port 25565 already in use"));

    const user = userEvent.setup();
    renderPage();

    const fileInput = screen.getByTestId("zip-file-input");
    const file = new File(["dummy zip bytes"], "my-server.zip", { type: "application/zip" });
    await user.upload(fileInput, file);

    const uploadBtn = screen.getByRole("button", { name: "Upload & Scan Server" });
    await user.click(uploadBtn);

    const importBtn = await screen.findByRole("button", { name: "Import Server" });
    await user.click(importBtn);

    expect(await screen.findByText("Port 25565 already in use")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Server Imported" })).not.toBeInTheDocument();
  });

  it("provides an accessible name on the hidden file input element", () => {
    renderPage();
    const fileInput = screen.getByLabelText("Choose server zip archive file");
    expect(fileInput).toBeInTheDocument();
    expect(fileInput).toHaveAttribute("type", "file");
  });
});
