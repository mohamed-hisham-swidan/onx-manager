import { describe, it, expect } from "vitest";
import { formatBytes, formatDateTime, formatRelativeTime, parseServerDate } from "./format";

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

describe("formatRelativeTime", () => {
  it("returns empty string for missing or invalid dates", () => {
    expect(formatRelativeTime(null)).toBe("");
    expect(formatRelativeTime("")).toBe("");
    expect(formatRelativeTime("invalid-date")).toBe("");
  });

  it("formats recent dates as relative time", () => {
    const recent = new Date(Date.now() - 30_000).toISOString();
    expect(formatRelativeTime(recent)).toBe("just now");

    const tenMinutesAgo = new Date(Date.now() - 10 * 60_000).toISOString();
    expect(formatRelativeTime(tenMinutesAgo)).toBe("10m ago");
  });
});

describe("parseServerDate", () => {
  it("returns null for empty, null, or undefined values", () => {
    expect(parseServerDate(null)).toBeNull();
    expect(parseServerDate(undefined)).toBeNull();
    expect(parseServerDate("")).toBeNull();
    expect(parseServerDate("   ")).toBeNull();
  });

  it("returns null for unparseable strings", () => {
    expect(parseServerDate("invalid-date-string")).toBeNull();
  });

  it("treats naive ISO datetimes as UTC", () => {
    const d = parseServerDate("2026-10-03T11:00:00");
    expect(d).not.toBeNull();
    expect(d!.toISOString()).toBe("2026-10-03T11:00:00.000Z");
  });

  it("treats space-separated datetimes as UTC", () => {
    const d = parseServerDate("2026-10-03 11:00:00");
    expect(d).not.toBeNull();
    expect(d!.toISOString()).toBe("2026-10-03T11:00:00.000Z");
  });

  it("preserves explicit Z without double appending", () => {
    const d = parseServerDate("2026-10-03T11:00:00Z");
    expect(d).not.toBeNull();
    expect(d!.toISOString()).toBe("2026-10-03T11:00:00.000Z");
  });

  it("preserves explicit timezone offsets", () => {
    const d = parseServerDate("2026-10-03T14:00:00+03:00");
    expect(d).not.toBeNull();
    expect(d!.toISOString()).toBe("2026-10-03T11:00:00.000Z");
  });

  it("treats date-only strings as UTC midnight", () => {
    const d = parseServerDate("2026-10-03");
    expect(d).not.toBeNull();
    expect(d!.toISOString()).toBe("2026-10-03T00:00:00.000Z");
  });

  it("handles numeric epoch in seconds and milliseconds", () => {
    const epochSec = 1762110000;
    const dSec = parseServerDate(epochSec);
    expect(dSec).not.toBeNull();
    expect(dSec!.getTime()).toBe(epochSec * 1000);

    const epochMs = 1762110000000;
    const dMs = parseServerDate(epochMs);
    expect(dMs).not.toBeNull();
    expect(dMs!.getTime()).toBe(epochMs);

    const strSec = parseServerDate("1762110000");
    expect(strSec).not.toBeNull();
    expect(strSec!.getTime()).toBe(epochSec * 1000);
  });

  it("handles existing Date objects", () => {
    const original = new Date("2026-10-03T11:00:00Z");
    const d = parseServerDate(original);
    expect(d).toBe(original);
  });
});
