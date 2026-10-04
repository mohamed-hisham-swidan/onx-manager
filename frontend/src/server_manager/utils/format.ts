const NAIVE_ISO_OR_SPACE_REGEX = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/;
const DATE_ONLY_REGEX = /^\d{4}-\d{2}-\d{2}$/;
const NUMERIC_ONLY_REGEX = /^\d+(\.\d+)?$/;

export function parseServerDate(
  value: string | number | Date | null | undefined
): Date | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  if (typeof value === "number") {
    if (!Number.isFinite(value) || value <= 0) return null;
    const ms = value < 1e11 ? value * 1000 : value;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  const str = String(value).trim();
  if (!str) return null;

  if (NUMERIC_ONLY_REGEX.test(str)) {
    const num = Number(str);
    if (!Number.isFinite(num) || num <= 0) return null;
    const ms = num < 1e11 ? num * 1000 : num;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  if (DATE_ONLY_REGEX.test(str)) {
    const d = new Date(`${str}T00:00:00Z`);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  if (NAIVE_ISO_OR_SPACE_REGEX.test(str)) {
    const normalized = str.replace(" ", "T") + "Z";
    const d = new Date(normalized);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  const d = new Date(str);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function formatDateTime(dateStr: string | number | Date | null | undefined): string {
  const d = parseServerDate(dateStr);
  if (!d) return "—";
  return d.toLocaleString();
}

export function formatDownloads(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function formatRelativeTime(dateStr: string | number | Date | null | undefined): string {
  const d = parseServerDate(dateStr);
  if (!d) return "";
  const diffMs = Math.max(0, Date.now() - d.getTime());
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(months / 12);
  return `${years}y ago`;
}
