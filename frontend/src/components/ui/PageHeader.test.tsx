import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PageHeader } from "./PageHeader";

function renderHeader(props: Parameters<typeof PageHeader>[0]) {
  return render(
    <MemoryRouter>
      <PageHeader {...props} />
    </MemoryRouter>,
  );
}

describe("PageHeader", () => {
  it("renders title and description", () => {
    renderHeader({ title: "Servers", description: "Manage your servers" });
    expect(screen.getByRole("heading", { name: "Servers" })).toBeInTheDocument();
    expect(screen.getByText("Manage your servers")).toBeInTheDocument();
  });

  it("renders back link when backTo is provided", () => {
    renderHeader({ title: "Detail", backTo: "/servers" });
    const link = screen.getByRole("link", { name: /Back/ });
    expect(link).toHaveAttribute("href", "/servers");
  });

  it("renders actions", () => {
    renderHeader({ title: "Servers", actions: <button>Create</button> });
    expect(screen.getByText("Create")).toBeInTheDocument();
  });
});
