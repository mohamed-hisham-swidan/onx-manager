import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./AppShell";
import { useUIStore } from "@/stores/uiStore";
import { useOperationStore } from "@/operations/stores/operationStore";

function renderShell() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div>Content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell", () => {
  it("renders top bar, sidebar and content", () => {
    renderShell();
    expect(screen.getByText("onx-manager")).toBeInTheDocument();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Servers")).toBeInTheDocument();
    expect(screen.getByText("Content")).toBeInTheDocument();
  });

  it("renders a loading bar", () => {
    renderShell();
    expect(screen.getByTestId("loading-bar")).toBeInTheDocument();
  });

  it("provides skip-to-content link as first focusable element targeting main", () => {
    renderShell();
    const skipLink = screen.getByRole("link", { name: "Skip to content" });
    expect(skipLink).toBeInTheDocument();
    expect(skipLink).toHaveAttribute("href", "#main-content");

    // Assert it is the first focusable element in container
    const focusable = document.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    expect(focusable[0]).toBe(skipLink);

    // Assert main landmark target
    const main = document.getElementById("main-content");
    expect(main).toBeInTheDocument();
    expect(main).toHaveAttribute("tabindex", "-1");

    // Activating link moves focus to main
    fireEvent.click(skipLink);
    expect(document.activeElement).toBe(main);
  });

  it("renders viewport flex column chain on main workspace and inner container", () => {
    renderShell();
    const main = document.getElementById("main-content");
    expect(main).not.toBeNull();
    expect(main?.className).toContain("flex");
    expect(main?.className).toContain("flex-col");
    expect(main?.className).toContain("flex-1");
    expect(main?.className).toContain("min-h-0");

    const innerWrapper = main?.firstElementChild as HTMLElement;
    expect(innerWrapper).not.toBeNull();
    expect(innerWrapper.className).toContain("flex");
    expect(innerWrapper.className).toContain("flex-col");
    expect(innerWrapper.className).toContain("flex-1");
    expect(innerWrapper.className).toContain("min-h-0");
  });

  it("auto-collapses desktop sidebar and pushes main content when a right panel opens, then restores sidebar on close", () => {
    useUIStore.setState({
      sidebarOpen: true,
      sidebarSavedBeforeRightPanel: null,
      changeVersionOpen: false,
    });
    useOperationStore.setState({ activeDrawerId: null, operations: {} });

    renderShell();
    const main = document.getElementById("main-content");
    expect(useUIStore.getState().sidebarOpen).toBe(true);
    expect(main?.className).not.toContain("lg:pr-[488px]");

    // Simulate opening Change Version panel
    act(() => {
      useUIStore.getState().setChangeVersionOpen(true);
    });
    expect(useUIStore.getState().sidebarOpen).toBe(false);
    expect(document.getElementById("main-content")?.className).toContain("lg:pr-[488px]");

    // Closing right panel restores sidebarOpen
    act(() => {
      useUIStore.getState().setChangeVersionOpen(false);
    });
    expect(useUIStore.getState().sidebarOpen).toBe(true);
    expect(document.getElementById("main-content")?.className).not.toContain("lg:pr-[488px]");
  });
});
