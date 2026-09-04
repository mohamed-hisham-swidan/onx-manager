import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ImportServerPage } from "./ImportServerPage";
import type { ScanResult } from "@/server_manager/types";

const mockScanDirectory = vi.fn();
const mockImportServer = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    scanDirectory: mockScanDirectory,
    importServer: mockImportServer,
  }),
}));

const sampleScanResult: ScanResult = {
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

  it("renders initial input step with disabled scan button when path is empty", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Import Server" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Server Directory" })).toBeInTheDocument();
    const scanBtn = screen.getByRole("button", { name: "Scan" });
    expect(scanBtn).toBeDisabled();
  });

  it("allows entering path and enables scan button", async () => {
    const user = userEvent.setup();
    renderPage();
    const input = screen.getByPlaceholderText("/opt/minecraft/survival");
    await user.type(input, "/srv/minecraft/survival");
    const scanBtn = screen.getByRole("button", { name: "Scan" });
    expect(scanBtn).toBeEnabled();
  });

  it("completes full scan and import flow successfully", async () => {
    mockScanDirectory.mockResolvedValueOnce(sampleScanResult);
    mockImportServer.mockResolvedValueOnce({ server_id: "srv-imported-123" });

    const user = userEvent.setup();
    renderPage();

    const input = screen.getByPlaceholderText("/opt/minecraft/survival");
    await user.type(input, "/srv/minecraft/survival");
    const scanBtn = screen.getByRole("button", { name: "Scan" });
    await user.click(scanBtn);

    expect(mockScanDirectory).toHaveBeenCalledWith("/srv/minecraft/survival");

    // Review step
    expect(await screen.findByRole("heading", { name: "Scan Results" })).toBeInTheDocument();
    expect(screen.getByText("survival-world")).toBeInTheDocument();
    expect(screen.getByText("paper")).toBeInTheDocument();
    expect(screen.getByText("1.20.4")).toBeInTheDocument();

    const importBtn = screen.getByRole("button", { name: "Import Server" });
    await user.click(importBtn);

    expect(mockImportServer).toHaveBeenCalledWith(
      expect.objectContaining({
        source_path: "/srv/minecraft/survival",
        name: "survival-world",
        server_type: "paper",
        minecraft_version: "1.20.4",
      }),
    );

    // Done step
    expect(await screen.findByRole("heading", { name: "Server Imported" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Go to Server" })).toBeInTheDocument();
  });

  it("displays error message when directory scan fails", async () => {
    mockScanDirectory.mockRejectedValueOnce(new Error("Directory not found or unreadable"));

    const user = userEvent.setup();
    renderPage();

    const input = screen.getByPlaceholderText("/opt/minecraft/survival");
    await user.type(input, "/invalid/path");
    const scanBtn = screen.getByRole("button", { name: "Scan" });
    await user.click(scanBtn);

    expect(await screen.findByText("Directory not found or unreadable")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Scan Results" })).not.toBeInTheDocument();
  });

  it("displays error message when import submission fails", async () => {
    mockScanDirectory.mockResolvedValueOnce(sampleScanResult);
    mockImportServer.mockRejectedValueOnce(new Error("Port 25565 already in use"));

    const user = userEvent.setup();
    renderPage();

    const input = screen.getByPlaceholderText("/opt/minecraft/survival");
    await user.type(input, "/srv/minecraft/survival");
    await user.click(screen.getByRole("button", { name: "Scan" }));

    const importBtn = await screen.findByRole("button", { name: "Import Server" });
    await user.click(importBtn);

    expect(await screen.findByText("Port 25565 already in use")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Server Imported" })).not.toBeInTheDocument();
  });
});
