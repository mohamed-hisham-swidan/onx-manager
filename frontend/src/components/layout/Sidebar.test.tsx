import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Sidebar } from "./Sidebar";
import { useUIStore } from "@/stores/uiStore";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";
import { useServersList } from "@/server_manager/hooks/useServers";

vi.mock("@/server_manager/hooks/useServers", () => ({
  useServersList: vi.fn(),
}));

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    useUIStore.setState({ sidebarOpen: true, mobileSidebarOpen: false, theme: "light" });
    useMarketplaceSourceStore.setState({ source: "modrinth" });
    vi.mocked(useServersList).mockReturnValue({ data: [] } as unknown as ReturnType<typeof useServersList>);
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

    it("renders dual high-contrast online and offline counters next to Servers nav item", () => {
      vi.mocked(useServersList).mockReturnValue({
        data: [
          { server_id: "s1", status: "RUNNING" },
          { server_id: "s2", status: "STARTING" },
          { server_id: "s3", status: "STOPPED" },
        ],
      } as unknown as ReturnType<typeof useServersList>);
      renderSidebar();
      expect(screen.getByText("2 ON")).toBeInTheDocument();
      expect(screen.getByText("1 OFF")).toBeInTheDocument();
      expect(screen.getByTestId("sidebar-server-counters")).toBeInTheDocument();
    });

    it("handles undefined or loading servers list gracefully", () => {
      vi.mocked(useServersList).mockReturnValue({
        data: undefined,
        isLoading: true,
      } as unknown as ReturnType<typeof useServersList>);
      renderSidebar();
      expect(screen.getByText("0 ON")).toBeInTheDocument();
      expect(screen.getByText("0 OFF")).toBeInTheDocument();
    });
  });
});
