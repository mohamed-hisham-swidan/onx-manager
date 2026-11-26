import { useUIStore } from "@/stores/uiStore";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import { THEME_SKINS, type AccentColor } from "@/tokens/storageKeys";

interface AccentDefinition {
  id: AccentColor;
  name: string;
  colorRgb: string;
}

const ACCENT_PRESET_OPTIONS: AccentDefinition[] = [
  { id: "blue", name: "Blue", colorRgb: "rgb(59, 130, 246)" },
  { id: "emerald", name: "Emerald", colorRgb: "rgb(16, 185, 129)" },
  { id: "violet", name: "Violet", colorRgb: "rgb(139, 92, 246)" },
  { id: "amber", name: "Amber", colorRgb: "rgb(245, 158, 11)" },
  { id: "rose", name: "Rose", colorRgb: "rgb(244, 63, 94)" },
  { id: "cyan", name: "Cyan", colorRgb: "rgb(6, 182, 212)" },
];

const CRISP_SKIN_TAGS: Record<string, string> = {
  graphite: "Carbon dark & cobalt",
  azure: "Arctic slate & cyan",
  emerald: "Deep pine & emerald",
  amethyst: "Midnight indigo & violet",
  amber: "Neutral zinc & amber",
  crimson: "Warm charcoal & crimson",
};

