import { describe, it, expect, beforeEach, vi } from "vitest";

const STORAGE_KEY = "mcs_auth";

function setStoredAuth(data: unknown) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

describe("authStore", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("starts unauthenticated when no stored auth", async () => {
    const { useAuthStore } = await import("./authStore");
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
  });

  it("starts authenticated with valid stored auth", async () => {
    setStoredAuth({
      accessToken: "tok1",
      refreshToken: "rtok1",
      expiresIn: 3600,
      acquiredAt: Date.now() - 60 * 1000,
    });
    const { useAuthStore } = await import("./authStore");
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.accessToken).toBe("tok1");
    expect(state.refreshToken).toBe("rtok1");
  });

  it("starts unauthenticated with expired stored auth", async () => {
    setStoredAuth({
      accessToken: "tok1",
      refreshToken: "rtok1",
      expiresIn: 1,
      acquiredAt: Date.now() - 5000,
    });
    const { useAuthStore } = await import("./authStore");
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.accessToken).toBeNull();
  });

  it("login stores tokens and sets authenticated", async () => {
    const { useAuthStore } = await import("./authStore");
    useAuthStore.getState().login("access1", "refresh1", 3600);
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.accessToken).toBe("access1");
    expect(state.refreshToken).toBe("refresh1");
  });

  it("login persists to localStorage", async () => {
    const { useAuthStore } = await import("./authStore");
    useAuthStore.getState().login("access2", "refresh2", 3600);
    const raw = localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.accessToken).toBe("access2");
    expect(parsed.refreshToken).toBe("refresh2");
  });

  it("logout clears tokens and localStorage", async () => {
    const { useAuthStore } = await import("./authStore");
    useAuthStore.getState().login("a", "r", 3600);
    useAuthStore.getState().logout();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.accessToken).toBeNull();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("setTokens updates tokens", async () => {
    const { useAuthStore } = await import("./authStore");
    useAuthStore.getState().setTokens("newA", "newR", 7200);
    const state = useAuthStore.getState();
    expect(state.accessToken).toBe("newA");
    expect(state.refreshToken).toBe("newR");
    expect(state.isAuthenticated).toBe(true);
  });

  it("getAccessToken returns current token", async () => {
    const { useAuthStore } = await import("./authStore");
    useAuthStore.getState().login("tok3", "rtok3", 3600);
    expect(useAuthStore.getState().getAccessToken()).toBe("tok3");
  });

  it("handles corrupt localStorage gracefully", async () => {
    localStorage.setItem(STORAGE_KEY, "not-json");
    const { useAuthStore } = await import("./authStore");
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.accessToken).toBeNull();
  });
});
