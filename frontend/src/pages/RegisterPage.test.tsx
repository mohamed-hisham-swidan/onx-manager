import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RegisterPage } from "./RegisterPage";

const mockCreateUser = vi.fn();
const mockGetSetupStatus = vi.fn();
const mockVerifyInvite = vi.fn();
const mockAcceptInvite = vi.fn();
const mockLogin = vi.fn();

vi.mock("@/services/api", () => ({
  createApiClient: () => ({
    createUser: mockCreateUser,
    getSetupStatus: mockGetSetupStatus,
    verifyInvite: mockVerifyInvite,
    acceptInvite: mockAcceptInvite,
  }),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (s: { login: typeof mockLogin }) => unknown) =>
    selector({ login: mockLogin }),
}));

function renderRegisterPage(initialRoute = "/register") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/login" element={<div data-testid="login-page">Login Page</div>} />
          <Route path="/" element={<div data-testid="home-page">Home Page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("RegisterPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders open registration form in LOCAL mode", async () => {
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "0.1.0",
    });

    renderRegisterPage();

    expect(await screen.findByLabelText(/Username/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Email/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create account/i })).toBeInTheDocument();
  });

  it("registers new user in LOCAL mode", async () => {
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "LOCAL",
      user_count: 1,
      version: "0.1.0",
    });
    mockCreateUser.mockResolvedValueOnce({ user_id: "u-2", username: "localuser", email: null });

    renderRegisterPage();

    await screen.findByLabelText(/Username/i);

    fireEvent.change(screen.getByLabelText(/Username/i), { target: { value: "localuser" } });
    fireEvent.change(screen.getByLabelText(/^Password$/i), { target: { value: "password123" } });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), { target: { value: "password123" } });

    fireEvent.click(screen.getByRole("button", { name: /Create account/i }));

    await waitFor(() => {
      expect(mockCreateUser).toHaveBeenCalledWith({
        username: "localuser",
        display_name: "localuser",
        password: "password123",
      });
      expect(screen.getByTestId("login-page")).toBeInTheDocument();
    });
  });

  it("disables standard registration and displays invite notice in GLOBAL mode", async () => {
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "GLOBAL",
      user_count: 1,
      version: "0.1.0",
    });

    renderRegisterPage();

    expect(await screen.findByText(/This instance uses invitation-only registration/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Username/i)).not.toBeInTheDocument();
  });

  it("verifies and accepts invitation token from URL parameter", async () => {
    mockGetSetupStatus.mockResolvedValueOnce({
      initialized: true,
      access_mode: "GLOBAL",
      user_count: 1,
      version: "0.1.0",
    });
    mockVerifyInvite.mockResolvedValueOnce({
      valid: true,
      email: "invited@test.com",
      expires_at: null,
    });
    mockAcceptInvite.mockResolvedValueOnce({
      user_id: "u-3",
      access_token: "acc_tok",
      refresh_token: "ref_tok",
      token_type: "bearer",
      expires_in: 900,
    });

    renderRegisterPage("/register?token=valid_token_123");

    expect(await screen.findByText(/Invitation verified!/i)).toBeInTheDocument();
    expect(screen.getByText("invited@test.com")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Username/i), { target: { value: "inviteduser" } });
    fireEvent.change(screen.getByLabelText(/^Password$/i), { target: { value: "password123" } });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), { target: { value: "password123" } });

    fireEvent.click(screen.getByRole("button", { name: /Accept & Complete Account/i }));

    await waitFor(() => {
      expect(mockAcceptInvite).toHaveBeenCalledWith({
        token: "valid_token_123",
        username: "inviteduser",
        display_name: "inviteduser",
        email: "invited@test.com",
        password: "password123",
      });
      expect(mockLogin).toHaveBeenCalledWith("acc_tok", "ref_tok", 900);
      expect(screen.getByTestId("home-page")).toBeInTheDocument();
    });
  });
});
