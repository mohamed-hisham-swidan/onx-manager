import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatCard } from "./StatCard";

describe("StatCard", () => {
  it("renders label and value", () => {
    render(<StatCard icon="server" label="Total" value={42} />);
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("renders an icon", () => {
    const { container } = render(<StatCard icon="backup" label="Backups" value={1} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("renders sublabel when provided", () => {
    render(<StatCard icon="check" label="Last" value="Alpha" sublabel="Jan 1" />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Jan 1")).toBeInTheDocument();
  });

  it("renders inset variant with bg-surface-muted and without border classes", () => {
    const { container } = render(<StatCard icon="server" label="Inset Stat" value={10} variant="inset" />);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("bg-surface-muted");
    expect(card.className).not.toMatch(/\bborder\b/);
    expect(card.className).not.toMatch(/\bborder-/);
  });
});
