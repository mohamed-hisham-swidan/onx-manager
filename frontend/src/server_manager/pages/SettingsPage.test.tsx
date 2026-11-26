import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SettingsPage } from "./SettingsPage";

const mockDefaults = {
  app_name: "onx-manager",
  debug: false,
  log_level: "INFO",
  rate_limit_per_minute: 60,
  idempotency_ttl_hours: 24,
  circuit_breaker_max_failures: 5,
  circuit_breaker_timeout_seconds: 30,
  event_bus_retry_attempts: 3,
  saga_timeout_seconds: 300,
  metrics_interval_seconds: 5.0,
  server_startup_timeout_seconds: 120,
  test_boot_timeout_seconds: 120,
  host_ram_reserve_mb: 0,
  host_cpu_reserve: 0,
};

const mockSettings = {
  ...mockDefaults,
  version: "0.1.0",
  requires_restart: ["app_name", "log_level", "debug", "panel_bind_host"],
  defaults: mockDefaults,
};

let mockData: typeof mockSettings | null = mockSettings;
let mockIsLoading = false;
let mockError: Error | null = null;
let mockMutateAsync = vi.fn();
let mockIsPending = false;
const mockToast = vi.fn();

vi.mock("@/server_manager/hooks/useSettings", () => ({
  useSettings: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
    refetch: vi.fn(),
  })),
  useUpdateSettings: vi.fn(() => ({
    mutateAsync: mockMutateAsync,
    isPending: mockIsPending,
  })),
}));

