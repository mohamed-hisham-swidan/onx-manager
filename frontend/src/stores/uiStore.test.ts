import { describe, it, expect, beforeEach, vi } from "vitest";

const THEME_KEY = "onx_theme";

describe("uiStore", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("defaults to light theme when no preference stored", async () => {
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().theme).toBe("light");
  });

  it("defaults to dark when system prefers dark", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().theme).toBe("dark");
    vi.unstubAllGlobals();
  });

  it("loads stored theme over system preference", async () => {
    localStorage.setItem(THEME_KEY, "light");
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().theme).toBe("light");
    vi.unstubAllGlobals();
  });

  it("toggleTheme switches to dark", async () => {
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().toggleTheme();
    expect(useUIStore.getState().theme).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  });

  it("toggleTheme switches back to light", async () => {
    localStorage.setItem(THEME_KEY, "dark");
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().toggleTheme();
    expect(useUIStore.getState().theme).toBe("light");
  });

  it("setTheme sets explicit theme", async () => {
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().setTheme("dark");
    expect(useUIStore.getState().theme).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  });

  it("sidebar defaults to open", async () => {
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().sidebarOpen).toBe(true);
  });

  it("toggleSidebar flips sidebar open state", async () => {
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarOpen).toBe(false);
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarOpen).toBe(true);
  });

  it("setSidebarOpen sets explicit value", async () => {
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().setSidebarOpen(false);
    expect(useUIStore.getState().sidebarOpen).toBe(false);
    useUIStore.getState().setSidebarOpen(true);
    expect(useUIStore.getState().sidebarOpen).toBe(true);
  });

  it("handles localStorage quota exceeded without throwing", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("The quota has been exceeded.", "QuotaExceededError");
    });

    const { useUIStore } = await import("./uiStore");
    expect(() => useUIStore.getState().setTheme("dark")).not.toThrow();
    expect(useUIStore.getState().theme).toBe("dark");

    expect(() => useUIStore.getState().toggleTheme()).not.toThrow();
    expect(useUIStore.getState().theme).toBe("light");

    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
    vi.restoreAllMocks();
  });
});
