import { ApiError } from "@/services/api";
import type { IconName } from "@/components/ui/Icon";
import type { FileItem, LiveStateFileEntry } from "@/server_manager/types";

export const NON_EDITABLE_EXTENSIONS = new Set([
  "dat",
  "dat_old",
  "mca",
  "mcr",
  "sqlite",
  "sqlite3",
  "db",
  "nbt",
  "jar",
  "zip",
  "tar",
  "gz",
  "7z",
  "rar",
  "png",
  "jpg",
  "jpeg",
  "gif",
  "webp",
  "ico",
  "class",
  "exe",
  "dll",
  "so",
  "dylib",
  "litematic",
  "schem",
  "schematic",
  "ogg",
  "mp3",
  "wav",
  "ttf",
  "otf",
]);

export const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "ico"]);

const CONFIG_EXTENSIONS = new Set([
  "properties",
  "yml",
  "yaml",
  "json",
  "json5",
  "toml",
  "ini",
  "cfg",
  "conf",
  "snbt",
  "mcmeta",
  "xml",
]);

const SCRIPT_EXTENSIONS = new Set(["sh", "bash", "bat", "cmd", "ps1", "js", "zs", "sk", "dsc"]);
const ARCHIVE_EXTENSIONS = new Set(["zip", "tar", "gz", "7z", "rar", "jar"]);

export interface UnifiedFileRow {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  modified_at?: string | number | null;
  file_class?: string | null;
  editable?: boolean | null;
  is_dynamic_class_c?: boolean;
  writable?: boolean;
}

export type SortField = "name" | "modified" | "size" | "type";
export type SortDirection = "asc" | "desc";

export function getExtension(fileName: string): string {
  const idx = fileName.lastIndexOf(".");
  if (idx <= 0 || idx === fileName.length - 1) return "";
  return fileName.slice(idx + 1).toLowerCase();
}

export function isImageFile(fileName: string): boolean {
  return IMAGE_EXTENSIONS.has(getExtension(fileName));
}

export function isBinaryFile(fileName: string): boolean {
  const ext = getExtension(fileName);
  return Boolean(ext && NON_EDITABLE_EXTENSIONS.has(ext));
}

export function getFileIconName(fileName: string, isDir: boolean): IconName {
  if (isDir) return "folder";
  const ext = getExtension(fileName);
  if (CONFIG_EXTENSIONS.has(ext)) return "settings";
  if (SCRIPT_EXTENSIONS.has(ext)) return "terminal";
  if (ARCHIVE_EXTENSIONS.has(ext)) return "backup";
  if (IMAGE_EXTENSIONS.has(ext)) return "eye";
  return "file";
}

export function toUnifiedFromStandard(item: FileItem): UnifiedFileRow {
  return {
    name: item.name,
    path: item.path,
    is_dir: item.is_dir,
    size: item.size,
    modified_at: item.modified_at ?? null,
    file_class: item.file_class ?? null,
    editable: item.editable ?? null,
  };
}

export function toUnifiedFromLiveState(item: LiveStateFileEntry): UnifiedFileRow {
  return {
    name: item.name,
    path: item.path,
    is_dir: item.is_dir,
    size: item.size,
    modified_at: item.modified_at ?? null,
    file_class: item.file_class,
    editable: item.is_dir ? false : item.writable,
    is_dynamic_class_c: item.is_dynamic_class_c,
    writable: item.writable,
  };
}

function toTimestampMs(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value <= 0) return 0;
    return value < 1e11 ? value * 1000 : value;
  }
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? 0 : ms;
}

export function sortFileRows(
  rows: UnifiedFileRow[],
  field: SortField,
  direction: SortDirection,
): UnifiedFileRow[] {
  const dirFactor = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    // Directories always stay grouped before files for predictable browsing
    if (a.is_dir !== b.is_dir) {
      return a.is_dir ? -1 : 1;
    }

    if (field === "size") {
      if (a.size !== b.size) return (a.size - b.size) * dirFactor;
    } else if (field === "modified") {
      const ta = toTimestampMs(a.modified_at);
      const tb = toTimestampMs(b.modified_at);
      if (ta !== tb) return (ta - tb) * dirFactor;
    } else if (field === "type") {
      const extA = a.is_dir ? "" : getExtension(a.name);
      const extB = b.is_dir ? "" : getExtension(b.name);
      const extCmp = extA.localeCompare(extB);
      if (extCmp !== 0) return extCmp * dirFactor;
    }

    return a.name.toLowerCase().localeCompare(b.name.toLowerCase()) * dirFactor;
  });
}

