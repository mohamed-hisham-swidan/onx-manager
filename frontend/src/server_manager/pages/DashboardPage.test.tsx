import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "./DashboardPage";
import type { ServerResponse } from "@/server_manager/types";

const mockServers: ServerResponse[] = [
  { server_id: "srv-1", name: "Online Server", server_type: "vanilla", minecraft_version: "1.21.4", status: "running", group_id: "default", port: 25565, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-2", name: "Stopped Server", server_type: "paper", minecraft_version: "1.21", status: "stopped", group_id: "default", port: 25566, motd: "", max_players: 10, gamemode: "creative", difficulty: "peaceful", created_at: "", updated_at: "" },
  { server_id: "srv-3", name: "Crashed Server", server_type: "vanilla", minecraft_version: "1.20.4", status: "crashed", group_id: "default", port: 25567, motd: "", max_players: 20, gamemode: "survival", difficulty: "normal", created_at: "", updated_at: "" },
];

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
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
    vi.mocked(useServersList).mockReturnValue({ data: mockServers, isLoading: false } as any);
  });

  it("renders dashboard title", () => {
    renderPage();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("renders status count cards", () => {
    renderPage();
    const statuses = ["Online", "Offline", "Starting", "Stopping", "Crashed", "Not Started"];
    for (const s of statuses) {
      expect(screen.getAllByText(s).length).toBeGreaterThanOrEqual(1);
    }
  });

  it("shows correct counts", () => {
    renderPage();
    const onlineCards = screen.getAllByText("1");
    expect(onlineCards.length).toBeGreaterThanOrEqual(1);
  });

  it("renders recent servers list", () => {
    renderPage();
    expect(screen.getByText("Online Server")).toBeInTheDocument();
    expect(screen.getByText("Stopped Server")).toBeInTheDocument();
  });

  it("renders view all link", () => {
    renderPage();
    expect(screen.getByText("View all")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    vi.mocked(useServersList).mockReturnValue({ data: undefined, isLoading: true } as any);
    renderPage();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows empty state when no servers", () => {
    vi.mocked(useServersList).mockReturnValue({ data: [], isLoading: false } as any);
    renderPage();
    expect(screen.getByText("No servers yet.")).toBeInTheDocument();
  });
});
