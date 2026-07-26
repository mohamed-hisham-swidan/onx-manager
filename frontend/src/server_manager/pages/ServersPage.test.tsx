import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServersPage } from "./ServersPage";
import type { ServerResponse } from "@/server_manager/types";

const mockServers: ServerResponse[] = [
  { server_id: "srv-1", name: "Survival World", server_type: "vanilla", minecraft_version: "1.21.4", status: "running", group_id: "default", port: 25565, motd: "Welcome", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-2", name: "Creative Plot", server_type: "paper", minecraft_version: "1.21", status: "stopped", group_id: "default", port: 25566, motd: "Build", max_players: 10, gamemode: "creative", difficulty: "peaceful", created_at: "", updated_at: "" },
];

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
  useDeleteServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

import { useServersList } from "@/server_manager/hooks/useServers";

const qc = new QueryClient();

function renderPage() {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ServersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ServersPage", () => {
  beforeEach(() => {
    vi.mocked(useServersList).mockReturnValue({ data: mockServers, isLoading: false, error: null } as any);
  });

  it("renders page title", () => {
    renderPage();
    expect(screen.getByText("Servers")).toBeInTheDocument();
  });

  it("renders create and import buttons", () => {
    renderPage();
    expect(screen.getByText("+ New Server")).toBeInTheDocument();
    expect(screen.getByText("Import")).toBeInTheDocument();
  });

  it("renders server rows", () => {
    renderPage();
    expect(screen.getByText("Survival World")).toBeInTheDocument();
    expect(screen.getByText("Creative Plot")).toBeInTheDocument();
  });

  it("renders server versions", () => {
    renderPage();
    expect(screen.getByText("1.21.4")).toBeInTheDocument();
    expect(screen.getByText("1.21")).toBeInTheDocument();
  });

  it("renders action buttons for each server", () => {
    renderPage();
    expect(screen.getByText("Stop")).toBeInTheDocument();
    expect(screen.getAllByText("Delete").length).toBe(2);
  });

  it("shows loading state", () => {
    vi.mocked(useServersList).mockReturnValue({ data: undefined, isLoading: true, error: null } as any);
    renderPage();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows error state", () => {
    vi.mocked(useServersList).mockReturnValue({ data: undefined, isLoading: false, error: new Error("API error") } as any);
    renderPage();
    expect(screen.getByText("API error")).toBeInTheDocument();
  });

  it("shows empty state", () => {
    vi.mocked(useServersList).mockReturnValue({ data: [], isLoading: false, error: null } as any);
    renderPage();
    expect(screen.getByText(/No servers found/)).toBeInTheDocument();
  });
});
