import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerConsole } from "./ServerConsole";

const mockGetServerConsole = vi.fn();
const mockSendServerCommand = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getServerConsole: (...args: unknown[]) => mockGetServerConsole(...args),
    sendServerCommand: (...args: unknown[]) => mockSendServerCommand(...args),
  }),
}));

const mockMetrics = [
  {
    tps: 20.0,
    players: 4,
    ram_used_mb: 2048,
    cpu_percent: 15.0,
    timestamp: "2026-08-18T19:00:00Z",
  },
];

vi.mock("@/server_manager/hooks/useServerMetrics", () => ({
  useServerMetrics: vi.fn(() => ({
    data: mockMetrics,
  })),
}));

function renderConsole(props: { serverId?: string; serverStatus?: string; tps?: number | null; players?: number } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ServerConsole
        serverId={props.serverId ?? "srv-1"}
        serverStatus={props.serverStatus ?? "running"}
        tps={props.tps}
        players={props.players}
      />
    </QueryClientProvider>
  );
}

describe("ServerConsole Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetServerConsole.mockResolvedValue({
      lines: ["[Server thread/INFO]: Done (2.4s)! For help, type 'help'"],
    });
    mockSendServerCommand.mockResolvedValue({ success: true });
  });

  it("renders server console header and lines", async () => {
    renderConsole();
    expect(screen.getByText("Server Console")).toBeInTheDocument();
    expect(await screen.findByText(/Done \(2\.4s\)!/)).toBeInTheDocument();
  });

  it("displays live TPS badge in console header when running", async () => {
    renderConsole({ serverStatus: "running", tps: 19.8 });
    const badge = screen.getByTestId("console-tps-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("TPS");
    expect(badge).toHaveTextContent("19.8");
    expect(badge).toHaveTextContent("(99%)");
  });

  it("displays — for TPS and hides players badge when server is stopped", async () => {
    renderConsole({ serverStatus: "stopped", tps: 20.0, players: 4 });
    const badge = screen.getByTestId("console-tps-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("—");
    expect(screen.queryByTestId("console-players-badge")).not.toBeInTheDocument();
  });

  it("displays — for TPS when running but TPS is null (unknown)", async () => {
    renderConsole({ serverStatus: "running", tps: null });
    const badge = screen.getByTestId("console-tps-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("—");
  });

  it("displays players badge when player count is available and server is running", async () => {
    renderConsole({ serverStatus: "running", players: 3 });
    const badge = screen.getByTestId("console-players-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("3");
  });

  it("sends command and appends to local command history", async () => {
    const user = userEvent.setup();
    renderConsole();

    const input = screen.getByPlaceholderText("Enter a command...");
    const sendBtn = screen.getByRole("button", { name: "Send" });

    await user.type(input, "tps");
    await user.click(sendBtn);

    expect(mockSendServerCommand).toHaveBeenCalledWith("srv-1", { command: "tps" });
    expect(await screen.findByText("> tps")).toBeInTheDocument();
  });

  it("clears local command history on Clear button click", async () => {
    const user = userEvent.setup();
    renderConsole();

    const input = screen.getByPlaceholderText("Enter a command...");
    const sendBtn = screen.getByRole("button", { name: "Send" });

    await user.type(input, "list");
    await user.click(sendBtn);
    expect(await screen.findByText("> list")).toBeInTheDocument();

    const clearBtn = screen.getByRole("button", { name: "Clear" });
    await user.click(clearBtn);

    expect(screen.queryByText("> list")).not.toBeInTheDocument();
  });
});
