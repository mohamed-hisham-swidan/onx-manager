import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { useUIStore } from "@/stores/uiStore";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar />
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    useUIStore.setState({ sidebarOpen: true, mobileSidebarOpen: false, theme: "light" });
    useMarketplaceSourceStore.setState({ source: "modrinth" });
  });

  it("renders all navigation items", () => {
    renderSidebar();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Servers")).toBeInTheDocument();
    expect(screen.getByText("Backups")).toBeInTheDocument();
    expect(screen.getByText("Marketplace")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("does not render nested Modrinth or CurseForge sublinks under Marketplace", () => {
    renderSidebar();
    expect(screen.queryByText("Modrinth")).not.toBeInTheDocument();
    expect(screen.queryByText("CurseForge")).not.toBeInTheDocument();
  });

  it("sets marketplace source to modrinth when clicking Marketplace", () => {
    useMarketplaceSourceStore.setState({ source: "curseforge" });
    expect(useMarketplaceSourceStore.getState().source).toBe("curseforge");

    renderSidebar();
    fireEvent.click(screen.getByText("Marketplace"));
    expect(useMarketplaceSourceStore.getState().source).toBe("modrinth");
  });

  it("renders nav links with correct paths", () => {
    renderSidebar();
    expect(screen.getByText("Dashboard").closest("a")).toHaveAttribute("href", "/");
    expect(screen.getByText("Servers").closest("a")).toHaveAttribute("href", "/servers");
    expect(screen.getByText("Backups").closest("a")).toHaveAttribute("href", "/backups");
    expect(screen.getByText("Marketplace").closest("a")).toHaveAttribute("href", "/marketplace");
  });

  it("shows backdrop and closes drawer on navigation when mobile is open", () => {
    useUIStore.setState({ mobileSidebarOpen: true });
    renderSidebar();
    expect(screen.getByText("Servers")).toBeInTheDocument();
    const backdrop = document.querySelector(".fixed.inset-0.z-30");
    expect(backdrop).toBeInTheDocument();
    backdrop!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(useUIStore.getState().mobileSidebarOpen).toBe(false);
  });

  it("hides desktop sidebar when sidebarOpen is false", () => {
    useUIStore.setState({ sidebarOpen: false });
    renderSidebar();
    const aside = document.querySelector("aside");
    expect(aside).toHaveClass("lg:-translate-x-full");
  });
});
