import { describe, it, expect, beforeEach } from "vitest";
import {
  THEME_KEY,
  SKIN_KEY,
  DENSITY_KEY,
  initPrePaintAttributes,
} from "./storageKeys";

describe("Pre-paint Persistence (Task 1 Regression Test)", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-mode");
    document.documentElement.removeAttribute("data-skin");
    document.documentElement.removeAttribute("data-density");
    document.documentElement.classList.remove("dark");
  });

  it("synchronously sets data-skin/data-mode/data-density matching stored onx_* keys", () => {
    localStorage.setItem(SKIN_KEY, "azure");
    localStorage.setItem(DENSITY_KEY, "compact");
    localStorage.setItem(THEME_KEY, "light");

    const result = initPrePaintAttributes();

    expect(result).toEqual({
      mode: "light",
      skin: "azure",
      density: "compact",
    });

    expect(document.documentElement.getAttribute("data-skin")).toBe("azure");
    expect(document.documentElement.getAttribute("data-mode")).toBe("light");
    expect(document.documentElement.getAttribute("data-density")).toBe("compact");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("sets dark class on <html> when stored mode is dark", () => {
    localStorage.setItem(SKIN_KEY, "graphite");
    localStorage.setItem(DENSITY_KEY, "comfortable");
    localStorage.setItem(THEME_KEY, "dark");

    const result = initPrePaintAttributes();

    expect(result.mode).toBe("dark");
    expect(document.documentElement.getAttribute("data-mode")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("falls back to safe defaults when stored keys have invalid or corrupt values", () => {
    localStorage.setItem(SKIN_KEY, "neon-cyan");
    localStorage.setItem(DENSITY_KEY, "super-compact");
    localStorage.setItem(THEME_KEY, "sepia");

    const result = initPrePaintAttributes();

    expect(result.skin).toBe("graphite");
    expect(result.density).toBe("comfortable");
    expect(document.documentElement.getAttribute("data-skin")).toBe("graphite");
    expect(document.documentElement.getAttribute("data-density")).toBe("comfortable");
  });

  it("handles missing localStorage values gracefully", () => {
    const result = initPrePaintAttributes();

    expect(result.skin).toBe("graphite");
    expect(result.density).toBe("comfortable");
    expect(document.documentElement.getAttribute("data-skin")).toBe("graphite");
    expect(document.documentElement.getAttribute("data-density")).toBe("comfortable");
  });
});
