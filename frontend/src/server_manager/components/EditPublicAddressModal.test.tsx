import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EditPublicAddressModal } from "./EditPublicAddressModal";
import type { TargetResponse } from "@/types";

const mockTarget: TargetResponse = {
  id: "target-1",
  exposure_id: "exp-1",
  service_type: "java",
  protocol: "tcp",
  local_port: 25565,
  public_address: "play.example.com:25565",
  status: "ACTIVE",
  error_code: null,
  error_message: null,
  dashboard_url: null,
  setup_instructions: null,
};

describe("EditPublicAddressModal Component", () => {
  it("does not render when isOpen is false or target is null", () => {
    const { rerender } = render(
      <EditPublicAddressModal
        isOpen={false}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
        target={mockTarget}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    rerender(
      <EditPublicAddressModal
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
        target={null}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders role='dialog' with accessible name, acquires scroll lock, and releases on unmount", () => {
    document.body.style.overflow = "";
    const { unmount } = render(
      <EditPublicAddressModal
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
        target={mockTarget}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Update Public Address" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes on Escape key when idle", () => {
    const onClose = vi.fn();
    render(
      <EditPublicAddressModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        target={mockTarget}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape when isSubmitting is true", () => {
    const onClose = vi.fn();
    render(
      <EditPublicAddressModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        target={mockTarget}
        isSubmitting={true}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does NOT close on backdrop click when idle (closeOnBackdrop=false)", () => {
    const onClose = vi.fn();
    render(
      <EditPublicAddressModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        target={mockTarget}
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
      <EditPublicAddressModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        target={mockTarget}
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
      <EditPublicAddressModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        target={mockTarget}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Update Public Address" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("moves focus to the address input on open", async () => {
    render(
      <EditPublicAddressModal
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={vi.fn()}
        target={mockTarget}
      />
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const input = screen.getByLabelText("Public Address *");
    expect(document.activeElement).toBe(input);
  });

  it("disables Cancel and Save Address buttons and ignores close button when isSubmitting is true", () => {
    const onClose = vi.fn();
    render(
      <EditPublicAddressModal
        isOpen={true}
        onClose={onClose}
        onSubmit={vi.fn()}
        target={mockTarget}
        isSubmitting={true}
      />
    );

    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Saving Address.../i })).toBeDisabled();

    const closeBtn = screen.getByRole("button", { name: "Close dialog" });
    fireEvent.click(closeBtn);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("submits updated address successfully", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <EditPublicAddressModal
        isOpen={true}
        onClose={vi.fn()}
        onSubmit={onSubmit}
        target={mockTarget}
      />
    );

    const input = screen.getByLabelText("Public Address *");
    await user.clear(input);
    await user.type(input, "new.mc.server:25565");

    const submitBtn = screen.getByRole("button", { name: "Save Address" });
    await user.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledWith("new.mc.server:25565");
  });
});
