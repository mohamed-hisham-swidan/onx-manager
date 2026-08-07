import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "./TopBar";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState } from "@/websocket/types";

function renderTopBar() {
  return render(
    <MemoryRouter>
      <TopBar />
    </MemoryRouter>,
  );
}

function setAuth() {
  useAuthStore.setState({
    isAuthenticated: true,
    accessToken: "tok",
    refreshToken: "rtok",
    getAccessToken: () => "tok",
  });
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
    useWSStore.setState({ connectionState: ConnectionState.DISCONNECTED, connected: false });
  });

  it("renders app title", () => {
    renderTopBar();
    expect(screen.getByText("MC Server Manager")).toBeInTheDocument();
  });

  it("shows hamburger and logout when authenticated", () => {
    setAuth();
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
    setAuth();
    renderTopBar();
    const btn = screen.getByText("Logout");
    expect(btn.tagName).toBe("BUTTON");
  });

  it.each([
    [ConnectionState.CONNECTED, "Live"],
    [ConnectionState.CONNECTING, "Connecting…"],
    [ConnectionState.RECONNECTING, "Reconnecting…"],
    [ConnectionState.DISCONNECTED, "Offline"],
  ] as const)("shows %s socket state in the top bar", (state, label) => {
    setAuth();
    useWSStore.setState({
      connectionState: state,
      connected: state === ConnectionState.CONNECTED,
    });
    renderTopBar();
    expect(screen.getByRole("status", { name: `Socket ${state}` })).toBeInTheDocument();
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
