import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ServerModsPage } from "./ServerModsPage";

function renderServerModsPage(initialEntry = "/servers/srv-mc-100/mods") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/servers/:serverId/mods" element={<ServerModsPage />} />
        <Route path="/mods" element={<ServerModsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ServerModsPage", () => {
  it("renders the coming soon title and badge correctly", () => {
    renderServerModsPage();
    expect(screen.getByText("Coming Soon")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Mods Management Coming Soon" })).toBeInTheDocument();
  });

  it("renders server-scoped description with serverId from route params", () => {
    renderServerModsPage("/servers/srv-mc-100/mods");
    expect(
      screen.getByText('In-server mods and plugins management for server "srv-mc-100" will be available in Batch 5.'),
    ).toBeInTheDocument();
  });

  it("handles missing serverId gracefully without crashing", () => {
    renderServerModsPage("/mods");
    expect(
      screen.getByText('In-server mods and plugins management for server "" will be available in Batch 5.'),
    ).toBeInTheDocument();
  });
});
