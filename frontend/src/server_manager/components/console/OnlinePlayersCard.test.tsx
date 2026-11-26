import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OnlinePlayersCard } from "./OnlinePlayersCard";

const mockSendServerCommand = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    sendServerCommand: (...args: unknown[]) => mockSendServerCommand(...args),
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

describe("OnlinePlayersCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("displays freshly fetched RCON roster even when livePlayersCount is 0", async () => {
    mockSendServerCommand.mockResolvedValueOnce({
      success: true,
      output: "There are 2 of a max of 20 players online: Steve, Alex",
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={qc}>
        <OnlinePlayersCard
          serverId="srv-1"
          isRunning={true}
          livePlayersCount={0}
          maxPlayers={20}
          canConsole={true}
        />
      </QueryClientProvider>,
    );

    await user.click(screen.getByTestId("refresh-players-btn"));

    await waitFor(() => {
      expect(screen.getByText("Steve")).toBeInTheDocument();
      expect(screen.getByText("Alex")).toBeInTheDocument();
    });
    expect(screen.getByTestId("online-players-count")).toHaveTextContent("2 / 20");
  });
});
