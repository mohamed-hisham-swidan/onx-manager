import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServerConsole } from "./ServerConsole";
import { notifyConsoleListeners } from "@/hooks/useWebSocket";
import { useWSStore } from "@/stores/wsStore";
import { ChannelStatus, ConnectionState } from "@/websocket/types";
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
    serverName?: string;
    serverStatus?: string;
    tps?: number | null;
    players?: number;
    provider?: string | null;
    host?: string | null;
    port?: number | null;
    compactHeader?: boolean;
    canConsole?: boolean;
    uptimeSeconds?: number | null;
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
        serverName={props.serverName}
        serverStatus={props.serverStatus ?? "running"}
        tps={props.tps}
        players={props.players}
        provider={props.provider}
        host={props.host}
        port={props.port}
        compactHeader={props.compactHeader}
        canConsole={props.canConsole}
        uptimeSeconds={props.uptimeSeconds}
      />
    </QueryClientProvider>,
  );
}

async function findConsoleLine(expectedText: string) {
  return screen.findByText(
    (_content, element) =>
      element?.hasAttribute("data-log-level") === true &&
      element.textContent === expectedText,
  );
}

function queryConsoleLine(expectedText: string) {
  return screen.queryByText(
    (_content, element) =>
      element?.hasAttribute("data-log-level") === true &&
      element.textContent === expectedText,
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
    renderConsole({ serverStatus: "running", port: 25565, players: 4 });
    expect(screen.getByText("Server Console")).toBeInTheDocument();
    expect(await screen.findByText(/Done \(2\.4s\)!/)).toBeInTheDocument();

    const capsule = screen.getByTestId("console-status-capsule");
    expect(capsule).toBeInTheDocument();
    expect(capsule).toHaveTextContent("ONLINE · PORT 25565");

    const playerCapsule = screen.getByTestId("console-player-counter-capsule");
    expect(playerCapsule).toBeInTheDocument();
    expect(playerCapsule).toHaveTextContent("4 / 20 Players");
  });

  it("renders prominent offline status capsule in console header when stopped", async () => {
    renderConsole({ serverStatus: "stopped" });
    const capsule = screen.getByTestId("console-status-capsule");
    expect(capsule).toBeInTheDocument();
    expect(capsule).toHaveTextContent("OFFLINE · CONTAINER HALTED");
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

  it("sends command, appends to console, and supports ArrowUp/ArrowDown history", async () => {
    const user = userEvent.setup();
    renderConsole();

    const input = screen.getByTestId("console-command-input");
    const sendBtn = screen.getByTestId("console-send-btn");

    await user.type(input, "tps");
    await user.click(sendBtn);

    expect(mockSendServerCommand).toHaveBeenCalledWith("srv-1", { command: "tps" });
    expect(await findConsoleLine("> tps")).toBeInTheDocument();

    await user.type(input, "list");
    await user.click(sendBtn);
    expect(await findConsoleLine("> list")).toBeInTheDocument();

    // Navigate command history with ArrowUp / ArrowDown preserving unsent draft
    await user.type(input, "draft");
    await user.keyboard("{ArrowUp}");
    expect(input).toHaveValue("list");
    await user.keyboard("{ArrowUp}");
    expect(input).toHaveValue("tps");
    await user.keyboard("{ArrowDown}");
    expect(input).toHaveValue("list");
    await user.keyboard("{ArrowDown}");
    expect(input).toHaveValue("draft");
  });

  it("disables command bar when server is offline or lacking console permission", () => {
    const { rerender } = renderConsole({ serverStatus: "stopped" });
    expect(screen.getByTestId("console-command-input")).toBeDisabled();
    expect(screen.getByTestId("quick-cmd-list")).toBeDisabled();

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ServerConsole serverId="srv-1" serverStatus="running" canConsole={false} />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("console-command-input")).toBeDisabled();
  });

  it("supports quick command chips", async () => {
    const user = userEvent.setup();
    renderConsole();

    await user.click(screen.getByTestId("quick-cmd-list"));
    expect(mockSendServerCommand).toHaveBeenCalledWith("srv-1", { command: "list" });

    await user.click(screen.getByTestId("quick-cmd-say"));
    expect(screen.getByTestId("console-command-input")).toHaveValue("say ");
  });

  it("renders command RCON output lines below the echoed command and strips Minecraft § formatting", async () => {
    mockSendServerCommand.mockResolvedValueOnce({
      success: true,
      output: "§aPlugins (2): §fVeinMiner, TAB\n§6TPS from last 1m: 20.0",
    });
    const user = userEvent.setup();
    renderConsole();

    const input = screen.getByTestId("console-command-input");
    await user.type(input, "plugins");
    await user.click(screen.getByTestId("console-send-btn"));

    expect(await findConsoleLine("> plugins")).toBeInTheDocument();
    expect(await screen.findByText("Plugins (2): VeinMiner, TAB")).toBeInTheDocument();
    expect(await screen.findByText("TPS from last 1m: 20.0")).toBeInTheDocument();
  });

  it("renders [ERROR] line in console when command execution fails", async () => {
    mockSendServerCommand.mockRejectedValueOnce(new Error("RCON connection refused"));
    const user = userEvent.setup();
    renderConsole();

    const input = screen.getByTestId("console-command-input");
    await user.type(input, "list");
    await user.click(screen.getByTestId("console-send-btn"));

    expect(await findConsoleLine("> list")).toBeInTheDocument();
    expect(await findConsoleLine("[ERROR] RCON connection refused")).toBeInTheDocument();
  });

  it("clears both HTTP history and local command output on Clear button click", async () => {
    const user = userEvent.setup();
    renderConsole();

    expect(await screen.findByText(/Done \(2\.4s\)!/)).toBeInTheDocument();

    const input = screen.getByTestId("console-command-input");
    await user.type(input, "list");
    await user.click(screen.getByTestId("console-send-btn"));
    expect(await findConsoleLine("> list")).toBeInTheDocument();

    await user.click(screen.getByTestId("console-clear-btn"));

    expect(queryConsoleLine("> list")).not.toBeInTheDocument();
    expect(screen.queryByText(/Done \(2\.4s\)!/)).not.toBeInTheDocument();
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

  it("displays dynamic address badge when host and port are provided", () => {
    renderConsole({ provider: "local", host: "192.168.1.253", port: 25565 });
    const badge = screen.getByTestId("console-ip-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("192.168.1.253:25565");
  });

  it("does not display IP badge when host is not provided", () => {
    renderConsole({ provider: "docker", host: null });
    expect(screen.queryByTestId("console-ip-badge")).not.toBeInTheDocument();
  });

  it("renders structured token colors (muted timestamp, colored level tag, violet [sourceTag], neutral INFO body, milestone green) and strips Docker nanosecond prefixes by default", async () => {
    const user = userEvent.setup();
    mockGetServerConsole.mockResolvedValue({
      lines: [
        "2026-11-24T09:51:16.206710177Z [09:51:16 INFO]: [Veinminer] Starting plugin setup",
        '[09:51:16 INFO]: Done (2.412s)! For help, type "help"',
        "[09:51:17 WARN]: Can't keep up! Is the server overloaded?",
        "[09:51:18 ERROR]: Encountered an unexpected exception",
        "Plain text log without level",
      ],
    });

    renderConsole();

    const infoLine = await findConsoleLine("[09:51:16 INFO]: [Veinminer] Starting plugin setup");
    expect(infoLine).toHaveAttribute("data-log-level", "info");

    const tsSpan = infoLine.querySelector('[data-log-token="timestamp"]');
    const levelSpan = infoLine.querySelector('[data-log-token="level"]');
    const sourceSpan = infoLine.querySelector('[data-log-token="source"]');
    const msgSpan = infoLine.querySelector('[data-log-token="message"]');
    expect(tsSpan).toHaveClass("text-terminal-timestamp");
    expect(levelSpan).toHaveClass("text-terminal-info");
    expect(levelSpan).toHaveTextContent("INFO");
    expect(sourceSpan).toHaveClass("text-terminal-source");
    expect(sourceSpan).toHaveTextContent("[Veinminer]");
    expect(msgSpan).toHaveClass("text-terminal-text");
    expect(msgSpan).not.toHaveClass("text-terminal-info");

    const milestoneMsg = screen.getByText('Done (2.412s)! For help, type "help"');
    expect(milestoneMsg).toHaveClass("text-terminal-success");

    const warnLine = screen.getByText(/Can't keep up!/);
    expect(warnLine).toHaveClass("text-terminal-warn");

    const errorLine = screen.getByText(/Encountered an unexpected exception/);
    expect(errorLine).toHaveClass("text-terminal-error");

    const plainLine = screen.getByText("Plain text log without level");
    expect(plainLine).toHaveClass("text-terminal-text");

    // Toggle ISO timestamps on
    await user.click(screen.getByTestId("console-iso-toggle"));
    expect(
      await findConsoleLine(
        "2026-11-24T09:51:16.206710177Z [09:51:16 INFO]: [Veinminer] Starting plugin setup",
      ),
    ).toBeInTheDocument();

    // Filter by Error level
    await user.click(screen.getByTestId("console-filter-error"));
    expect(screen.getByText(/Encountered an unexpected exception/)).toBeInTheDocument();
    expect(screen.queryByText(/Can't keep up!/)).not.toBeInTheDocument();
  });

  it("filters logs, highlights search matches, and displays match count", async () => {
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
    expect(screen.getAllByText("Alice")).toHaveLength(2);
    expect(screen.queryByText(/Bob logged in/)).not.toBeInTheDocument();

    // Clear search
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByText(/Bob logged in/)).toBeInTheDocument();
  });

  it("toggles follow log auto-scroll button and pauses on scroll up with Jump to latest button", async () => {
    const user = userEvent.setup();
    renderConsole();
    await screen.findByText(/Done \(2\.4s\)!/);

    const followBtn = screen.getByTestId("follow-log-toggle");
    expect(followBtn).toHaveTextContent("Follow Log");
    expect(followBtn).toHaveAttribute("title", "Auto-scrolling enabled");

    const viewport = screen.getByTestId("console-output-viewport");
    Object.defineProperty(viewport, "scrollHeight", { value: 1000, configurable: true });
    Object.defineProperty(viewport, "clientHeight", { value: 400, configurable: true });
    Object.defineProperty(viewport, "scrollTop", { value: 200, writable: true, configurable: true });

    fireEvent.scroll(viewport);
    expect(followBtn).toHaveAttribute("title", "Auto-scrolling paused");

    const jumpBtn = screen.getByTestId("console-jump-latest-btn");
    expect(jumpBtn).toBeInTheDocument();
    await user.click(jumpBtn);
    expect(followBtn).toHaveAttribute("title", "Auto-scrolling enabled");
  });

  it("displays crash alert banner when server is crashed and opens crash report modal with server name", async () => {
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

    renderConsole({ serverStatus: "crashed", serverName: "Survival SMP" });

    const banner = await screen.findByTestId("crash-alert-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent("Crash Detected:");
    expect(banner).toHaveTextContent("MOD_CRASH");
    expect(screen.getByTestId("crash-banner-blamed-mod")).toHaveTextContent("Blamed: create");

    await user.click(screen.getByTestId("crash-banner-view-btn"));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Crash Report Inspector")).toBeInTheDocument();
    expect(screen.getByText(/Survival SMP/)).toBeInTheDocument();
    expect(screen.getByTestId("blamed-mod-callout")).toHaveTextContent("create");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("suppresses loud crash alert banner for historical crashes on a healthy running server while keeping toolbar button", async () => {
    const oldCrash: CrashReportSummary = {
      filename: "crash-2025-01-01-server.txt",
      timestamp: "2025-01-01T01:00:00Z",
      failure_code: "MOD_CRASH",
      blamed_mod: "oldmod",
      stack_trace_snippet: "",
      suggested_remediation: "Remove oldmod",
      raw_content: "old crash",
    };
    mockGetServerCrashReports.mockResolvedValue([oldCrash]);

    renderConsole({ serverStatus: "running", uptimeSeconds: 3600 });

    const toolbarCrashBtn = await screen.findByTestId("view-crash-reports-btn");
    expect(toolbarCrashBtn).toHaveTextContent("Crash (1)");
    expect(screen.queryByTestId("crash-alert-banner")).not.toBeInTheDocument();
  });

  it("appends live console lines received via WebSocket stream", async () => {
    renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);

    act(() => {
      notifyConsoleListeners("srv-live", ["[INFO] Player Steve joined the game"]);
    });

    expect(await findConsoleLine("[INFO] Player Steve joined the game")).toBeInTheDocument();
  });

  it("disables 3s polling query when WS connection is active", async () => {
    useWSStore.setState({
      connected: true,
      connectionState: ConnectionState.CONNECTED,
    });
    renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);

    expect(mockGetServerConsole).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("console-stream-status")).toHaveTextContent("Live");
  });

  it("merges re-tailed lines on WS reconnection without wiping existing live lines", async () => {
    useWSStore.setState({
      connected: false,
      connectionState: ConnectionState.RECONNECTING,
    });

    renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);

    act(() => {
      notifyConsoleListeners("srv-live", ["[INFO] Transient live message"]);
    });
    expect(await findConsoleLine("[INFO] Transient live message")).toBeInTheDocument();

    mockGetServerConsole.mockResolvedValueOnce({
      lines: [
        "[INFO] Transient live message",
        "[Server thread/INFO]: Refetched re-tail line 1",
      ],
    });

    act(() => {
      useWSStore.getState().setConnectionState(ConnectionState.CONNECTED);
    });

    expect(await screen.findByText(/Refetched re-tail line 1/)).toBeInTheDocument();
    expect(await findConsoleLine("[INFO] Transient live message")).toBeInTheDocument();
  });

  it("refetches history and merges missed lines when visibility changes from hidden to visible, and cleans up listener", async () => {
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

    expect(
      await screen.findByText(/Player joined while tab was in background/),
    ).toBeInTheDocument();
    expect(mockGetServerConsole).toHaveBeenCalledTimes(2);

    unmount();
    expect(removeEventListenerSpy).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
    removeEventListenerSpy.mockRestore();
  });

  it("does not mount duplicate terminal containers when navigating away and back", async () => {
    const { unmount } = renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);

    expect(screen.getAllByTestId("console-command-input")).toHaveLength(1);
    expect(screen.getAllByTestId("console-search-input")).toHaveLength(1);

    unmount();
    expect(screen.queryByTestId("console-command-input")).not.toBeInTheDocument();

    renderConsole({ serverId: "srv-live" });
    await screen.findByText(/Done \(2\.4s\)!/);

    expect(screen.getAllByTestId("console-command-input")).toHaveLength(1);
    expect(screen.getAllByTestId("console-search-input")).toHaveLength(1);
  });

  it("places viewport-balanced clamp height on outer console container so log viewport stretches with flex-1 min-h-0", async () => {
    renderConsole({ serverId: "srv-viewport" });
    await screen.findByText(/Done \(2\.4s\)!/);

    const outerContainer = screen.getByTestId("server-console-container");
    expect(outerContainer.className).toContain("h-[460px]");
    expect(outerContainer.className).toContain("lg:h-[clamp(400px,calc(100dvh-14.5rem),640px)]");

    const logContainer = screen.getByTestId("console-output-viewport");
    expect(logContainer).toBeInTheDocument();
    expect(logContainer.className).toContain("flex-1");
    expect(logContainer.className).toContain("min-h-0");
    expect(logContainer.className).toContain("overflow-y-auto");
    expect(logContainer.className).not.toContain("calc(100dvh-33rem)");
  });

  it("clears stale crash lines immediately when server status transitions from crashed to starting", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    mockGetServerConsole.mockResolvedValueOnce({
      lines: ["[ERROR] docker start failed: port is already allocated"],
    });

    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <ServerConsole serverId="srv-transition" serverStatus="crashed" />
      </QueryClientProvider>,
    );

    expect(
      await findConsoleLine("[ERROR] docker start failed: port is already allocated"),
    ).toBeInTheDocument();

    mockGetServerConsole.mockResolvedValueOnce({
      lines: ["[12:00:01 INFO]: Starting minecraft server version 1.21.11"],
    });

    rerender(
      <QueryClientProvider client={queryClient}>
        <ServerConsole serverId="srv-transition" serverStatus="starting" />
      </QueryClientProvider>,
    );

    expect(
      await findConsoleLine("[12:00:01 INFO]: Starting minecraft server version 1.21.11"),
    ).toBeInTheDocument();
    expect(
      queryConsoleLine("[ERROR] docker start failed: port is already allocated"),
    ).not.toBeInTheDocument();
  });

  it("hides duplicated status, player, provider, and IP capsules when compactHeader is enabled", async () => {
    renderConsole({
      serverStatus: "stopped",
      provider: "docker",
      host: "127.0.0.1",
      port: 25565,
      compactHeader: true,
    });
    expect(screen.getByText("Server Console")).toBeInTheDocument();
    expect(screen.getByTestId("console-tps-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("console-status-capsule")).not.toBeInTheDocument();
    expect(screen.queryByTestId("console-player-counter-capsule")).not.toBeInTheDocument();
    expect(screen.queryByTestId("console-provider-badge")).not.toBeInTheDocument();
    expect(screen.queryByTestId("console-ip-badge")).not.toBeInTheDocument();
  });

  it("activates 3s HTTP fallback polling when WS is connected but console channel is degraded", async () => {
    vi.useFakeTimers();
    try {
      useWSStore.setState({
        connected: true,
        connectionState: ConnectionState.CONNECTED,
        channelStates: {
          "server:srv-degraded:console": {
            channel: "server:srv-degraded:console",
            status: ChannelStatus.RETRYING,
            authorized: true,
            retryCount: 1,
          },
        },
      });
      renderConsole({ serverId: "srv-degraded" });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(100);
      });
      expect(mockGetServerConsole).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3100);
      });
      expect(mockGetServerConsole).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("preserves Clear Console across tab visibility switch and WS reconnect while showing only post-clear lines", async () => {
    mockGetServerConsole.mockResolvedValue({
      lines: [
        "[Server thread/INFO]: Line before clear 1",
        "[Server thread/INFO]: Line before clear 2",
      ],
    });
    useWSStore.setState({
      connected: false,
      connectionState: ConnectionState.RECONNECTING,
    });

    const user = userEvent.setup();
    renderConsole({ serverId: "srv-clear-persist" });

    expect(await findConsoleLine("[Server thread/INFO]: Line before clear 1")).toBeInTheDocument();
    expect(await findConsoleLine("[Server thread/INFO]: Line before clear 2")).toBeInTheDocument();

    await user.click(screen.getByTestId("console-clear-btn"));
    expect(queryConsoleLine("[Server thread/INFO]: Line before clear 1")).not.toBeInTheDocument();

    // Tab visibility switch triggers syncMissedTail returning the same lines -> must stay cleared
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(queryConsoleLine("[Server thread/INFO]: Line before clear 1")).not.toBeInTheDocument();

    // WS reconnect triggers syncMissedTail with a new post-clear line -> old lines stay cleared, new line renders
    mockGetServerConsole.mockResolvedValueOnce({
      lines: [
        "[Server thread/INFO]: Line before clear 1",
        "[Server thread/INFO]: Line before clear 2",
        "[Server thread/INFO]: New line after clear",
      ],
    });
    await act(async () => {
      useWSStore.getState().setConnectionState(ConnectionState.CONNECTED);
    });

    expect(await findConsoleLine("[Server thread/INFO]: New line after clear")).toBeInTheDocument();
    expect(queryConsoleLine("[Server thread/INFO]: Line before clear 1")).not.toBeInTheDocument();
    expect(queryConsoleLine("[Server thread/INFO]: Line before clear 2")).not.toBeInTheDocument();
  });
});
