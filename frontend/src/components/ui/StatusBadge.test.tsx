import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("maps known statuses to friendly labels", () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByText("Online")).toBeInTheDocument();
  });

  it("falls back to raw status for unknown values", () => {
    render(<StatusBadge status="mystery" />);
    expect(screen.getByText("mystery")).toBeInTheDocument();
  });

  it("shows a status dot", () => {
    const { container } = render(<StatusBadge status="running" />);
    expect(container.querySelector("span > span")).toBeInTheDocument();
  });
});
