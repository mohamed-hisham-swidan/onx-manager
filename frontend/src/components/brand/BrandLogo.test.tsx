import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrandLogo } from "./BrandLogo";
import { updateDynamicFavicon } from "@/tokens/dynamicFavicon";
import { useUIStore } from "@/stores/uiStore";

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

describe("BrandLogo Component (Theme-Aware)", () => {
  it("renders full lockup with mark and wordmark", () => {
    const { container } = render(<BrandLogo variant="full" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(screen.getByText("ONX")).toBeInTheDocument();
    expect(screen.getByText("Manager")).toBeInTheDocument();
  });

  it("renders mark-only variant with accessible aria-label", () => {
    const { container } = render(<BrandLogo variant="mark" />);
    const markContainer = container.firstElementChild;
    expect(markContainer).toHaveAttribute("aria-label", "ONX Manager");
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(screen.queryByText("ONX")).not.toBeInTheDocument();
  });

  it("uses CSS variables for shapes and text with zero hardcoded colors", () => {
    const { container } = render(<BrandLogo variant="full" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toBeInTheDocument();

    const rect = svg.querySelector("rect");
    expect(rect).toHaveAttribute("fill", "var(--brand-mark-2)");

    const g = svg.querySelector("g");
    expect(g).toHaveAttribute("stroke", "var(--brand-mark-1)");

    const circle = svg.querySelector("circle");
    expect(circle).toHaveAttribute("stroke", "var(--brand-mark-1)");
    expect(circle).toHaveAttribute("fill", "var(--brand-mark-2)");

    // Ensure zero hard-coded hex or rgb colors in the rendered SVG
    expect(svg.innerHTML).not.toMatch(/#[0-9a-fA-F]{3,8}/);
    expect(svg.innerHTML).not.toMatch(/rgba?\(/);

    // Wordmark text uses var(--brand-ink)
    const onxText = screen.getByText("ONX");
    expect(onxText.className).toContain("text-[var(--brand-ink)]");
  });

  it("applies customized size attributes", () => {
    const { container } = render(<BrandLogo variant="mark" size="lg" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("width", "48");
    expect(svg).toHaveAttribute("height", "48");
  });
});

describe("Skin Registry Brand Tokens Contract", () => {
  it("defines --brand-mark-1, --brand-mark-2, and --brand-ink in every skin and mode", () => {
    const cssPath = path.resolve(process.cwd().endsWith("frontend") ? "src/index.css" : "frontend/src/index.css");
    const cssText = fs.readFileSync(cssPath, "utf-8");

    const requiredSelectors = [
      ":root",
      '.dark, [data-mode="dark"]',
      '[data-skin="graphite"]',
      '[data-skin="graphite"][data-mode="light"]',
      '[data-skin="azure"]',
      '[data-skin="azure"][data-mode="light"]',
      '[data-skin="emerald"]',
      '[data-skin="emerald"][data-mode="light"]',
      '[data-skin="amethyst"]',
      '[data-skin="amethyst"][data-mode="light"]',
      '[data-skin="amber"]',
      '[data-skin="amber"][data-mode="light"]',
      '[data-skin="crimson"]',
      '[data-skin="crimson"][data-mode="light"]',
    ];

    for (const sel of requiredSelectors) {
      const escaped = sel
        .replace(/\[/g, "\\[")
        .replace(/\]/g, "\\]")
        .replace(/\(/g, "\\(")
        .replace(/\)/g, "\\)")
        .replace(/\./g, "\\.")
        .replace(/,\s+/g, ",\\s*");
      const regex = new RegExp(escaped + "[^{]*\\{([^}]+)\\}", "m");
      const match = cssText.match(regex);
      expect(match, `Block matching ${sel} must exist in index.css`).not.toBeNull();
      const body = match![1];
      expect(body, `${sel} must define --brand-mark-1`).toContain("--brand-mark-1");
      expect(body, `${sel} must define --brand-mark-2`).toContain("--brand-mark-2");
      expect(body, `${sel} must define --brand-ink`).toContain("--brand-ink");
    }
  });
});

describe("Dynamic Favicon Utility", () => {
  let originalLink: HTMLLinkElement | null = null;

  beforeEach(() => {
    originalLink = document.querySelector('link[rel="icon"][type="image/svg+xml"]');
    if (!originalLink) {
      originalLink = document.createElement("link");
      originalLink.rel = "icon";
      originalLink.type = "image/svg+xml";
      originalLink.href = "/favicon.svg";
      document.head.appendChild(originalLink);
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("updates favicon href with SVG data URI reflecting current mark color", () => {
    updateDynamicFavicon("#38bdf8", "#090d16");
    expect(originalLink!.href).toContain("data:image/svg+xml,");
    expect(decodeURIComponent(originalLink!.href)).toContain("#38bdf8");
    expect(decodeURIComponent(originalLink!.href)).toContain("#090d16");
  });

  it("leaves static favicon intact on failure", () => {
    originalLink!.href = "/favicon.svg";
    vi.spyOn(document, "querySelector").mockImplementationOnce(() => {
      throw new Error("DOM access failed");
    });

    expect(() => updateDynamicFavicon("#ff0000", "#000000")).not.toThrow();
    expect(originalLink!.href).toBe("http://localhost:3000/favicon.svg");
  });

  it("updates favicon when useUIStore sets skin", () => {
    useUIStore.getState().setSkin("azure");
    expect(originalLink!.href).toContain("data:image/svg+xml,");
  });
});

describe("index.html Brand & Icon Meta Links", () => {
  it("contains SVG favicon, ICO fallback, apple-touch-icon, and site manifest", () => {
    const htmlPath = path.resolve(process.cwd().endsWith("frontend") ? "index.html" : "frontend/index.html");
    const html = fs.readFileSync(htmlPath, "utf-8");

    expect(html).toContain('rel="icon" type="image/svg+xml" href="/favicon.svg"');
    expect(html).toContain('rel="alternate icon" href="/favicon.ico"');
    expect(html).toContain('rel="apple-touch-icon" href="/apple-touch-icon.png"');
    expect(html).toContain('rel="manifest" href="/site.webmanifest"');
    expect(html).toContain('<meta name="theme-color"');
  });
});
