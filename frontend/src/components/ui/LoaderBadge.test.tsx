import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LoaderBadge } from "./LoaderBadge";

describe("LoaderBadge", () => {
  it("renders Paper badge correctly", () => {
    render(<LoaderBadge loader="paper" />);
    expect(screen.getByText("Paper")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-teal-700");
  });

  it("renders Purpur badge correctly", () => {
    render(<LoaderBadge loader="purpur" />);
    expect(screen.getByText("Purpur")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-purple-700");
  });

  it("renders Fabric badge correctly", () => {
    render(<LoaderBadge loader="fabric" />);
    expect(screen.getByText("Fabric")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-sky-700");
  });

  it("renders Forge badge correctly", () => {
    render(<LoaderBadge loader="forge" />);
    expect(screen.getByText("Forge")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-amber-700");
  });

  it("renders NeoForge badge correctly", () => {
    render(<LoaderBadge loader="neoforge" />);
    expect(screen.getByText("NeoForge")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-orange-700");
  });

  it("renders Vanilla badge correctly", () => {
    render(<LoaderBadge loader="vanilla" />);
    expect(screen.getByText("Vanilla")).toBeInTheDocument();
    expect(screen.getByTestId("loader-badge")).toHaveClass("text-gray-700");
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
