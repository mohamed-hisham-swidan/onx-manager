import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SetupPage } from "./SetupPage";

const mockBootstrapInstance = vi.fn();
const mockLogin = vi.fn();

vi.mock("@/services/api", () => ({
  createApiClient: () => ({
    bootstrapInstance: mockBootstrapInstance,
  }),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (s: { login: typeof mockLogin }) => unknown) =>
    selector({ login: mockLogin }),
}));

function renderSetupPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/setup"]}>
        <Routes>
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/login" element={<div data-testid="login-page">Login</div>} />
          <Route path="/" element={<div data-testid="dashboard-page">Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("SetupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("1. Renders setup wizard form with all fields from backend contract", () => {
    renderSetupPage();
    expect(screen.getByLabelText(/Display Name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Owner Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Confirm Password/i)).toBeInTheDocument();
    expect(screen.getByText(/Local Mode/i)).toBeInTheDocument();
    expect(screen.getByText(/Global Mode/i)).toBeInTheDocument();
  });

  it("2 & 3. Validates password confirmation mismatch", async () => {
    renderSetupPage();

    fireEvent.change(screen.getByLabelText(/Display Name/i), { target: { value: "Owner Name" } });
    fireEvent.change(screen.getByLabelText(/Owner Email/i), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText(/^Password$/i), { target: { value: "password123" } });
    fireEvent.change(screen.getByLabelText(/Confirm Password/i), { target: { value: "mismatch321" } });

    fireEvent.click(screen.getByRole("button", { name: /Complete Setup/i }));

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(mockBootstrapInstance).not.toHaveBeenCalled();
  });

  it("4. Validates password length requirement (< 8 chars)", async () => {
    renderSetupPage();

    fireEvent.change(screen.getByLabelText(/Display Name/i), { target: { value: "Owner Name" } });
    fireEvent.change(screen.getByLabelText(/Owner Email/i), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText(/^Password$/i), { target: { value: "short" } });
    fireEvent.change(screen.getByLabelText(/Confirm Password/i), { target: { value: "short" } });

    fireEvent.click(screen.getByRole("button", { name: /Complete Setup/i }));

    expect(await screen.findByText("Password must be at least 8 characters long.")).toBeInTheDocument();
    expect(mockBootstrapInstance).not.toHaveBeenCalled();
  });

  it("5 & 6. Sends exact expected bootstrap payload and logs in Owner on success", async () => {
    mockBootstrapInstance.mockResolvedValueOnce({
      success: true,
      message: "Bootstrap successful",
      user_id: "u-123",
      access_token: "access_token_123",
      refresh_token: "refresh_token_123",
      token_type: "bearer",
      expires_in: 900,
    });

    renderSetupPage();

    fireEvent.change(screen.getByLabelText(/Display Name/i), { target: { value: "Owner Admin" } });
    fireEvent.change(screen.getByLabelText(/Owner Email/i), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText(/^Password$/i), { target: { value: "password123" } });
    fireEvent.change(screen.getByLabelText(/Confirm Password/i), { target: { value: "password123" } });

    fireEvent.click(screen.getByRole("button", { name: /Complete Setup/i }));

    await waitFor(() => {
      expect(mockBootstrapInstance).toHaveBeenCalledWith({
        display_name: "Owner Admin",
        email: "owner@example.com",
        password: "password123",
        access_mode: "LOCAL",
      });
      expect(mockLogin).toHaveBeenCalledWith("access_token_123", "refresh_token_123", 900);
      expect(screen.getByTestId("dashboard-page")).toBeInTheDocument();
    });
  });

  it("7 & 8. Handles backend & network failure", async () => {
    mockBootstrapInstance.mockRejectedValueOnce(new Error("Network Error"));

    renderSetupPage();

    fireEvent.change(screen.getByLabelText(/Display Name/i), { target: { value: "Owner Admin" } });
    fireEvent.change(screen.getByLabelText(/Owner Email/i), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText(/^Password$/i), { target: { value: "password123" } });
    fireEvent.change(screen.getByLabelText(/Confirm Password/i), { target: { value: "password123" } });

    fireEvent.click(screen.getByRole("button", { name: /Complete Setup/i }));

    expect(await screen.findByText("Network Error")).toBeInTheDocument();
  });

  it("9. Handles already-initialized race response", async () => {
    mockBootstrapInstance.mockRejectedValueOnce(new Error("Conflict: Instance is already initialized"));

    renderSetupPage();

    fireEvent.change(screen.getByLabelText(/Display Name/i), { target: { value: "Owner Admin" } });
    fireEvent.change(screen.getByLabelText(/Owner Email/i), { target: { value: "owner@example.com" } });
    fireEvent.change(screen.getByLabelText(/^Password$/i), { target: { value: "password123" } });
    fireEvent.change(screen.getByLabelText(/Confirm Password/i), { target: { value: "password123" } });

    fireEvent.click(screen.getByRole("button", { name: /Complete Setup/i }));

    expect(await screen.findByText("Conflict: Instance is already initialized")).toBeInTheDocument();

    const goToLoginBtn = screen.getByRole("button", { name: /Go to Login Page/i });
    expect(goToLoginBtn).toBeInTheDocument();

    fireEvent.click(goToLoginBtn);
    expect(await screen.findByTestId("login-page")).toBeInTheDocument();
  });
});
