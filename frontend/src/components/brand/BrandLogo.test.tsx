import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrandLogo } from "./BrandLogo";

describe("BrandLogo Component (Phase 7)", () => {
  it("renders full lockup with SVG vortex mark and wordmark", () => {
    const { container } = render(<BrandLogo variant="full" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(screen.getByText("ONX")).toBeInTheDocument();
    expect(screen.getByText("Manager")).toBeInTheDocument();
  });

  it("renders mark-only variant without text wordmark", () => {
    const { container } = render(<BrandLogo variant="mark" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(screen.queryByText("ONX")).not.toBeInTheDocument();
  });

  it("renders wordmark-only variant without vortex mark svg", () => {
    const { container } = render(<BrandLogo variant="wordmark" />);
    expect(container.querySelector("svg")).not.toBeInTheDocument();
    expect(screen.getByText("ONX")).toBeInTheDocument();
  });

  it("supports monochrome styling with currentColor fill and stroke", () => {
    const { container } = render(<BrandLogo variant="mark" monochrome={true} />);
    const circle = container.querySelector("circle");
    expect(circle).toHaveAttribute("fill", "currentColor");
  });

  it("applies customized size attributes", () => {
    const { container } = render(<BrandLogo variant="mark" size="lg" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "48");
    expect(svg).toHaveAttribute("height", "48");
  });
});
