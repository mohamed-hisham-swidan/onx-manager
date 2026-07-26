import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LoginPage } from "./LoginPage";

const mockLogin = vi.fn();
const mockNavigate = vi.fn();
const mockApiLogin = vi.fn().mockResolvedValue({
  access_token: "tok1",
  refresh_token: "rtok1",
  expires_in: 3600,
});

vi.mock("@/stores/authStore", () => ({
  useAuthStore: vi.fn((selector: ((s: { login: typeof mockLogin }) => unknown) | undefined) => {
    const state = { login: mockLogin };
    return selector ? selector(state) : state;
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual as object, useNavigate: () => mockNavigate };
});

vi.mock("@/services/api", () => ({
  createApiClient: vi.fn(() => ({ login: mockApiLogin })),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    mockLogin.mockReset();
    mockNavigate.mockReset();
    mockApiLogin.mockReset();
    mockApiLogin.mockResolvedValue({
      access_token: "tok1",
      refresh_token: "rtok1",
      expires_in: 3600,
    });
  });

  it("renders sign-in form", () => {
    renderPage();
    expect(screen.getByText("MC Server Manager")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows error when fields are empty", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Email and password are required")).toBeInTheDocument();
  });

  it("calls api.login on valid submit and navigates to /", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Email"), "a@b.com");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(mockApiLogin).toHaveBeenCalledWith({ email: "a@b.com", password: "secret" });
    expect(mockLogin).toHaveBeenCalledWith("tok1", "rtok1", 3600);
    expect(mockNavigate).toHaveBeenCalledWith("/");
  });

  it("displays error message on failed login", async () => {
    mockApiLogin.mockRejectedValue(new Error("Invalid credentials"));

    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Email"), "a@b.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
  });

  it("disables button while loading", async () => {
    let resolvePromise!: (v: unknown) => void;
    mockApiLogin.mockReturnValue(new Promise((resolve) => { resolvePromise = resolve; }));

    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Email"), "a@b.com");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(screen.getByRole("button", { name: "Signing in..." })).toBeDisabled();

    resolvePromise({ access_token: "t", refresh_token: "r", expires_in: 3600 });
  });
});
