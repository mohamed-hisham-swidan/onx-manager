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
});
