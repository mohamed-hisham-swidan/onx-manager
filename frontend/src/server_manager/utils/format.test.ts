import { describe, it, expect } from "vitest";
import { formatBytes, formatDateTime } from "./format";

describe("formatBytes", () => {
  it("formats zero as 0 B", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(null)).toBe("0 B");
    expect(formatBytes(undefined)).toBe("0 B");
  });

  it("formats bytes with units", () => {
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1048576)).toBe("1.0 MB");
  });
});

describe("formatDateTime", () => {
  it("returns a placeholder for missing dates", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("")).toBe("—");
  });

  it("returns a placeholder for invalid dates", () => {
    expect(formatDateTime("not-a-date")).toBe("—");
  });

  it("formats valid dates", () => {
    expect(formatDateTime("2024-01-01T00:00:00Z")).toContain("2024");
  });
});
