import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ServerActivityPage } from "./ServerActivityPage";

const mockApi = {
  getServerActivity: vi.fn(),
};

vi.mock("@/services/api", () => ({
  createApiClient: () => mockApi,
  createAuthenticatedApi: () => mockApi,
}));

const mockLogs = [
  {
    id: "act-1",
    server_id: "srv-act-1",
    timestamp: 1789390000,
    event_type: "server.started",
    actor_type: "user",
    actor_id: "usr-admin",
    summary: "Server started successfully",
    details: { port: 25565, pid: 4321 },
  },
  {
    id: "act-2",
    server_id: "srv-act-1",
    timestamp: 1789389000,
    event_type: "plugin.installed",
    actor_type: "system",
    actor_id: null,
    summary: "Plugin 'WorldEdit' installed (v7.3.0)",
    details: { plugin_id: "worldedit", version: "7.3.0" },
  },
  {
    id: "act-3",
    server_id: "srv-act-1",
    timestamp: 1789388000,
    event_type: "server.crashed",
    actor_type: "system",
    actor_id: null,
    summary: "Server crashed (exit code: 1)",
    details: { exit_code: 1, error: "Out of memory" },
  },
];

describe("ServerActivityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getServerActivity.mockResolvedValue({
      items: mockLogs,
      total: 3,
      limit: 25,
      offset: 0,
    });
  });

  const renderPage = () =>
    render(
      <MemoryRouter initialEntries={["/servers/srv-act-1/activity"]}>
        <Routes>
          <Route path="/servers/:serverId/activity" element={<ServerActivityPage />} />
        </Routes>
      </MemoryRouter>
    );

  it("renders page title, categories, and activity items", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Change History & Activity Log")).toBeInTheDocument();
    });

    expect(screen.getByText("Server started successfully")).toBeInTheDocument();
    expect(screen.getByText("Plugin 'WorldEdit' installed (v7.3.0)")).toBeInTheDocument();
    expect(screen.getByText("Server crashed (exit code: 1)")).toBeInTheDocument();
    expect(screen.getByText("usr-admin")).toBeInTheDocument();
  });

  it("filters activity logs when clicking category filter buttons", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Change History & Activity Log")).toBeInTheDocument();
    });

    // Click on "Crashes" category
    const crashBtn = screen.getByText("Crashes");
    fireEvent.click(crashBtn);

    await waitFor(() => {
      expect(mockApi.getServerActivity).toHaveBeenCalledWith(
        "srv-act-1",
        expect.objectContaining({
          event_type: "server.crashed",
        })
      );
    });
  });

  it("filters visible items dynamically with the search input", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Server started successfully")).toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText("Search activity summaries...");
    fireEvent.change(searchInput, { target: { value: "WorldEdit" } });

    expect(screen.getByText("Plugin 'WorldEdit' installed (v7.3.0)")).toBeInTheDocument();
    expect(screen.queryByText("Server started successfully")).not.toBeInTheDocument();
  });

  it("expands JSON details when clicking View Details", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Server started successfully")).toBeInTheDocument();
    });

    const viewDetailsBtns = screen.getAllByText("View Details");
    fireEvent.click(viewDetailsBtns[0]);

    await waitFor(() => {
      expect(screen.getByText("Event Payload Details")).toBeInTheDocument();
      expect(screen.getByText(/"port": 25565/)).toBeInTheDocument();
      expect(screen.getByText("Hide Details")).toBeInTheDocument();
    });
  });

  it("renders empty state when no activity logs exist", async () => {
    mockApi.getServerActivity.mockResolvedValue({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("activity-empty-state")).toBeInTheDocument();
      expect(screen.getByText("No activity logs found")).toBeInTheDocument();
    });
  });

  it("renders error state when API call fails", async () => {
    mockApi.getServerActivity.mockRejectedValue(new Error("Network connection lost"));

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Network connection lost")).toBeInTheDocument();
      expect(screen.getByText("Retry")).toBeInTheDocument();
    });
  });
});
