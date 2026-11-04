/**
 * Custom Skin Contract & Token JSON Validator (Phase 6)
 *
 * Provides a pure, zero-dependency validator for custom skin JSON specifications.
 * Enforces strict key allowlists, rigid color grammar (hex/rgb/rgba/hsl), forbidden
 * CSS injection patterns (url, braces, semicolons, script), and strict payload size limits.
 *
 * NOTE: This is the CONTRACT ONLY. No import/editor UI is exposed per ADR-0021.
 */

export const ALLOWED_TOKEN_KEYS = new Set([
  // Surface tokens
  "surface-page",
  "surface-card",
  "surface-hover",
  "surface-active",
  "surface-elevated",
  "surface-overlay",
  "surface-muted",

  // Typography & Text
  "text-primary",
  "text-secondary",
  "text-muted",
  "text-inverse",
  "text-accent",

  // Borders & Boundaries
  "border-subtle",
  "border-default",
  "border-strong",
  "border-focus",

  // Accent & Brand
  "accent-primary",
  "accent-hover",
  "accent-active",
  "accent-contrast-text",

  // Status & Alerts
  "status-success",
  "status-warning",
  "status-danger",
  "status-info",
  "status-neutral",
  "status-success-bg",
  "status-success-border",
  "status-warning-bg",
  "status-warning-border",
  "status-danger-bg",
  "status-danger-border",
  "status-info-bg",
  "status-info-border",

  // Terminal & Console
  "terminal-bg",
  "terminal-text",
  "terminal-cursor",
]);

export interface CustomSkin {
  id: string;
  name: string;
  description?: string;
  version?: string;
  author?: string;
  tokens: Record<string, string>;
}

export interface SkinValidationResult {
  valid: boolean;
  errors: string[];
  skin?: CustomSkin;
}

const MAX_JSON_BYTES = 32 * 1024; // 32 KB limit
const MAX_TOKENS_COUNT = 50;

// Strict color formats allowed:
// #RGB, #RGBA, #RRGGBB, #RRGGBBAA
const HEX_COLOR_REGEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
// rgb(...) and rgba(...) with integers or percentages
const RGB_COLOR_REGEX = /^rgba?\(\s*(\d{1,3}%?)\s*,\s*(\d{1,3}%?)\s*,\s*(\d{1,3}%?)(?:\s*,\s*(0|1|0?\.\d+))?\s*\)$/;
// hsl(...) and hsla(...)
const HSL_COLOR_REGEX = /^hsla?\(\s*(\d{1,3}(?:deg)?)\s*,\s*(\d{1,3}%)\s*,\s*(\d{1,3}%)(?:\s*,\s*(0|1|0?\.\d+))?\s*\)$/;

// Dangerous strings that must never appear in token values
const FORBIDDEN_SUBSTRINGS = [
  "url(",
  "javascript:",
  "expression(",
  "@import",
  "<",
  ">",
  ";",
  "{",
  "}",
  "/*",
  "*/",
  "\\",
];

export function validateSkinJson(input: string | unknown): SkinValidationResult {
  const errors: string[] = [];

  let parsed: unknown;

  if (typeof input === "string") {
    if (new TextEncoder().encode(input).length > MAX_JSON_BYTES) {
      return { valid: false, errors: [`Skin specification exceeds maximum payload limit of ${MAX_JSON_BYTES} bytes.`] };
    }
    try {
      parsed = JSON.parse(input);
    } catch {
      return { valid: false, errors: ["Invalid JSON syntax."] };
    }
  } else if (input && typeof input === "object") {
    parsed = input;
  } else {
    return { valid: false, errors: ["Skin input must be a valid JSON string or object."] };
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { valid: false, errors: ["Root of skin definition must be a JSON object."] };
  }

  const obj = parsed as Record<string, unknown>;

  // Validate ID
  if (typeof obj.id !== "string" || !/^[a-z0-9_-]{2,32}$/.test(obj.id)) {
    errors.push("Skin 'id' is required and must be 2-32 lowercase alphanumeric characters, dashes, or underscores.");
  }

  // Validate Name
  if (typeof obj.name !== "string" || obj.name.trim().length === 0 || obj.name.length > 50) {
    errors.push("Skin 'name' is required and must be between 1 and 50 characters.");
  }

  // Optional description
  if (obj.description !== undefined && (typeof obj.description !== "string" || obj.description.length > 200)) {
    errors.push("Skin 'description' must be a string up to 200 characters.");
  }

  // Validate Tokens
  if (!obj.tokens || typeof obj.tokens !== "object" || Array.isArray(obj.tokens)) {
    errors.push("Skin 'tokens' must be an object mapping token names to valid color values.");
  } else {
    const tokens = obj.tokens as Record<string, unknown>;
    const tokenKeys = Object.keys(tokens);

    if (tokenKeys.length === 0) {
      errors.push("Skin 'tokens' object cannot be empty.");
    }

    if (tokenKeys.length > MAX_TOKENS_COUNT) {
      errors.push(`Skin defines ${tokenKeys.length} tokens, exceeding maximum allowed of ${MAX_TOKENS_COUNT}.`);
    }

    for (const [key, value] of Object.entries(tokens)) {
      if (!ALLOWED_TOKEN_KEYS.has(key)) {
        errors.push(`Unrecognized token key: '${key}'. Key must be in the approved design token registry.`);
        continue;
      }

      if (typeof value !== "string") {
        errors.push(`Token '${key}' must have a string value, received ${typeof value}.`);
        continue;
      }

      const val = value.trim();

      // Check forbidden substrings
      const hasForbidden = FORBIDDEN_SUBSTRINGS.some((sub) => val.toLowerCase().includes(sub));
      if (hasForbidden) {
        errors.push(`Security violation in token '${key}': prohibited syntax or CSS injection attempt detected.`);
        continue;
      }

      // Check valid color formats
      const isHex = HEX_COLOR_REGEX.test(val);
      const isRgb = RGB_COLOR_REGEX.test(val);
      const isHsl = HSL_COLOR_REGEX.test(val);

      if (!isHex && !isRgb && !isHsl) {
        errors.push(`Invalid color grammar for token '${key}': '${val}'. Must be hex (#RRGGBB, #RGB), rgb(), rgba(), or hsl().`);
      }
    }
  }

  if (errors.length > 0) {
    return { valid: false, errors };
  }

  return {
    valid: true,
    errors: [],
    skin: parsed as CustomSkin,
  };
}
