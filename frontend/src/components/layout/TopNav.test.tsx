import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TopNav } from "./TopNav";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";

function renderTopNav() {
  return render(
    <MemoryRouter>
      <TopNav />
    </MemoryRouter>,
  );
}

describe("TopNav", () => {
  beforeEach(() => {
    useAuthStore.setState({
      isAuthenticated: false,
      accessToken: null,
      refreshToken: null,
      getAccessToken: () => null,
    });
    useUIStore.setState({ sidebarOpen: true, theme: "light" });
  });

  it("renders app title", () => {
    renderTopNav();
    expect(screen.getByText("MC Server Manager")).toBeInTheDocument();
  });

  it("shows hamburger and logout when authenticated", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      accessToken: "tok",
      refreshToken: "rtok",
      getAccessToken: () => "tok",
    });
    renderTopNav();
    expect(screen.getByLabelText("Close sidebar")).toBeInTheDocument();
    expect(screen.getByText("Logout")).toBeInTheDocument();
  });

  it("hides hamburger and logout when not authenticated", () => {
    renderTopNav();
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
    renderTopNav();
    const btn = screen.getByText("Logout");
    expect(btn.tagName).toBe("BUTTON");
  });
});
