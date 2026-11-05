import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Tabs } from "./Tabs";

describe("Tabs Primitive", () => {
  const items = [
    { id: "overview", label: "Overview", count: 3 },
    { id: "files", label: "Files" },
    { id: "settings", label: "Settings", disabled: true },
  ];

  it("renders tab items with appropriate ARIA attributes without dangling aria-controls", () => {
    render(<Tabs value="overview" onChange={() => {}} items={items} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");
    expect(tabs[0]).toHaveAttribute("tabindex", "0");
    expect(tabs[1]).toHaveAttribute("tabindex", "-1");
    // aria-controls is omitted to avoid dangling id references since tabs are consumed without tabpanel ids
    expect(tabs[0]).not.toHaveAttribute("aria-controls");
    expect(tabs[1]).not.toHaveAttribute("aria-controls");
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("calls onChange on click", () => {
    const onChange = vi.fn();
    render(<Tabs value="overview" onChange={onChange} items={items} />);
    fireEvent.click(screen.getByText("Files"));
    expect(onChange).toHaveBeenCalledWith("files");
  });

  it("does not call onChange on disabled tab click", () => {
    const onChange = vi.fn();
    render(<Tabs value="overview" onChange={onChange} items={items} />);
    fireEvent.click(screen.getByText("Settings"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("navigates with ArrowRight and ArrowLeft keys", () => {
    const onChange = vi.fn();
    render(<Tabs value="overview" onChange={onChange} items={items} />);
    const overviewTab = screen.getByRole("tab", { name: /overview/i });
    overviewTab.focus();

    fireEvent.keyDown(overviewTab, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("files");

    fireEvent.keyDown(overviewTab, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenCalledWith("files");
  });

  it("navigates to first and last enabled tabs with Home and End keys", () => {
    const onChange = vi.fn();
    render(<Tabs value="overview" onChange={onChange} items={items} />);
    const overviewTab = screen.getByRole("tab", { name: /overview/i });
    overviewTab.focus();

    fireEvent.keyDown(overviewTab, { key: "End" });
    expect(onChange).toHaveBeenCalledWith("files"); // 'settings' is disabled, so skips to last enabled 'files'

    fireEvent.keyDown(overviewTab, { key: "Home" });
    expect(onChange).toHaveBeenCalledWith("overview");
  });
});
