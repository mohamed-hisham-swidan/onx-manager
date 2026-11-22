import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/services/api";
import { ServerModeConversionCard } from "./ServerModeConversionCard";
import type { ServerDetailResponse } from "@/server_manager/types";

function LocationDisplay() {
  const { pathname, search } = useLocation();
  return <div data-testid="location-display">{pathname + search}</div>;
}

function renderCardWithLocation(serverOverride?: Partial<ServerDetailResponse>) {
  const server = { ...baseServer, ...serverOverride };
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/servers/srv-1/settings"]}>
        <ServerModeConversionCard serverId="srv-1" server={server} />
        <LocationDisplay />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const mockConvertToAdvanced = vi.fn();
const mockConvertToSimple = vi.fn();

vi.mock("@/server_manager/hooks/useConversion", () => ({
  useConvertToAdvanced: vi.fn(() => ({ mutateAsync: mockConvertToAdvanced, isPending: false })),
  useConvertToSimple: vi.fn(() => ({ mutateAsync: mockConvertToSimple, isPending: false })),
}));

const baseServer: ServerDetailResponse = {
  server_id: "srv-1",
  name: "Production SMP",
  server_type: "purpur",
  minecraft_version: "1.20.4",
  status: "stopped",
  mode: "simple",
  group_id: "default",
  port: 25565,
  motd: "Welcome!",
  max_players: 20,
  gamemode: "survival",
  difficulty: "normal",
  min_memory_mb: 1024,
  max_memory_mb: 2048,
  java_args: "-Xmx2G",
  spawn_protection: 16,
  pvp: true,
  enable_command_block: false,
  online_mode: true,
  whitelist: false,
  view_distance: 10,
  simulation_distance: 10,
  provider: "docker",
  deployment_host: null,
  deployment_port: null,
  deployment_pid: null,
  location_type: null,
  location_uri: null,
  root_path: null,
  working_directory: null,
  startup_jar: null,
  startup_command: null,
  primary_world: null,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
};

function renderCard(serverOverride?: Partial<ServerDetailResponse>) {
  const server = { ...baseServer, ...serverOverride };
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/servers/srv-1/settings"]}>
        <ServerModeConversionCard serverId="srv-1" server={server} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServerModeConversionCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConvertToAdvanced.mockReset();
    mockConvertToSimple.mockReset();
    mockConvertToAdvanced.mockResolvedValue({
      server_id: "srv-1",
      mode: "advanced",
      main_commit_sha: "abc123",
      backup_id: "bkp-1",
      cas_ingested: 3,
    });
    mockConvertToSimple.mockResolvedValue({ new_server_id: "srv-2", name: "Production SMP (Simple)" });
  });

  it("renders Simple mode state and enables conversion when stopped", () => {
    renderCard({ mode: "simple", status: "stopped" });
    expect(screen.getByText("Mode: Simple")).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /Convert to Advanced/ });
    expect(btn).not.toBeDisabled();
  });

  it("disables conversion and warns when server is not stopped", () => {
    renderCard({ mode: "simple", status: "running" });
    const btn = screen.getByRole("button", { name: /Convert to Advanced/ });
    expect(btn).toBeDisabled();
    expect(screen.getByText(/Server must be stopped before converting to Advanced mode/i)).toBeInTheDocument();
  });

  it("executes Simple -> Advanced conversion on confirm", async () => {
    const user = userEvent.setup();
    renderCard({ mode: "simple", status: "stopped" });
    await user.click(screen.getByRole("button", { name: /Convert to Advanced/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Convert Server to Advanced Mode?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Convert" }));
    expect(mockConvertToAdvanced).toHaveBeenCalledWith("srv-1");
    expect(screen.getByText(/Conversion complete/i)).toBeInTheDocument();
    expect(screen.getByText("abc123")).toBeInTheDocument();
    expect(screen.getByText("bkp-1")).toBeInTheDocument();
    expect(screen.getByText(/CAS objects ingested: 3/)).toBeInTheDocument();
  });

  it("renders Advanced mode state with untouched source explanation", () => {
    renderCard({ mode: "advanced", status: "running" });
    expect(screen.getByText("Mode: Advanced")).toBeInTheDocument();
    expect(screen.getByText(/brand-new Simple server/i)).toBeInTheDocument();
    expect(screen.getByText(/NOT modified or deleted/i)).toBeInTheDocument();
    expect(screen.getByText(/Recommendation: Stop server before converting/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Name/i)).toHaveValue("Production SMP (Simple)");
    expect(screen.getByPlaceholderText("Auto-allocate or specify port")).toBeInTheDocument();
  });

  it("executes Advanced -> Simple conversion with name/port inputs and offers settings link", async () => {
    const user = userEvent.setup();
    renderCard({ mode: "advanced" });
    await user.click(screen.getByRole("button", { name: /Create Simple Server/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText('Create Simple Server from "Production SMP"?')).toBeInTheDocument();
    const nameInput = screen.getByLabelText(/Name/i);
    const portInput = screen.getByLabelText(/Port/i);
    fireEvent.change(nameInput, { target: { value: "My Simple Server" } });
    fireEvent.change(portInput, { target: { value: "26566" } });
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Create Simple Server" }));
    expect(mockConvertToSimple).toHaveBeenCalledWith({ serverId: "srv-1", body: { name: "My Simple Server", port: 26566 } });
    expect(screen.getByRole("button", { name: "Go to New Server Settings" })).toBeInTheDocument();
  });

  it("View Server Backups navigates to /backups?server_id=srv-1", () => {
    renderCardWithLocation({ mode: "advanced" });
    expect(screen.getByTestId("location-display")).toHaveTextContent("/servers/srv-1/settings");
    const backupsBtn = screen.getByRole("button", { name: "View Server Backups" });
    fireEvent.click(backupsBtn);
    expect(screen.getByTestId("location-display")).toHaveTextContent("/backups?server_id=srv-1");
  });

  it("View Server Backups is present in Simple mode too", () => {
    renderCardWithLocation({ mode: "simple", status: "stopped" });
    expect(screen.getByRole("button", { name: "View Server Backups" })).toBeInTheDocument();
  });

  it("blocks Advanced -> Simple conversion when name is empty", async () => {
    const user = userEvent.setup();
    renderCard({ mode: "advanced" });
    await user.click(screen.getByRole("button", { name: /Create Simple Server/ }));
    const nameInput = screen.getByLabelText(/Name/i);
    fireEvent.change(nameInput, { target: { value: "" } });
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Create Simple Server" }));
    expect(screen.getByText("Server name is required.")).toBeInTheDocument();
    expect(mockConvertToSimple).not.toHaveBeenCalled();
  });

  it("blocks Advanced -> Simple conversion when port is out of range", async () => {
    const user = userEvent.setup();
    renderCard({ mode: "advanced" });
    await user.click(screen.getByRole("button", { name: /Create Simple Server/ }));
    const portInput = screen.getByLabelText(/Port/i);
    fireEvent.change(portInput, { target: { value: "99" } });
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Create Simple Server" }));
    expect(screen.getByText("Port must be between 1024 and 65535.")).toBeInTheDocument();
    expect(mockConvertToSimple).not.toHaveBeenCalled();
  });

  it("maps SECRET_FILE_IN_GIT_FORBIDDEN to friendly copy", async () => {
    const user = userEvent.setup();
    mockConvertToAdvanced.mockRejectedValueOnce(
      new ApiError(422, "SECRET_FILE_IN_GIT_FORBIDDEN", "secret found", { error: "x" }),
    );
    renderCard({ mode: "simple", status: "stopped" });
    await user.click(screen.getByRole("button", { name: /Convert to Advanced/ }));
    await user.click(screen.getByRole("button", { name: "Convert" }));
    expect(screen.getByText(/Class-B secret file detected/i)).toBeInTheDocument();
  });

  it("maps CAS_UNSUPPORTED_PLATFORM to friendly copy", async () => {
    const user = userEvent.setup();
    mockConvertToAdvanced.mockRejectedValueOnce(new ApiError(501, "CAS_UNSUPPORTED_PLATFORM", "no posix", {}));
    renderCard({ mode: "simple", status: "stopped" });
    await user.click(screen.getByRole("button", { name: /Convert to Advanced/ }));
    await user.click(screen.getByRole("button", { name: "Convert" }));
    expect(screen.getByText(/Advanced mode requires a POSIX operating system/i)).toBeInTheDocument();
  });

  it("maps CONFLICT to friendly copy", async () => {
    const user = userEvent.setup();
    mockConvertToAdvanced.mockRejectedValueOnce(new ApiError(409, "CONFLICT", "conflict", {}));
    renderCard({ mode: "simple", status: "stopped" });
    await user.click(screen.getByRole("button", { name: /Convert to Advanced/ }));
    await user.click(screen.getByRole("button", { name: "Convert" }));
    expect(screen.getByText(/Server must be stopped before converting to Advanced mode/i)).toBeInTheDocument();
  });
});
