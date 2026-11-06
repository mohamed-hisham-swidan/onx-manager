import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TestDefinitionsModal } from "./TestDefinitionsModal";
import type { TestDefinition } from "@/server_manager/types";

const mockGetTestDefinitions = vi.fn();
const mockCreateTestDefinition = vi.fn();
const mockDeleteTestDefinition = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getTestDefinitions: mockGetTestDefinitions,
    createTestDefinition: mockCreateTestDefinition,
    deleteTestDefinition: mockDeleteTestDefinition,
  }),
}));

const mockToast = vi.fn();
vi.mock("@/stores/toastStore", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

const sampleDefinitions: TestDefinition[] = [
  {
    id: "def-1",
    server_id: "srv-1",
    name: "Standard 10-Bot Stress Test",
    description: "Purpur stress run before promoting updates",
    server_type: "paper",
    bot_technology: "auto",
    bot_count: 10,
    duration_seconds: 900,
    join_stagger_seconds: 1,
    connect_grace_seconds: 30,
    placement_mode: "sidecar",
    assertion_rules: {},
    timeout_seconds: 1200,
    created_at: "2026-09-18T10:00:00Z",
    updated_at: "2026-09-18T10:00:00Z",
  },
];

describe("TestDefinitionsModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetTestDefinitions.mockResolvedValue(sampleDefinitions);
  });

  it("does not render when isOpen is false", () => {
    render(
      <TestDefinitionsModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders role='dialog' with accessible name, locks body scroll, and releases on unmount", () => {
    document.body.style.overflow = "";

    const { unmount } = render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Reusable Test Profiles" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("fetches and renders test definition profiles when open", async () => {
    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Reusable Test Profiles")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockGetTestDefinitions).toHaveBeenCalledWith("srv-1");
    });

    expect(screen.getByText("Standard 10-Bot Stress Test")).toBeInTheDocument();
    expect(screen.getByText(/10 bots • 15m/)).toBeInTheDocument();
    expect(screen.getByText("Purpur stress run before promoting updates")).toBeInTheDocument();
  });

  it("creates a new test profile successfully", async () => {
    const user = userEvent.setup();
    mockCreateTestDefinition.mockResolvedValueOnce({ success: true });
    const onDefinitionsChanged = vi.fn();

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={onDefinitionsChanged}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "New Profile" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "New Profile" }));

    const nameInput = screen.getByPlaceholderText("e.g. Standard 10-Bot Stress Test");
    fireEvent.change(nameInput, { target: { value: "Extreme 20-Bot Test" } });

    const saveBtn = screen.getByRole("button", { name: "Save Profile" });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockCreateTestDefinition).toHaveBeenCalledWith("srv-1", {
        name: "Extreme 20-Bot Test",
        description: undefined,
        bot_count: 10,
        duration_seconds: 900,
        placement_mode: "sidecar",
        bot_technology: "auto",
      });
      expect(mockToast).toHaveBeenCalledWith("success", "Profile Created", expect.stringContaining("Extreme 20-Bot Test"));
      expect(onDefinitionsChanged).toHaveBeenCalled();
    });
  });

  it("displays error message when createTestDefinition fails", async () => {
    const user = userEvent.setup();
    mockCreateTestDefinition.mockRejectedValueOnce(new Error("Profile name already exists"));

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "New Profile" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "New Profile" }));

    const nameInput = screen.getByPlaceholderText("e.g. Standard 10-Bot Stress Test");
    fireEvent.change(nameInput, { target: { value: "Duplicate Profile" } });

    const saveBtn = screen.getByRole("button", { name: "Save Profile" });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText("Profile name already exists")).toBeInTheDocument();
    });
  });

  it("closes on Escape key press when idle", () => {
    const onClose = vi.fn();

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape and disables cancel button while submitting", async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: unknown) => void = () => {};
    mockCreateTestDefinition.mockReturnValueOnce(
      new Promise((res) => {
        resolveCreate = res;
      })
    );
    const onClose = vi.fn();

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "New Profile" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "New Profile" }));

    const nameInput = screen.getByPlaceholderText("e.g. Standard 10-Bot Stress Test");
    fireEvent.change(nameInput, { target: { value: "Pending Profile" } });

    const saveBtn = screen.getByRole("button", { name: "Save Profile" });
    await user.click(saveBtn);

    // Cancel buttons in form should be disabled
    const cancelBtns = screen.getAllByRole("button", { name: "Cancel" });
    expect(cancelBtns.length).toBeGreaterThan(0);
    cancelBtns.forEach((btn) => expect(btn).toBeDisabled());

    // Escape should be ignored while submitting
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveCreate({ success: true });
    });
  });

  it("calls onClose when clicking backdrop while idle", () => {
    const onClose = vi.fn();

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking backdrop while submitting", async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: unknown) => void = () => {};
    mockCreateTestDefinition.mockReturnValueOnce(
      new Promise((res) => {
        resolveCreate = res;
      })
    );
    const onClose = vi.fn();

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "New Profile" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "New Profile" }));

    const nameInput = screen.getByPlaceholderText("e.g. Standard 10-Bot Stress Test");
    fireEvent.change(nameInput, { target: { value: "Pending Profile" } });

    const saveBtn = screen.getByRole("button", { name: "Save Profile" });
    await user.click(saveBtn);

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveCreate({ success: true });
    });
  });

  it("does not call onClose when clicking inside dialog content", () => {
    const onClose = vi.fn();

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Reusable Test Profiles" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog on open", async () => {
    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Reusable Test Profiles" });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
  });

  it("opens ConfirmDialog on delete click and calls deleteTestDefinition on confirm", async () => {
    mockDeleteTestDefinition.mockResolvedValue({ success: true });

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Delete profile" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete profile" }));

    // Confirm dialog should open
    expect(screen.getByRole("dialog", { name: "Delete Test Profile" })).toBeInTheDocument();
    expect(
      screen.getByText(/Delete test profile 'Standard 10-Bot Stress Test'\? This action cannot be undone\./i)
    ).toBeInTheDocument();

    // Confirm deletion
    const confirmButton = screen.getByRole("button", { name: "Delete Profile" });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mockDeleteTestDefinition).toHaveBeenCalledWith("srv-1", "def-1");
    });
  });

  it("closes ConfirmDialog without deleting when Cancel is clicked", async () => {
    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Delete profile" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete profile" }));

    expect(screen.getByRole("dialog", { name: "Delete Test Profile" })).toBeInTheDocument();

    const cancelButton = screen.getByRole("button", { name: "Cancel" });
    fireEvent.click(cancelButton);

    expect(screen.queryByRole("dialog", { name: "Delete Test Profile" })).not.toBeInTheDocument();
    expect(mockDeleteTestDefinition).not.toHaveBeenCalled();
  });

  it("guards against double-click on delete confirm button triggering only one API call", async () => {
    let resolveDelete: (val?: unknown) => void = () => {};
    mockDeleteTestDefinition.mockImplementationOnce(() => new Promise((resolve) => {
      resolveDelete = resolve;
    }));

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Delete profile" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete profile" }));
    const confirmButton = screen.getByRole("button", { name: "Delete Profile" });

    // Click twice rapidly
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    expect(mockDeleteTestDefinition).toHaveBeenCalledTimes(1);
    resolveDelete({ success: true });
  });

  it("allows retrying delete if an initial delete attempt fails with an error", async () => {
    mockDeleteTestDefinition.mockRejectedValueOnce(new Error("Server error"));

    render(
      <TestDefinitionsModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        onDefinitionsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Delete profile" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete profile" }));
    const confirmButton = screen.getByRole("button", { name: "Delete Profile" });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mockDeleteTestDefinition).toHaveBeenCalledTimes(1);
    });

    // Second attempt after failure succeeds
    mockDeleteTestDefinition.mockResolvedValueOnce({ success: true });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Delete profile" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete profile" }));
    const retryConfirmBtn = screen.getByRole("button", { name: "Delete Profile" });
    fireEvent.click(retryConfirmBtn);

    await waitFor(() => {
      expect(mockDeleteTestDefinition).toHaveBeenCalledTimes(2);
    });
  });
});
