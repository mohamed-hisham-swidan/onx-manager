import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Skeleton, TableSkeleton } from "./Skeleton";

describe("Skeleton", () => {
  it("renders a single line", () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("renders multiple lines", () => {
    const { container } = render(<Skeleton lines={3} />);
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(3);
  });

  it("applies custom className", () => {
    const { container } = render(<Skeleton className="w-32" />);
    expect(container.querySelector(".w-32")).toBeInTheDocument();
  });
});

describe("TableSkeleton", () => {
  it("renders with correct row count", () => {
    const { container } = render(<TableSkeleton rows={3} cols={4} />);
    const rows = container.querySelectorAll(".border-b");
    expect(rows.length).toBe(4); // header + 3 rows
  });
});
