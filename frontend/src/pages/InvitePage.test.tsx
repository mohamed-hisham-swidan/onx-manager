import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { InvitePage } from "./InvitePage";

const mockVerifyInvite = vi.fn();
const mockAcceptInvite = vi.fn();
const mockLogin = vi.fn();

vi.mock("@/services/api", () => ({
  createApiClient: () => ({
    verifyInvite: mockVerifyInvite,
    acceptInvite: mockAcceptInvite,
  }),
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (s: { login: typeof mockLogin }) => unknown) =>
    selector({ login: mockLogin }),
}));

function renderInvitePage(token = "valid_token_123") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/invite/${token}`]}>
        <Routes>
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="/" element={<div data-testid="dashboard-page">Dashboard</div>} />
          <Route path="/login" element={<div data-testid="login-page">Login</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("InvitePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("1. Renders error card when invitation token is invalid or expired", async () => {
    mockVerifyInvite.mockResolvedValueOnce({
      valid: false,
      email: null,
      expires_at: null,
    });

    renderInvitePage("invalid_token");

    expect(await screen.findByText(/Invalid or Expired Invitation/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Go to Sign In/i })).toBeInTheDocument();
  });

  it("2. Renders redemption form when token is valid", async () => {
    mockVerifyInvite.mockResolvedValueOnce({
      valid: true,
      email: "invited@example.com",
      expires_at: "2026-12-31T23:59:59Z",
    });

    renderInvitePage("valid_token_123");

    expect(await screen.findByText(/Invitation Verified!/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
    expect(screen.getByText("invited@example.com")).toBeInTheDocument();
  });

  it("3. Validates password mismatch and password length requirement", async () => {
    mockVerifyInvite.mockResolvedValueOnce({
      valid: true,
      email: null,
      expires_at: null,
    });

    renderInvitePage("valid_token_123");

    const usernameInput = await screen.findByLabelText(/Username/i);
    const passInput = screen.getByLabelText(/^Password$/i);
    const confirmInput = screen.getByLabelText(/Confirm Password/i);
    const submitBtn = screen.getByRole("button", { name: /Accept Invitation/i });

    // Test password mismatch
    fireEvent.change(usernameInput, { target: { value: "newuser" } });
    fireEvent.change(passInput, { target: { value: "password123" } });
    fireEvent.change(confirmInput, { target: { value: "mismatch123" } });
    fireEvent.click(submitBtn);

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(mockAcceptInvite).not.toHaveBeenCalled();
  });

  it("4. Submits acceptInvite and authenticates user on success", async () => {
    mockVerifyInvite.mockResolvedValueOnce({
      valid: true,
      email: "invited@example.com",
      expires_at: null,
    });
    mockAcceptInvite.mockResolvedValueOnce({
      user_id: "u-100",
      access_token: "acc_token_999",
      refresh_token: "ref_token_999",
      token_type: "bearer",
      expires_in: 900,
    });

    renderInvitePage("valid_token_123");

    const usernameInput = await screen.findByLabelText(/Username/i);
    const passInput = screen.getByLabelText(/^Password$/i);
    const confirmInput = screen.getByLabelText(/Confirm Password/i);
    const submitBtn = screen.getByRole("button", { name: /Accept Invitation/i });

    fireEvent.change(usernameInput, { target: { value: "inviteduser" } });
    fireEvent.change(passInput, { target: { value: "password123" } });
    fireEvent.change(confirmInput, { target: { value: "password123" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockAcceptInvite).toHaveBeenCalledWith({
        token: "valid_token_123",
        username: "inviteduser",
        display_name: "inviteduser",
        email: "invited@example.com",
        password: "password123",
      });
      expect(mockLogin).toHaveBeenCalledWith("acc_token_999", "ref_token_999", 900);
      expect(screen.getByTestId("dashboard-page")).toBeInTheDocument();
    });
  });
});
