import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Chip } from "./Chip";

describe("Chip Primitive", () => {
  it("renders chip label", () => {
    render(<Chip label="Vanilla 1.21.1" />);
    expect(screen.getByText("Vanilla 1.21.1")).toBeInTheDocument();
  });

  it("handles click when interactive", () => {
    const onClick = vi.fn();
    render(<Chip label="Active" onClick={onClick} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalled();
  });

  it("calls onRemove when remove icon is clicked", () => {
    const onRemove = vi.fn();
    render(<Chip label="Filter" onRemove={onRemove} />);
    fireEvent.click(screen.getByLabelText("Remove"));
    expect(onRemove).toHaveBeenCalled();
  });

  it("renders inset variant with bg-surface-muted and without border classes", () => {
    const { container } = render(<Chip label="Inset Chip" variant="inset" />);
    const chip = container.firstChild as HTMLElement;
    expect(chip.className).toContain("bg-surface-muted");
    expect(chip.className).not.toMatch(/\bborder\b/);
    expect(chip.className).not.toMatch(/\bborder-/);
  });
});
