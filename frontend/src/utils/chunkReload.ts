import { type ComponentType, lazy, type LazyExoticComponent } from "react";

const RELOAD_STORAGE_KEY = "onx_chunk_reload_at";
const RELOAD_COOLDOWN_MS = 10_000;

export function isChunkLoadError(error: unknown): boolean {
  if (!error) return false;
  const name = error instanceof Error ? error.name : "";
  const message =
    error instanceof Error ? error.message : typeof error === "string" ? error : "";
  const combined = `${name} ${message}`.toLowerCase();
  return (
    combined.includes("failed to fetch dynamically imported module") ||
    combined.includes("importing a module script failed") ||
    combined.includes("error loading dynamically imported module") ||
    combined.includes("unable to preload css") ||
    combined.includes("chunkloaderror")
  );
}

export function tryChunkReloadOnce(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const raw = window.sessionStorage?.getItem(RELOAD_STORAGE_KEY);
    const last = raw ? Number(raw) : 0;
    const now = Date.now();
    if (last && Number.isFinite(last) && now - last < RELOAD_COOLDOWN_MS) {
      return false;
    }
    window.sessionStorage?.setItem(RELOAD_STORAGE_KEY, String(now));
    window.location.reload();
    return true;
  } catch {
    return false;
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- React.lazy requires ComponentType<any>
export function lazyWithReload<T extends ComponentType<any>>(
  factory: () => Promise<{ default: T }>,
): LazyExoticComponent<T> {
  return lazy(async () => {
    try {
      return await factory();
    } catch (err) {
      if (isChunkLoadError(err) && tryChunkReloadOnce()) {
        // Suspend indefinitely while the page reloads to avoid flashing an error UI.
        return new Promise<{ default: T }>(() => {});
      }
      throw err;
    }
  });
}
