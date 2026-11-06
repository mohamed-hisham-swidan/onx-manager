import React, { useState } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Modal } from "./Modal";
import { ConfirmDialog } from "./ConfirmDialog";

describe("Modal Primitive", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <Modal open={false} onClose={() => {}}>
        <div>Modal Content</div>
      </Modal>
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders title, description and content when open", () => {
    render(
      <Modal open onClose={() => {}} title="Test Title" description="Test Description">
        <div>Modal Content</div>
      </Modal>
    );
    expect(screen.getByText("Test Title")).toBeInTheDocument();
    expect(screen.getByText("Test Description")).toBeInTheDocument();
    expect(screen.getByText("Modal Content")).toBeInTheDocument();
  });

  it("calls onClose when close button clicked", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Test Title">
        <div>Content</div>
      </Modal>
    );
    fireEvent.click(screen.getByLabelText("Close dialog"));
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose on Escape key press", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Test Title">
        <div>Content</div>
      </Modal>
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when backdrop is clicked by default", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} title="Test Title">
        <div>Content</div>
      </Modal>
    );
    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when backdrop is clicked if closeOnBackdrop is false", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} closeOnBackdrop={false} title="Test Title">
        <div>Content</div>
      </Modal>
    );
    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does not call onClose on Escape when closeOnEscape is false", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} closeOnEscape={false} title="Test Title">
        <div>Content</div>
      </Modal>
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("calls onClose on Escape when closeOnEscape is true", () => {
    const onClose = vi.fn();
    render(
      <Modal open onClose={onClose} closeOnEscape={true} title="Test Title">
        <div>Content</div>
      </Modal>
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders size='2xl' with max-w-3xl class", () => {
    render(
      <Modal open onClose={() => {}} size="2xl" title="2XL Modal">
        <div>Content</div>
      </Modal>
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveClass("max-w-3xl");
  });

  it("traps focus between focusable elements", () => {
    render(
      <Modal open onClose={() => {}} title="Test Title">
        <button>First Action</button>
        <button>Second Action</button>
      </Modal>
    );
    const closeBtn = screen.getByLabelText("Close dialog");
    const firstBtn = screen.getByText("First Action");
    const secondBtn = screen.getByText("Second Action");

    // Close button, first, and second buttons are present
    expect(closeBtn).toBeInTheDocument();
    expect(firstBtn).toBeInTheDocument();
    expect(secondBtn).toBeInTheDocument();
  });

  describe("body scroll lock", () => {
    it("locks body scroll on open and restores previous overflow on close", () => {
      document.body.style.overflow = "auto";
      const { rerender, unmount } = render(
        <Modal open={true} onClose={() => {}}>
          <div>Content</div>
        </Modal>
      );
      expect(document.body.style.overflow).toBe("hidden");

      rerender(
        <Modal open={false} onClose={() => {}}>
          <div>Content</div>
        </Modal>
      );
      expect(document.body.style.overflow).toBe("auto");

      // Reset
      document.body.style.overflow = "";
      unmount();
    });

    it("two stacked modals restore body scroll only after the second closes", () => {
      document.body.style.overflow = "";

      const { unmount: unmountFirst } = render(
        <Modal open={true} onClose={() => {}}>
          <div>First Modal</div>
        </Modal>
      );
      expect(document.body.style.overflow).toBe("hidden");

      const { unmount: unmountSecond } = render(
        <Modal open={true} onClose={() => {}}>
          <div>Second Modal</div>
        </Modal>
      );
      expect(document.body.style.overflow).toBe("hidden");

      // Close second modal
      unmountSecond();
      // First modal is still open, body scroll must remain locked
      expect(document.body.style.overflow).toBe("hidden");

      // Close first modal
      unmountFirst();
      // Both modals are closed, body scroll must be restored
      expect(document.body.style.overflow).toBe("");
    });
  });

  describe("focus management and stacking hardening", () => {
    it("returns focus to the opener element when closed", () => {
      const opener = document.createElement("button");
      opener.textContent = "Open Modal";
      document.body.appendChild(opener);
      opener.focus();
      expect(document.activeElement).toBe(opener);

      const { rerender } = render(
        <Modal open={true} onClose={() => {}} title="Test Modal">
          <button>Inside Action</button>
        </Modal>
      );

      // Close the modal
      rerender(
        <Modal open={false} onClose={() => {}} title="Test Modal">
          <button>Inside Action</button>
        </Modal>
      );

      expect(document.activeElement).toBe(opener);
      document.body.removeChild(opener);
    });

    it("retains focus inside dialog when closeOnEscape is toggled while open", async () => {
      const opener = document.createElement("button");
      opener.textContent = "Opener";
      document.body.appendChild(opener);
      opener.focus();
      expect(document.activeElement).toBe(opener);

      const { rerender } = render(
        <Modal open={true} closeOnEscape={true} onClose={() => {}} title="Dynamic Modal">
          <button>Inside Action</button>
        </Modal>
      );

      const insideBtn = screen.getByText("Inside Action");
      await waitFor(() => {
        expect(document.activeElement).not.toBe(opener);
      });
      insideBtn.focus();
      expect(insideBtn).toHaveFocus();

      // Toggle closeOnEscape to false while dialog remains open
      rerender(
        <Modal open={true} closeOnEscape={false} onClose={() => {}} title="Dynamic Modal">
          <button>Inside Action</button>
        </Modal>
      );

      expect(document.activeElement).not.toBe(opener);
      expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);

      // Toggle closeOnEscape back to true while dialog remains open
      rerender(
        <Modal open={true} closeOnEscape={true} onClose={() => {}} title="Dynamic Modal">
          <button>Inside Action</button>
        </Modal>
      );

      expect(document.activeElement).not.toBe(opener);
      expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);

      document.body.removeChild(opener);
    });

    it("waits for initial focus inside dialog before verifying focus returns to opener on close", async () => {
      const opener = document.createElement("button");
      opener.textContent = "Opener Button";
      document.body.appendChild(opener);
      opener.focus();
      expect(document.activeElement).toBe(opener);

      const { rerender } = render(
        <Modal open={true} onClose={() => {}} title="Focus Return Modal">
          <button>Action Button</button>
        </Modal>
      );

      const actionBtn = screen.getByText("Action Button");
      await waitFor(() => {
        expect(document.activeElement).not.toBe(opener);
      });

      // Explicitly move focus inside dialog
      actionBtn.focus();
      expect(actionBtn).toHaveFocus();

      // Close the modal
      rerender(
        <Modal open={false} onClose={() => {}} title="Focus Return Modal">
          <button>Action Button</button>
        </Modal>
      );

      expect(document.activeElement).toBe(opener);
      document.body.removeChild(opener);
    });

    it("cycles focus with Tab and Shift+Tab within the dialog", () => {
      render(
        <Modal open onClose={() => {}} title="Test Title">
          <button>First Item</button>
          <button>Last Item</button>
        </Modal>
      );

      const closeBtn = screen.getByLabelText("Close dialog");
      const firstBtn = screen.getByText("First Item");
      const lastBtn = screen.getByText("Last Item");
      expect(firstBtn).toBeInTheDocument();

      // Focus last item, press Tab -> wraps to first focusable element (closeBtn)
      lastBtn.focus();
      expect(document.activeElement).toBe(lastBtn);

      fireEvent.keyDown(window, { key: "Tab", shiftKey: false });
      expect(document.activeElement).toBe(closeBtn);

      // Focus close button, press Shift+Tab -> wraps to last focusable element (lastBtn)
      closeBtn.focus();
      expect(document.activeElement).toBe(closeBtn);

      fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
      expect(document.activeElement).toBe(lastBtn);
    });

    it("supports stacking a ConfirmDialog opened from within a Modal", () => {
      function StackedComponent() {
        const [confirmOpen, setConfirmOpen] = useState(false);
        return (
          <Modal open={true} onClose={() => {}} title="Parent Modal">
            <button onClick={() => setConfirmOpen(true)}>Trigger Confirm</button>
            <ConfirmDialog
              open={confirmOpen}
              title="Confirm Action"
              onConfirm={() => setConfirmOpen(false)}
              onCancel={() => setConfirmOpen(false)}
            />
          </Modal>
        );
      }

      render(<StackedComponent />);
      expect(screen.getByRole("dialog", { name: "Parent Modal" })).toBeInTheDocument();
      expect(screen.queryByRole("dialog", { name: "Confirm Action" })).not.toBeInTheDocument();

      fireEvent.click(screen.getByText("Trigger Confirm"));

      // Both dialogs exist in DOM; confirm is on top
      const dialogs = screen.getAllByRole("dialog");
      expect(dialogs).toHaveLength(2);
      expect(screen.getByRole("dialog", { name: "Confirm Action" })).toBeInTheDocument();

      // Confirm cancellation
      fireEvent.click(screen.getByText("Cancel"));
      expect(screen.queryByRole("dialog", { name: "Confirm Action" })).not.toBeInTheDocument();
      expect(screen.getByRole("dialog", { name: "Parent Modal" })).toBeInTheDocument();
    });
  });
});
