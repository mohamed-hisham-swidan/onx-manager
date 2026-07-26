import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SettingsPage } from "./SettingsPage";

const mockSettings = {
  app_name: "MCS Manager",
  version: "4.0.0",
  debug: false,
  log_level: "INFO",
  rate_limit_per_minute: 60,
  idempotency_ttl_hours: 24,
  circuit_breaker_max_failures: 5,
  circuit_breaker_timeout_seconds: 30,
  event_bus_retry_attempts: 3,
  saga_timeout_seconds: 300,
};

let mockData = mockSettings;
let mockIsLoading = false;
let mockError: Error | null = null;

vi.mock("@/server_manager/hooks/useSettings", () => ({
  useSettings: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useUpdateSettings: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
}));

function renderPage() {
  const qc = new QueryClient();
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
  });

  it("renders title", () => {
    renderPage();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("shows loading skeletons", () => {
    mockIsLoading = true;
    const { container } = renderPage();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error on failure", () => {
    mockError = new Error("Settings failed");
    renderPage();
    expect(screen.getByText("Settings failed")).toBeInTheDocument();
  });

  it("renders setting sections", () => {
    renderPage();
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Rate Limiting & Security")).toBeInTheDocument();
    expect(screen.getByText("Circuit Breaker")).toBeInTheDocument();
    expect(screen.getByText("Event Bus & Sagas")).toBeInTheDocument();
  });

  it("renders save button", () => {
    renderPage();
    expect(screen.getByText("Save Settings")).toBeInTheDocument();
  });
});
