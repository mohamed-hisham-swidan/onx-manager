import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AccessModeCard } from "./AccessModeCard";

const mockGetSetupStatus = vi.fn();
const mockUpdateAccessMode = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getSetupStatus: () => mockGetSetupStatus(),
    updateAccessMode: (body: unknown) => mockUpdateAccessMode(body),
  }),
}));

vi.mock("@/stores/toastStore", () => ({
  toast: vi.fn(),
}));

function renderComponent() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AccessModeCard />
    </QueryClientProvider>
  );
}

describe("AccessModeCard modal behavior (FIX-3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSetupStatus.mockResolvedValue({ access_mode: "LOCAL" });
  });

  it("renders dialog with accessible title, focuses inside, and supports Escape when idle", async () => {
    renderComponent();
    const switchBtn = await screen.findByRole("button", { name: /switch to global mode/i });
    fireEvent.click(switchBtn);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /switch to global access mode\?/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("does not close on backdrop click or content click", async () => {
    renderComponent();
    const switchBtn = await screen.findByRole("button", { name: /switch to global mode/i });
    fireEvent.click(switchBtn);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60")!;
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(dialog);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("guards against Escape and disables Cancel/Confirm buttons while pending", async () => {
    let resolveMutation!: (val: unknown) => void;
    mockUpdateAccessMode.mockImplementation(
      () => new Promise((resolve) => { resolveMutation = resolve; })
    );

    renderComponent();
    const switchBtn = await screen.findByRole("button", { name: /switch to global mode/i });
    fireEvent.click(switchBtn);

    const confirmBtn = screen.getByRole("button", { name: /confirm switch to global/i });
    const cancelBtn = screen.getByRole("button", { name: /cancel/i });

    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /updating mode/i })).toBeDisabled();
      expect(cancelBtn).toBeDisabled();
    });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    resolveMutation({ access_mode: "GLOBAL" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
