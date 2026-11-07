/**
 * Dynamic Favicon Utility
 *
 * Synchronizes the browser tab SVG favicon with the active skin's brand mark color tokens.
 * Gracefully catches all runtime/DOM errors to guarantee the static favicon remains intact on failure.
 */

export function updateDynamicFavicon(markColor?: string, bgFill?: string): void {
  try {
    if (typeof document === "undefined") return;
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"][type="image/svg+xml"]');
    if (!link) return;

    const computed = typeof window !== "undefined" && typeof window.getComputedStyle === "function"
      ? window.getComputedStyle(document.documentElement)
      : null;

    const color =
      markColor ||
      computed?.getPropertyValue("--brand-mark-1").trim() ||
      "rgb(214, 242, 92)";

    const bg =
      bgFill ||
      computed?.getPropertyValue("--brand-mark-2").trim() ||
      "rgb(16, 22, 20)";

    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="${bg}"/><g fill="none" stroke-width="5.5" stroke-linecap="round" stroke="${color}"><path d="M12 12 L52 52"/><path d="M52 12 L12 52"/></g><circle cx="32" cy="32" r="13" fill="${bg}" stroke="${color}" stroke-width="5.5"/></svg>`;

    link.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  } catch {
    // Graceful fallback: leave static favicon untouched
  }
}