export interface FileClassBadgeInfo {
  label: string;
  title: string;
  tone: "neutral" | "info" | "warning" | "accent";
}

export function getFileClassBadge(
  row: UnifiedFileRow,
  isLiveState: boolean,
  isAdvancedMode = true,
): FileClassBadgeInfo | null {
  if (!isAdvancedMode) return null;
  if (isLiveState) {
    if (row.is_dir) return null;
    if (row.is_dynamic_class_c) {
      return {
        label: "Live Runtime",
        title: "Live runtime file",
        tone: "accent",
      };
    }
    return {
      label: "Live Data",
      title: "Live data runtime file",
      tone: "info",
    };
  }

  if (row.is_dir || !row.file_class) return null;
  if (row.file_class === "A") {
    return {
      label: "Managed Binary",
      title: "Managed binary (read-only in Files)",
      tone: "neutral",
    };
  }
  if (row.file_class === "C") {
    return {
      label: "Live Data",
      title: "Runtime live-state file (edit via Live State view)",
      tone: "info",
    };
  }
  if (row.file_class === "E") {
    return {
      label: "Class E",
      title: "Untracked runtime/ephemeral file",
      tone: "warning",
    };
  }
  return null;
}

export function extractApiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.message.trim().length > 0) {
    return err.message;
  }
  if (err instanceof Error && err.message.trim().length > 0) {
    return err.message;
  }
  return fallback;
}

export function joinRelativePath(baseDir: string, name: string): string {
  const cleanBase = baseDir.replace(/^\/+|\/+$/g, "");
  const cleanName = name.replace(/^\/+|\/+$/g, "");
  return cleanBase ? `${cleanBase}/${cleanName}` : cleanName;
}

export const FILES_SPLIT_RATIO_STORAGE_KEY = "onx_files_split_ratio";
export const DEFAULT_FILES_SPLIT_RATIO = 43;
export const MIN_FILES_SPLIT_RATIO = 26;
export const MAX_FILES_SPLIT_RATIO = 68;
export const FILES_SPLIT_KEYBOARD_STEP = 2;

export function clampSplitRatio(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_FILES_SPLIT_RATIO;
  const rounded = Math.round(value * 10) / 10;
  return Math.min(MAX_FILES_SPLIT_RATIO, Math.max(MIN_FILES_SPLIT_RATIO, rounded));
}

export function readStoredSplitRatio(): number {
  if (typeof window === "undefined") return DEFAULT_FILES_SPLIT_RATIO;
  try {
    const raw = window.localStorage.getItem(FILES_SPLIT_RATIO_STORAGE_KEY);
    if (raw === null || raw.trim() === "") return DEFAULT_FILES_SPLIT_RATIO;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? clampSplitRatio(parsed) : DEFAULT_FILES_SPLIT_RATIO;
  } catch {
    return DEFAULT_FILES_SPLIT_RATIO;
  }
}

export function writeStoredSplitRatio(ratio: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(FILES_SPLIT_RATIO_STORAGE_KEY, String(clampSplitRatio(ratio)));
  } catch {
    // Storage can be unavailable in privacy-restricted contexts.
  }
}

export function validateNewEntryName(rawName: string): string | null {
  const trimmed = rawName.trim();
  if (!trimmed) return "Name is required.";
  if (trimmed.includes("\\") || trimmed.includes("\0")) {
    return "Name cannot contain backslashes or null bytes.";
  }
  if (trimmed.startsWith("/") || trimmed.endsWith("/")) {
    return "Name cannot start or end with '/'.";
  }
  const segments = trimmed.split("/");
  if (segments.some((seg) => !seg || seg === "." || seg === "..")) {
    return "Name cannot contain empty, '.' or '..' segments.";
  }
  const normalizedLast = segments[segments.length - 1].replace(/[. ]+$/, "").toLowerCase();
  if (normalizedLast === ".env") {
    return "'.env' is a protected secret file and cannot be created here.";
  }
  return null;
}
