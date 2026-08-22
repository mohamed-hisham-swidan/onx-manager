import { describe, it, expect } from "vitest";
import {
  isModernForgeVersion,
  forgeEditionForVersion,
  FORGE_EDITION_LABELS,
} from "./forgeEdition";

describe("forgeEdition", () => {
  it("classifies modern versions (>= 1.17) as the installer flow", () => {
    expect(isModernForgeVersion("1.17")).toBe(true);
    expect(isModernForgeVersion("1.17.1")).toBe(true);
    expect(isModernForgeVersion("1.18.2")).toBe(true);
    expect(isModernForgeVersion("1.20.4")).toBe(true);
    expect(isModernForgeVersion("1.21.8")).toBe(true);
    expect(isModernForgeVersion("2.0")).toBe(true);
    expect(isModernForgeVersion("1.21.8")).toBe(true);
  });

  it("classifies legacy versions (< 1.17) as the universal-jar flow", () => {
    expect(isModernForgeVersion("1.16.5")).toBe(false);
    expect(isModernForgeVersion("1.12.2")).toBe(false);
    expect(isModernForgeVersion("1.8.9")).toBe(false);
    expect(isModernForgeVersion("1.0")).toBe(false);
  });

  it("defaults unparseable input to the modern installer flow (matches backend)", () => {
    expect(isModernForgeVersion("latest")).toBe(true);
    expect(isModernForgeVersion("")).toBe(true);
  });

  it("compares numerically, never lexically (1.17 vs 1.8)", () => {
    expect(isModernForgeVersion("1.8")).toBe(false);
    expect(forgeEditionForVersion("1.8")).toBe("legacy");
    expect(forgeEditionForVersion("1.21.1")).toBe("modern");
  });

  it("labels both editions", () => {
    expect(FORGE_EDITION_LABELS.modern.label).toContain("1.17+");
    expect(FORGE_EDITION_LABELS.legacy.label).toContain("< 1.17");
  });
});