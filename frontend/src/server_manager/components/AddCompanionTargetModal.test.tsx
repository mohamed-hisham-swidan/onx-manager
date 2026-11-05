import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AddCompanionTargetModal } from "./AddCompanionTargetModal";

describe("AddCompanionTargetModal Component", () => {
  it("does not render when isOpen is false", () => {
    render(
      <AddCompanionTargetModal
        isOpen={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders role='dialog' with accessible name, acquires scroll lock, and releases on unmount", () => {
    document.body.style.overflow = "";
    const { unmount } = render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Add Companion Service Target" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes on Escape key when idle", () => {
    const onClose = vi.fn();
    render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape when isSubmitting is true", () => {
    const onClose = vi.fn();
    render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        isSubmitting={true}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does NOT close on backdrop click when idle (closeOnBackdrop=false)", () => {
    const onClose = vi.fn();
    render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close on backdrop click while isSubmitting is true", () => {
    const onClose = vi.fn();
    render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        isSubmitting={true}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not close when clicking inside dialog content", () => {
    const onClose = vi.fn();
    render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Add Companion Service Target" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("moves focus to the port input on open", async () => {
    render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const portInput = screen.getByLabelText(/Local Service Port/i);
    expect(document.activeElement).toBe(portInput);
  });

  it("disables Cancel and Add Target buttons and ignores close button when isSubmitting is true", () => {
    const onClose = vi.fn();
    render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        isSubmitting={true}
      />
    );

    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Creating Target.../i })).toBeDisabled();

    const closeBtn = screen.getByRole("button", { name: "Close dialog" });
    fireEvent.click(closeBtn);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("submits the form with selected companion service and port", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <AddCompanionTargetModal
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />
    );

    // Click "Simple Voice Chat"
    const voiceBtn = screen.getByRole("button", { name: /Simple Voice Chat/i });
    await user.click(voiceBtn);

    const submitBtn = screen.getByRole("button", { name: "Add Target" });
    await user.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledWith({
      service_type: "voice",
      protocol: "udp",
      local_port: 24454,
    });
  });
});
