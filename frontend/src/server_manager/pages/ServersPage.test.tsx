import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServersPage } from "./ServersPage";
import type { ServerResponse } from "@/server_manager/types";

const mockServers: ServerResponse[] = [
  { server_id: "srv-1", name: "Alpha World", server_type: "vanilla", minecraft_version: "1.21.4", status: "running", group_id: "default", port: 25565, motd: "Welcome", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-2", name: "Beta Plot", server_type: "paper", minecraft_version: "1.21", status: "stopped", group_id: "default", port: 25566, motd: "Build", max_players: 10, gamemode: "creative", difficulty: "peaceful", created_at: "", updated_at: "" },
  { server_id: "srv-3", name: "Crash Test", server_type: "vanilla", minecraft_version: "1.20.4", status: "crashed", group_id: "default", port: 25567, motd: "", max_players: 20, gamemode: "survival", difficulty: "normal", created_at: "", updated_at: "" },
];

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
  useDeleteServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
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
    vi.mocked(useServersList).mockReturnValue({ data: mockServers, isLoading: false, error: null } as unknown as ReturnType<typeof useServersList>);
  });

  it("renders page header and buttons", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Servers" })).toBeInTheDocument();
    expect(screen.getByText("New Server")).toBeInTheDocument();
    expect(screen.getByText("Import")).toBeInTheDocument();
  });

  it("renders server rows", () => {
    renderPage();
    expect(screen.getByText("Alpha World")).toBeInTheDocument();
    expect(screen.getByText("Beta Plot")).toBeInTheDocument();
  });

  it("renders status badges", () => {
    renderPage();
    for (const label of ["Online", "Offline", "Crashed"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1);
    }
  });

  it("shows quick action buttons per status", () => {
    renderPage();
    expect(screen.getByLabelText("Start Beta Plot")).toBeInTheDocument();
    expect(screen.getByLabelText("Stop Alpha World")).toBeInTheDocument();
    expect(screen.getByLabelText("Restart Alpha World")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/Delete/)).toHaveLength(3);
  });

  it("filters by search text", () => {
    renderPage();
    const search = screen.getByLabelText("Search servers by name");
    fireEvent.change(search, { target: { value: "alpha" } });
    expect(screen.getByText("Alpha World")).toBeInTheDocument();
    expect(screen.queryByText("Beta Plot")).not.toBeInTheDocument();
  });

  it("filters by status", () => {
    renderPage();
    const filter = screen.getByLabelText("Filter by status");
    fireEvent.change(filter, { target: { value: "running" } });
    expect(screen.getByText("Alpha World")).toBeInTheDocument();
    expect(screen.queryByText("Beta Plot")).not.toBeInTheDocument();
  });

  it("sorts by name", () => {
    renderPage();
    const rows = screen.getAllByRole("link", { name: /World|Plot|Test/ });
    expect(rows[0]).toHaveTextContent("Alpha World");
    expect(rows[rows.length - 1]).toHaveTextContent("Crash Test");
  });

  it("shows a no-results empty state", () => {
    renderPage();
    const search = screen.getByLabelText("Search servers by name");
    fireEvent.change(search, { target: { value: "zzz" } });
    expect(screen.getByText("No matching servers")).toBeInTheDocument();
  });

  it("shows empty state when no servers exist", () => {
    vi.mocked(useServersList).mockReturnValue({ data: [], isLoading: false, error: null } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByText("No servers yet")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    vi.mocked(useServersList).mockReturnValue({ data: undefined, isLoading: true, error: null } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(document.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error state", () => {
    vi.mocked(useServersList).mockReturnValue({ data: undefined, isLoading: false, error: new Error("API error") } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    expect(screen.getByText("API error")).toBeInTheDocument();
  });

  it("opens delete confirmation dialog", () => {
    renderPage();
    fireEvent.click(screen.getByLabelText("Delete Alpha World"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Delete server?")).toBeInTheDocument();
  });

  it("truncates long names with a tooltip", () => {
    const longName = "A".repeat(60);
    vi.mocked(useServersList).mockReturnValue({
      data: [{ ...mockServers[0], server_id: "srv-x", name: longName }],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useServersList>);
    renderPage();
    const link = screen.getByRole("link", { name: longName });
    expect(link).toHaveAttribute("title", longName);
    expect(link.className).toContain("truncate");
  });
});
