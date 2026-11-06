import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GlobalExposureActionsCard } from "./GlobalExposureActionsCard";

const mockGetMe = vi.fn();
const mockStopAllExposures = vi.fn();
const mockResetAgent = vi.fn();
const mockRemoveCredentials = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getMe: () => mockGetMe(),
    stopAllExposures: () => mockStopAllExposures(),
    resetAgent: () => mockResetAgent(),
    removeCredentials: () => mockRemoveCredentials(),
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
      <GlobalExposureActionsCard />
    </QueryClientProvider>
  );
}

describe("GlobalExposureActionsCard modal behavior (FIX-3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMe.mockResolvedValue({ roles: ["owner"] });
  });

  it("renders dialog with accessible title, focuses inside, and supports Escape when idle", async () => {
    renderComponent();
    const trigger = await screen.findByRole("button", { name: /stop all exposures/i });
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Stop All Instance Exposures")).toBeInTheDocument();

    const input = screen.getByPlaceholderText('Type "STOP ALL"');
    await waitFor(() => {
      expect(document.activeElement).toBe(input);
    });

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("does not close on backdrop click or content click", async () => {
    renderComponent();
    const trigger = await screen.findByRole("button", { name: /stop all exposures/i });
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60")!;
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(dialog);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("guards against Escape and disables Cancel/Action buttons while in-flight", async () => {
    let resolveAction!: (val: unknown) => void;
    mockStopAllExposures.mockImplementation(
      () => new Promise((resolve) => { resolveAction = resolve; })
    );

    renderComponent();
    const trigger = await screen.findByRole("button", { name: /stop all exposures/i });
    fireEvent.click(trigger);

    const input = screen.getByPlaceholderText('Type "STOP ALL"');
    fireEvent.change(input, { target: { value: "STOP ALL" } });

    const submitBtn = screen.getByRole("button", { name: "Stop All Exposures" });
    const cancelBtn = screen.getByRole("button", { name: "Cancel" });

    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Stopping All..." })).toBeDisabled();
      expect(cancelBtn).toBeDisabled();
      expect(input).toBeDisabled();
    });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    resolveAction({ success: true });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
