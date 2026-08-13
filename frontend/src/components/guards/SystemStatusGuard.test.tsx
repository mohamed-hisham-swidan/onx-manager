import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SystemStatusGuard } from "./SystemStatusGuard";

const mockGetSetupStatus = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getSetupStatus: mockGetSetupStatus,
  }),
}));

function renderWithRouter(initialRoute = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route element={<SystemStatusGuard />}>
            <Route path="/setup" element={<div data-testid="setup-page">Setup</div>} />
            <Route path="/login" element={<div data-testid="login-page">Login</div>} />
            <Route path="/register" element={<div data-testid="register-page">Register</div>} />
            <Route path="/" element={<div data-testid="home-page">Home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("SystemStatusGuard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("1. UNINITIALIZED redirects /login to /setup", async () => {
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: false,
      access_mode: "LOCAL",
      user_count: 0,
      version: "4.0.0",
    });

    renderWithRouter("/login");
    expect(await screen.findByTestId("setup-page")).toBeInTheDocument();
  });

  it("2. UNINITIALIZED redirects /register to /setup", async () => {
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: false,
      access_mode: "LOCAL",
      user_count: 0,
      version: "4.0.0",
    });

    renderWithRouter("/register");
    expect(await screen.findByTestId("setup-page")).toBeInTheDocument();
  });

  it("3. UNINITIALIZED allows rendering /setup", async () => {
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: false,
      access_mode: "LOCAL",
      user_count: 0,
      version: "4.0.0",
    });

    renderWithRouter("/setup");
    expect(await screen.findByTestId("setup-page")).toBeInTheDocument();
  });

  it("4 & 5. INITIALIZED prevents /setup and redirects direct /setup navigation to /login", async () => {
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "4.0.0",
    });

    renderWithRouter("/setup");
    expect(await screen.findByTestId("login-page")).toBeInTheDocument();
    expect(screen.queryByTestId("setup-page")).not.toBeInTheDocument();
  });

  it("6. Loading state renders indicator and does not render protected content", () => {
    mockGetSetupStatus.mockReturnValue(new Promise(() => {})); // Never resolves

    renderWithRouter("/");
    expect(screen.getByText(/checking system status\.\.\./i)).toBeInTheDocument();
    expect(screen.queryByTestId("home-page")).not.toBeInTheDocument();
    expect(screen.queryByTestId("setup-page")).not.toBeInTheDocument();
  });

  it("7. API failure state renders error/retry screen and does not expose setup or protected routes", async () => {
    mockGetSetupStatus.mockRejectedValueOnce(new Error("Network Error"));

    renderWithRouter("/");

    expect(await screen.findByRole("alert")).toHaveTextContent("System Status Error");
    expect(screen.queryByTestId("home-page")).not.toBeInTheDocument();
    expect(screen.queryByTestId("setup-page")).not.toBeInTheDocument();

    // Clicking retry calls refetch
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: false,
      access_mode: "LOCAL",
      user_count: 0,
      version: "4.0.0",
    });

    fireEvent.click(screen.getByRole("button", { name: /retry connection/i }));
    expect(await screen.findByTestId("setup-page")).toBeInTheDocument();
  });
});
