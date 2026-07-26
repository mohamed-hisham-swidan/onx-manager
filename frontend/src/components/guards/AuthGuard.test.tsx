import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthGuard } from "./AuthGuard";

let mockIsAuthenticated = true;

vi.mock("@/stores/authStore", () => ({
  useAuthStore: vi.fn((selector: (s: { isAuthenticated: boolean }) => unknown) =>
    selector({ isAuthenticated: mockIsAuthenticated }),
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
  });

  it("renders children when authenticated", () => {
    renderWithRouter("/");
    expect(screen.getByTestId("protected-page")).toBeInTheDocument();
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
  });

  it("redirects to /login when not authenticated", () => {
    mockIsAuthenticated = false;
    renderWithRouter("/");
    expect(screen.getByTestId("login-page")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-page")).not.toBeInTheDocument();
  });
});
