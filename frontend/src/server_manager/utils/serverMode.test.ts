import { describe, it, expect } from "vitest";
import { resolveServerMode, serverModeLabel } from "./serverMode";

describe("serverMode utils", () => {
  describe("resolveServerMode", () => {
    it("resolves lowercase advanced", () => {
      expect(resolveServerMode("advanced")).toBe("advanced");
    });

    it("resolves uppercase and mixed-case advanced", () => {
      expect(resolveServerMode("ADVANCED")).toBe("advanced");
      expect(resolveServerMode("  Advanced  ")).toBe("advanced");
    });

    it("resolves simple", () => {
      expect(resolveServerMode("simple")).toBe("simple");
      expect(resolveServerMode("SIMPLE")).toBe("simple");
    });

    it("failsafe defaults to simple for null or undefined", () => {
      expect(resolveServerMode(undefined)).toBe("simple");
      expect(resolveServerMode(null)).toBe("simple");
    });

    it("failsafe defaults to simple for empty or unrecognized values", () => {
      expect(resolveServerMode("")).toBe("simple");
      expect(resolveServerMode("   ")).toBe("simple");
      expect(resolveServerMode("custom")).toBe("simple");
      expect(resolveServerMode("intermediate")).toBe("simple");
    });
  });

  describe("serverModeLabel", () => {
    it("returns Advanced for advanced mode", () => {
      expect(serverModeLabel("advanced")).toBe("Advanced");
      expect(serverModeLabel("ADVANCED")).toBe("Advanced");
    });

    it("returns Simple for simple mode or fallback values", () => {
      expect(serverModeLabel("simple")).toBe("Simple");
      expect(serverModeLabel(undefined)).toBe("Simple");
      expect(serverModeLabel(null)).toBe("Simple");
      expect(serverModeLabel("unknown")).toBe("Simple");
    });
  });
});
