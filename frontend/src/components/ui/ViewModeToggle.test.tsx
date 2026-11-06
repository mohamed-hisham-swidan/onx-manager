import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ViewModeToggle } from "./ViewModeToggle";

describe("ViewModeToggle", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("renders both Cards and List buttons with correct pressed state", () => {
    render(<ViewModeToggle mode="grid" onChange={() => {}} />);

    const gridBtn = screen.getByRole("button", { name: "Grid card view" });
    const listBtn = screen.getByRole("button", { name: "Compact list view" });

    expect(gridBtn).toBeInTheDocument();
    expect(listBtn).toBeInTheDocument();
    expect(gridBtn).toHaveAttribute("aria-pressed", "true");
    expect(listBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onChange when clicking a view option", async () => {
    const user = userEvent.setup();
    const handleChange = vi.fn();

    render(<ViewModeToggle mode="grid" onChange={handleChange} />);

    const listBtn = screen.getByRole("button", { name: "Compact list view" });
    await user.click(listBtn);

    expect(handleChange).toHaveBeenCalledWith("list");
  });

  it("persists to and reads from localStorage when storageKey is provided", () => {
    localStorage.setItem("test_view_mode", "list");
    const handleChange = vi.fn();

    render(
      <ViewModeToggle
        mode="grid"
        onChange={handleChange}
        storageKey="test_view_mode"
      />
    );

    expect(handleChange).toHaveBeenCalledWith("list");
  });
});
