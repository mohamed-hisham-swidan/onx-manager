import { describe, it, expect, beforeEach, vi } from "vitest";

const THEME_KEY = "onx_theme";
const SKIN_KEY = "onx_skin";
const DENSITY_KEY = "onx_density";

describe("uiStore", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = "";
    document.documentElement.removeAttribute("data-mode");
    document.documentElement.removeAttribute("data-skin");
    document.documentElement.removeAttribute("data-density");
    vi.resetModules();
  });

  it("defaults to light theme when no preference stored", async () => {
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().theme).toBe("light");
    expect(document.documentElement.getAttribute("data-mode")).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("defaults to dark when system prefers dark", async () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().theme).toBe("dark");
    expect(document.documentElement.getAttribute("data-mode")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    vi.unstubAllGlobals();
  });

  it("loads stored theme over system preference", async () => {
    localStorage.setItem(THEME_KEY, "light");
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().theme).toBe("light");
    expect(document.documentElement.getAttribute("data-mode")).toBe("light");
    vi.unstubAllGlobals();
  });

  it("toggleTheme switches to dark", async () => {
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().toggleTheme();
    expect(useUIStore.getState().theme).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(document.documentElement.getAttribute("data-mode")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("toggleTheme switches back to light", async () => {
    localStorage.setItem(THEME_KEY, "dark");
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().toggleTheme();
    expect(useUIStore.getState().theme).toBe("light");
    expect(document.documentElement.getAttribute("data-mode")).toBe("light");
  });

  it("setTheme sets explicit theme", async () => {
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().setTheme("dark");
    expect(useUIStore.getState().theme).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(document.documentElement.getAttribute("data-mode")).toBe("dark");
  });

  it("defaults to graphite skin and sets data-skin attribute", async () => {
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().skin).toBe("graphite");
    expect(document.documentElement.getAttribute("data-skin")).toBe("graphite");
  });

  it("setSkin updates skin and sets data-skin attribute", async () => {
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().setSkin("azure");
    expect(useUIStore.getState().skin).toBe("azure");
    expect(localStorage.getItem(SKIN_KEY)).toBe("azure");
    expect(document.documentElement.getAttribute("data-skin")).toBe("azure");
  });

  it("defaults to comfortable density and sets data-density attribute", async () => {
    const { useUIStore } = await import("./uiStore");
    expect(useUIStore.getState().density).toBe("comfortable");
    expect(document.documentElement.getAttribute("data-density")).toBe("comfortable");
  });

  it("setDensity and toggleDensity update density attribute and persistence", async () => {
    const { useUIStore } = await import("./uiStore");
    useUIStore.getState().setDensity("compact");
    expect(useUIStore.getState().density).toBe("compact");
    expect(localStorage.getItem(DENSITY_KEY)).toBe("compact");
    expect(document.documentElement.getAttribute("data-density")).toBe("compact");

    useUIStore.getState().toggleDensity();
    expect(useUIStore.getState().density).toBe("comfortable");
    expect(localStorage.getItem(DENSITY_KEY)).toBe("comfortable");
    expect(document.documentElement.getAttribute("data-density")).toBe("comfortable");
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

    expect(() => useUIStore.getState().setSkin("azure")).not.toThrow();
    expect(() => useUIStore.getState().setDensity("compact")).not.toThrow();

    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
    vi.restoreAllMocks();
  });
});
