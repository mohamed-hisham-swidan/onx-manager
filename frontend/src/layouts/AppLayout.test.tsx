import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppLayout } from "./AppLayout";

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <AppLayout />
    </MemoryRouter>,
  );
}

describe("AppLayout", () => {
  it("renders sidebar and top nav", () => {
    renderLayout();
    expect(screen.getByText("MC Server Manager")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Servers")).toBeInTheDocument();
  });

  it("renders main content area", () => {
    const { container } = renderLayout();
    const main = container.querySelector("main");
    expect(main).toBeInTheDocument();
  });
});
