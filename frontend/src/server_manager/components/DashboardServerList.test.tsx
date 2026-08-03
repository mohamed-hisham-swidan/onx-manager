import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardServerList } from "./DashboardServerList";
import { useToastStore } from "@/stores/toastStore";
import type { ServerResponse } from "@/server_manager/types";

const servers: ServerResponse[] = [
  { server_id: "srv-1", name: "Running", server_type: "vanilla", minecraft_version: "1.21", status: "running", group_id: "default", port: 25565, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-2", name: "Stopped", server_type: "vanilla", minecraft_version: "1.21", status: "stopped", group_id: "default", port: 25566, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-3", name: "Starting", server_type: "vanilla", minecraft_version: "1.21", status: "starting", group_id: "default", port: 25567, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
];

vi.mock("@/server_manager/hooks/useServers", () => ({
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

import { useStartServer } from "@/server_manager/hooks/useServers";
const useStartServerMock = vi.mocked(useStartServer);

const qc = new QueryClient();

function renderList() {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DashboardServerList servers={servers} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DashboardServerList", () => {
  beforeEach(() => {
    useToastStore.getState().clear();
  });

  it("renders each server with a name link and status badge", () => {
    renderList();
    expect(screen.getByRole("link", { name: "Running" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stopped" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Starting" })).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("shows stop and restart buttons for running servers", () => {
    renderList();
    expect(screen.getByLabelText("Stop Running")).toBeInTheDocument();
    expect(screen.getByLabelText("Restart Running")).toBeInTheDocument();
  });

  it("shows start button for stopped servers", () => {
    renderList();
    expect(screen.getByLabelText("Start Stopped")).toBeInTheDocument();
  });

  it("shows a spinner for transitioning servers", () => {
    renderList();
    expect(screen.getByLabelText("Starting is starting")).toBeInTheDocument();
  });

  it("fires start with a success toast", () => {
    const mutate = vi.fn((_id: string, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.());
    useStartServerMock.mockReturnValue({ mutate, isPending: false } as unknown as ReturnType<typeof useStartServer>);

    renderList();
    fireEvent.click(screen.getByLabelText("Start Stopped"));
    expect(mutate).toHaveBeenCalledWith("srv-2", expect.anything());
    expect(useToastStore.getState().toasts.some((t) => t.title === "Server started")).toBe(true);
  });
});
