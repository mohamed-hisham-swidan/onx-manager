import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Button, IconButton } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

declare const require: (mod: string) => { readFileSync: (p: string, enc: string) => string; resolve: (...args: string[]) => string };
declare const process: { cwd: () => string };
const fs = require("node:fs");
const path = require("node:path");

describe("Phase 8: Accessibility & Motion Polish", () => {
  const cssPath = path.resolve(process.cwd().endsWith("frontend") ? "src/index.css" : "frontend/src/index.css");
  const cssContent = fs.readFileSync(cssPath, "utf8");

  describe("Restrained Motion & Easing Tokens", () => {
    it("defines motion duration tokens (fast, normal, slow)", () => {
      expect(cssContent).toContain("--motion-duration-fast");
      expect(cssContent).toContain("--motion-duration-normal");
      expect(cssContent).toContain("--motion-duration-slow");
    });

    it("defines natural cubic-bezier motion ease token", () => {
      expect(cssContent).toContain("--motion-ease-default");
      expect(cssContent).toContain("cubic-bezier");
    });

    it("includes prefers-reduced-motion media query that zeroes animation durations", () => {
      expect(cssContent).toContain("@media (prefers-reduced-motion: reduce)");
      expect(cssContent).toContain("animation-duration: 0.01ms !important");
      expect(cssContent).toContain("transition-duration: 0.01ms !important");
    });
  });

  describe("Accessibility: Visible Focus & ARIA Contracts", () => {
    it("defines global :focus-visible outline with tokenized border-focus", () => {
      expect(cssContent).toContain(":focus-visible");
      expect(cssContent).toContain("var(--border-focus)");
    });

    it("Button renders with proper keyboard focusable element", () => {
      render(<Button>Click me</Button>);
      const btn = screen.getByRole("button", { name: "Click me" });
      expect(btn).toBeInTheDocument();
      expect(btn.tabIndex).toBe(0);
    });

    it("IconButton mandates accessible label via aria-label", () => {
      render(<IconButton icon="settings" aria-label="Open settings" />);
      const btn = screen.getByRole("button", { name: "Open settings" });
      expect(btn).toBeInTheDocument();
      expect(btn).toHaveAttribute("aria-label", "Open settings");
    });

    it("Modal provides role='dialog' and aria-modal='true'", () => {
      render(
        <Modal open={true} onClose={() => {}} title="Test Modal">
          <p>Modal content</p>
        </Modal>
      );
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(dialog).toHaveAttribute("aria-modal", "true");
    });

    it("ConfirmDialog provides role='dialog' and aria-modal='true'", () => {
      render(
        <ConfirmDialog
          open={true}
          title="Delete Server"
          description="Are you sure?"
          confirmLabel="Delete"
          onConfirm={() => {}}
          onCancel={() => {}}
          variant="danger"
        />
      );
      const dialog = screen.getByRole("dialog");
      expect(dialog).toBeInTheDocument();
      expect(dialog).toHaveAttribute("aria-modal", "true");
    });
  });
});
