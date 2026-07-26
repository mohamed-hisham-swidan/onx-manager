import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { useUIStore } from "@/stores/uiStore";

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    useUIStore.setState({ sidebarOpen: true, theme: "light" });
  });

  it("renders all navigation items", () => {
    renderSidebar();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Servers")).toBeInTheDocument();
    expect(screen.getByText("Backups")).toBeInTheDocument();
    expect(screen.getByText("Plugins")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders nav links with correct paths", () => {
    renderSidebar();
    expect(screen.getByText("Dashboard").closest("a")).toHaveAttribute("href", "/");
    expect(screen.getByText("Servers").closest("a")).toHaveAttribute("href", "/servers");
    expect(screen.getByText("Backups").closest("a")).toHaveAttribute("href", "/backups");
  });

  it("hides labels when sidebar is closed", () => {
    useUIStore.setState({ sidebarOpen: false });
    renderSidebar();
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
    expect(screen.queryByText("Servers")).not.toBeInTheDocument();
  });

  it("shows icons when sidebar is closed", () => {
    useUIStore.setState({ sidebarOpen: false });
    renderSidebar();
    expect(screen.getByText("◆")).toBeInTheDocument();
    expect(screen.getByText("⚡")).toBeInTheDocument();
  });
});
