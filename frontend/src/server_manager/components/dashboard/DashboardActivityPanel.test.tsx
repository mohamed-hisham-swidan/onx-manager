import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardActivityPanel } from "./DashboardActivityPanel";
import { useActivityStore } from "@/stores/activityStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import type { ServerResponse } from "@/server_manager/types";
import type { OperationDetail, OperationSummary } from "@/operations/types";

const mockApi = {
  listOperations: vi.fn(),
  getOperation: vi.fn(),
  getServerActivity: vi.fn(),
};

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>("@/services/api");
  return {
    ...actual,
    createAuthenticatedApi: vi.fn(() => mockApi),
  };
});

const sampleServers: ServerResponse[] = [
  {
    server_id: "srv-1",
    name: "Alpha SMP",
    server_type: "paper",
    minecraft_version: "1.21.4",
    status: "running",
    group_id: "default",
    port: 25565,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    created_at: "",
    updated_at: "",
  },
];

function renderPanel(servers: ServerResponse[] = sampleServers) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <DashboardActivityPanel
                servers={servers}
                serverNames={{ "srv-1": "Alpha SMP" }}
              />
            }
          />
          <Route
            path="/servers/:serverId/console"
            element={<div data-testid="quick-console-dest">Console</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DashboardActivityPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useActivityStore.getState().clear();
    useOperationStore.setState({ operations: {}, activeDrawerId: null });
    mockApi.listOperations.mockResolvedValue([]);
    mockApi.getServerActivity.mockResolvedValue({ items: [], total: 0, limit: 5, offset: 0 });
  });

  it("renders calm honest empty state with zero fake log lines", async () => {
    renderPanel();
    expect(
      await screen.findByText(/No recent activity yet\. Server actions, backups, and tasks appear here\./i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\[SYS\]/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\[DOCKER\]/i)).not.toBeInTheDocument();
  });

  it("renders persisted operations and opens OperationDrawer on click", async () => {
    const ops: OperationSummary[] = [
      {
        id: "op-42",
        type: "backup_create",
        target_type: "server",
        target_id: "srv-1",
        status: "COMPLETED",
        current_step_id: null,
        last_event_seq: 3,
        failure_code: null,
        error_message: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
        elapsed_ms: 1400,
      },
    ];
    const opDetail: OperationDetail = {
      ...ops[0],
      actor_id: "admin",
      idempotency_key: null,
      cancellation_requested: false,
      timeout_seconds: 120,
      steps: [],
      metadata: {},
    };

    mockApi.listOperations.mockResolvedValue(ops);
    mockApi.getOperation.mockResolvedValue(opDetail);

    renderPanel();

    const opBtn = await screen.findByRole("button", { name: /Backup Create/i });
    expect(opBtn).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();

    fireEvent.click(opBtn);

    await waitFor(() => {
      expect(mockApi.getOperation).toHaveBeenCalledWith("op-42");
      expect(useOperationStore.getState().activeDrawerId).toBe("op-42");
    });
  });

  it("merges persisted server activity and live WebSocket events, filters Tasks vs Events, and clears live buffer", async () => {
    mockApi.listOperations.mockResolvedValue([
      {
        id: "op-1",
        type: "modpack_install",
        target_type: "server",
        target_id: "srv-1",
        status: "RUNNING",
        current_step_id: "download",
        last_event_seq: 1,
        failure_code: null,
        error_message: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        finished_at: null,
        elapsed_ms: 500,
      },
    ]);
    mockApi.getServerActivity.mockResolvedValue({
      items: [
        {
          id: "act-1",
          server_id: "srv-1",
          timestamp: Date.now() / 1000 - 15,
          event_type: "ServerStartedEvent",
          actor_type: "user",
          actor_id: "u1",
          summary: "Alpha SMP started cleanly",
          details: {},
        },
      ],
      total: 1,
      limit: 5,
      offset: 0,
    });

    useActivityStore.getState().addEvent({
      event_type: "ServerConfigChangedEvent",
      server_id: "srv-1",
      name: "Alpha SMP",
      timestamp: Math.floor(Date.now() / 1000),
    });

    renderPanel();

    expect(await screen.findByText("Modpack Install")).toBeInTheDocument();
    expect(screen.getByText("Alpha SMP started cleanly")).toBeInTheDocument();
    expect(screen.getByText("Updated configuration for Alpha SMP")).toBeInTheDocument();

    // Tasks filter
    fireEvent.click(screen.getByRole("button", { name: "Tasks" }));
    expect(screen.getByText("Modpack Install")).toBeInTheDocument();
    expect(screen.queryByText("Alpha SMP started cleanly")).not.toBeInTheDocument();

    // Events filter
    fireEvent.click(screen.getByRole("button", { name: "Events" }));
    expect(screen.queryByText("Modpack Install")).not.toBeInTheDocument();
    expect(screen.getByText("Updated configuration for Alpha SMP")).toBeInTheDocument();

    // Clear live buffer
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText("Updated configuration for Alpha SMP")).not.toBeInTheDocument();
  });

  it("renders single-server direct Quick Console CTA and navigates cleanly", () => {
    renderPanel();
    const btn = screen.getByRole("button", { name: /Open Alpha SMP Console/i });
    fireEvent.click(btn);
    expect(screen.getByTestId("quick-console-dest")).toBeInTheDocument();
  });

  it("formats uppercase operation enums in Title Case, filters deleted-server operations, and resolves plugin hex IDs", async () => {
    mockApi.listOperations.mockResolvedValue([
      {
        id: "op-active-1",
        type: "RUN_TEST",
        target_type: "server",
        target_id: "srv-1",
        status: "COMPLETED",
        current_step_id: null,
        last_event_seq: 1,
        failure_code: null,
        error_message: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
        elapsed_ms: 800,
      },
      {
        id: "op-active-2",
        type: "SAFE_UPGRADE",
        target_type: "server",
        target_id: "srv-1",
        status: "FAILED",
        current_step_id: null,
        last_event_seq: 1,
        failure_code: null,
        error_message: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
        elapsed_ms: 800,
      },
      {
        id: "op-ghost-1",
        type: "MODPACK_INSTALL",
        target_type: "server",
        target_id: "deleted-srv-999",
        status: "FAILED",
        current_step_id: null,
        last_event_seq: 1,
        failure_code: null,
        error_message: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
        elapsed_ms: 800,
      },
    ]);
    mockApi.getServerActivity.mockResolvedValue({
      items: [
        {
          id: "act-plug-hex",
          server_id: "srv-1",
          timestamp: Date.now() / 1000 - 10,
          event_type: "plugin.disabled",
          actor_type: "user",
          actor_id: "u1",
          summary: "Plugin/mod '03b2ea67c4db450faac98f39f021b318' disabled",
          details: {
            plugin_id: "03b2ea67c4db450faac98f39f021b318",
            plugin_name: "SkinsRestorer",
          },
        },
      ],
      total: 1,
      limit: 5,
      offset: 0,
    });

    renderPanel();

    expect(await screen.findByText("Isolated Test")).toBeInTheDocument();
    expect(screen.getByText("Safe Upgrade")).toBeInTheDocument();
    expect(screen.queryByText("Modpack Install")).not.toBeInTheDocument();
    expect(screen.getByText("Plugin/mod 'SkinsRestorer' disabled")).toBeInTheDocument();
    expect(screen.queryByText(/03b2ea67c4db450faac98f39f021b318/)).not.toBeInTheDocument();
  });
});
