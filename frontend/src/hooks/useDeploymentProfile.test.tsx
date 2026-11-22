import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SettingsPage } from "@/server_manager/pages/SettingsPage";
import { SetupPage } from "@/pages/SetupPage";
import { ServerExposurePage } from "@/server_manager/pages/ServerExposurePage";
import { useUIStore } from "@/stores/uiStore";
import type { SystemStatusResponse } from "@/types";

const mockGetSetupStatus = vi.fn<() => Promise<SystemStatusResponse>>();
const mockBootstrapInstance = vi.fn();

vi.mock("@/services/api", () => {
  const client = {
    getSetupStatus: () => mockGetSetupStatus(),
    bootstrapInstance: (...args: unknown[]) => mockBootstrapInstance(...args),
    getMe: vi.fn().mockResolvedValue({
      user_id: "u-1",
      email: "owner@example.com",
      display_name: "Owner",
      is_active: true,
      roles: ["owner"],
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
    }),
    listInvites: vi.fn().mockResolvedValue([]),
    createInvite: vi.fn(),
    revokeInvite: vi.fn(),
    stopAllExposures: vi.fn(),
    removeCredentials: vi.fn(),
  };
  return {
    createApiClient: () => client,
    createAuthenticatedApi: () => client,
  };
});

vi.mock("@/server_manager/hooks/useSettings", () => ({
  useSettings: vi.fn(() => ({
    data: {
      app_name: "onx-manager",
      version: "0.1.0",
      debug: false,
      log_level: "INFO",
      rate_limit_per_minute: 60,
      idempotency_ttl_hours: 24,
      circuit_breaker_max_failures: 5,
      circuit_breaker_timeout_seconds: 30,
      event_bus_retry_attempts: 3,
      saga_timeout_seconds: 300,
      metrics_interval_seconds: 0.2,
      server_startup_timeout_seconds: 120,
      test_boot_timeout_seconds: 120,
      requires_restart: ["app_name", "log_level", "debug"],
    },
    isLoading: false,
    error: null,
  })),
  useUpdateSettings: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
}));

const MOCK_SERVER = {
  server_id: "srv-1",
  name: "My Local Server",
  port: 25565,
  status: "stopped",
  mode: "simple",
};

const MOCK_EXPOSURE = {
  server_id: "srv-1",
  method: "none",
  desired_state: "DISABLED",
  aggregate_status: "DISABLED",
  targets: [],
};

const MOCK_AGENT = { claimed: false, running: false };
const NOOP = vi.fn();

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServerDetail: vi.fn(() => ({
    data: MOCK_SERVER,
    isLoading: false,
  })),
}));

vi.mock("@/server_manager/hooks/useServerExposure", () => ({
  useServerExposure: vi.fn(() => ({
    exposure: MOCK_EXPOSURE,
    isLoading: false,
    refetch: NOOP,
    agent: MOCK_AGENT,
    setExposure: NOOP,
    isSettingExposure: false,
    setExposureState: NOOP,
    isSettingExposureState: false,
    createTarget: NOOP,
    isCreatingTarget: false,
    updateTargetAddress: NOOP,
    isUpdatingTargetAddress: false,
    deleteTarget: NOOP,
    isDeletingTarget: false,
  })),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
  useToastStore: vi.fn(() => ({ toasts: [], dismiss: vi.fn() })),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (s: { login: ReturnType<typeof vi.fn> }) => unknown) =>
    selector({ login: vi.fn() }),
}));

function renderWithQuery(ui: React.ReactElement, prefill?: SystemStatusResponse) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (prefill) {
    qc.setQueryData(["systemStatus"], prefill);
  }
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Deployment Profile UX adaptation (local vs vps)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useUIStore.setState({ showFullVpsControls: false });
  });

  it("SettingsPage hides VPS-only tabs in local mode and reveals them via toggle", async () => {
    const localStatus: SystemStatusResponse = {
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "0.1.0",
      deployment_profile: "local",
    };
    mockGetSetupStatus.mockResolvedValue(localStatus);

    renderWithQuery(<SettingsPage />, localStatus);

    expect(screen.getByText("System Settings")).toBeInTheDocument();
    expect(screen.getByText("Appearance & Themes")).toBeInTheDocument();
    expect(screen.queryByText("Invitations")).not.toBeInTheDocument();
    expect(screen.queryByText("Access Control")).not.toBeInTheDocument();
    expect(screen.queryByText("API Keys")).not.toBeInTheDocument();

    const toggleBtn = screen.getByRole("button", { name: /Show VPS & multi-user settings/i });
    fireEvent.click(toggleBtn);

    expect(await screen.findByText("Invitations")).toBeInTheDocument();
    expect(screen.getByText("Access Control")).toBeInTheDocument();
    expect(screen.getByText("API Keys")).toBeInTheDocument();
  });

  it("SettingsPage shows all 6 tabs immediately in vps mode", () => {
    const vpsStatus: SystemStatusResponse = {
      initialized: true,
      access_mode: "GLOBAL",
      user_count: 1,
      version: "0.1.0",
      deployment_profile: "vps",
    };
    mockGetSetupStatus.mockResolvedValue(vpsStatus);

    renderWithQuery(<SettingsPage />, vpsStatus);

    expect(screen.getByText("Invitations")).toBeInTheDocument();
    expect(screen.getByText("Access Control")).toBeInTheDocument();
    expect(screen.getByText("API Keys")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Show VPS & multi-user settings/i }),
    ).not.toBeInTheDocument();
  });

  it("SetupPage streamlines access mode selection in local mode while preserving LOCAL submit", async () => {
    const localStatus: SystemStatusResponse = {
      initialized: false,
      access_mode: "LOCAL",
      user_count: 0,
      version: "0.1.0",
      deployment_profile: "local",
    };
    mockGetSetupStatus.mockResolvedValue(localStatus);
    mockBootstrapInstance.mockResolvedValue({
      success: true,
      message: "ok",
      user_id: "u-1",
      access_token: "tok",
      refresh_token: "rtok",
      token_type: "bearer",
      expires_in: 900,
    });

    renderWithQuery(<SetupPage />, localStatus);

    expect(screen.getByText(/Local Desktop Setup/i)).toBeInTheDocument();
    expect(screen.queryByText("Global Mode")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Network access options/i }));
    expect(await screen.findByText("Global Mode")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Username/i), { target: { value: "playerone" } });
    fireEvent.change(screen.getByLabelText(/^Password$/i), { target: { value: "password123" } });
    fireEvent.change(screen.getByLabelText(/Confirm Password/i), { target: { value: "password123" } });
    fireEvent.click(screen.getByRole("button", { name: /Complete Setup/i }));

    await waitFor(() => {
      expect(mockBootstrapInstance).toHaveBeenCalledWith(
        expect.objectContaining({ username: "playerone", access_mode: "LOCAL" }),
      );
    });
  });

  it("ServerExposurePage shows Quick Share banner in local mode and toggles full routing topology", async () => {
    const localStatus: SystemStatusResponse = {
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "0.1.0",
      deployment_profile: "local",
    };
    mockGetSetupStatus.mockResolvedValue(localStatus);

    renderWithQuery(<ServerExposurePage />, localStatus);

    expect(screen.getByTestId("local-quick-share-banner")).toBeInTheDocument();
    expect(screen.queryByText(/Connection Flow & Routing Topology/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Show VPS \/ routing topology details/i }));

    expect(await screen.findByText(/Connection Flow & Routing Topology/i)).toBeInTheDocument();
  });
});
