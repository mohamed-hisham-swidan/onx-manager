import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ServersPage } from "./ServersPage";
import { SERVERS_VIEW_MODE_STORAGE_KEY } from "@/server_manager/components/servers/serversUtils";
import { queryKeys } from "@/services/queryClient";
import { useToastStore } from "@/stores/toastStore";
import type { ServerResponse } from "@/server_manager/types";
import type { HostResourceBudget } from "@/types";

const mockServers: ServerResponse[] = [
  {
    server_id: "srv-1",
    name: "Alpha World",
    server_type: "vanilla",
    minecraft_version: "1.21.4",
    status: "running",
    group_id: "default",
    port: 25565,
    motd: "§aWelcome to §lAlpha",
    max_players: 20,
    gamemode: "survival",
    difficulty: "easy",
    mode: "simple",
    max_memory_mb: 4096,
    uptime_seconds: 3720,
    deployment_host: "play.example.local",
    public_address: "alpha.playit.gg:25565",
    icon_data_url: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
  },
  {
    server_id: "srv-2",
    name: "Beta Plot",
    server_type: "paper",
    minecraft_version: "1.21",
    status: "stopped",
    group_id: "default",
    port: 25566,
    motd: "Creative Build",
    max_players: 10,
    gamemode: "creative",
    difficulty: "peaceful",
    mode: "advanced",
    active_branch: "staging",
    max_memory_mb: 2048,
    deployment_host: "192.168.1.50",
    icon_data_url: "data:image/png;base64,iVBORw0KGgo=",
    created_at: "2026-11-02T00:00:00Z",
    updated_at: "2026-11-02T00:00:00Z",
  },
  {
    server_id: "srv-3",
    name: "Crash Test",
    server_type: "forge",
    minecraft_version: "1.20.4",
    status: "crashed",
    group_id: "default",
    port: 25567,
    motd: "",
    max_players: 20,
    gamemode: "survival",
    difficulty: "normal",
    mode: "simple",
    max_memory_mb: 2048,
    icon_data_url: null,
    created_at: "2026-11-03T00:00:00Z",
    updated_at: "2026-11-03T00:00:00Z",
  },
];

const mockHostBudget: HostResourceBudget = {
  total_ram_mb: 16384,
  os_reserve_ram_mb: 4096,
  allocatable_ram_mb: 12288,
  allocated_ram_mb: 4096,
  available_ram_mb: 8192,
  total_cpus: 8,
  reserved_cpus: 2,
  allocatable_cpus: 6,
  allocated_cpus: 2,
  available_cpus: 4,
  profile: "local",
  ram_reserve_override_mb: 0,
  cpu_reserve_override: 0,
  allocations: [
    {
      id: "srv-1",
      name: "Alpha World",
      kind: "server",
      status: "running",
      ram_mb: 4096,
      cpu_cores: 2,
    },
  ],
};

const mockGetMe = vi.fn();
const mockGetMetrics = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getMe: () => mockGetMe(),
    getMetrics: (...args: unknown[]) => mockGetMetrics(...args),
    getHostResources: vi.fn().mockResolvedValue(mockHostBudget),
    downloadServerFile: vi.fn(),
  }),
}));

vi.mock("@/server_manager/hooks/useHostResources", () => ({
  useHostResources: vi.fn(),
}));

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
  useDeleteServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useStopServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestartServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRetryProvisioningServer: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

import { useHostResources } from "@/server_manager/hooks/useHostResources";
import {
  useServersList,
  useStartServer,
  useStopServer,
  useRetryProvisioningServer,
} from "@/server_manager/hooks/useServers";

function createQueryClient(seedMetrics = true, seedAdmin = true) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (seedAdmin) {
    qc.setQueryData(queryKeys.auth.me, {
      user_id: "u1",
      username: "admin",
      email: null,
      display_name: "Admin",
      is_active: true,
      roles: ["owner"],
      permissions: ["admin:full"],
      created_at: "",
      last_login_at: null,
    });
  }
  if (seedMetrics) {
    qc.setQueryData(queryKeys.monitoring.metrics("srv-1"), [
      {
        tps: 19.8,
        players: 7,
        ram_used_mb: 2048,
        cpu_percent: 34.5,
        timestamp: "2026-11-24T09:00:00Z",
      },
    ]);
  }
  return qc;
}

