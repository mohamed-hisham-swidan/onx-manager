import { describe, it, expect } from "vitest";
import { validateSkinJson, ALLOWED_TOKEN_KEYS } from "./skinValidator";

describe("Custom Skin Validator (Phase 6 Contract)", () => {
  it("approves a valid custom skin definition", () => {
    const valid = {
      id: "emerald-forest",
      name: "Emerald Forest",
      description: "Lush green natural Minecraft server theme",
      version: "1.0.0",
      tokens: {
        "surface-page": "#0a130e",
        "surface-card": "#112017",
        "surface-hover": "#172c20",
        "surface-elevated": "#193123",
        "text-primary": "#f0fdf4",
        "text-secondary": "#bbf7d0",
        "text-muted": "#86efac",
        "border-default": "#22c55e",
        "border-focus": "#4ade80",
        "accent-primary": "#16a34a",
        "accent-contrast-text": "#ffffff",
      },
    };

    const res = validateSkinJson(valid);
    expect(res.valid).toBe(true);
    expect(res.errors).toHaveLength(0);
    expect(res.skin?.id).toBe("emerald-forest");
  });

  it("approves a valid skin when passed as a JSON string", () => {
    const jsonStr = JSON.stringify({
      id: "minimal",
      name: "Minimal Skin",
      tokens: {
        "surface-page": "#121212",
        "text-primary": "rgba(255, 255, 255, 0.95)",
      },
    });

    const res = validateSkinJson(jsonStr);
    expect(res.valid).toBe(true);
    expect(res.skin?.name).toBe("Minimal Skin");
  });

  it("rejects invalid JSON syntax string", () => {
    const res = validateSkinJson("{ invalid json");
    expect(res.valid).toBe(false);
    expect(res.errors[0]).toMatch(/invalid json syntax/i);
  });

  it("rejects non-object root types", () => {
    expect(validateSkinJson(null).valid).toBe(false);
    expect(validateSkinJson(42).valid).toBe(false);
    expect(validateSkinJson(["array"]).valid).toBe(false);
  });

  it("rejects invalid IDs (uppercase, special characters, whitespace)", () => {
    const invalidIds = ["Invalid-Caps", "with spaces", "a", "too_long_".repeat(6), "special$char"];
    for (const id of invalidIds) {
      const res = validateSkinJson({
        id,
        name: "Test",
        tokens: { "surface-page": "#111" },
      });
      expect(res.valid, `Expected ID '${id}' to be rejected`).toBe(false);
      expect(res.errors.some((e) => e.includes("id"))).toBe(true);
    }
  });

  it("rejects unknown or unallowlisted token keys", () => {
    const res = validateSkinJson({
      id: "rogue-tokens",
      name: "Rogue",
      tokens: {
        "surface-page": "#111111",
        "fake-token-not-in-spec": "#222222",
        "background-color": "#333333",
      },
    });

    expect(res.valid).toBe(false);
    expect(res.errors.some((e) => e.includes("fake-token-not-in-spec"))).toBe(true);
    expect(res.errors.some((e) => e.includes("background-color"))).toBe(true);
  });

  it("rejects CSS injection attempts (url, semicolons, brackets, script)", () => {
    const maliciousValues = [
      "url('https://evil.com/leak')",
      "#111111; color: red;",
      "#111111; } body { display: none; } {",
      "<script>alert(1)</script>",
      "expression(document.cookie)",
      "@import 'evil.css'",
    ];

    for (const val of maliciousValues) {
      const res = validateSkinJson({
        id: "exploit-test",
        name: "Exploit",
        tokens: { "surface-page": val },
      });
      expect(res.valid, `Expected injection '${val}' to be rejected`).toBe(false);
      expect(res.errors.some((e) => e.includes("injection") || e.includes("Invalid color"))).toBe(true);
    }
  });

  it("rejects invalid color values that are not hex, rgb, rgba, or hsl", () => {
    const nonColors = ["red", "transparent", "inherit", "12px", "bold", "#12", "rgb(9999,0)"];
    for (const val of nonColors) {
      const res = validateSkinJson({
        id: "color-test",
        name: "Color Test",
        tokens: { "surface-page": val },
      });
      expect(res.valid, `Expected invalid color '${val}' to be rejected`).toBe(false);
    }
  });

  it("rejects payloads that exceed size or key count limits", () => {
    const oversizedString = JSON.stringify({
      id: "huge",
      name: "Huge",
      description: "x".repeat(35000),
      tokens: { "surface-page": "#111111" },
    });

    const res = validateSkinJson(oversizedString);
    expect(res.valid).toBe(false);
    expect(res.errors[0]).toMatch(/payload limit/i);
  });

  it("allows all tokens defined in the design token registry", () => {
    const allTokens: Record<string, string> = {};
    for (const key of ALLOWED_TOKEN_KEYS) {
      allTokens[key] = "#123456";
    }

    const res = validateSkinJson({
      id: "complete-palette",
      name: "Complete Palette",
      tokens: allTokens,
    });

    expect(res.valid).toBe(true);
    expect(Object.keys(res.skin?.tokens || {})).toHaveLength(ALLOWED_TOKEN_KEYS.size);
  });
});