vi.mock("@/services/api", () => ({
  ApiError: class MockApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  createAuthenticatedApi: () => ({
    getMe: vi.fn().mockResolvedValue({
      user_id: "u1",
      roles: ["owner"],
      display_name: "Owner",
      email: "owner@example.com",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
    }),
    getSetupStatus: vi.fn().mockResolvedValue({
      initialized: true,
      access_mode: "GLOBAL",
      user_count: 1,
      version: "0.1.0",
      deployment_profile: "vps",
    }),
    listInvites: vi.fn().mockResolvedValue([]),
    listServers: vi.fn().mockResolvedValue([]),
    createInvite: vi.fn(),
    revokeInvite: vi.fn(),
    getCurseForgeIntegrationStatus: vi.fn().mockResolvedValue({
      configured: false,
      source: "none",
      hint: null,
    }),
    listLecEntries: vi.fn().mockResolvedValue([]),
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
  useToastStore: vi.fn(() => ({ toasts: [], dismiss: vi.fn() })),
}));

vi.mock("@/server_manager/hooks/useApiKeys", () => ({
  useApiKeys: vi.fn(() => ({
    data: [
      {
        api_key_id: "key-1",
        name: "Test API Key",
        prefix: "mcs_test",
        key: null,
        permissions: ["read"],
        expires_at: null,
        is_revoked: false,
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    isLoading: false,
    error: null,
  })),
  useCreateApiKey: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useRevokeApiKey: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

function renderPage(initialEntry = "/settings") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockData = mockSettings;
    mockIsLoading = false;
    mockError = null;
    mockIsPending = false;
    mockMutateAsync = vi.fn().mockResolvedValue({
      success: true,
      message: "Settings updated",
      requires_restart: [],
      settings: mockSettings,
    });
  });

  it("renders 2-column settings shell and everyday General sections", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "General" })).toBeInTheDocument();
    expect(screen.getByText("Host Resource Reserve")).toBeInTheDocument();
    expect(screen.getByText("Server Lifecycle")).toBeInTheDocument();
    expect(screen.getByText("Advanced Engine Settings")).toBeInTheDocument();
    expect(screen.queryByLabelText("App Name")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("API Rate Limit")).not.toBeInTheDocument();
  });

  it("maps legacy ?tab=system query param cleanly to General tab", () => {
    renderPage("/settings?tab=system");
    expect(screen.getByRole("heading", { name: "General" })).toBeInTheDocument();
    expect(screen.getByText("Host Resource Reserve")).toBeInTheDocument();
  });

  it("shows loading skeletons", () => {
    mockIsLoading = true;
    const { container } = renderPage();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error on initial fetch failure and ForbiddenState on 403", () => {
    mockError = new Error("Settings failed to load");
    const { unmount } = renderPage();
    expect(screen.getByText("Settings failed to load")).toBeInTheDocument();
    unmount();

    mockError = new Error("403 Forbidden - permission 'settings:read' required");
    renderPage();
    expect(screen.getByText("Settings Access Restricted")).toBeInTheDocument();
  });

  it("shows ErrorState when settings payload is missing", () => {
    mockData = null;
    renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent("Settings not available");
  });

  it("displays version pill from settings.version and handles missing/null version", () => {
    const { unmount } = renderPage();
    expect(screen.getByTestId("settings-version-pill")).toHaveTextContent("v0.1.0");
    unmount();

    mockData = { ...mockSettings, version: "5.7.2" };
    const { unmount: unmount2 } = renderPage();
    expect(screen.getByTestId("settings-version-pill")).toHaveTextContent("v5.7.2");
    unmount2();

    mockData = { ...mockSettings, version: null as unknown as string };
    renderPage();
    expect(screen.queryByTestId("settings-version-pill")).not.toBeInTheDocument();
  });

  it("sends dirty-only PATCH payload and syncs clamped response so dirtyCount resets to 0", async () => {
    mockMutateAsync.mockResolvedValueOnce({
      success: true,
      message: "Settings updated",
      requires_restart: [],
      settings: { ...mockSettings, host_ram_reserve_mb: 4096 },
    });

    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "4 GB (4096)" }));
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({ host_ram_reserve_mb: 4096 });
    });

    await waitFor(() => {
      expect(screen.queryByText(/unsaved change/i)).not.toBeInTheDocument();
    });
    expect(mockToast).toHaveBeenCalledWith("success", "Settings saved", expect.any(String));
  });

  it("clamps number inputs on Enter-key submit without needing blur first", async () => {
    mockMutateAsync.mockResolvedValueOnce({
      success: true,
      message: "Settings updated",
      requires_restart: [],
      settings: { ...mockSettings, server_startup_timeout_seconds: 1800 },
    });

    renderPage();

    const timeoutInput = screen.getByLabelText("Server Startup Timeout") as HTMLInputElement;
    fireEvent.change(timeoutInput, { target: { value: "99999" } });
    fireEvent.submit(timeoutInput.closest("form")!);

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({ server_startup_timeout_seconds: 1800 });
    });
  });

  it("discards unsaved General changes when Discard is clicked", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "2 GB (2048)" }));
    expect(screen.getByText("1 unsaved change")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.queryByText(/unsaved change/i)).not.toBeInTheDocument();
    expect((screen.getByLabelText("Host RAM Reserve") as HTMLInputElement).value).toBe("0");
  });

  it("opens Advanced Engine Settings drawer, filters settings, edits, and saves dirty-only keys", async () => {
    mockMutateAsync.mockResolvedValueOnce({
      success: true,
      message: "Settings updated",
      requires_restart: ["log_level"],
      settings: { ...mockSettings, rate_limit_per_minute: 120, log_level: "WARNING" },
    });

    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /configure engine/i }));
    const drawer = await screen.findByRole("dialog", { name: /advanced engine settings/i });
    expect(drawer).toBeInTheDocument();

    // Filter with search input
    const searchInput = within(drawer).getByPlaceholderText("Filter engine settings...");
    fireEvent.change(searchInput, { target: { value: "circuit" } });
    expect(within(drawer).getByLabelText("Failure Limit")).toBeInTheDocument();
    expect(within(drawer).queryByLabelText("API Rate Limit")).not.toBeInTheDocument();

    // Clear search and edit Rate Limit + Log Level
    fireEvent.change(searchInput, { target: { value: "" } });
    const rateInput = within(drawer).getByLabelText("API Rate Limit") as HTMLInputElement;
    fireEvent.change(rateInput, { target: { value: "120" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "WARNING" }));

    fireEvent.click(within(drawer).getByRole("button", { name: /save engine settings/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({
        rate_limit_per_minute: 120,
        log_level: "WARNING",
      });
    });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /advanced engine settings/i })).not.toBeInTheDocument();
    });
  });

  it("prompts before discarding dirty changes in Advanced Engine Settings drawer", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /configure engine/i }));
    const drawer = await screen.findByRole("dialog", { name: /advanced engine settings/i });

    const rateInput = within(drawer).getByLabelText("API Rate Limit") as HTMLInputElement;
    fireEvent.change(rateInput, { target: { value: "250" } });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(within(drawer).getByText(/discard 1 unsaved engine change/i)).toBeInTheDocument();

    fireEvent.click(within(drawer).getByRole("button", { name: /discard & close/i }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /advanced engine settings/i })).not.toBeInTheDocument();
    });
  });

  it("switches between Appearance, Modpacks & Cache, Invitations, and API Keys tabs", async () => {
    renderPage();

    fireEvent.click(screen.getAllByRole("tab", { name: /Appearance/i })[0]);
    expect(await screen.findByText("Visual Skin")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("tab", { name: /Modpacks & Cache/i })[0]);
    expect(await screen.findByText("CurseForge API Key")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("tab", { name: /Invitations/i })[0]);
    expect(await screen.findByRole("heading", { name: "Invitations" })).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("tab", { name: /API Keys/i })[0]);
    expect(await screen.findByText("Test API Key")).toBeInTheDocument();
  });

  it("applies wider 2xl max-width classes on SettingsShell without changing xl laptop widths", () => {
    const { container } = renderPage();
    const outerWrapper = container.firstElementChild;
    expect(outerWrapper).toHaveClass("max-w-6xl", "xl:max-w-[78rem]", "2xl:max-w-[86rem]");
    const tabPanel = screen.getByRole("tabpanel");
    expect(tabPanel).toHaveClass("max-w-4xl", "2xl:max-w-5xl");
  });

  it("allows non-admin users to access Appearance and API Keys tabs when global settings returns 403", async () => {
    mockData = null;
    mockError = new Error("403 Forbidden - permission 'settings:read' required");
    const { unmount } = renderPage("/settings?tab=appearance");
    expect(await screen.findByText("Visual Skin")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("tab", { name: /API Keys/i })[0]);
    expect(await screen.findByText("Test API Key")).toBeInTheDocument();
    unmount();

    // Navigating back to General still shows ForbiddenState cleanly inside SettingsShell
    renderPage("/settings");
    expect(screen.getByText("Settings Access Restricted")).toBeInTheDocument();
  });
});
