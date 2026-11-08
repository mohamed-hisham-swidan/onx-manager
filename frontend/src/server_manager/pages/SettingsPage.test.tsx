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
    expect(screen.getByText("Automatic Failure Protection")).toBeInTheDocument();
    expect(screen.getByText("Background Tasks & Operations")).toBeInTheDocument();
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

  it("switches to Appearance & Themes tab and renders studio controls", async () => {
    renderPage();
    expect(screen.getByText("General")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Appearance & Themes/i }));

    expect(await screen.findByText("Appearance & Theme Studio")).toBeInTheDocument();
    expect(screen.getByText("Theme Skin Gallery")).toBeInTheDocument();
    expect(screen.getByText("Interface Density")).toBeInTheDocument();
    expect(screen.queryByText("General")).not.toBeInTheDocument();
  });

  it("switches to API Keys tab and renders inline API key management", async () => {
    renderPage();
    expect(screen.getByText("General")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /API Keys/i }));

    expect(await screen.findByText("Test API Key")).toBeInTheDocument();
    expect(screen.queryByText("General")).not.toBeInTheDocument();
  });

  it("filters system setting sections using category pills and search input", () => {
    renderPage();
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Rate Limiting & Security")).toBeInTheDocument();
    expect(screen.getByText("Automatic Failure Protection")).toBeInTheDocument();

    // Click "Security & Throttling" category pill
    fireEvent.click(screen.getByRole("button", { name: "Security & Throttling" }));
    expect(screen.getByText("Rate Limiting & Security")).toBeInTheDocument();
    expect(screen.queryByText("General")).not.toBeInTheDocument();
    expect(screen.queryByText("Automatic Failure Protection")).not.toBeInTheDocument();

    // Click "All Sections (6)" to restore all
    fireEvent.click(screen.getByRole("button", { name: "All Sections (6)" }));
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Automatic Failure Protection")).toBeInTheDocument();

    // Use search input (matches "circuit" keyword in failure protection section)
    const searchInput = screen.getByPlaceholderText("Filter system settings...");
    fireEvent.change(searchInput, { target: { value: "circuit" } });
    expect(screen.getByText("Automatic Failure Protection")).toBeInTheDocument();
    expect(screen.queryByText("General")).not.toBeInTheDocument();
    expect(screen.queryByText("Rate Limiting & Security")).not.toBeInTheDocument();
  });

  it("does not coerce empty string to 0 in numeric settings while typing", () => {
    renderPage();

    const rateLimitInput = screen.getByLabelText("Rate Limit (per minute)") as HTMLInputElement;
    expect(rateLimitInput.value).toBe("60");

    // Clear input completely
    fireEvent.change(rateLimitInput, { target: { value: "" } });
    expect(rateLimitInput.value).toBe("");

    // Type a new number freely
    fireEvent.change(rateLimitInput, { target: { value: "120" } });
    expect(rateLimitInput.value).toBe("120");
  });

  it("adjusts numeric fields via stepper buttons", () => {
    renderPage();

    const rateLimitInput = screen.getByLabelText("Rate Limit (per minute)") as HTMLInputElement;
    expect(rateLimitInput.value).toBe("60");

    const increaseBtn = screen.getByRole("button", { name: "Increase Rate Limit (per minute)" });
    const decreaseBtn = screen.getByRole("button", { name: "Decrease Rate Limit (per minute)" });

    fireEvent.click(increaseBtn);
    expect(rateLimitInput.value).toBe("61");

    fireEvent.click(decreaseBtn);
    expect(rateLimitInput.value).toBe("60");
  });

  it("updates log level using segmented pill selectors", () => {
    renderPage();

    const warnPill = screen.getByRole("button", { name: "WARNING" });
    fireEvent.click(warnPill);

    const logLevelSelect = screen.getByLabelText("Log Level") as HTMLSelectElement;
    expect(logLevelSelect.value).toBe("WARNING");
  });

  it("does not render raw backend key badges in rendered UI", () => {
    const { container } = renderPage();
    // Key pills like idempotency_ttl_hours, rate_limit_per_minute, saga_timeout_seconds should not be rendered
    expect(screen.queryByText("idempotency_ttl_hours")).not.toBeInTheDocument();
    expect(screen.queryByText("rate_limit_per_minute")).not.toBeInTheDocument();
    expect(screen.queryByText("circuit_breaker_max_failures")).not.toBeInTheDocument();
    expect(screen.queryByText("circuit_breaker_timeout_seconds")).not.toBeInTheDocument();
    expect(screen.queryByText("event_bus_retry_attempts")).not.toBeInTheDocument();
    expect(screen.queryByText("saga_timeout_seconds")).not.toBeInTheDocument();
    expect(screen.queryByText("metrics_interval_seconds")).not.toBeInTheDocument();
    expect(screen.queryByText("server_startup_timeout_seconds")).not.toBeInTheDocument();
    expect(screen.queryByText("test_boot_timeout_seconds")).not.toBeInTheDocument();

    // Check that no monospace code pills are rendered inside setting rows
    const codePills = container.querySelectorAll("code");
    expect(codePills.length).toBe(0);
  });

  it("renders plain explanations and tooltips for advanced settings", () => {
    renderPage();
    // Plain explanation for Idempotency TTL
    expect(screen.getByText(/duplicate requests/i)).toBeInTheDocument();
    // Plain explanation / tooltip for Circuit Breaker
    expect(screen.getByText(/pausing calls|pausing requests/i)).toBeInTheDocument();
    // Plain explanation / tooltip for Rate Limit
    expect(screen.getByText(/maximum api requests/i)).toBeInTheDocument();
    // Plain explanation / tooltip for Sagas
    expect(screen.getAllByText(/multi-step workflows/i).length).toBeGreaterThan(0);
  });
});
