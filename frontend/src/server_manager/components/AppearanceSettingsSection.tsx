import { useState, useEffect } from "react";
import { useUIStore } from "@/stores/uiStore";
import { Icon } from "@/components/ui/Icon";
import { THEME_SKINS } from "@/tokens/storageKeys";

interface AccentDefinition {
  id: string;
  name: string;
  colorRgb: string;
  isDefault?: boolean;
}

const ACCENTS: AccentDefinition[] = [
  { id: "default", name: "Theme Default", colorRgb: "rgb(99, 102, 241)", isDefault: true },
  { id: "blue", name: "Blue", colorRgb: "rgb(59, 130, 246)" },
  { id: "emerald", name: "Emerald", colorRgb: "rgb(16, 185, 129)" },
  { id: "violet", name: "Violet", colorRgb: "rgb(139, 92, 246)" },
  { id: "amber", name: "Amber", colorRgb: "rgb(245, 158, 11)" },
  { id: "rose", name: "Rose", colorRgb: "rgb(244, 63, 94)" },
  { id: "cyan", name: "Cyan", colorRgb: "rgb(6, 182, 212)" },
];

const ACCENT_STORAGE_KEY = "onx_accent";

function getInitialAccent(): string {
  try {
    return localStorage.getItem(ACCENT_STORAGE_KEY) || "default";
  } catch {
    return "default";
  }
}