export function AppearanceSettingsSection() {
  const theme = useUIStore((s) => s.theme);
  const skin = useUIStore((s) => s.skin);
  const accent = useUIStore((s) => s.accent);
  const cornerStyle = useUIStore((s) => s.cornerStyle ?? "rounded");
  const setTheme = useUIStore((s) => s.setTheme);
  const setSkin = useUIStore((s) => s.setSkin);
  const setAccent = useUIStore((s) => s.setAccent);
  const setCornerStyle = useUIStore((s) => s.setCornerStyle);

  const activeSkinMeta = THEME_SKINS.find((s) => s.id === skin) ?? THEME_SKINS[0];
  const skinDefaultColor =
    theme === "light" && skin === "amber" ? "rgb(51, 65, 85)" : activeSkinMeta.accentColor;
  const accentOptions: AccentDefinition[] = [
    { id: "theme", name: "Skin Default", colorRgb: skinDefaultColor },
    ...ACCENT_PRESET_OPTIONS,
  ];

  const handleResetToDefaults = () => {
    setTheme("dark");
    setSkin("graphite");
    setAccent("theme");
    setCornerStyle("rounded");
  };

  return (
    <div className="space-y-6" data-testid="appearance-settings-section">
      {/* Unified Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">Appearance</h2>
          <p className="text-sm text-text-muted mt-0.5">
            Theme, colors, and layout. Saves instantly.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          icon="restart"
          onClick={handleResetToDefaults}
        >
          Reset Default
        </Button>
      </div>

      {/* 1. Color Mode & Layout Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Color Mode */}
        <section className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-text-primary">Color Mode</h3>
            <p className="text-xs text-text-muted mt-0.5">Switch between dark and light surfaces.</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setTheme("dark")}
              className={`text-left rounded-xl border p-3 transition-all cursor-pointer ${
                theme === "dark"
                  ? "border-accent-primary bg-accent-primary/8 ring-1 ring-accent-primary/25"
                  : "border-border-subtle bg-surface-page hover:border-border-hover"
              }`}
            >
              <div className="flex items-center justify-between mb-2.5">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-text-primary">
                  <Icon name="moon" size={14} />
                  Dark
                </span>
                {theme === "dark" && (
                  <Icon name="check" size={14} className="text-text-accent" />
                )}
              </div>
              <div className="rounded-lg p-2 space-y-1.5" style={{ backgroundColor: "rgb(15, 23, 42)" }}>
                <div className="flex items-center justify-between">
                  <div className="h-1.5 w-8 rounded-xs" style={{ backgroundColor: "rgb(71, 85, 105)" }} />
                  <div className="h-1.5 w-4 rounded-xs" style={{ backgroundColor: "rgb(59, 130, 246)" }} />
                </div>
                <div className="h-6 rounded-xs" style={{ backgroundColor: "rgb(30, 41, 59)" }} />
              </div>
            </button>

            <button
              type="button"
              onClick={() => setTheme("light")}
              className={`text-left rounded-xl border p-3 transition-all cursor-pointer ${
                theme === "light"
                  ? "border-accent-primary bg-accent-primary/8 ring-1 ring-accent-primary/25"
                  : "border-border-subtle bg-surface-page hover:border-border-hover"
              }`}
            >
              <div className="flex items-center justify-between mb-2.5">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-text-primary">
                  <Icon name="sun" size={14} />
                  Light
                </span>
                {theme === "light" && (
                  <Icon name="check" size={14} className="text-text-accent" />
                )}
              </div>
              <div className="rounded-lg p-2 space-y-1.5" style={{ backgroundColor: "rgb(226, 232, 240)" }}>
                <div className="flex items-center justify-between">
                  <div className="h-1.5 w-8 rounded-xs" style={{ backgroundColor: "rgb(148, 163, 184)" }} />
                  <div className="h-1.5 w-4 rounded-xs" style={{ backgroundColor: "rgb(37, 99, 235)" }} />
                </div>
                <div className="h-6 rounded-xs" style={{ backgroundColor: "rgb(248, 250, 252)" }} />
              </div>
            </button>
          </div>
        </section>

        {/* Corner Style */}
        <section
          className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-3"
          data-testid="corner-style-section"
        >
          <div>
            <h3 className="text-sm font-semibold text-text-primary">Corner Style</h3>
            <p className="text-xs text-text-muted mt-0.5">Choose rounded or sharp corner geometry.</p>
          </div>

          <div className="grid grid-cols-2 gap-3" role="radiogroup" aria-label="Corner style">
            <button
              type="button"
              role="radio"
              aria-checked={cornerStyle === "rounded"}
              onClick={() => setCornerStyle("rounded")}
              className={`text-left rounded-xl border p-3 transition-all cursor-pointer ${
                cornerStyle === "rounded"
                  ? "border-accent-primary bg-accent-primary/8 ring-1 ring-accent-primary/25"
                  : "border-border-subtle bg-surface-page hover:border-border-hover"
              }`}
            >
              <div className="flex items-center justify-between mb-2.5">
                <span className="text-xs font-semibold text-text-primary">Rounded</span>
                {cornerStyle === "rounded" && (
                  <Icon name="check" size={14} className="text-text-accent" />
                )}
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-card p-2 space-y-1.5">
                <div className="flex items-center justify-between">
                  <div className="h-1.5 w-8 rounded-full bg-text-muted/40" />
                  <div className="h-1.5 w-4 rounded-full bg-accent-primary/70" />
                </div>
                <div className="h-6 rounded-md border border-border-subtle bg-surface-muted/60" />
              </div>
            </button>

            <button
              type="button"
              role="radio"
              aria-checked={cornerStyle === "sharp"}
              onClick={() => setCornerStyle("sharp")}
              className={`text-left rounded-xl border p-3 transition-all cursor-pointer ${
                cornerStyle === "sharp"
                  ? "border-accent-primary bg-accent-primary/8 ring-1 ring-accent-primary/25"
                  : "border-border-subtle bg-surface-page hover:border-border-hover"
              }`}
            >
              <div className="flex items-center justify-between mb-2.5">
                <span className="text-xs font-semibold text-text-primary">Sharp</span>
                {cornerStyle === "sharp" && (
                  <Icon name="check" size={14} className="text-text-accent" />
                )}
              </div>
              <div className="rounded-[2px] border border-border-subtle bg-surface-card p-2 space-y-1.5">
                <div className="flex items-center justify-between">
                  <div className="h-1.5 w-8 rounded-[1px] bg-text-muted/40" />
                  <div className="h-1.5 w-4 rounded-[1px] bg-accent-primary/70" />
                </div>
                <div className="h-6 rounded-[2px] border border-border-subtle bg-surface-muted/60" />
              </div>
            </button>
          </div>
        </section>
      </div>

      {/* 2. Visual Skin Gallery */}
      <section className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Visual Skin</h3>
          <p className="text-xs text-text-muted mt-0.5">
            Choose a color palette for surfaces and highlights.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {THEME_SKINS.map((s) => {
            const isSelected = skin === s.id;
            const crispTag = CRISP_SKIN_TAGS[s.id] ?? s.tagline;
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => setSkin(s.id)}
                className={`text-left rounded-xl border p-3.5 transition-all cursor-pointer flex flex-col justify-between ${
                  isSelected
                    ? "border-accent-primary bg-accent-primary/8 ring-1 ring-accent-primary/25"
                    : "border-border-subtle bg-surface-page hover:border-border-hover hover:bg-surface-hover/50"
                }`}
              >
                <div className="flex items-start justify-between gap-2 mb-2.5">
                  <div>
                    <span className="text-xs font-semibold text-text-primary">{s.name}</span>
                    <p className="text-[11px] text-text-muted mt-0.5">{crispTag}</p>
                  </div>
                  {isSelected && <Icon name="check" size={14} className="text-text-accent shrink-0 mt-0.5" />}
                </div>

                <div
                  className="rounded-lg p-2 space-y-1.5 border"
                  style={{ backgroundColor: s.canvasColor, borderColor: s.borderColor }}
                >
                  <div className="flex items-center justify-between pb-1 border-b" style={{ borderColor: s.borderColor }}>
                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: s.accentColor }} />
                    <div className="h-1.5 w-6 rounded-xs" style={{ backgroundColor: s.accentColor }} />
                  </div>
                  <div className="flex gap-1.5">
                    <div className="w-1/4 h-8 rounded-xs" style={{ backgroundColor: s.surfaceColor }} />
                    <div className="w-3/4 space-y-1">
                      <div className="h-3.5 rounded-xs" style={{ backgroundColor: s.surfaceColor }} />
                      <div className="h-3.5 rounded-xs" style={{ backgroundColor: s.elevatedColor }} />
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* 3. Accent Color Override */}
      <section className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Accent Color</h3>
          <p className="text-xs text-text-muted mt-0.5">
            Override the primary highlight color across buttons and controls.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {accentOptions.map((item) => {
            const isSelected = accent === item.id;
            const useDarkCheck = item.id === "theme" && skin === "amber" && theme === "dark";
            return (
              <button
                key={item.id}
                type="button"
                aria-pressed={isSelected}
                onClick={() => setAccent(item.id)}
                className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all cursor-pointer ${
                  isSelected
                    ? "border-accent-primary bg-accent-primary/10 text-text-primary ring-1 ring-accent-primary/25"
                    : "border-border-subtle bg-surface-page text-text-secondary hover:text-text-primary hover:border-border-hover"
                }`}
              >
                <span
                  data-testid={item.id === "theme" ? "skin-default-swatch" : undefined}
                  className="w-3.5 h-3.5 rounded-full shrink-0 flex items-center justify-center"
                  style={{ backgroundColor: item.colorRgb }}
                >
                  {isSelected && (
                    <Icon
                      name="check"
                      size={9}
                      className={useDarkCheck ? "text-text-inverse" : "text-white"}
                    />
                  )}
                </span>
                <span>{item.name}</span>
              </button>
            );
          })}
        </div>
      </section>

      {/* 4. Compact Live Preview Strip */}
      <section className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            Preview
          </span>
          <span className="text-[11px] font-mono text-text-muted">
            {theme} · {skin} · {accent} · {cornerStyle}
          </span>
        </div>

        <div className="rounded-lg border border-border-subtle bg-surface-page p-3.5 flex flex-wrap items-center justify-between gap-3 pointer-events-none select-none">
          <div className="flex items-center gap-3 min-w-0">
            <span className="h-2.5 w-2.5 rounded-full bg-status-success shrink-0" />
            <div className="min-w-0 font-mono text-xs text-text-primary truncate">
              survival-main · Online · 20.0 TPS · 2.4 / 6 GB
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <div className="px-2.5 py-1 rounded-lg bg-accent-primary text-accent-contrast-text text-xs font-medium">
              Console
            </div>
            <div className="px-2.5 py-1 rounded-lg border border-border-subtle bg-surface-card text-text-secondary text-xs font-medium">
              Restart
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
