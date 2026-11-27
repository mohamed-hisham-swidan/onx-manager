import type { IconName } from "@/components/ui/Icon";
import { useAuthPermissions } from "@/hooks/useAuthPermissions";
import type { SettingsResponse, SettingsUpdateRequest } from "@/types";

export type SettingsTabId =
  | "general"
  | "appearance"
  | "integrations"
  | "access"
  | "users"
  | "api-keys";

export interface SettingsNavItem {
  id: SettingsTabId;
  label: string;
  icon: IconName;
  group: "panel" | "team";
  vpsOnly?: boolean;
  ownerOnly?: boolean;
  adminOnly?: boolean;
  ownerOnlyHint?: boolean;
}

export const SETTINGS_NAV_ITEMS: SettingsNavItem[] = [
  { id: "general", label: "General", icon: "sliders", group: "panel", adminOnly: true },
  { id: "appearance", label: "Appearance", icon: "palette", group: "panel" },
  { id: "integrations", label: "Modpacks & Cache", icon: "mod", group: "panel", adminOnly: true },
  {
    id: "access",
    label: "Remote & Access",
    icon: "globe",
    group: "team",
    vpsOnly: true,
    ownerOnly: true,
    ownerOnlyHint: true,
  },
  { id: "users", label: "Users & Invitations", icon: "users", group: "team", vpsOnly: true, adminOnly: true },
  { id: "api-keys", label: "API Keys", icon: "key", group: "team", vpsOnly: true, adminOnly: true },
];

export interface SystemFormState {
  app_name: string;
  log_level: string;
  debug: boolean;
  rate_limit_per_minute: number;
  idempotency_ttl_hours: number;
  circuit_breaker_max_failures: number;
  circuit_breaker_timeout_seconds: number;
  event_bus_retry_attempts: number;
  saga_timeout_seconds: number;
  metrics_interval_seconds: number;
  server_startup_timeout_seconds: number;
  test_boot_timeout_seconds: number;
  host_ram_reserve_mb: number;
  host_cpu_reserve: number;
}

export type NumericSettingKey =
  | "rate_limit_per_minute"
  | "idempotency_ttl_hours"
  | "circuit_breaker_max_failures"
  | "circuit_breaker_timeout_seconds"
  | "event_bus_retry_attempts"
  | "saga_timeout_seconds"
  | "metrics_interval_seconds"
  | "server_startup_timeout_seconds"
  | "test_boot_timeout_seconds"
  | "host_ram_reserve_mb"
  | "host_cpu_reserve";

export const GENERAL_SETTING_KEYS = [
  "host_ram_reserve_mb",
  "host_cpu_reserve",
  "server_startup_timeout_seconds",
] as const;

export const ENGINE_SETTING_KEYS = [
  "metrics_interval_seconds",
  "test_boot_timeout_seconds",
  "log_level",
  "debug",
  "rate_limit_per_minute",
  "idempotency_ttl_hours",
  "circuit_breaker_max_failures",
  "circuit_breaker_timeout_seconds",
  "event_bus_retry_attempts",
  "saga_timeout_seconds",
] as const;

export const FALLBACK_DEFAULTS: SystemFormState = {
  app_name: "onx-manager",
  log_level: "INFO",
  debug: false,
  rate_limit_per_minute: 60,
  idempotency_ttl_hours: 24,
  circuit_breaker_max_failures: 5,
  circuit_breaker_timeout_seconds: 30,
  event_bus_retry_attempts: 3,
  saga_timeout_seconds: 300,
  metrics_interval_seconds: 5.0,
  server_startup_timeout_seconds: 120,
  test_boot_timeout_seconds: 120,
  host_ram_reserve_mb: 0,
  host_cpu_reserve: 0,
};

export interface NumericBound {
  min: number;
  max: number;
  integer?: boolean;
  precision?: number;
}

export const SETTINGS_BOUNDS: Record<NumericSettingKey, NumericBound> = {
  rate_limit_per_minute: { min: 10, max: 10000, integer: true },
  idempotency_ttl_hours: { min: 1, max: 720, integer: true },
  circuit_breaker_max_failures: { min: 1, max: 100, integer: true },
  circuit_breaker_timeout_seconds: { min: 1, max: 3600, integer: true },
  event_bus_retry_attempts: { min: 0, max: 10, integer: true },
  saga_timeout_seconds: { min: 10, max: 3600, integer: true },
  metrics_interval_seconds: { min: 0.1, max: 60, precision: 2 },
  server_startup_timeout_seconds: { min: 30, max: 1800, integer: true },
  test_boot_timeout_seconds: { min: 30, max: 1800, integer: true },
  host_ram_reserve_mb: { min: 0, max: 1048576, integer: true },
  host_cpu_reserve: { min: 0, max: 256, precision: 2 },
};