export function AppearanceSettingsSection() {
  const uiStore = useUIStore();
  const theme = uiStore.theme;
  const skin = uiStore.skin;
  const density = uiStore.density;
  const setTheme = uiStore.setTheme;
  const setSkin = uiStore.setSkin;
  const setDensity = uiStore.setDensity;

  const [activeAccent, setActiveAccent] = useState<string>(getInitialAccent);

  useEffect(() => {
    const stored = getInitialAccent();
    if (stored !== "default") {
      document.documentElement.setAttribute("data-accent", stored);
    }
  }, []);

  const handleSelectSkin = (skinId: string) => {
    (setSkin as (s: string) => void)(skinId);
    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-skin", skinId);
      try {
        localStorage.setItem("onx_skin", skinId);
      } catch {
        /* ignore */
      }
    }
  };

  const handleSelectAccent = (accentId: string) => {
    setActiveAccent(accentId);
    if (typeof document !== "undefined") {
      if (accentId === "default") {
        document.documentElement.removeAttribute("data-accent");
      } else {
        document.documentElement.setAttribute("data-accent", accentId);
      }
    }
    try {
      if (accentId === "default") {
        localStorage.removeItem(ACCENT_STORAGE_KEY);
      } else {
        localStorage.setItem(ACCENT_STORAGE_KEY, accentId);
      }
    } catch {
      /* ignore */
    }
    if (typeof (uiStore as unknown as Record<string, unknown>).setAccent === "function") {
      ((uiStore as unknown as Record<string, (a: string) => void>).setAccent)(accentId);
    }
  };

  const handleResetToDefaults = () => {
    setTheme("dark");
    handleSelectSkin("graphite");
    setDensity("comfortable");
    handleSelectAccent("default");
  };

  return (
    <div className="space-y-8" data-testid="appearance-settings-section">
      {/* Header Info Banner */}
      <div className="rounded-xl border border-border-default bg-surface-card p-6 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
              <Icon name="sun" size={20} className="text-accent-primary" />
              Appearance & Theme Studio
            </h2>
            <p className="text-xs text-text-muted mt-1 max-w-2xl">
              Customize your operational cockpit experience. Changes are persisted to your browser and applied instantly across all workspace views.
            </p>
          </div>
          <button
            type="button"
            onClick={handleResetToDefaults}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border-default bg-surface-elevated text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors shrink-0 cursor-pointer"
          >
            <Icon name="restart" size={14} />
            Reset Appearance to Default
          </button>
        </div>
      </div>

      {/* 1. Color Mode Selector */}
      <div className="rounded-xl border border-border-default bg-surface-card p-6 shadow-xs space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
            Color Mode
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Select between high-contrast dark room aesthetics or clean daytime light layout.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Dark Mode Card */}
          <button
            type="button"
            onClick={() => setTheme("dark")}
            className={`text-left rounded-xl border p-4 transition-all cursor-pointer relative group ${
              theme === "dark"
                ? "border-accent-primary bg-surface-elevated ring-2 ring-accent-primary/20 shadow-sm"
                : "border-border-default bg-surface-page hover:border-border-strong"
            }`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="p-1.5 rounded-lg bg-surface-card border border-border-default text-text-primary">
                  <Icon name="moon" size={16} />
                </span>
                <span className="text-sm font-semibold text-text-primary">Dark Mode</span>
              </div>
              {theme === "dark" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-accent-primary px-2 py-0.5 text-[10px] font-semibold text-accent-contrast-text">
                  <Icon name="check" size={10} />
                  Active
                </span>
              )}
            </div>

            {/* Wireframe Mini Preview */}
            <div
              className="rounded-lg p-2.5 border border-border-subtle space-y-2"
              style={{ backgroundColor: "rgb(15, 23, 42)" }}
            >
              <div className="flex items-center justify-between pb-1 border-b border-border-subtle">
                <div
                  className="h-2 w-12 rounded-sm"
                  style={{ backgroundColor: "rgb(51, 65, 85)" }}
                />
                <div
                  className="h-2 w-6 rounded-sm"
                  style={{ backgroundColor: "rgb(59, 130, 246)" }}
                />
              </div>
              <div className="flex gap-2">
                <div
                  className="w-1/4 h-12 rounded-sm"
                  style={{ backgroundColor: "rgb(30, 41, 59)" }}
                />
                <div className="w-3/4 space-y-1.5">
                  <div
                    className="h-5 rounded-sm"
                    style={{ backgroundColor: "rgb(30, 41, 59)" }}
                  />
                  <div
                    className="h-5 rounded-sm"
                    style={{ backgroundColor: "rgb(30, 41, 59)" }}
                  />
                </div>
              </div>
            </div>
            <p className="text-xs text-text-muted mt-3">
              Low glare, deep blacks and slates optimized for extended console operations.
            </p>
          </button>

          {/* Light Mode Card */}
          <button
            type="button"
            onClick={() => setTheme("light")}
            className={`text-left rounded-xl border p-4 transition-all cursor-pointer relative group ${
              theme === "light"
                ? "border-accent-primary bg-surface-elevated ring-2 ring-accent-primary/20 shadow-sm"
                : "border-border-default bg-surface-page hover:border-border-strong"
            }`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="p-1.5 rounded-lg bg-surface-card border border-border-default text-text-primary">
                  <Icon name="sun" size={16} />
                </span>
                <span className="text-sm font-semibold text-text-primary">Light Mode</span>
              </div>
              {theme === "light" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-accent-primary px-2 py-0.5 text-[10px] font-semibold text-accent-contrast-text">
                  <Icon name="check" size={10} />
                  Active
                </span>
              )}
            </div>

            {/* Wireframe Mini Preview */}
            <div
              className="rounded-lg p-2.5 space-y-2 border"
              style={{
                backgroundColor: "rgb(226, 232, 240)",
                borderColor: "rgb(203, 213, 225)",
              }}
            >
              <div
                className="flex items-center justify-between pb-1 border-b"
                style={{ borderColor: "rgb(203, 213, 225)" }}
              >
                <div
                  className="h-2 w-12 rounded-xs"
                  style={{ backgroundColor: "rgb(148, 163, 184)" }}
                />
                <div
                  className="h-2 w-6 rounded-xs"
                  style={{ backgroundColor: "rgb(37, 99, 235)" }}
                />
              </div>
              <div className="flex gap-2">
                <div
                  className="w-1/4 h-12 rounded-xs border"
                  style={{
                    backgroundColor: "rgb(241, 245, 249)",
                    borderColor: "rgb(203, 213, 225)",
                  }}
                />
                <div className="w-3/4 space-y-1.5">
                  <div
                    className="h-5 rounded-xs border"
                    style={{
                      backgroundColor: "rgb(241, 245, 249)",
                      borderColor: "rgb(203, 213, 225)",
                    }}
                  />
                  <div
                    className="h-5 rounded-xs border"
                    style={{
                      backgroundColor: "rgb(241, 245, 249)",
                      borderColor: "rgb(203, 213, 225)",
                    }}
                  />
                </div>
              </div>
            </div>
            <p className="text-xs text-text-muted mt-3">
              Crisp contrast and clean paper surfaces designed for well-lit environments.
            </p>
          </button>
        </div>
      </div>

      {/* 2. Theme Skin Gallery */}
      <div className="rounded-xl border border-border-default bg-surface-card p-6 shadow-xs space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
            Theme Skin Gallery
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Choose a visual skin profile to tailor background tones, card elevation hues, and subtle lighting.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {THEME_SKINS.map((s) => {
            const isSelected = skin === s.id;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => handleSelectSkin(s.id)}
                className={`text-left rounded-xl border p-4 transition-all cursor-pointer relative flex flex-col justify-between ${
                  isSelected
                    ? "border-accent-primary bg-surface-elevated ring-2 ring-accent-primary/20 shadow-sm"
                    : "border-border-default bg-surface-page hover:border-border-strong hover:bg-surface-hover"
                }`}
              >
                <div>
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-sm font-semibold text-text-primary">{s.name}</span>
                        <span className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded-sm bg-surface-card border border-border-default text-text-secondary">
                          {s.paletteBadge}
                        </span>
                      </div>
                      <p className="text-[11px] text-text-secondary mt-0.5">{s.tagline}</p>
                    </div>
                    {isSelected && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-accent-primary px-2 py-0.5 text-[10px] font-semibold text-accent-contrast-text shrink-0">
                        <Icon name="check" size={10} />
                        Active
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-text-muted min-h-[32px]">{s.description}</p>
                </div>

                {/* Rich Mini-UI Preview Window */}
                <div
                  className="mt-3 rounded-lg p-2.5 space-y-2 border"
                  style={{
                    backgroundColor: s.canvasColor,
                    borderColor: s.borderColor,
                  }}
                >
                  {/* Mini Window Top Header */}
                  <div
                    className="flex items-center justify-between pb-1.5 border-b"
                    style={{ borderColor: s.borderColor }}
                  >
                    <div className="flex items-center gap-1">
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: s.accentColor }}
                      />
                      <div
                        className="h-1.5 w-10 rounded-xs"
                        style={{ backgroundColor: s.borderColor }}
                      />
                    </div>
                    <div className="flex items-center gap-1">
                      <div
                        className="h-1.5 w-4 rounded-xs"
                        style={{ backgroundColor: s.badgeColor }}
                      />
                      <div
                        className="h-2 w-6 rounded-xs"
                        style={{ backgroundColor: s.accentColor }}
                      />
                    </div>
                  </div>

                  {/* Mini Body: Sidebar + Main Surface Content */}
                  <div className="flex gap-1.5">
                    {/* Mini Sidebar */}
                    <div
                      className="w-1/4 h-12 rounded-xs p-1 space-y-1 border"
                      style={{
                        backgroundColor: s.surfaceColor,
                        borderColor: s.borderColor,
                      }}
                    >
                      <div
                        className="h-1.5 w-full rounded-xs"
                        style={{ backgroundColor: s.borderColor }}
                      />
                      <div
                        className="h-1.5 w-3/4 rounded-xs"
                        style={{ backgroundColor: s.accentColor }}
                      />
                      <div
                        className="h-1.5 w-1/2 rounded-xs"
                        style={{ backgroundColor: s.borderColor }}
                      />
                    </div>

                    {/* Mini Surface Cards */}
                    <div className="w-3/4 space-y-1.5">
                      <div
                        className="h-5 rounded-xs p-1 flex items-center justify-between border"
                        style={{
                          backgroundColor: s.surfaceColor,
                          borderColor: s.borderColor,
                        }}
                      >
                        <div
                          className="h-1.5 w-10 rounded-xs"
                          style={{ backgroundColor: s.borderColor }}
                        />
                        <div
                          className="h-1.5 w-3 rounded-xs"
                          style={{ backgroundColor: s.accentColor }}
                        />
                      </div>
                      <div
                        className="h-5 rounded-xs p-1 flex items-center justify-between border"
                        style={{
                          backgroundColor: s.surfaceColor,
                          borderColor: s.borderColor,
                        }}
                      >
                        <div
                          className="h-1.5 w-7 rounded-xs"
                          style={{ backgroundColor: s.badgeColor }}
                        />
                        <div
                          className="h-1.5 w-5 rounded-xs"
                          style={{ backgroundColor: s.borderColor }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Surface layers preview chips & technical palette specification */}
                <div className="mt-3 pt-2.5 border-t border-border-subtle flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    <div
                      className="w-4 h-4 rounded-full border border-border-default"
                      style={{ backgroundColor: s.canvasColor }}
                      title="Canvas color"
                    />
                    <div
                      className="w-4 h-4 rounded-full border border-border-default -ml-1.5"
                      style={{ backgroundColor: s.surfaceColor }}
                      title="Surface card color"
                    />
                    <div
                      className="w-4 h-4 rounded-full border border-border-default -ml-1.5"
                      style={{ backgroundColor: s.borderColor }}
                      title="Border default color"
                    />
                    <div
                      className="w-4 h-4 rounded-full border border-border-default -ml-1.5 shadow-xs"
                      style={{ backgroundColor: s.accentColor }}
                      title="Primary accent color"
                    />
                    <div
                      className="w-4 h-4 rounded-full border border-border-default -ml-1.5"
                      style={{ backgroundColor: s.badgeColor }}
                      title="Secondary badge color"
                    />
                  </div>
                  <span className="text-[11px] font-mono text-text-muted capitalize">
                    {s.id}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 3. Accent Color Overrides */}
      <div className="rounded-xl border border-border-default bg-surface-card p-6 shadow-xs space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
            Accent Color Override
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Select a custom brand accent for buttons, active tabs, focus rings, and highlighted metrics.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 pt-1">
          {ACCENTS.map((accent) => {
            const isSelected = activeAccent === accent.id;
            return (
              <button
                key={accent.id}
                type="button"
                onClick={() => handleSelectAccent(accent.id)}
                className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-medium transition-all cursor-pointer ${
                  isSelected
                    ? "border-accent-primary bg-surface-elevated ring-2 ring-accent-primary/20 text-text-primary shadow-xs"
                    : "border-border-default bg-surface-page text-text-secondary hover:text-text-primary hover:border-border-strong"
                }`}
                title={`Select ${accent.name} accent`}
              >
                <span
                  className="w-4 h-4 rounded-full border border-border-subtle shrink-0 flex items-center justify-center"
                  style={{ backgroundColor: accent.colorRgb }}
                >
                  {isSelected && (
                    <Icon name="check" size={10} className="text-white" />
                  )}
                </span>
                <span>{accent.name}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 4. Interface Density */}
      <div className="rounded-xl border border-border-default bg-surface-card p-6 shadow-xs space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
            Interface Density
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Adjust padding and item height across tables, forms, and audit streams.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Comfortable */}
          <button
            type="button"
            onClick={() => setDensity("comfortable")}
            className={`text-left rounded-xl border p-4 transition-all cursor-pointer ${
              density === "comfortable"
                ? "border-accent-primary bg-surface-elevated ring-2 ring-accent-primary/20 shadow-sm"
                : "border-border-default bg-surface-page hover:border-border-strong hover:bg-surface-hover"
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-text-primary">Comfortable</span>
              {density === "comfortable" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-accent-primary px-2 py-0.5 text-[10px] font-semibold text-accent-contrast-text">
                  <Icon name="check" size={10} />
                  Active
                </span>
              )}
            </div>
            <p className="text-xs text-text-muted mb-4">
              Spacious forms, relaxed padding, and increased breathing room for monitors and touch interfaces.
            </p>
            {/* Density mini rows */}
            <div className="space-y-2 rounded-lg border border-border-subtle bg-surface-card p-3">
              <div className="h-6 rounded bg-surface-muted flex items-center px-2">
                <div className="h-2 w-1/3 rounded bg-surface-active" />
              </div>
              <div className="h-6 rounded bg-surface-muted flex items-center px-2">
                <div className="h-2 w-1/2 rounded bg-surface-active" />
              </div>
            </div>
          </button>

          {/* Compact */}
          <button
            type="button"
            onClick={() => setDensity("compact")}
            className={`text-left rounded-xl border p-4 transition-all cursor-pointer ${
              density === "compact"
                ? "border-accent-primary bg-surface-elevated ring-2 ring-accent-primary/20 shadow-sm"
                : "border-border-default bg-surface-page hover:border-border-strong hover:bg-surface-hover"
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-text-primary">Compact</span>
              {density === "compact" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-accent-primary px-2 py-0.5 text-[10px] font-semibold text-accent-contrast-text">
                  <Icon name="check" size={10} />
                  Active
                </span>
              )}
            </div>
            <p className="text-xs text-text-muted mb-4">
              High information density with compact table rows and tighter margins for multi-server management.
            </p>
            {/* Density mini rows */}
            <div className="space-y-1 rounded-lg border border-border-subtle bg-surface-card p-3">
              <div className="h-4 rounded bg-surface-muted flex items-center px-2">
                <div className="h-1.5 w-1/3 rounded bg-surface-active" />
              </div>
              <div className="h-4 rounded bg-surface-muted flex items-center px-2">
                <div className="h-1.5 w-1/2 rounded bg-surface-active" />
              </div>
              <div className="h-4 rounded bg-surface-muted flex items-center px-2">
                <div className="h-1.5 w-2/5 rounded bg-surface-active" />
              </div>
            </div>
          </button>
        </div>
      </div>

      {/* 5. Live Interactive Preview Card */}
      <div className="rounded-xl border border-border-default bg-surface-card p-6 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border-subtle pb-3">
          <div>
            <h3 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
              Live Interactive Preview
            </h3>
            <p className="text-xs text-text-muted mt-0.5">
              Real-time demonstration of active tokens, components, and contrast balance.
            </p>
          </div>
          <div className="text-[11px] font-mono text-text-muted bg-surface-page px-2.5 py-1 rounded-lg border border-border-subtle self-start sm:self-auto">
            Mode: {theme} • Skin: {skin} • Accent: {activeAccent} • Density: {density}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 pt-2">
          {/* Component Showcase Card */}
          <div className="rounded-xl border border-border-default bg-surface-page p-4 space-y-4">
            <h4 className="text-xs font-semibold text-text-secondary uppercase">
              Action Primitives & Badges
            </h4>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="px-3 py-1.5 rounded-lg bg-accent-primary text-accent-contrast-text text-xs font-medium hover:bg-accent-hover transition-colors shadow-xs"
              >
                Primary Accent Action
              </button>
              <button
                type="button"
                className="px-3 py-1.5 rounded-lg border border-border-default bg-surface-card text-text-secondary text-xs font-medium hover:bg-surface-elevated transition-colors"
              >
                Secondary Action
              </button>
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-status-success-bg text-status-success border border-status-success-border">
                <span className="w-1.5 h-1.5 rounded-full bg-status-success" />
                Online
              </span>
              <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-status-warning-bg text-status-warning border border-status-warning-border">
                <span className="w-1.5 h-1.5 rounded-full bg-status-warning" />
                Degraded
              </span>
              <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-status-danger-bg text-status-danger border border-status-danger-border">
                <span className="w-1.5 h-1.5 rounded-full bg-status-danger" />
                Offline
              </span>
              <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-status-info-bg text-status-info border border-status-info-border">
                <span className="w-1.5 h-1.5 rounded-full bg-status-info" />
                Syncing
              </span>
            </div>
          </div>

          {/* Terminal Console Preview */}
          <div className="rounded-xl border border-border-default bg-surface-page p-4 space-y-3 font-mono">
            <div className="flex items-center justify-between text-xs text-text-muted border-b border-border-subtle pb-2">
              <span className="flex items-center gap-1.5">
                <Icon name="terminal" size={14} className="text-text-muted" />
                Live Shell Preview
              </span>
              <span className="text-[10px] text-text-muted">bash session</span>
            </div>
            <div className="text-xs space-y-1.5">
              <p className="text-text-primary">
                <span className="text-accent-primary font-bold">onx@node-01</span>
                <span className="text-text-muted">:</span>
                <span className="text-text-secondary">~$</span>{" "}
                <span className="text-text-primary">onx-manager status --fleet</span>
              </p>
              <p className="text-status-success text-[11px]">
                [OK] Cluster nodes 4/4 operational. TPS 20.0 (0.2s tick interval)
              </p>
              <p className="text-text-muted text-[11px]">
                Theme engine verified. Active profile: {skin} ({theme} mode)
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
