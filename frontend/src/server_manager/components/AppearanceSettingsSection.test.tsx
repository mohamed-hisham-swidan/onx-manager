import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AppearanceSettingsSection } from "./AppearanceSettingsSection";
import { useUIStore } from "@/stores/uiStore";
import { CORNER_STYLE_KEY } from "@/tokens/storageKeys";

interface NodeFs {
  readFileSync: (path: string, encoding: "utf8" | "utf-8") => string;
}

interface NodePath {
  resolve: (...args: string[]) => string;
}

declare const require: (mod: string) => NodeFs & NodePath;
declare const process: { cwd: () => string };
const fs: NodeFs = require("node:fs");
const path: NodePath = require("node:path");

describe("AppearanceSettingsSection - Corner Style Setting", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.className = "";
    document.documentElement.removeAttribute("data-mode");
    document.documentElement.removeAttribute("data-skin");
    document.documentElement.removeAttribute("data-density");
    document.documentElement.removeAttribute("data-accent");
    document.documentElement.removeAttribute("data-corners");
    useUIStore.setState({
      theme: "dark",
      skin: "graphite",
      density: "comfortable",
      cornerStyle: "rounded",
    });
  });

  it("1. Defaults corner style to 'rounded' and renders both option cards", () => {
    render(<AppearanceSettingsSection />);

    const cornerSection = screen.getByTestId("corner-style-section");
    expect(cornerSection).toBeInTheDocument();

    const roundedCard = screen.getByRole("radio", { name: /rounded/i });
    const sharpCard = screen.getByRole("radio", { name: /sharp/i });

    expect(roundedCard).toHaveAttribute("aria-checked", "true");
    expect(sharpCard).toHaveAttribute("aria-checked", "false");
    expect(useUIStore.getState().cornerStyle).toBe("rounded");
  });

  it("2. Clicking 'Sharp' updates the store, localStorage, and <html data-corners='sharp'>", () => {
    render(<AppearanceSettingsSection />);

    const sharpCard = screen.getByRole("radio", { name: /sharp/i });
    fireEvent.click(sharpCard);

    expect(useUIStore.getState().cornerStyle).toBe("sharp");
    expect(localStorage.getItem(CORNER_STYLE_KEY)).toBe("sharp");
    expect(document.documentElement.getAttribute("data-corners")).toBe("sharp");
    expect(sharpCard).toHaveAttribute("aria-checked", "true");
  });

  it("3. Clicking 'Rounded' updates the store, localStorage, and <html data-corners='rounded'>", () => {
    useUIStore.getState().setCornerStyle("sharp");
    render(<AppearanceSettingsSection />);

    const roundedCard = screen.getByRole("radio", { name: /rounded/i });
    fireEvent.click(roundedCard);

    expect(useUIStore.getState().cornerStyle).toBe("rounded");
    expect(localStorage.getItem(CORNER_STYLE_KEY)).toBe("rounded");
    expect(document.documentElement.getAttribute("data-corners")).toBe("rounded");
    expect(roundedCard).toHaveAttribute("aria-checked", "true");
  });

  it("4. Reset Appearance to Default restores corner style to 'rounded'", () => {
    useUIStore.getState().setCornerStyle("sharp");
    render(<AppearanceSettingsSection />);

    expect(useUIStore.getState().cornerStyle).toBe("sharp");

    const resetButton = screen.getByRole("button", { name: /Reset Appearance to Default/i });
    fireEvent.click(resetButton);

    expect(useUIStore.getState().cornerStyle).toBe("rounded");
    expect(localStorage.getItem(CORNER_STYLE_KEY)).toBe("rounded");
    expect(document.documentElement.getAttribute("data-corners")).toBe("rounded");
  });

  it("5. CSS contains radius token scale under @theme and [data-corners='sharp'] overrides", () => {
    const cssPath = path.resolve(process.cwd().endsWith("frontend") ? "src/index.css" : "frontend/src/index.css");
    const cssText = fs.readFileSync(cssPath, "utf-8");

    // Check @theme radius variables
    expect(cssText).toContain("--radius-xs: var(--radius-xs);");
    expect(cssText).toContain("--radius-sm: var(--radius-sm);");
    expect(cssText).toContain("--radius-md: var(--radius-md);");
    expect(cssText).toContain("--radius-lg: var(--radius-lg);");
    expect(cssText).toContain("--radius-xl: var(--radius-xl);");
    expect(cssText).toContain("--radius-2xl: var(--radius-2xl);");
    expect(cssText).toContain("--radius-3xl: var(--radius-3xl);");
    expect(cssText).toContain("--radius: var(--radius-md);");

    // Check sharp mode overrides
    const sharpMatch = cssText.match(/\[data-corners="sharp"\]\s*\{([^}]+)\}/);
    expect(sharpMatch, "Must define [data-corners='sharp'] block in index.css").not.toBeNull();
    const sharpBody = sharpMatch![1];
    expect(sharpBody).toContain("--radius-xs: 1px;");
    expect(sharpBody).toContain("--radius-sm: 2px;");
    expect(sharpBody).toContain("--radius-md: 2px;");
    expect(sharpBody).toContain("--radius-lg: 2px;");
    expect(sharpBody).toContain("--radius-xl: 3px;");
    expect(sharpBody).toContain("--radius-2xl: 3px;");
    expect(sharpBody).toContain("--radius-3xl: 4px;");
  });

  it("6. Does not render duplicate paletteBadge next to skin title in skin gallery cards", () => {
    render(<AppearanceSettingsSection />);
    // Each skin should have its name rendered exactly once per card, not duplicated as a badge
    const obsidianMatches = screen.getAllByText("Obsidian Graphite");
    expect(obsidianMatches).toHaveLength(1);

    const midnightMatches = screen.getAllByText("Midnight Nord");
    expect(midnightMatches).toHaveLength(1);

    const cyberMatches = screen.getAllByText("Cyber Matrix");
    expect(cyberMatches).toHaveLength(1);
  });

  it("7. Density cards use bg-surface-muted without inner bordered boxes", () => {
    const { container } = render(<AppearanceSettingsSection />);
    // Density preview boxes should use bg-surface-muted and not have border-border-subtle inside the card
    const mutedDensityBoxes = container.querySelectorAll(".bg-surface-muted");
    expect(mutedDensityBoxes.length).toBeGreaterThan(0);
    const densityBorderedBoxes = container.querySelectorAll(".space-y-2.border-border-subtle, .space-y-1.border-border-subtle");
    expect(densityBorderedBoxes.length).toBe(0);
  });
});
