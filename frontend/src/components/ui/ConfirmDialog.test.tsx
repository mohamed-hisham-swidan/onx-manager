import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <ConfirmDialog open={false} title="Delete?" onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders title and description when open", () => {
    render(
      <ConfirmDialog open title="Delete server?" description="This cannot be undone." onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(screen.getByText("Delete server?")).toBeInTheDocument();
    expect(screen.getByText("This cannot be undone.")).toBeInTheDocument();
  });

  it("calls onConfirm when confirm button clicked", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog open title="Delete?" onConfirm={onConfirm} onCancel={() => {}} />);
    fireEvent.click(screen.getByText("Confirm"));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("calls onCancel when cancel button clicked", () => {
    const onCancel = vi.fn();
    render(<ConfirmDialog open title="Delete?" onConfirm={() => {}} onCancel={onCancel} />);
    fireEvent.click(screen.getByText("Cancel"));
    expect(onCancel).toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    const onCancel = vi.fn();
    render(<ConfirmDialog open title="Delete?" onConfirm={() => {}} onCancel={onCancel} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });

  it("sets initial focus to the confirm button on open for non-danger variants", () => {
    render(<ConfirmDialog open variant="info" title="Continue?" onConfirm={() => {}} onCancel={() => {}} />);
    const confirmBtn = screen.getByText("Confirm");
    expect(document.activeElement).toBe(confirmBtn);
  });

  it("sets initial focus to the cancel button on open for danger variant", () => {
    render(<ConfirmDialog open variant="danger" title="Delete permanently?" onConfirm={() => {}} onCancel={() => {}} />);
    const cancelBtn = screen.getByText("Cancel");
    expect(document.activeElement).toBe(cancelBtn);
  });

  it("traps focus with Tab and Shift+Tab", () => {
    render(<ConfirmDialog open variant="info" title="Proceed?" onConfirm={() => {}} onCancel={() => {}} />);
    const confirmBtn = screen.getByText("Confirm");
    const cancelBtn = screen.getByText("Cancel");

    // Initially focused on confirmBtn (last element)
    expect(document.activeElement).toBe(confirmBtn);

    // Tab on last element wraps to first element (cancelBtn)
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(cancelBtn);

    // Shift+Tab on first element wraps back to last element (confirmBtn)
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirmBtn);
  });

  it("restores focus to previously active element on close", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Open Dialog";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { unmount } = render(
      <ConfirmDialog open variant="info" title="Delete?" onConfirm={() => {}} onCancel={() => {}} />
    );
    expect(document.activeElement).toBe(screen.getByText("Confirm"));

    unmount();
    expect(document.activeElement).toBe(trigger);
    document.body.removeChild(trigger);
  });
});
