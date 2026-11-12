import type { ServerMode } from "../types";

/**
 * Resolves a raw server mode string into a valid ServerMode ('simple' | 'advanced').
 * Failsafe: defaults to 'simple' for undefined, null, empty string, or any unknown value.
 */
export function resolveServerMode(mode?: string | null): ServerMode {
  if (typeof mode === "string" && mode.trim().toLowerCase() === "advanced") {
    return "advanced";
  }
  return "simple";
}

/**
 * Returns the human-readable display label for a server mode.
 */
export function serverModeLabel(mode?: string | null): "Simple" | "Advanced" {
  return resolveServerMode(mode) === "advanced" ? "Advanced" : "Simple";
}
