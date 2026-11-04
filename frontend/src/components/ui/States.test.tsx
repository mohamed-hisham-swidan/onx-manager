import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EmptyState, ErrorState, Skeleton, ForbiddenState } from "./States";

describe("State Feedback Primitives", () => {
  it("renders EmptyState with action", () => {
    const onAction = vi.fn();
    render(
      <EmptyState
        title="No servers found"
        description="Get started by deploying your first server."
        action={{ label: "Create Server", onClick: onAction }}
      />
    );
    expect(screen.getByText("No servers found")).toBeInTheDocument();
    expect(screen.getByText("Get started by deploying your first server.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create Server" }));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("renders ErrorState with retry button", () => {
    const onRetry = vi.fn();
    render(<ErrorState title="Connection failed" onRetry={onRetry} />);
    expect(screen.getByText("Connection failed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try Again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders Skeleton elements", () => {
    const { container } = render(<Skeleton count={3} />);
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(3);
  });

  it("renders ForbiddenState", () => {
    render(<ForbiddenState title="Restricted Area" />);
    expect(screen.getByText("Restricted Area")).toBeInTheDocument();
  });
});
