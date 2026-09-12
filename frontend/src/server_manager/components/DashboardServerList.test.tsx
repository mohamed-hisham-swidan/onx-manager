import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardServerList } from "./DashboardServerList";
import { useToastStore } from "@/stores/toastStore";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState, ChannelStatus } from "@/websocket/types";
import type { ChannelState } from "@/websocket/types";
import type { ServerResponse } from "@/server_manager/types";

function rejectedChannelState(channel: string): ChannelState {
  return {
    channel,
    status: ChannelStatus.REJECTED,
    authorized: false,
    error: `Not authorized for channel: ${channel}`,
    retryCount: 3,
  };
}

const servers: ServerResponse[] = [
  { server_id: "srv-1", name: "Running", server_type: "vanilla", minecraft_version: "1.21", status: "running", group_id: "default", port: 25565, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-2", name: "Stopped", server_type: "vanilla", minecraft_version: "1.21", status: "stopped", group_id: "default", port: 25566, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-3", name: "Starting", server_type: "vanilla", minecraft_version: "1.21", status: "starting", group_id: "default", port: 25567, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
  { server_id: "srv-4", name: "Stopping", server_type: "vanilla", minecraft_version: "1.21", status: "stopping", group_id: "default", port: 25568, motd: "", max_players: 20, gamemode: "survival", difficulty: "easy", created_at: "", updated_at: "" },
];

vi.mock("@/server_manager/hooks/useServers", () => ({
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRetryProvisioningServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

import {
  useStartServer,
  useStopServer,
  useRetryProvisioningServer,
} from "@/server_manager/hooks/useServers";
const useStartServerMock = vi.mocked(useStartServer);
const useStopServerMock = vi.mocked(useStopServer);
const useRetryProvisioningServerMock = vi.mocked(useRetryProvisioningServer);

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
    useToastStore.setState({ toasts: [] });
    useWSStore.setState({
      channelStates: {
        "servers:list": { channel: "servers:list", status: ChannelStatus.SUBSCRIBED, authorized: true, retryCount: 0 },
      },
      connectionState: ConnectionState.CONNECTED,
    });
  });

  it("renders each server with a name link and status badge", () => {
    renderList();
    expect(screen.getByRole("link", { name: "Running" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stopped" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Starting" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Stopping" })).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("shows stop and restart buttons for running servers", () => {
    renderList();
    expect(screen.getByLabelText("Stop Running")).toBeInTheDocument();
    expect(screen.getByLabelText("Restart Running")).toBeInTheDocument();
  });

  it("shows stop button for starting servers", () => {
    renderList();
    expect(screen.getByLabelText("Stop Starting")).toBeInTheDocument();
    expect(screen.queryByLabelText("Restart Starting")).not.toBeInTheDocument();
  });

  it("shows start button for stopped servers", () => {
    renderList();
    expect(screen.getByLabelText("Start Stopped")).toBeInTheDocument();
  });

  it("shows a spinner for transitioning stopping servers", () => {
    renderList();
    expect(screen.getByLabelText("Stopping is stopping")).toBeInTheDocument();
  });

  it("fires start with a success toast", () => {
    const mutate = vi.fn((_id: string, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.());
    useStartServerMock.mockReturnValue({ mutate, isPending: false } as unknown as ReturnType<typeof useStartServer>);

    renderList();
    fireEvent.click(screen.getByLabelText("Start Stopped"));
    expect(mutate).toHaveBeenCalledWith("srv-2", expect.anything());
    expect(useToastStore.getState().toasts.some((t) => t.title === "Server started")).toBe(true);
  });

  it.each([
    [ConnectionState.CONNECTED, false],
    [ConnectionState.CONNECTING, true],
    [ConnectionState.RECONNECTING, true],
    [ConnectionState.DISCONNECTED, true],
  ] as const)("connectionState=%s shows the not-live note only when not connected", (state, expectNote) => {
    useWSStore.setState({ connectionState: state, connected: state === ConnectionState.CONNECTED });
    renderList();
    if (expectNote) {
      expect(screen.getByRole("status")).toBeInTheDocument();
    } else {
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Running" })).toBeInTheDocument();
  });

  it("shows the subscription-rejected note when transport is connected but a server channel is rejected (K1)", () => {
    useWSStore.setState({
      connectionState: ConnectionState.CONNECTED,
      connected: true,
      channelStates: { "server:s01": rejectedChannelState("server:s01") },
    });
    renderList();
    expect(screen.getByRole("status")).toHaveTextContent("Status not live — subscription rejected");
    expect(screen.getByRole("link", { name: "Running" })).toBeInTheDocument();
  });

  it("does not show retry provisioning button when provisioning_retryable is true", () => {
    const failedAutoRetryingServer: ServerResponse = {
      server_id: "srv-failed-retrying",
      name: "AutoRetrying",
      server_type: "forge",
      minecraft_version: "1.20.1",
      status: "provisioning_failed",
      provisioning_error: "Transient connection drop",
      provisioning_retryable: true,
      group_id: "default",
      port: 25569,
      motd: "",
      max_players: 20,
      gamemode: "survival",
      difficulty: "easy",
      created_at: "",
      updated_at: "",
    };

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <DashboardServerList servers={[failedAutoRetryingServer]} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.queryByLabelText("Retry Provisioning AutoRetrying")).not.toBeInTheDocument();
  });

  it("shows retry provisioning button when provisioning_retryable is false and triggers action", () => {
    const mutate = vi.fn((_id: string, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.());
    useRetryProvisioningServerMock.mockReturnValue({ mutate, isPending: false } as unknown as ReturnType<typeof useRetryProvisioningServer>);

    const failedExhaustedServer: ServerResponse = {
      server_id: "srv-failed-exhausted",
      name: "ExhaustedServer",
      server_type: "forge",
      minecraft_version: "1.20.1",
      status: "provisioning_failed",
      provisioning_error: "Installer timeout",
      provisioning_retryable: false,
      group_id: "default",
      port: 25570,
      motd: "",
      max_players: 20,
      gamemode: "survival",
      difficulty: "easy",
      created_at: "",
      updated_at: "",
    };

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <DashboardServerList servers={[failedExhaustedServer]} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const retryBtn = screen.getByLabelText("Retry Provisioning ExhaustedServer");
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);
    expect(mutate).toHaveBeenCalledWith("srv-failed-exhausted", expect.anything());
    expect(useToastStore.getState().toasts.some((t) => t.title === "Retry started")).toBe(true);
  });

  it("does not show the note when an unrelated channel is rejected", () => {
    useWSStore.setState({
      connectionState: ConnectionState.CONNECTED,
      connected: true,
      channelStates: { "metrics:s99": rejectedChannelState("metrics:s99") },
    });
    renderList();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not start a background interval timer when no start cooldown is active (ISS-052)", () => {
    vi.useFakeTimers();
    try {
      const setIntervalSpy = vi.spyOn(window, "setInterval");
      renderList();
      expect(setIntervalSpy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("starts interval only during active cooldown and disables start button until cooldown expires (ISS-052)", async () => {
    vi.useFakeTimers();
    try {
      renderList();

      const startBtn = screen.getByLabelText("Start Stopped");
      expect(startBtn).not.toBeDisabled();

      fireEvent.click(startBtn);

      // Cooldown is active: start button disabled
      expect(startBtn).toBeDisabled();

      // Advance time past 3s cooldown inside act
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3500);
      });

      // Cooldown expired: button re-enabled
      expect(startBtn).not.toBeDisabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens stop confirmation dialog and triggers stop on confirm", async () => {
    const user = userEvent.setup();
    const mockStopMutate = vi.fn();
    useStopServerMock.mockReturnValue(
      { mutate: mockStopMutate, isPending: false } as unknown as ReturnType<typeof useStopServer>,
    );
    renderList();
    await user.click(screen.getByLabelText("Stop Running"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Stop server?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stop Server" }));
    expect(mockStopMutate).toHaveBeenCalledWith("srv-1", expect.any(Object));
  });
});
