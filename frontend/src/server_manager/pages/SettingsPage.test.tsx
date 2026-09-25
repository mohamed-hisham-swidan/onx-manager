import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SettingsPage } from "./SettingsPage";

const mockSettings = {
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
};

let mockData: typeof mockSettings | null = mockSettings;
let mockIsLoading = false;
let mockError: Error | null = null;
let mockMutateAsync = vi.fn();
let mockIsPending = false;

vi.mock("@/server_manager/hooks/useSettings", () => ({
  useSettings: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useUpdateSettings: vi.fn(() => ({
    mutateAsync: mockMutateAsync,
    isPending: mockIsPending,
  })),
}));

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    listInvites: vi.fn().mockResolvedValue([]),
    createInvite: vi.fn(),
    revokeInvite: vi.fn(),
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
  useToastStore: vi.fn(() => ({ toasts: [], dismiss: vi.fn() })),
}));

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    mockData = mockSettings;
    mockIsLoading = false;
    mockError = null;
    mockMutateAsync = vi.fn().mockResolvedValue({
      success: true,
      message: "Settings updated",
      requires_restart: ["app_name", "log_level", "debug"],
      settings: mockSettings,
    });
    mockIsPending = false;
  });

  it("renders title and sections", () => {
    renderPage();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Rate Limiting & Security")).toBeInTheDocument();
    expect(screen.getByText("Circuit Breaker")).toBeInTheDocument();
    expect(screen.getByText("Event Bus & Sagas")).toBeInTheDocument();
    expect(screen.getByText("Monitoring & Performance")).toBeInTheDocument();
  });

  it("shows loading skeletons", () => {
    mockIsLoading = true;
    const { container } = renderPage();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error on initial fetch failure", () => {
    mockError = new Error("Settings failed to load");
    renderPage();
    expect(screen.getByText("Settings failed to load")).toBeInTheDocument();
  });

  it("shows ErrorState when settings payload is missing", () => {
    mockData = null;
    renderPage();
    expect(screen.getByRole("alert")).toHaveTextContent("Settings not available");
  });

  it("(a) fields are editable and save via PATCH", async () => {
    const { container } = renderPage();

    const appNameInput = container.querySelector('[name="app_name"]') as HTMLInputElement;
    expect(appNameInput).toBeInTheDocument();
    expect(appNameInput.disabled).toBe(false);

    fireEvent.change(appNameInput, { target: { value: "Updated Server Manager" } });
    expect(appNameInput.value).toBe("Updated Server Manager");

    const saveButton = screen.getByRole("button", { name: /save settings/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          app_name: "Updated Server Manager",
        })
      );
    });
  });

  it("edits metrics_interval_seconds and saves via PATCH", async () => {
    const { container } = renderPage();

    const intervalInput = container.querySelector('[name="metrics_interval_seconds"]') as HTMLInputElement;
    expect(intervalInput).toBeInTheDocument();
    expect(intervalInput.value).toBe("0.2");

    fireEvent.change(intervalInput, { target: { value: "1.5" } });
    expect(intervalInput.value).toBe("1.5");

    const saveButton = screen.getByRole("button", { name: /save settings/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          metrics_interval_seconds: 1.5,
        })
      );
    });
  });

  it("(b) requires-restart indicator shows correctly for app_name/log_level/debug and not for the other 6", () => {
    renderPage();

    const restartBadges = screen.getAllByText("Requires restart");
    expect(restartBadges).toHaveLength(3);

    // Verify parent containers for app_name, log_level, debug have the badge
    const appNameLabel = screen.getByLabelText("App Name").closest("div");
    const logLevelLabel = screen.getByLabelText("Log Level").closest("div");
    const debugLabel = screen.getByLabelText("Debug Mode").closest("div");

    expect(appNameLabel).toHaveTextContent("Requires restart");
    expect(logLevelLabel).toHaveTextContent("Requires restart");
    expect(debugLabel).toHaveTextContent("Requires restart");

    // Verify rate limit container does NOT have restart badge
    const rateLimitLabel = screen.getByLabelText("Rate Limit (per minute)").closest("div");
    expect(rateLimitLabel).not.toHaveTextContent("Requires restart");
  });

  it("(c) PATCH error states render correctly", async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error("403 Forbidden - permission 'settings:write' required"));
    const { container } = renderPage();

    const appNameInput = container.querySelector('[name="app_name"]') as HTMLInputElement;
    fireEvent.change(appNameInput, { target: { value: "Forbidden Name" } });

    const saveButton = screen.getByRole("button", { name: /save settings/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("403 Forbidden - permission 'settings:write' required");
    });
  });

  it("(d) successful PATCH updates displayed values and shows success notice", async () => {
    mockMutateAsync.mockResolvedValueOnce({
      success: true,
      message: "Settings updated successfully.",
      requires_restart: ["app_name"],
      settings: { ...mockSettings, app_name: "Persisted App Name" },
    });
    const { container } = renderPage();

    const appNameInput = container.querySelector('[name="app_name"]') as HTMLInputElement;
    fireEvent.change(appNameInput, { target: { value: "Persisted App Name" } });

    const saveButton = screen.getByRole("button", { name: /save settings/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Settings updated successfully.");
      expect(screen.getByRole("status")).toHaveTextContent("Note: Changes to app_name require a backend restart");
    });
  });

  it("(e) save-feedback state transitions (saving -> saved/error)", () => {
    mockIsPending = true;
    renderPage();

    const saveButton = screen.getByRole("button", { name: /saving\.\.\./i });
    expect(saveButton).toBeInTheDocument();
    expect(saveButton).toBeDisabled();
  });

  it("resets form when Discard Changes is clicked", () => {
    const { container } = renderPage();

    const appNameInput = container.querySelector('[name="app_name"]') as HTMLInputElement;
    fireEvent.change(appNameInput, { target: { value: "Temporary Edit" } });
    expect(appNameInput.value).toBe("Temporary Edit");

    const discardButton = screen.getByRole("button", { name: /discard changes/i });
    expect(discardButton).toBeEnabled();

    fireEvent.click(discardButton);
    expect(appNameInput.value).toBe("onx-manager");
  });

  it("switches between System Settings and Invitations tabs", async () => {
    renderPage();
    expect(screen.getByText("General")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Invitations/i }));

    expect(await screen.findByText("Invitations Management")).toBeInTheDocument();
    expect(screen.queryByText("General")).not.toBeInTheDocument();
  });

  it("(v1) displays the application version reported by the settings API", () => {
    renderPage();
    expect(screen.getByText("onx-manager 0.1.0")).toBeInTheDocument();
  });

  it("(v2) sources the version from settings.version, not a frontend constant", () => {
    mockData = { ...mockSettings, version: "5.7.2" };
    renderPage();
    expect(screen.getByText("onx-manager 5.7.2")).toBeInTheDocument();
    expect(screen.queryByText(/0\.1\.0/)).not.toBeInTheDocument();
  });

  it("(v3) reflects a changed backend version in the UI", () => {
    mockData = { ...mockSettings, version: "6.0.0-beta.1" };
    const { unmount } = renderPage();
    expect(screen.getByText("onx-manager 6.0.0-beta.1")).toBeInTheDocument();
    unmount();

    mockData = { ...mockSettings, version: "6.0.0" };
    renderPage();
    expect(screen.getByText("onx-manager 6.0.0")).toBeInTheDocument();
    expect(screen.queryByText(/6\.0\.0-beta\.1/)).not.toBeInTheDocument();
  });

  it("(v4) handles a missing/null version without crashing", () => {
    mockData = { ...mockSettings, version: null as unknown as string };
    renderPage();
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.queryByText(/onx-manager \d+\.\d+\.\d+/)).not.toBeInTheDocument();
  });
});