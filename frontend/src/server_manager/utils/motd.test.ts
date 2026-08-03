import { describe, it, expect } from "vitest";
import { stripMinecraftFormatting } from "./motd";

describe("stripMinecraftFormatting", () => {
  it("removes section-sign color codes", () => {
    expect(stripMinecraftFormatting("\u00a7bHello\u00a7r")).toBe("Hello");
  });

  it("removes ampersand color codes", () => {
    expect(stripMinecraftFormatting("&6Gold &eServer")).toBe("Gold Server");
  });

  it("removes dollar-style color codes", () => {
    expect(stripMinecraftFormatting("$bWelcome $r")).toBe("Welcome");
  });

  it("removes hex color codes", () => {
    expect(stripMinecraftFormatting("\u00a7x\u00a7f\u00a7f\u00a7a\u00a7b\u00a7c\u00a7dRainbow")).toBe("Rainbow");
    expect(stripMinecraftFormatting("&#ff0000Red")).toBe("Red");
  });

  it("converts escaped newlines to spaces", () => {
    expect(stripMinecraftFormatting("Line one\\nLine two")).toBe("Line one Line two");
  });

  it("leaves plain text untouched", () => {
    expect(stripMinecraftFormatting("A Minecraft Server")).toBe("A Minecraft Server");
  });

  it("trims surrounding whitespace", () => {
    expect(stripMinecraftFormatting("  hello  ")).toBe("hello");
  });
});
