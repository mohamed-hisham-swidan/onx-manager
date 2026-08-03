import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { StatusOverviewCards } from "./StatusOverviewCards";

function renderCards(counts: Record<string, number>) {
  return render(
    <MemoryRouter>
      <StatusOverviewCards counts={counts} />
    </MemoryRouter>,
  );
}

describe("StatusOverviewCards", () => {
  it("renders all six status cards", () => {
    renderCards({});
    for (const label of ["Online", "Offline", "Starting", "Stopping", "Crashed", "Not Started"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders counts per status", () => {
    renderCards({ running: 2, crashed: 1 });
    const online = screen.getByText("Online").parentElement!.parentElement!;
    expect(online.querySelector("p")!.textContent).toBe("2");
    const crashed = screen.getByText("Crashed").parentElement!.parentElement!;
    expect(crashed.querySelector("p")!.textContent).toBe("1");
  });

  it("shows zero for missing statuses and total", () => {
    renderCards({});
    const total = screen.getByText("Total").parentElement!.parentElement!;
    expect(total.querySelector("p")!.textContent).toBe("0");
  });

  it("links to the servers page", () => {
    renderCards({ running: 1 });
    const online = screen.getByText("Online").closest("a");
    expect(online).toHaveAttribute("href", "/servers");
  });
});
