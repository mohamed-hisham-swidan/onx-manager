import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WebSocketManager } from "./WebSocketManager";
import { useAuthStore } from "@/stores/authStore";

const { subscribeMock } = vi.hoisted(() => ({ subscribeMock: vi.fn() }));

vi.mock("@/hooks/useWebSocket", () => ({
  useWebSocket: vi.fn(() => ({ subscribe: subscribeMock, unsubscribe: vi.fn(), send: vi.fn() })),
}));

const qc = new QueryClient();

function renderWS() {
  return render(
    <QueryClientProvider client={qc}>
      <WebSocketManager />
    </QueryClientProvider>,
  );
}

describe("WebSocketManager", () => {
  beforeEach(() => {
    subscribeMock.mockClear();
    useAuthStore.setState({
      isAuthenticated: false,
      accessToken: null,
      refreshToken: null,
      getAccessToken: () => null,
    });
  });

  it("renders nothing (returns null)", () => {
    const { container } = renderWS();
    expect(container.innerHTML).toBe("");
  });

  it("does not crash when rendered", () => {
    expect(() => renderWS()).not.toThrow();
  });

  it("renders when authenticated", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      accessToken: "tok",
      refreshToken: "rtok",
      getAccessToken: () => "tok",
    });
    const { container } = renderWS();
    expect(container.innerHTML).toBe("");
  });

  it("subscribes to server:* when authenticated", () => {
    useAuthStore.setState({
      isAuthenticated: true,
      accessToken: "tok",
      refreshToken: "rtok",
      getAccessToken: () => "tok",
    });
    renderWS();
    expect(subscribeMock).toHaveBeenCalledWith(["server:*"]);
  });

  it("does not subscribe when not authenticated", () => {
    renderWS();
    expect(subscribeMock).not.toHaveBeenCalled();
  });
});