function renderPage(initialEntry = "/servers", qc = createQueryClient()) {
  return {
    qc,
    ...render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <ServersPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

describe("ServersPage", () => {
  beforeEach(() => {
    window.localStorage.removeItem(SERVERS_VIEW_MODE_STORAGE_KEY);
    useToastStore.setState({ toasts: [] });
    mockGetMe.mockResolvedValue({
      user_id: "u1",
      username: "admin",
      email: null,
      display_name: "Admin",
      is_active: true,
      roles: ["owner"],
      permissions: ["admin:full"],
      created_at: "",
      last_login_at: null,
    });
    mockGetMetrics.mockResolvedValue([
      {
        tps: 19.8,
        players: 7,
        ram_used_mb: 2048,
        cpu_percent: 34.5,
        timestamp: "2026-11-24T09:00:00Z",
      },
    ]);
    vi.mocked(useHostResources).mockReturnValue({
      data: mockHostBudget,
    } as unknown as ReturnType<typeof useHostResources>);
    vi.mocked(useServersList).mockReturnValue({
      data: mockServers,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useServersList>);
    vi.mocked(useStartServer).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useStartServer>);
    vi.mocked(useStopServer).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useStopServer>);
    vi.mocked(useRetryProvisioningServer).mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useRetryProvisioningServer>);
  });

  it("renders header with count pill, action buttons, and FleetOverviewStrip live totals", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Servers" })).toBeInTheDocument();
    expect(screen.getByTestId("servers-count-pill")).toHaveTextContent("3");
    expect(screen.getByText("New Server")).toBeInTheDocument();
    expect(screen.getByText("Import")).toBeInTheDocument();

    const strip = screen.getByTestId("fleet-overview-strip");
    expect(strip).toHaveTextContent("Instances Online");
    expect(strip).toHaveTextContent(/1\s*\/\s*3/);
    expect(strip).toHaveTextContent("Active Players");
    expect(strip).toHaveTextContent(/7\s*\/\s*20/);
    expect(strip).toHaveTextContent("4 GB");
    expect(strip).toHaveTextContent("12 GB");
    expect(strip).toHaveTextContent(/2\s*\/\s*6 cores/);
  });

  it("defaults directly to Cards (grid) view with zero initial List flash", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "Grid card view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("server-card-srv-1")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("initializes directly in List view when localStorage prefers list", () => {
    window.localStorage.setItem(SERVERS_VIEW_MODE_STORAGE_KEY, "list");
    renderPage();
    expect(screen.getByRole("button", { name: "Compact list view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByTestId("server-card-srv-1")).not.toBeInTheDocument();
  });

  it("renders real icon_data_url and loader fallback emblem, cleaned MOTD, mode, branch, Gamemode label, and live telemetry", () => {
    renderPage();

    const card1 = screen.getByTestId("server-card-srv-1");
    expect(card1).toHaveTextContent("Alpha World");
    expect(card1).toHaveTextContent("Welcome to Alpha"); // stripped §a / §l
    expect(card1).toHaveTextContent("Simple");
    expect(card1).toHaveTextContent("7 / 20");
    expect(card1).toHaveTextContent("19.8");
    expect(card1).toHaveTextContent("34.5%");
    expect(card1).toHaveTextContent("2 GB / 4 GB");
    expect(card1.querySelector('[data-testid="server-card-uptime"]')).toHaveTextContent("Up 1h 2m");
    // Neutral loader emblem without monogram letters
    const fallbackIcon = card1.querySelector('[data-testid="server-icon-default"]');
    expect(fallbackIcon).toHaveAttribute("data-loader-icon", "vanilla");
    expect(fallbackIcon).toHaveTextContent("");

    const card2 = screen.getByTestId("server-card-srv-2");
    expect(card2).toHaveTextContent("Advanced");
    expect(card2).toHaveTextContent("staging");
    expect(card2).toHaveTextContent("Gamemode");
    expect(card2).not.toHaveTextContent(/^Mode$/);
    const img = card2.querySelector('[data-testid="server-icon-img"]');
    expect(img).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
  });

  it("copies full join address (public_address or host:port) and shows toast", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    renderPage();

    await user.click(screen.getByLabelText("Copy join address alpha.playit.gg:25565"));
    expect(writeText).toHaveBeenCalledWith("alpha.playit.gg:25565");
    expect(useToastStore.getState().toasts.some((t) => t.message?.includes("alpha.playit.gg:25565"))).toBe(true);

    await user.click(screen.getByLabelText("Copy join address 192.168.1.50:25566"));
    expect(writeText).toHaveBeenCalledWith("192.168.1.50:25566");
  });

  it("renders full parity columns in List view including icons, join addresses, telemetry, and console links", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Compact list view" }));
    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    expect(table).toHaveTextContent("alpha.playit.gg:25565");
    expect(table).toHaveTextContent("7/20 players");
    expect(table).toHaveTextContent("19.8 TPS");
    expect(table).toHaveTextContent("RAM 2 GB / 4 GB");
    expect(table).toHaveTextContent("CPU 34.5%");
    expect(screen.getByLabelText("Open Console Alpha World")).toBeInTheDocument();
    expect(screen.getAllByTestId("server-icon").length).toBe(3);
  });

  it("locks power actions per server via busyServerIds without disabling unrelated servers", async () => {
    // Keep srv-2 Start mutation pending (never invokes onSettled)
    const pendingMutate = vi.fn();
    vi.mocked(useStartServer).mockReturnValue({
      mutate: pendingMutate,
      isPending: true,
    } as unknown as ReturnType<typeof useStartServer>);

    const user = userEvent.setup();
    renderPage();

    const startBeta = screen.getByLabelText("Start Beta Plot");
    const startCrash = screen.getByLabelText("Start Crash Test");
    expect(startBeta).not.toBeDisabled();
    expect(startCrash).not.toBeDisabled();

    await user.click(startBeta);

    expect(startBeta).toBeDisabled();
    expect(startCrash).not.toBeDisabled();
  });

  it("fixes provisioning_retryable polarity and displays provisioning_error in both Cards and List views", async () => {
    const retryMutate = vi.fn();
    vi.mocked(useRetryProvisioningServer).mockReturnValue({
      mutate: retryMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useRetryProvisioningServer>);

    vi.mocked(useServersList).mockReturnValue({
      data: [
        {
          ...mockServers[1],
          server_id: "srv-retryable",
          name: "Retryable Failed",
          status: "provisioning_failed",
          provisioning_error: "Forge mirror timeout",
          provisioning_retryable: true,
        },
        {
          ...mockServers[1],
          server_id: "srv-nonretryable",
          name: "Permanent Failed",
          status: "provisioning_failed",
          provisioning_error: "Corrupt manifest",
          provisioning_retryable: false,
        },
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useServersList>);

    const user = userEvent.setup();
    renderPage();

    // Cards view
    expect(screen.getByText("Forge mirror timeout")).toBeInTheDocument();
    expect(screen.getByText("Corrupt manifest")).toBeInTheDocument();
    expect(screen.getByLabelText("Retry Provisioning Retryable Failed")).toBeInTheDocument();
    expect(screen.queryByLabelText("Retry Provisioning Permanent Failed")).not.toBeInTheDocument();

    // Switch to List view and verify parity
    await user.click(screen.getByRole("button", { name: "Compact list view" }));
    expect(screen.getByLabelText("Retry Provisioning Retryable Failed")).toBeInTheDocument();
    expect(screen.queryByLabelText("Retry Provisioning Permanent Failed")).not.toBeInTheDocument();
  });

  it("renders matching CardSkeleton in grid mode and TableSkeleton in list mode", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useServersList>);

    const { unmount } = renderPage();
    expect(screen.getByTestId("cards-skeleton")).toBeInTheDocument();
    unmount();

    window.localStorage.setItem(SERVERS_VIEW_MODE_STORAGE_KEY, "list");
    renderPage();
    expect(screen.queryByTestId("cards-skeleton")).not.toBeInTheDocument();
    expect(document.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("passes onRetry to ErrorState and invokes refetch on click", async () => {
    const refetch = vi.fn().mockResolvedValue({});
    vi.mocked(useServersList).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("API error"),
      refetch,
    } as unknown as ReturnType<typeof useServersList>);

    const user = userEvent.setup();
    renderPage();

    expect(screen.getByText("API error")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders both Create Server and Import Existing Server in 0-server EmptyState", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    expect(screen.getByText("No servers yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create Server" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import Existing Server" })).toBeInTheDocument();
  });

  it("renders quick-deploy card when exactly 1 server exists and uses 2-column grid", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: [mockServers[0]],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    expect(screen.getByTestId("quick-deploy-card")).toBeInTheDocument();
    expect(screen.getByText("Deploy Another Instance")).toBeInTheDocument();
    const grid = screen.getByTestId("servers-cards-grid");
    expect(grid.className).toContain("md:grid-cols-2");
    expect(grid.className).not.toContain("xl:grid-cols-3");
  });

  it("adapts cards grid dynamically between 2-column (<= 2 cards) and 3-column (>= 3 cards)", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: [mockServers[0], mockServers[1]],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useServersList>);

    const { unmount } = renderPage();
    const twoCardGrid = screen.getByTestId("servers-cards-grid");
    expect(twoCardGrid.className).toContain("md:grid-cols-2");
    expect(twoCardGrid.className).not.toContain("xl:grid-cols-3");
    unmount();

    vi.mocked(useServersList).mockReturnValue({
      data: mockServers,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    const threeCardGrid = screen.getByTestId("servers-cards-grid");
    expect(threeCardGrid.className).toContain("md:grid-cols-2");
    expect(threeCardGrid.className).toContain("xl:grid-cols-3");
  });

  it("filters by search, status, loader, mode, sort, and resets via Clear filters", async () => {
    const user = userEvent.setup();
    renderPage("/servers?status=stopped");

    expect(screen.getByText("Beta Plot")).toBeInTheDocument();
    expect(screen.queryByText("Alpha World")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(screen.getByText("Alpha World")).toBeInTheDocument();
    expect(screen.getByText("Beta Plot")).toBeInTheDocument();

    const search = screen.getByLabelText("Search servers");
    fireEvent.change(search, { target: { value: "zzz-not-found" } });
    expect(screen.getByText("No matching servers")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /clear filters/i }).length).toBeGreaterThanOrEqual(1);
  });

  it("locks Stop ConfirmDialog when stopServer.isPending is true", async () => {
    vi.mocked(useStopServer).mockReturnValue({
      mutate: vi.fn(),
      isPending: true,
    } as unknown as ReturnType<typeof useStopServer>);

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText("Stop Alpha World"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Stopping..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("hides New Server, Import, Delete, and power buttons for viewer-only users", async () => {
    mockGetMe.mockResolvedValue({
      user_id: "u-viewer",
      username: "viewer",
      email: null,
      display_name: "Viewer",
      is_active: true,
      roles: ["viewer"],
      permissions: ["server:read"],
      created_at: "",
      last_login_at: null,
    });

    renderPage("/servers", createQueryClient(true, false));

    // Wait for getMe query resolution
    await vi.waitFor(() => {
      expect(screen.queryByText("New Server")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Import")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Delete Alpha World")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Start Beta Plot")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Stop Alpha World")).not.toBeInTheDocument();
  });

  it("does not offer Start button for restoring servers", () => {
    vi.mocked(useServersList).mockReturnValue({
      data: [
        {
          ...mockServers[0],
          server_id: "srv-restore",
          name: "Restoring World",
          status: "restoring",
        },
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useServersList>);

    renderPage();
    expect(screen.getByText("Restoring")).toBeInTheDocument();
    expect(screen.queryByLabelText("Start Restoring World")).not.toBeInTheDocument();
  });
});
