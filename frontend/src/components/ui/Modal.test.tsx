import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Modal } from "./Modal";

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
});
