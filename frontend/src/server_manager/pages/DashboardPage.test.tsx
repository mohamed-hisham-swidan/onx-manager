import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "./DashboardPage";
import { useActivityStore } from "@/stores/activityStore";
import type { ServerResponse } from "@/server_manager/types";

const mockServers: ServerResponse[] = [
  { server_id: "srv-1", name: "Online Server", server_type: "vanilla", minecraft_version: "1.21.4", status: "running", group_id: "default", port: 25565, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-2", name: "Stopped Server", server_type: "paper", minecraft_version: "1.21", status: "stopped", group_id: "default", port: 25566, motd: "", max_players: 10, gamemode: "creative", difficulty: "peaceful", created_at: "", updated_at: "" },
  { server_id: "srv-3", name: "Crashed Server", server_type: "vanilla", minecraft_version: "1.20.4", status: "crashed", group_id: "default", port: 25567, motd: "", max_players: 20, gamemode: "survival", difficulty: "normal", created_at: "", updated_at: "" },
];

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRetryProvisioningServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

import { useServersList } from "@/server_manager/hooks/useServers";

const qc = new QueryClient();

function renderPage() {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.mocked(useServersList).mockReturnValue({ data: mockServers, isLoading: false } as unknown as ReturnType<typeof useServersList>);
    useActivityStore.getState().clear();
  });

  it("renders page header", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("renders status count cards with correct labels", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "1 Online" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "1 Offline" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "0 Starting" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "0 Stopping" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "1 Crashed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "0 Not Started" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "3 Total" })).toBeInTheDocument();
  });

  it("shows real counts from the servers list", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "1 Online" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "1 Crashed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "3 Total" })).toBeInTheDocument();
  });

  it("renders the compact servers list with names and badges", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "Online Server" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stopped Server" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Crashed Server" })).toBeInTheDocument();
    expect(screen.getAllByText("Online").length).toBeGreaterThanOrEqual(2);
  });

  it("renders view all link", () => {
    renderPage();
    expect(screen.getByText("View all")).toBeInTheDocument();
  });

  it("renders recent activity placeholder when no events", () => {
    renderPage();
    expect(screen.getByText("No activity yet")).toBeInTheDocument();
  });

  it("renders recent activity events when present", () => {
    useActivityStore.getState().addEvent({
      event_type: "ServerStartedEvent",
      server_id: "srv-1",
      name: "Online Server",
      timestamp: Date.now() / 1000,
    });
    renderPage();
    expect(screen.queryByText("No activity yet")).not.toBeInTheDocument();
    expect(screen.getAllByText("Online Server").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("started")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    vi.mocked(useServersList).mockReturnValue({ data: undefined, isLoading: true } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("shows empty state when no servers", () => {
    vi.mocked(useServersList).mockReturnValue({ data: [], isLoading: false } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByText("No servers yet")).toBeInTheDocument();
    expect(screen.getByText("Create your first Minecraft server to get started.")).toBeInTheDocument();
  });

  it("shows error state", () => {
    vi.mocked(useServersList).mockReturnValue({ data: undefined, isLoading: false, error: new Error("boom") } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });
});
