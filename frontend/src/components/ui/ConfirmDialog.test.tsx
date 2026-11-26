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

  describe("pending guard", () => {
    it("disables Confirm and Cancel buttons and sets aria-busy while pending", () => {
      render(
        <ConfirmDialog
          open
          title="Delete?"
          isPending={true}
          onConfirm={() => {}}
          onCancel={() => {}}
        />
      );

      const confirmBtn = screen.getByRole("button", { name: "Confirm" });
      const cancelBtn = screen.getByRole("button", { name: "Cancel" });
      const dialog = screen.getByRole("dialog");

      expect(confirmBtn).toBeDisabled();
      expect(cancelBtn).toBeDisabled();
      expect(dialog).toHaveAttribute("aria-busy", "true");
    });

    it("ignores Escape when pending", () => {
      const onCancel = vi.fn();
      render(
        <ConfirmDialog
          open
          title="Delete?"
          isPending={true}
          onConfirm={() => {}}
          onCancel={onCancel}
        />
      );

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onCancel).not.toHaveBeenCalled();
    });

    it("ignores backdrop click when pending", () => {
      const onCancel = vi.fn();
      const { container } = render(
        <ConfirmDialog
          open
          title="Delete?"
          isPending={true}
          onConfirm={() => {}}
          onCancel={onCancel}
        />
      );

      const backdrop = container.querySelector('[aria-hidden="true"]');
      expect(backdrop).not.toBeNull();
      fireEvent.click(backdrop!);
      expect(onCancel).not.toHaveBeenCalled();
    });

    it("prevents second confirm click while pending", () => {
      const onConfirm = vi.fn();
      const { rerender } = render(
        <ConfirmDialog
          open
          title="Delete?"
          isPending={false}
          onConfirm={onConfirm}
          onCancel={() => {}}
        />
      );

      const confirmBtn = screen.getByRole("button", { name: "Confirm" });
      fireEvent.click(confirmBtn);
      expect(onConfirm).toHaveBeenCalledTimes(1);

      // Now pending
      rerender(
        <ConfirmDialog
          open
          title="Delete?"
          isPending={true}
          onConfirm={onConfirm}
          onCancel={() => {}}
        />
      );

      fireEvent.click(confirmBtn);
      // Still only called once
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it("allows cancel and confirm when not pending", () => {
      const onCancel = vi.fn();
      const onConfirm = vi.fn();
      render(
        <ConfirmDialog
          open
          title="Delete?"
          isPending={false}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );

      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      expect(onCancel).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });
  });

  it("renders children callout and uses semantic contrast tokens instead of hardcoded white/black", () => {
    render(
      <ConfirmDialog
        open
        variant="danger"
        title="Restore backup?"
        description="Confirm restore."
        onConfirm={() => {}}
        onCancel={() => {}}
      >
        <div data-testid="running-callout">Server is running</div>
      </ConfirmDialog>,
    );

    expect(screen.getByTestId("running-callout")).toBeInTheDocument();
    const confirmBtn = screen.getByRole("button", { name: "Confirm" });
    expect(confirmBtn.className).toContain("text-text-inverse");
    expect(confirmBtn.className).not.toContain("text-white");
    expect(confirmBtn.className).not.toContain("text-black");
  });
});
