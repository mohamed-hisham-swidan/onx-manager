import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ComingSoonState } from "./ComingSoonState";

describe("ComingSoonState", () => {
  it("renders title, description, and badge", () => {
    render(
      <ComingSoonState
        title="Feature Coming Soon"
        description="This feature is under development."
        badge="Soon"
      />,
    );
    expect(screen.getByText("Feature Coming Soon")).toBeInTheDocument();
    expect(screen.getByText("This feature is under development.")).toBeInTheDocument();
    expect(screen.getByText("Soon")).toBeInTheDocument();
  });

  it("renders with default badge 'Coming Soon'", () => {
    render(<ComingSoonState title="Feature Coming Soon" />);
    expect(screen.getByText("Coming Soon")).toBeInTheDocument();
  });
});
