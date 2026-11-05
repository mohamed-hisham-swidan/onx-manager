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
});
