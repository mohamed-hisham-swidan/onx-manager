import { describe, it, expect } from "vitest";
import {
  clampSplitRatio,
  DEFAULT_FILES_SPLIT_RATIO,
  extractApiErrorMessage,
  FILES_SPLIT_RATIO_STORAGE_KEY,
  getFileClassBadge,
  getFileIconName,
  isBinaryFile,
  isImageFile,
  joinRelativePath,
  MAX_FILES_SPLIT_RATIO,
  MIN_FILES_SPLIT_RATIO,
  readStoredSplitRatio,
  sortFileRows,
  validateNewEntryName,
  writeStoredSplitRatio,
  type UnifiedFileRow,
} from "./filesUtils";
import { ApiError } from "@/services/api";

describe("filesUtils", () => {
  it("identifies images and binary files accurately", () => {
    expect(isImageFile("server-icon.png")).toBe(true);
    expect(isImageFile("banner.WEBP")).toBe(true);
    expect(isImageFile("server.properties")).toBe(false);

    expect(isBinaryFile("world.mca")).toBe(true);
    expect(isBinaryFile("plugin.jar")).toBe(true);
    expect(isBinaryFile("latest.log")).toBe(false);
    expect(isBinaryFile("config.yml")).toBe(false);
  });

  it("maps file extensions to appropriate semantic icons", () => {
    expect(getFileIconName("plugins", true)).toBe("folder");
    expect(getFileIconName("server.properties", false)).toBe("settings");
    expect(getFileIconName("start.sh", false)).toBe("terminal");
    expect(getFileIconName("backup.zip", false)).toBe("backup");
    expect(getFileIconName("server-icon.png", false)).toBe("eye");
    expect(getFileIconName("latest.log", false)).toBe("file");
  });

  it("sorts directories first while respecting sort field and direction", () => {
    const rows: UnifiedFileRow[] = [
      { name: "b.txt", path: "b.txt", is_dir: false, size: 100, modified_at: "2026-01-01T00:00:00Z" },
      { name: "world", path: "world", is_dir: true, size: 0, modified_at: "2026-01-02T00:00:00Z" },
      { name: "a.yml", path: "a.yml", is_dir: false, size: 500, modified_at: "2026-01-03T00:00:00Z" },
    ];

    expect(sortFileRows(rows, "name", "asc").map((r) => r.name)).toEqual(["world", "a.yml", "b.txt"]);
    expect(sortFileRows(rows, "size", "desc").map((r) => r.name)).toEqual(["world", "a.yml", "b.txt"]);
    expect(sortFileRows(rows, "modified", "desc").map((r) => r.name)).toEqual(["world", "a.yml", "b.txt"]);
  });

  it("preserves backend ApiError message in extractApiErrorMessage", () => {
    const err = new ApiError(403, "PERMISSION_DENIED", "Only Class-B configuration files can be edited on an Advanced branch");
    expect(extractApiErrorMessage(err, "Fallback")).toBe(
      "Only Class-B configuration files can be edited on an Advanced branch",
    );
    expect(extractApiErrorMessage(new Error(""), "Fallback")).toBe("Fallback");
  });

  it("validates new entry names against traversal and .env", () => {
    expect(validateNewEntryName("")).not.toBeNull();
    expect(validateNewEntryName("../secret.txt")).not.toBeNull();
    expect(validateNewEntryName(".env")).not.toBeNull();
    expect(validateNewEntryName(".ENV ")).not.toBeNull();
    expect(validateNewEntryName("config/custom.yml")).toBeNull();
    expect(joinRelativePath("config", "custom.yml")).toBe("config/custom.yml");
    expect(joinRelativePath("", "ops.json")).toBe("ops.json");
  });

  it("never labels Live State directories as Read-Only Binary", () => {
    const dirRow: UnifiedFileRow = {
      name: "warps",
      path: "/plugins/Essentials/warps",
      is_dir: true,
      size: 0,
      file_class: "C",
      writable: false,
    };
    expect(getFileClassBadge(dirRow, true)).toBeNull();

    const dynFile: UnifiedFileRow = {
      name: "whitelist.json",
      path: "/whitelist.json",
      is_dir: false,
      size: 20,
      file_class: "C",
      is_dynamic_class_c: true,
      writable: true,
    };
    expect(getFileClassBadge(dynFile, true)?.label).toBe("Live Runtime");
    expect(getFileClassBadge(dynFile, true, false)).toBeNull();
    expect(getFileClassBadge({ ...dynFile, file_class: "A", is_dynamic_class_c: false }, false, false)).toBeNull();
    expect(getFileClassBadge({ ...dynFile, file_class: "E", is_dynamic_class_c: false }, false, false)).toBeNull();
    expect(getFileClassBadge({ ...dynFile, file_class: "A", is_dynamic_class_c: false }, false, true)?.label).toBe("Managed Binary");
  });

  it("clamps and persists split view ratio with safe fallback to 43", () => {
    window.localStorage.removeItem(FILES_SPLIT_RATIO_STORAGE_KEY);
    expect(readStoredSplitRatio()).toBe(DEFAULT_FILES_SPLIT_RATIO);

    expect(clampSplitRatio(10)).toBe(MIN_FILES_SPLIT_RATIO);
    expect(clampSplitRatio(90)).toBe(MAX_FILES_SPLIT_RATIO);
    expect(clampSplitRatio(Number.NaN)).toBe(DEFAULT_FILES_SPLIT_RATIO);

    writeStoredSplitRatio(55);
    expect(readStoredSplitRatio()).toBe(55);

    window.localStorage.setItem(FILES_SPLIT_RATIO_STORAGE_KEY, "invalid-num");
    expect(readStoredSplitRatio()).toBe(DEFAULT_FILES_SPLIT_RATIO);

    window.localStorage.setItem(FILES_SPLIT_RATIO_STORAGE_KEY, "12");
    expect(readStoredSplitRatio()).toBe(MIN_FILES_SPLIT_RATIO);
  });
});
