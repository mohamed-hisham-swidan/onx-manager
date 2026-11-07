import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TestRunModal } from "./TestRunModal";
import type { PreflightStatus, TestDefinition } from "@/server_manager/types";

const mockGetTestDefinitions = vi.fn();
const mockGetPreflightStatus = vi.fn();
const mockRunIsolatedTest = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getTestDefinitions: mockGetTestDefinitions,
    getPreflightStatus: mockGetPreflightStatus,
    runIsolatedTest: mockRunIsolatedTest,
  }),
}));

const sampleDefinitions: TestDefinition[] = [
  {
    id: "def-1",
    server_id: "srv-1",
    name: "Quick Stress",
    description: "Quick 5-bot stress test",
    server_type: "paper",
    bot_technology: "auto",
    bot_count: 5,
    duration_seconds: 300,
    join_stagger_seconds: 1,
    connect_grace_seconds: 30,
    placement_mode: "sidecar",
    assertion_rules: {},
    timeout_seconds: 600,
    created_at: "2026-09-18T10:00:00Z",
    updated_at: "2026-09-18T10:00:00Z",
  },
];

const samplePreflight: PreflightStatus = {
  reflink_supported: true,
  available_ram_mb: 8192,
  available_cores: 4,
  min_required_ram_mb: 2048,
  min_required_cores: 2,
  passed: true,
  error: null,
};

describe("TestRunModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetTestDefinitions.mockResolvedValue(sampleDefinitions);
    mockGetPreflightStatus.mockResolvedValue(samplePreflight);
  });

  it("does not render when isOpen is false", () => {
    render(
      <TestRunModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders role='dialog' with accessible name, locks body scroll, and releases on unmount", () => {
    document.body.style.overflow = "";

    const { unmount } = render(
      <TestRunModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Launch Isolated Bot Test" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("fetches test definitions and preflight status when open", async () => {
    render(
      <TestRunModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Launch Isolated Bot Test")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockGetTestDefinitions).toHaveBeenCalledWith("srv-1");
      expect(mockGetPreflightStatus).toHaveBeenCalledWith("srv-1", 10);
    });

    expect(screen.getByText("Preflight Passed")).toBeInTheDocument();
    expect(screen.getByText(/Supported \(Btrfs\/ZFS\)/)).toBeInTheDocument();
  });

  it("submits test run successfully", async () => {
    const user = userEvent.setup();
    mockRunIsolatedTest.mockResolvedValueOnce({ test_id: "test-run-new-1" });
    const onTestStarted = vi.fn();
    const onClose = vi.fn();

    render(
      <TestRunModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={onTestStarted}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Launch Test Run" })).toBeInTheDocument();
    });

    const launchBtn = screen.getByRole("button", { name: "Launch Test Run" });
    await user.click(launchBtn);

    await waitFor(() => {
      expect(mockRunIsolatedTest).toHaveBeenCalledWith("srv-1", {
        commit_id: "abcdef1234567890",
        bot_count: 10,
        duration_minutes: 15,
        placement_mode: "sidecar",
        bot_tech: "auto",
        test_definition_id: undefined,
      });
      expect(onTestStarted).toHaveBeenCalledWith("test-run-new-1");
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("displays error message when runIsolatedTest fails", async () => {
    const user = userEvent.setup();
    mockRunIsolatedTest.mockRejectedValueOnce(new Error("Resource quota exceeded"));

    render(
      <TestRunModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Launch Test Run" })).toBeInTheDocument();
    });

    const launchBtn = screen.getByRole("button", { name: "Launch Test Run" });
    await user.click(launchBtn);

    await waitFor(() => {
      expect(screen.getByText("Resource quota exceeded")).toBeInTheDocument();
    });
  });

  it("closes on Escape key press when idle", () => {
    const onClose = vi.fn();

    render(
      <TestRunModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape and disables cancel button while launching", async () => {
    const user = userEvent.setup();
    let resolveLaunch: (value: unknown) => void = () => {};
    mockRunIsolatedTest.mockReturnValueOnce(
      new Promise((res) => {
        resolveLaunch = res;
      })
    );
    const onClose = vi.fn();

    render(
      <TestRunModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Launch Test Run" })).toBeInTheDocument();
    });

    const launchBtn = screen.getByRole("button", { name: "Launch Test Run" });
    await user.click(launchBtn);

    // Cancel button should be disabled
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    // Escape should be ignored while launching
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveLaunch({ test_id: "test-run-done" });
    });
  });

  it("calls onClose when clicking backdrop while idle", () => {
    const onClose = vi.fn();

    render(
      <TestRunModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking backdrop while launching", async () => {
    const user = userEvent.setup();
    let resolveLaunch: (value: unknown) => void = () => {};
    mockRunIsolatedTest.mockReturnValueOnce(
      new Promise((res) => {
        resolveLaunch = res;
      })
    );
    const onClose = vi.fn();

    render(
      <TestRunModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Launch Test Run" })).toBeInTheDocument();
    });

    const launchBtn = screen.getByRole("button", { name: "Launch Test Run" });
    await user.click(launchBtn);

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveLaunch({ test_id: "test-run-done" });
    });
  });

  it("does not call onClose when clicking inside dialog content", () => {
    const onClose = vi.fn();

    render(
      <TestRunModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Launch Isolated Bot Test" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog on open", async () => {
    render(
      <TestRunModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Launch Isolated Bot Test" });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
  });

  it("allows clearing numeric inputs with backspace and typing multi-digit numbers without forcing 1", async () => {
    render(
      <TestRunModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTestStarted={vi.fn()}
      />
    );

    const botInput = screen.getByLabelText<HTMLInputElement>("Verification Bot Count");
    expect(botInput.value).toBe("10");

    // Clear input completely to ""
    await act(async () => {
      fireEvent.change(botInput, { target: { value: "" } });
    });
    expect(botInput.value).toBe("");

    // Type a multi-digit number "25"
    await act(async () => {
      fireEvent.change(botInput, { target: { value: "25" } });
    });
    expect(botInput.value).toBe("25");

    // Stepper buttons
    const incBtn = screen.getByRole("button", { name: "Increase bot count" });
    const decBtn = screen.getByRole("button", { name: "Decrease bot count" });

    await act(async () => {
      fireEvent.click(incBtn);
    });
    expect(botInput.value).toBe("26");

    await act(async () => {
      fireEvent.click(decBtn);
    });
    expect(botInput.value).toBe("25");

    // Duration input
    const durationInput = screen.getByLabelText<HTMLInputElement>("Test Duration (Minutes)");
    expect(durationInput.value).toBe("15");

    await act(async () => {
      fireEvent.change(durationInput, { target: { value: "" } });
    });
    expect(durationInput.value).toBe("");

    await act(async () => {
      fireEvent.change(durationInput, { target: { value: "45" } });
    });
    expect(durationInput.value).toBe("45");
  });
});
