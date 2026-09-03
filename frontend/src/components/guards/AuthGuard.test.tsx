import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthGuard } from "./AuthGuard";

let mockIsAuthenticated = true;
let mockRefreshToken: string | null = null;
let mockRefreshAuth = vi.fn(async () => true);

vi.mock("@/stores/authStore", () => ({
  useAuthStore: vi.fn((selector: (s: { isAuthenticated: boolean; refreshToken: string | null; refreshAuth: () => Promise<boolean> }) => unknown) =>
    selector({
      isAuthenticated: mockIsAuthenticated,
      refreshToken: mockRefreshToken,
      refreshAuth: mockRefreshAuth,
    }),
  ),
}));

function renderWithRouter(initialRoute = "/") {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <Routes>
        <Route path="/login" element={<div data-testid="login-page">Login</div>} />
        <Route element={<AuthGuard />}>
          <Route path="/" element={<div data-testid="protected-page">Protected</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthGuard", () => {
  beforeEach(() => {
    mockIsAuthenticated = true;
    mockRefreshToken = null;
    mockRefreshAuth = vi.fn(async () => true);
  });

  it("renders children when authenticated", () => {
    renderWithRouter("/");
    expect(screen.getByTestId("protected-page")).toBeInTheDocument();
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
  });

  it("redirects to /login when not authenticated and no refresh token exists", () => {
    mockIsAuthenticated = false;
    mockRefreshToken = null;
    renderWithRouter("/");
    expect(screen.getByTestId("login-page")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-page")).not.toBeInTheDocument();
  });

  it("ISS-047: attempts refresh when unauthenticated but refresh token exists in storage", async () => {
    mockIsAuthenticated = false;
    mockRefreshToken = "valid-refresh-token";
    mockRefreshAuth = vi.fn(async () => {
      mockIsAuthenticated = true;
      return true;
    });

    renderWithRouter("/");

    expect(mockRefreshAuth).toHaveBeenCalledTimes(1);
    // After refresh completes and updates isAuthenticated to true
    expect(await screen.findByTestId("protected-page")).toBeInTheDocument();
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
  });

  it("ISS-047: redirects to /login when refresh attempt fails", async () => {
    mockIsAuthenticated = false;
    mockRefreshToken = "expired-or-revoked-refresh-token";
    mockRefreshAuth = vi.fn(async () => {
      mockIsAuthenticated = false;
      return false;
    });

    renderWithRouter("/");

    expect(mockRefreshAuth).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId("login-page")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-page")).not.toBeInTheDocument();
  });
});
