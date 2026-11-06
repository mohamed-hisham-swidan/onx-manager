import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "./TopBar";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import { useWSStore } from "@/stores/wsStore";
import { ConnectionState, ChannelStatus } from "@/websocket/types";
import type { ChannelState } from "@/websocket/types";

function rejectedChannelState(channel: string): ChannelState {
  return {
    channel,
    status: ChannelStatus.REJECTED,
    authorized: false,
    error: `Not authorized for channel: ${channel}`,
    retryCount: 3,
  };
}

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
    useUIStore.setState({
      sidebarOpen: true,
      mobileSidebarOpen: false,
      theme: "light",
      skin: "graphite",
      density: "comfortable",
      accent: "theme",
    });
    useWSStore.setState({
      connectionState: ConnectionState.DISCONNECTED,
      connected: false,
      channelStates: {},
      unattributedRejection: false,
    });
  });

  it("renders app title", () => {
    renderTopBar();
    expect(screen.getByText("onx-manager")).toBeInTheDocument();
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

  it("shows Degraded state when transport is connected but a subscription is rejected", () => {
    setAuth();
    useWSStore.setState({
      connectionState: ConnectionState.CONNECTED,
      connected: true,
      channelStates: { "server:s01": rejectedChannelState("server:s01") },
    });
    renderTopBar();
    expect(screen.getByRole("status", { name: "Socket degraded" })).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute(
      "title",
      "WebSocket connected, but 1 or more subscriptions were rejected",
    );
  });

  it("shows Degraded state when an unattributed rejection is set", () => {
    setAuth();
    useWSStore.setState({ connectionState: ConnectionState.CONNECTED, connected: true, unattributedRejection: true });
    renderTopBar();
    expect(screen.getByRole("status", { name: "Socket degraded" })).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
  });

  it("renders appearance options button and toggles Theme Studio popover", () => {
    setAuth();
    renderTopBar();
    const btn = screen.getByLabelText("Appearance options");
    expect(btn).toBeInTheDocument();

    expect(screen.queryByRole("dialog", { name: "Theme Studio" })).not.toBeInTheDocument();
    fireEvent.click(btn);
    expect(screen.getByRole("dialog", { name: "Theme Studio" })).toBeInTheDocument();

    // Check all 6 skins are present
    expect(screen.getByText("Graphite")).toBeInTheDocument();
    expect(screen.getByText("Azure")).toBeInTheDocument();
    expect(screen.getByText("Emerald")).toBeInTheDocument();
    expect(screen.getByText("Amethyst")).toBeInTheDocument();
    expect(screen.getByText("Amber")).toBeInTheDocument();
    expect(screen.getByText("Crimson")).toBeInTheDocument();

    // Selecting a skin updates uiStore
    fireEvent.click(screen.getByText("Emerald"));
    expect(useUIStore.getState().skin).toBe("emerald");

    // Check accent swatches are present and selectable
    const emeraldAccent = screen.getByLabelText("Accent Emerald");
    expect(emeraldAccent).toBeInTheDocument();
    fireEvent.click(emeraldAccent);
    expect(useUIStore.getState().accent).toBe("emerald");

    // Check settings link is present
    expect(screen.getByText("Appearance settings")).toBeInTheDocument();

    // Close popover
    fireEvent.click(screen.getByLabelText("Close appearance popover"));
    expect(screen.queryByRole("dialog", { name: "Theme Studio" })).not.toBeInTheDocument();
  });

  it("cycles skins via toggle skin button and preserves density & theme buttons", () => {
    setAuth();
    renderTopBar();

    const skinBtn = screen.getByLabelText("Toggle skin");
    expect(skinBtn).toBeInTheDocument();
    fireEvent.click(skinBtn);
    expect(useUIStore.getState().skin).toBe("azure");

    const densityBtn = screen.getByLabelText("Toggle density");
    expect(densityBtn).toBeInTheDocument();
    fireEvent.click(densityBtn);
    expect(useUIStore.getState().density).toBe("compact");

    const themeBtn = screen.getByLabelText("Toggle theme");
    expect(themeBtn).toBeInTheDocument();
    fireEvent.click(themeBtn);
    expect(useUIStore.getState().theme).toBe("dark");
  });
});
