import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiKeysPage } from "./ApiKeysPage";

const mockKeys = [
  {
    api_key_id: "key-1",
    name: "CI/CD Key",
    prefix: "mcs_a",
    key: null,
    permissions: ["read"],
    expires_at: null,
    is_revoked: false,
    created_at: "2024-01-01T00:00:00Z",
  },
];

let mockData = mockKeys;
let mockIsLoading = false;
let mockError: Error | null = null;

vi.mock("@/server_manager/hooks/useApiKeys", () => ({
  useApiKeys: vi.fn(() => ({
    data: mockData,
    isLoading: mockIsLoading,
    error: mockError,
  })),
  useCreateApiKey: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useRevokeApiKey: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}));

function renderPage() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ApiKeysPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ApiKeysPage", () => {
  beforeEach(() => {
    mockData = mockKeys;
    mockIsLoading = false;
    mockError = null;
  });

  it("renders title", () => {
    renderPage();
    expect(screen.getByText("API Keys")).toBeInTheDocument();
  });

  it("shows loading skeletons", () => {
    mockIsLoading = true;
    const { container } = renderPage();
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows error on failure", () => {
    mockError = new Error("Keys failed");
    renderPage();
    expect(screen.getByText("Keys failed")).toBeInTheDocument();
  });

  it("renders API key rows", () => {
    renderPage();
    expect(screen.getByText("CI/CD Key")).toBeInTheDocument();
    expect(screen.getByText(/mcs_a\.\.\./)).toBeInTheDocument();
  });

  it("shows empty state when no keys", () => {
    mockData = [];
    renderPage();
    expect(screen.getByText("No API keys")).toBeInTheDocument();
  });

  it("toggles create form", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Create API Key" }));
    expect(screen.getByText("Create API Key")).toBeInTheDocument();
  });
});
