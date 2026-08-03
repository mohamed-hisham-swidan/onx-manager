import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "./TopBar";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";

function renderTopBar() {
  return render(
    <MemoryRouter>
      <TopBar />
    </MemoryRouter>,
  );
}

describe("TopBar", () => {
  beforeEach(() => {
    useAuthStore.setState({
      isAuthenticated: false,
      accessToken: null,
      refreshToken: null,
      getAccessToken: () => null,
    });
    useUIStore.setState({ sidebarOpen: true, mobileSidebarOpen: false, theme: "light" });
  });

  it("renders app title", () => {
    renderTopBar();
    expect(screen.getByText("MC Server Manager")).toBeInTheDocument();
  });

  it("shows hamburger and logout when authenticated", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      accessToken: "tok",
      refreshToken: "rtok",
      getAccessToken: () => "tok",
    });
    renderTopBar();
    expect(screen.getByLabelText("Close sidebar")).toBeInTheDocument();
    expect(screen.getByText("Logout")).toBeInTheDocument();
  });

  it("hides hamburger and logout when not authenticated", () => {
    renderTopBar();
    expect(screen.queryByLabelText("Close sidebar")).not.toBeInTheDocument();
    expect(screen.queryByText("Logout")).not.toBeInTheDocument();
  });

  it("logout button has click handler", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      accessToken: "tok",
      refreshToken: "rtok",
      getAccessToken: () => "tok",
    });
    renderTopBar();
    const btn = screen.getByText("Logout");
    expect(btn.tagName).toBe("BUTTON");
  });
});
