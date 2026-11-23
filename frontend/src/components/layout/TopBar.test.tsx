import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "./TopBar";
import { useAuthStore } from "@/stores/authStore";
import { useUIStore } from "@/stores/uiStore";
import { useOperationStore } from "@/operations/stores/operationStore";

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
    useOperationStore.setState({
      operations: {},
      activeDrawerId: null,
      logs: {},
      gapDetectedOperations: {},
    });
  });

  it("renders app title", () => {
    renderTopBar();
    expect(screen.getByText("onx-manager")).toBeInTheDocument();
  });

  it("shows only hamburger, theme toggle, and logout when authenticated with no active operations", () => {
    setAuth();
    renderTopBar();
    expect(screen.getByLabelText("Close sidebar")).toBeInTheDocument();
    expect(screen.getByLabelText("Toggle theme")).toBeInTheDocument();
    expect(screen.getByText("Logout")).toBeInTheDocument();

    expect(screen.queryByLabelText("Toggle skin")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Toggle density")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Appearance options")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Background Operations")).not.toBeInTheDocument();
    expect(screen.queryByTestId("deployment-profile-badge")).not.toBeInTheDocument();
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

  it("toggles between light and dark theme", () => {
    setAuth();
    renderTopBar();

    const themeBtn = screen.getByLabelText("Toggle theme");
    expect(themeBtn).toBeInTheDocument();
    fireEvent.click(themeBtn);
    expect(useUIStore.getState().theme).toBe("dark");
    fireEvent.click(themeBtn);
    expect(useUIStore.getState().theme).toBe("light");
  });

  it("shows active background operations pill only while an operation is running", () => {
    setAuth();
    useOperationStore.setState({
      operations: {
        "op-1": {
          id: "op-1",
          type: "MODPACK_INSTALL",
          target_type: "server",
          target_id: "srv-1",
          actor_id: null,
          status: "RUNNING",
          idempotency_key: null,
          current_step_id: "INSTALL_MODPACK",
          last_event_seq: 1,
          failure_code: null,
          error_message: null,
          cancellation_requested: false,
          timeout_seconds: 600,
          created_at: "2026-11-23T00:00:00Z",
          started_at: "2026-11-23T00:00:00Z",
          finished_at: null,
          elapsed_ms: 1000,
          steps: [],
          metadata: {},
        },
      },
    });
    renderTopBar();

    const opBtn = screen.getByLabelText("Background Operations");
    expect(opBtn).toHaveTextContent("Running (1)");
    fireEvent.click(opBtn);
    expect(useOperationStore.getState().activeDrawerId).toBe("op-1");
  });
});