export function resolveCanonicalDefaults(settings: SettingsResponse): SystemFormState {
  const d = settings.defaults ?? {};
  return {
    app_name: d.app_name ?? FALLBACK_DEFAULTS.app_name,
    log_level: d.log_level ?? FALLBACK_DEFAULTS.log_level,
    debug: d.debug ?? FALLBACK_DEFAULTS.debug,
    rate_limit_per_minute: d.rate_limit_per_minute ?? FALLBACK_DEFAULTS.rate_limit_per_minute,
    idempotency_ttl_hours: d.idempotency_ttl_hours ?? FALLBACK_DEFAULTS.idempotency_ttl_hours,
    circuit_breaker_max_failures:
      d.circuit_breaker_max_failures ?? FALLBACK_DEFAULTS.circuit_breaker_max_failures,
    circuit_breaker_timeout_seconds:
      d.circuit_breaker_timeout_seconds ?? FALLBACK_DEFAULTS.circuit_breaker_timeout_seconds,
    event_bus_retry_attempts:
      d.event_bus_retry_attempts ?? FALLBACK_DEFAULTS.event_bus_retry_attempts,
    saga_timeout_seconds: d.saga_timeout_seconds ?? FALLBACK_DEFAULTS.saga_timeout_seconds,
    metrics_interval_seconds:
      d.metrics_interval_seconds ?? FALLBACK_DEFAULTS.metrics_interval_seconds,
    server_startup_timeout_seconds:
      d.server_startup_timeout_seconds ?? FALLBACK_DEFAULTS.server_startup_timeout_seconds,
    test_boot_timeout_seconds:
      d.test_boot_timeout_seconds ?? FALLBACK_DEFAULTS.test_boot_timeout_seconds,
    host_ram_reserve_mb: d.host_ram_reserve_mb ?? FALLBACK_DEFAULTS.host_ram_reserve_mb,
    host_cpu_reserve: d.host_cpu_reserve ?? FALLBACK_DEFAULTS.host_cpu_reserve,
  };
}

export function formStateFromSettings(settings: SettingsResponse): SystemFormState {
  const defaults = resolveCanonicalDefaults(settings);
  return {
    app_name: settings.app_name ?? defaults.app_name,
    log_level: settings.log_level ?? defaults.log_level,
    debug: Boolean(settings.debug),
    rate_limit_per_minute: settings.rate_limit_per_minute ?? defaults.rate_limit_per_minute,
    idempotency_ttl_hours: settings.idempotency_ttl_hours ?? defaults.idempotency_ttl_hours,
    circuit_breaker_max_failures:
      settings.circuit_breaker_max_failures ?? defaults.circuit_breaker_max_failures,
    circuit_breaker_timeout_seconds:
      settings.circuit_breaker_timeout_seconds ?? defaults.circuit_breaker_timeout_seconds,
    event_bus_retry_attempts:
      settings.event_bus_retry_attempts ?? defaults.event_bus_retry_attempts,
    saga_timeout_seconds: settings.saga_timeout_seconds ?? defaults.saga_timeout_seconds,
    metrics_interval_seconds: settings.metrics_interval_seconds ?? defaults.metrics_interval_seconds,
    server_startup_timeout_seconds:
      settings.server_startup_timeout_seconds ?? defaults.server_startup_timeout_seconds,
    test_boot_timeout_seconds:
      settings.test_boot_timeout_seconds ?? defaults.test_boot_timeout_seconds,
    host_ram_reserve_mb: settings.host_ram_reserve_mb ?? defaults.host_ram_reserve_mb,
    host_cpu_reserve: settings.host_cpu_reserve ?? defaults.host_cpu_reserve,
  };
}

export function clampNumericValue(key: NumericSettingKey, rawValue: number | string): number | null {
  const bound = SETTINGS_BOUNDS[key];
  const parsed = typeof rawValue === "number" ? rawValue : Number(String(rawValue).trim());
  if (!Number.isFinite(parsed)) return null;
  let next = Math.max(bound.min, Math.min(bound.max, parsed));
  if (bound.integer) {
    next = Math.round(next);
  } else if (bound.precision !== undefined) {
    const factor = 10 ** bound.precision;
    next = Math.round(next * factor) / factor;
  }
  return next;
}

export function normalizeFormWithDrafts(
  form: SystemFormState,
  drafts: Record<string, string>,
  keys: readonly (keyof SystemFormState)[],
): SystemFormState {
  const next = { ...form };
  for (const key of keys) {
    if (key in SETTINGS_BOUNDS) {
      const numKey = key as NumericSettingKey;
      const draft = drafts[key];
      const source = draft !== undefined && draft.trim() !== "" ? draft : form[numKey];
      const clamped = clampNumericValue(numKey, source);
      if (clamped !== null) {
        next[numKey] = clamped;
      } else {
        const fallback = clampNumericValue(numKey, form[numKey]);
        next[numKey] = fallback ?? SETTINGS_BOUNDS[numKey].min;
      }
    }
  }
  return next;
}

export function computeDirtyPatch(
  current: SystemFormState,
  baseline: SystemFormState,
  keys: readonly (keyof SystemFormState)[],
): SettingsUpdateRequest {
  const patch: Record<string, string | number | boolean> = {};
  for (const key of keys) {
    if (current[key] !== baseline[key]) {
      patch[key] = current[key];
    }
  }
  return patch as SettingsUpdateRequest;
}

export function useSettingsPermissions() {
  const auth = useAuthPermissions();
  const roles = auth.user?.roles ?? [];
  const isOwner = auth.isOwner;
  const isAdminOrOwner = auth.isAdmin;
  const hasResolvedUser = Boolean(auth.user);

  return {
    user: auth.user ?? null,
    roles,
    hasResolvedUser,
    isOwner,
    isAdminOrOwner,
    canWriteSettings: isAdminOrOwner,
    canManageInvites: isAdminOrOwner,
    canManageApiKeys: isAdminOrOwner,
    isLoadingUser: auth.isLoading,
  };
}
