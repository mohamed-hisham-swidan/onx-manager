import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { useUIStore } from "@/stores/uiStore";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";
import type { ServerMode } from "@/server_manager/types";

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

  it("navigates to /marketplace when clicking Marketplace nav item", () => {
    let currentLocation = "";
    function LocationWatcher() {
      const location = useLocation();
      currentLocation = location.pathname;
      return null;
    }

    render(
      <MemoryRouter initialEntries={["/"]}>
        <Sidebar />
        <LocationWatcher />
      </MemoryRouter>,
    );

    expect(currentLocation).toBe("/");
    fireEvent.click(screen.getByRole("link", { name: /marketplace/i }));
    expect(currentLocation).toBe("/marketplace");
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

  describe("mobile off-canvas a11y & interaction", () => {
    it("closes mobile sidebar on Escape key press", () => {
      useUIStore.setState({ mobileSidebarOpen: true });
      renderSidebar();

      expect(useUIStore.getState().mobileSidebarOpen).toBe(true);
      fireEvent.keyDown(window, { key: "Escape" });
      expect(useUIStore.getState().mobileSidebarOpen).toBe(false);
    });

    it("locks body scroll when mobile drawer is open and restores on close", () => {
      document.body.style.overflow = "";
      useUIStore.setState({ mobileSidebarOpen: true });
      const { rerender } = renderSidebar();

      expect(document.body.style.overflow).toBe("hidden");

      act(() => {
        useUIStore.setState({ mobileSidebarOpen: false });
      });
      rerender(
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>,
      );
      expect(document.body.style.overflow).toBe("");
    });

    it("moves focus to first focusable item on open and returns focus to opener on close", async () => {
      const TestShell = () => {
        const mobileSidebarOpen = useUIStore((s) => s.mobileSidebarOpen);
        const setMobileSidebarOpen = useUIStore((s) => s.setMobileSidebarOpen);

        return (
          <MemoryRouter>
            <button
              data-testid="toggle-btn"
              onClick={() => setMobileSidebarOpen(!mobileSidebarOpen)}
            >
              Toggle
            </button>
            <Sidebar />
          </MemoryRouter>
        );
      };

      const { unmount } = render(<TestShell />);
      const toggleBtn = screen.getByTestId("toggle-btn");
      toggleBtn.focus();
      expect(document.activeElement).toBe(toggleBtn);

      // Open drawer
      fireEvent.click(toggleBtn);
      expect(useUIStore.getState().mobileSidebarOpen).toBe(true);

      // Wait for focus timer to move focus inside drawer
      await new Promise((resolve) => setTimeout(resolve, 20));
      const firstLink = screen.getByText("Dashboard").closest("a");
      expect(document.activeElement).toBe(firstLink);

      // Close drawer with Escape
      fireEvent.keyDown(window, { key: "Escape" });
      expect(useUIStore.getState().mobileSidebarOpen).toBe(false);

      // Focus should return to opener button
      expect(document.activeElement).toBe(toggleBtn);
      unmount();
    });

    it("desktop visible state does not lock scroll or react to Escape", () => {
      document.body.style.overflow = "";
      useUIStore.setState({ sidebarOpen: true, mobileSidebarOpen: false });
      renderSidebar();

      expect(document.body.style.overflow).toBe("");
      fireEvent.keyDown(window, { key: "Escape" });
      expect(useUIStore.getState().sidebarOpen).toBe(true);
      expect(useUIStore.getState().mobileSidebarOpen).toBe(false);
      expect(document.body.style.overflow).toBe("");
    });
  });

  describe("landmarks and active aria-current contracts", () => {
    it("exposes distinct aria-label on global nav landmark and sets aria-current='page' on active link", () => {
      render(
        <MemoryRouter initialEntries={["/servers"]}>
          <Sidebar />
        </MemoryRouter>,
      );

      const nav = screen.getByRole("navigation", { name: "Main" });
      expect(nav).toBeInTheDocument();

      const serversLink = screen.getByRole("link", { name: /servers/i });
      expect(serversLink).toHaveAttribute("aria-current", "page");

      const dashboardLink = screen.getByRole("link", { name: /dashboard/i });
      expect(dashboardLink).not.toHaveAttribute("aria-current");
    });

    it("exposes distinct aria-label on server contextual nav landmark and sets aria-current='page' on active sublink", () => {
      render(
        <MemoryRouter initialEntries={["/servers/srv-1/console"]}>
          <Sidebar
            serverContext={{
              serverId: "srv-1",
              serverName: "Survival World",
              serverType: "paper",
              supportsPlugins: true,
            }}
          />
        </MemoryRouter>,
      );

      const serverNav = screen.getByRole("navigation", { name: "Server sections" });
      expect(serverNav).toBeInTheDocument();

      const consoleLink = screen.getByRole("link", { name: /console/i });
      expect(consoleLink).toHaveAttribute("aria-current", "page");

      const filesLink = screen.getByRole("link", { name: /files/i });
      expect(filesLink).not.toHaveAttribute("aria-current");
    });
  });

  describe("resizable sidebar handle", () => {
    it("renders resize handle when sidebarOpen is true on global navigation", () => {
      useUIStore.setState({ sidebarOpen: true, mobileSidebarOpen: false });
      renderSidebar();
      const handle = screen.getByRole("separator", { name: /resize sidebar/i });
      expect(handle).toBeInTheDocument();
      expect(handle).toHaveAttribute("aria-orientation", "vertical");
      expect(handle).toHaveAttribute("aria-valuenow", "224");
      expect(handle).toHaveAttribute("aria-valuemin", "200");
      expect(handle).toHaveAttribute("aria-valuemax", "420");
    });

    it("hides resize handle when desktop sidebarOpen is false", () => {
      useUIStore.setState({ sidebarOpen: false });
      renderSidebar();
      const handle = screen.queryByRole("separator", { name: /resize sidebar/i });
      expect(handle).not.toBeInTheDocument();
    });

    it("does not render resize handle when serverContext is present (per-server sidebar)", () => {
      useUIStore.setState({ sidebarOpen: true });
      render(
        <MemoryRouter>
          <Sidebar
            serverContext={{
              serverId: "srv-test",
              serverName: "Test Server",
            }}
          />
        </MemoryRouter>,
      );
      const handle = screen.queryByRole("separator", { name: /resize sidebar/i });
      expect(handle).not.toBeInTheDocument();
    });

    it("resizes via keyboard arrow keys on the handle", () => {
      useUIStore.setState({ sidebarOpen: true });
      renderSidebar();
      const handle = screen.getByRole("separator", { name: /resize sidebar/i });

      fireEvent.keyDown(handle, { key: "ArrowRight" });
      expect(handle).toHaveAttribute("aria-valuenow", "240");

      fireEvent.keyDown(handle, { key: "ArrowLeft" });
      expect(handle).toHaveAttribute("aria-valuenow", "224");
    });

    it("resets to default width on double-click", () => {
      useUIStore.setState({ sidebarOpen: true });
      localStorage.setItem("onx_sidebar_width", "350");
      renderSidebar();
      const handle = screen.getByRole("separator", { name: /resize sidebar/i });
      expect(handle).toHaveAttribute("aria-valuenow", "350");

      fireEvent.doubleClick(handle);
      expect(handle).toHaveAttribute("aria-valuenow", "224");
    });
  });

  describe("mode-based navigation gating", () => {
    it("hides Versions & Testing link when serverContext mode is simple", () => {
      render(
        <MemoryRouter>
          <Sidebar
            serverContext={{
              serverId: "srv-simple",
              serverName: "Simple Server",
              mode: "simple",
            }}
          />
        </MemoryRouter>,
      );

      expect(screen.queryByRole("link", { name: /Versions & Testing/i })).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Network & Exposure/i })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Change History/i })).toBeInTheDocument();
    });

    it("renders Versions & Testing link when serverContext mode is advanced", () => {
      render(
        <MemoryRouter>
          <Sidebar
            serverContext={{
              serverId: "srv-adv",
              serverName: "Advanced Server",
              mode: "advanced",
            }}
          />
        </MemoryRouter>,
      );

      const versioningLink = screen.getByRole("link", { name: /Versions & Testing/i });
      expect(versioningLink).toBeInTheDocument();
      expect(versioningLink).toHaveAttribute("href", "/servers/srv-adv/versioning");
    });

    it("falls back to hiding Versions & Testing when mode is undefined or unknown", () => {
      const { rerender } = render(
        <MemoryRouter>
          <Sidebar
            serverContext={{
              serverId: "srv-undef",
              serverName: "Undefined Server",
            }}
          />
        </MemoryRouter>,
      );

      expect(screen.queryByRole("link", { name: /Versions & Testing/i })).not.toBeInTheDocument();

      rerender(
        <MemoryRouter>
          <Sidebar
            serverContext={{
              serverId: "srv-unknown",
              serverName: "Unknown Mode Server",
              mode: "invalid-mode" as unknown as ServerMode,
            }}
          />
        </MemoryRouter>,
      );

      expect(screen.queryByRole("link", { name: /Versions & Testing/i })).not.toBeInTheDocument();
    });
  });
});
