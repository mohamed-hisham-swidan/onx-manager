import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { VoxelBanner } from "./VoxelBanner";

describe("VoxelBanner Component (Phase 7)", () => {
  it("renders dashboard panoramic banner with crisp edges and svg grid", () => {
    const { container } = render(<VoxelBanner variant="dashboard" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("shape-rendering", "crispEdges");
    expect(svg?.querySelectorAll("rect").length).toBeGreaterThan(10);
  });

  it("renders auth variant with compact voxel cluster", () => {
    const { container } = render(<VoxelBanner variant="auth" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("shape-rendering", "crispEdges");
  });

  it("renders empty state variant with floating isometric voxel cubes", () => {
    const { container } = render(<VoxelBanner variant="empty" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg?.querySelectorAll("polygon").length).toBeGreaterThan(4);
  });
});
