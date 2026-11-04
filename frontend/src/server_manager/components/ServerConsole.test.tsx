import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerConsole } from "./ServerConsole";
import { notifyConsoleListeners } from "@/hooks/useWebSocket";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState } from "@/websocket/types";
import type { CrashReportSummary } from "@/server_manager/types";

const mockGetServerConsole = vi.fn();
const mockGetServerCrashReports = vi.fn();
const mockSendServerCommand = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getServerConsole: (...args: unknown[]) => mockGetServerConsole(...args),
    getServerCrashReports: (...args: unknown[]) => mockGetServerCrashReports(...args),
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

function renderConsole(
  props: {
    serverId?: string;
    serverStatus?: string;
    tps?: number | null;
    players?: number;
    provider?: string | null;
    host?: string | null;
    port?: number | null;
  } = {},
) {
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
        provider={props.provider}
        host={props.host}
        port={props.port}
      />
    </QueryClientProvider>,
  );
}

describe("ServerConsole Component", () => {
  afterEach(() => {
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      writable: true,
      configurable: true,
    });
  });

  beforeEach(() => {
    vi.clearAllMocks();
    useWSStore.setState({
      connected: false,
      connectionState: ConnectionState.DISCONNECTED,
      channelStates: {},
      unattributedRejection: false,
    });
    mockGetServerConsole.mockResolvedValue({
      lines: ["[Server thread/INFO]: Done (2.4s)! For help, type 'help'"],
    });
    mockGetServerCrashReports.mockResolvedValue([]);
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

  it("displays Container tag badge when provider is docker", () => {
    renderConsole({ provider: "docker" });
    const badge = screen.getByTestId("console-provider-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Container");
  });

  it("displays File / Host tag badge when provider is not docker", () => {
    renderConsole({ provider: "local_process" });
    const badge = screen.getByTestId("console-provider-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("File / Host");
  });

  it("displays dynamic container IP badge when host and port are provided for docker", () => {
    renderConsole({ provider: "docker", host: "172.17.0.3", port: 25569 });
    const badge = screen.getByTestId("console-ip-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("172.17.0.3:25569");
    expect(badge).toHaveAttribute("title", "Container IP: 172.17.0.3:25569");
  });

  it("displays dynamic host IP badge when host and port are provided for host process", () => {
    renderConsole({ provider: "local", host: "192.168.1.253", port: 25565 });
    const badge = screen.getByTestId("console-ip-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("192.168.1.253:25565");
    expect(badge).toHaveAttribute("title", "Host IP: 192.168.1.253:25565");
  });

  it("does not display IP badge when host is not provided", () => {
    renderConsole({ provider: "docker", host: null });
    expect(screen.queryByTestId("console-ip-badge")).not.toBeInTheDocument();
  });

  it("colorizes log lines according to severity level classes", async () => {
    mockGetServerConsole.mockResolvedValue({
      lines: [
        "[INFO] Starting server",
        "[WARN] Can't keep up! Is the server overloaded?",
        "[ERROR] Encountered an unexpected exception",
        "Plain text log without level",
      ],
    });

    renderConsole();

    const infoLine = await screen.findByText("[INFO] Starting server");
    expect(infoLine).toHaveClass("text-sky-300");

    const warnLine = await screen.findByText(/Can't keep up!/);
    expect(warnLine).toHaveClass("text-amber-400");

    const errorLine = await screen.findByText(/Encountered an unexpected exception/);
    expect(errorLine).toHaveClass("text-rose-400");

    const plainLine = await screen.findByText("Plain text log without level");
    expect(plainLine).toHaveClass("text-gray-300");
  });

  it("filters logs and displays match count when searching", async () => {
    const user = userEvent.setup();
    mockGetServerConsole.mockResolvedValue({
      lines: [
        "[INFO] User Alice logged in",
        "[INFO] User Bob logged in",
        "[WARN] User Alice timed out",
      ],
    });

    renderConsole();
    await screen.findByText(/Alice logged in/);

    const searchInput = screen.getByTestId("console-search-input");
    await user.type(searchInput, "alice");

    expect(screen.getByTestId("console-search-matches")).toHaveTextContent("2 matches");
    expect(screen.getByText(/Alice logged in/)).toBeInTheDocument();
    expect(screen.getByText(/Alice timed out/)).toBeInTheDocument();
    expect(screen.queryByText(/Bob logged in/)).not.toBeInTheDocument();

    // Clear search
    const clearSearchBtn = screen.getByRole("button", { name: "Clear search" });
    await user.click(clearSearchBtn);

    expect(screen.getByText(/Bob logged in/)).toBeInTheDocument();
  });

  it("toggles follow log auto-scroll button", async () => {
    const user = userEvent.setup();
    renderConsole();

    const followBtn = screen.getByTestId("follow-log-toggle");
    expect(followBtn).toHaveTextContent("Follow Log");
    expect(followBtn).toHaveAttribute("title", "Auto-scrolling enabled");

    await user.click(followBtn);
    expect(followBtn).toHaveAttribute("title", "Auto-scrolling paused");

    await user.click(followBtn);
    expect(followBtn).toHaveAttribute("title", "Auto-scrolling enabled");
  });

  it("displays crash alert banner and opens crash report modal when crash reports exist", async () => {
    const user = userEvent.setup();
    const sampleCrash: CrashReportSummary = {
      filename: "crash-2026-09-14-server.txt",
      timestamp: "2026-09-14T01:00:00Z",
      failure_code: "MOD_CRASH",
      blamed_mod: "create",
      stack_trace_snippet: "net.minecraftforge.fml.ModLoadingException: Failed to load mod create",
      suggested_remediation: "Check or disable conflicting mod: create",
      raw_content: "Crash details for create mod\n-- System Details --",
    };

    mockGetServerCrashReports.mockResolvedValue([sampleCrash]);

    renderConsole();

    const banner = await screen.findByTestId("crash-alert-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent("Crash Detected:");
    expect(banner).toHaveTextContent("MOD_CRASH");
    expect(screen.getByTestId("crash-banner-blamed-mod")).toHaveTextContent("Blamed: create");

    // Click "View Crash Report" in banner
    const viewBtn = screen.getByTestId("crash-banner-view-btn");
    await user.click(viewBtn);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Crash Report Inspector")).toBeInTheDocument();
    expect(screen.getByTestId("blamed-mod-callout")).toHaveTextContent("create");

    // Close modal
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("appends live console lines received via WebSocket stream", async () => {
    renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);

    act(() => {
      notifyConsoleListeners("srv-live", ["[INFO] Player Steve joined the game"]);
    });

    expect(await screen.findByText("[INFO] Player Steve joined the game")).toBeInTheDocument();
  });

  it("disables 3s polling query when WS connection is active", async () => {
    useWSStore.setState({
      connected: true,
      connectionState: ConnectionState.CONNECTED,
    });
    renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);

    // Initial fetch was done
    expect(mockGetServerConsole).toHaveBeenCalledTimes(1);
    expect(useWSStore.getState().connected).toBe(true);
  });

  it("triggers reconnect re-tail flow and resets live lines on WS reconnection", async () => {
    useWSStore.setState({
      connected: false,
      connectionState: ConnectionState.RECONNECTING,
    });

    renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);

    // Add a live line while reconnecting
    act(() => {
      notifyConsoleListeners("srv-live", ["[INFO] Transient live message"]);
    });
    expect(await screen.findByText("[INFO] Transient live message")).toBeInTheDocument();

    // Reconnection occurs: RECONNECTING -> CONNECTED
    mockGetServerConsole.mockResolvedValueOnce({
      lines: ["[Server thread/INFO]: Refetched re-tail line 1"],
    });

    act(() => {
      useWSStore.getState().setConnectionState(ConnectionState.CONNECTED);
    });

    // Re-tail refetch should be triggered and transient live lines cleared
    expect(await screen.findByText(/Refetched re-tail line 1/)).toBeInTheDocument();
    expect(screen.queryByText("[INFO] Transient live message")).not.toBeInTheDocument();
  });

  it("refetches history and displays missed lines when visibility changes from hidden to visible, and cleans up listener", async () => {
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      writable: true,
      configurable: true,
    });

    const removeEventListenerSpy = vi.spyOn(document, "removeEventListener");

    const { unmount } = renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);
    expect(mockGetServerConsole).toHaveBeenCalledTimes(1);

    mockGetServerConsole.mockResolvedValueOnce({
      lines: [
        "[Server thread/INFO]: Done (2.4s)! For help, type 'help'",
        "[Server thread/INFO]: Player joined while tab was in background",
      ],
    });

    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      writable: true,
      configurable: true,
    });

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(await screen.findByText(/Player joined while tab was in background/)).toBeInTheDocument();
    expect(mockGetServerConsole).toHaveBeenCalledTimes(2);

    unmount();
    expect(removeEventListenerSpy).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
    removeEventListenerSpy.mockRestore();
  });
});
