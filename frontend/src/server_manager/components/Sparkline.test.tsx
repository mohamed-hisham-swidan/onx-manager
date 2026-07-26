import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders svg with data points", () => {
    const { container } = render(<Sparkline data={[1, 2, 3, 4, 5]} />);
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(container.querySelector("polyline")).toBeInTheDocument();
    expect(container.querySelector("polygon")).toBeInTheDocument();
  });

  it("renders placeholder for single point", () => {
    const { container } = render(<Sparkline data={[1]} />);
    expect(container.querySelector("svg")).not.toBeInTheDocument();
  });
});
