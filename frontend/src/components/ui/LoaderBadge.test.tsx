import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LoaderBadge } from "./LoaderBadge";

describe("LoaderBadge", () => {
  it("renders Paper badge with semantic tokens", () => {
    render(<LoaderBadge loader="paper" />);
    const badge = screen.getByTestId("loader-badge");
    expect(screen.getByText("Paper")).toBeInTheDocument();
    expect(badge).toHaveClass("text-status-info");
    expect(badge.className).not.toMatch(/teal-|purple-|sky-|amber-|orange-|gray-/);
  });

  it("renders Purpur badge with semantic tokens", () => {
    render(<LoaderBadge loader="purpur" />);
    expect(screen.getByText("Purpur")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-text-accent");
  });

  it("renders Fabric badge with semantic tokens", () => {
    render(<LoaderBadge loader="fabric" />);
    expect(screen.getByText("Fabric")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-status-info");
  });

  it("renders Forge and NeoForge badges with semantic tokens", () => {
    const { rerender } = render(<LoaderBadge loader="forge" />);
    expect(screen.getByText("Forge")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-status-warning");

    rerender(<LoaderBadge loader="neoforge" />);
    expect(screen.getByText("NeoForge")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-status-warning");
  });

  it("renders Vanilla badge with semantic tokens", () => {
    render(<LoaderBadge loader="vanilla" />);
    expect(screen.getByText("Vanilla")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-text-secondary");
  });

  it("renders Folia, Velocity, BungeeCord, Waterfall, and Minestom badges", () => {
    const entries: Array<[string, string]> = [
      ["folia", "Folia"],
      ["velocity", "Velocity"],
      ["bungeecord", "BungeeCord"],
      ["waterfall", "Waterfall"],
      ["minestom", "Minestom"],
    ];

    for (const [loader, label] of entries) {
      const { unmount } = render(<LoaderBadge loader={loader} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("gracefully falls back for unknown loader type", () => {
    render(<LoaderBadge loader="custom_modded" />);
    expect(screen.getByText("Custom_modded")).toBeInTheDocument();
  });

  it("handles null or undefined loader gracefully", () => {
    render(<LoaderBadge loader={null} />);
    expect(screen.getByText("Universal")).toBeInTheDocument();
  });
});
