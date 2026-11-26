import React, { useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import {
  SETTINGS_NAV_ITEMS,
  type SettingsNavItem,
  type SettingsTabId,
} from "./settingsModel";

export interface SettingsShellProps {
  activeTab: SettingsTabId;
  onTabChange: (tab: SettingsTabId) => void;
  version?: string | null;
  isLocal: boolean;
  showFullControls: boolean;
  showFullVpsControls: boolean;
  onToggleVpsControls: () => void;
  isOwner: boolean;
  children: React.ReactNode;
}

export function SettingsShell({
  activeTab,
  onTabChange,
  version,
  isLocal,
  showFullControls,
  showFullVpsControls,
  onToggleVpsControls,
  isOwner,
  children,
}: SettingsShellProps) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const visibleItems = SETTINGS_NAV_ITEMS.filter(
    (item) => showFullControls || !item.vpsOnly || item.id === activeTab,
  );
  const panelItems = visibleItems.filter((i) => i.group === "panel");
  const teamItems = visibleItems.filter((i) => i.group === "team");

  const handleTabKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
    orientation: "vertical" | "horizontal",
  ) => {
    const prevKey = orientation === "vertical" ? "ArrowUp" : "ArrowLeft";
    const nextKey = orientation === "vertical" ? "ArrowDown" : "ArrowRight";
    if (e.key !== prevKey && e.key !== nextKey && e.key !== "Home" && e.key !== "End") {
      return;
    }
    e.preventDefault();
    let targetIndex = currentIndex;
    if (e.key === prevKey) {
      targetIndex = (currentIndex - 1 + visibleItems.length) % visibleItems.length;
    } else if (e.key === nextKey) {
      targetIndex = (currentIndex + 1) % visibleItems.length;
    } else if (e.key === "Home") {
      targetIndex = 0;
    } else if (e.key === "End") {
      targetIndex = visibleItems.length - 1;
    }
    const target = visibleItems[targetIndex];
    if (target) {
      onTabChange(target.id);
      tabRefs.current[`${orientation}-${target.id}`]?.focus();
    }
  };

  const renderDesktopButton = (item: SettingsNavItem) => {
    const isActive = activeTab === item.id;
    const idx = visibleItems.findIndex((i) => i.id === item.id);
    return (
      <button
        key={item.id}
        ref={(el) => {
          tabRefs.current[`vertical-${item.id}`] = el;
        }}
        id={`settings-tab-${item.id}`}
        type="button"
        role="tab"
        aria-selected={isActive}
        aria-controls="settings-tabpanel"
        tabIndex={isActive ? 0 : -1}
        onClick={() => onTabChange(item.id)}
        onKeyDown={(e) => handleTabKeyDown(e, idx, "vertical")}
        className={`relative w-full flex items-center justify-between gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors cursor-pointer text-left focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus ${
          isActive
            ? "bg-accent-primary/12 text-text-primary font-semibold"
            : "text-text-secondary hover:text-text-primary hover:bg-surface-hover font-medium"
        }`}
      >
        {isActive && (
          <span
            aria-hidden="true"
            className="absolute left-0 top-1/2 -translate-y-1/2 h-4 w-[3px] rounded-full bg-accent-primary"
          />
        )}
        <span className="flex items-center gap-2.5 min-w-0">
          <Icon
            name={item.icon}
            size={16}
            className={isActive ? "text-text-accent shrink-0" : "text-text-muted shrink-0"}
          />
          <span className="truncate">{item.label}</span>
        </span>
        {item.ownerOnlyHint && !isOwner && (
          <Icon name="lock" size={13} className="text-text-muted shrink-0" />
        )}
      </button>
    );
  };

  return (
    <div className="mx-auto w-full max-w-6xl xl:max-w-[78rem] 2xl:max-w-[86rem] px-6 py-6 lg:px-8">
      <div className="flex flex-col md:flex-row md:items-stretch gap-6 lg:gap-8">
        {/* Mobile Top Sticky Pill Bar */}
        <div className="md:hidden sticky top-0 z-20 -mx-6 px-6 py-2.5 bg-surface-page/95 backdrop-blur-xs border-b border-border-subtle">
          <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5" role="tablist" aria-label="Settings sections">
            {visibleItems.map((item, idx) => {
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  ref={(el) => {
                    tabRefs.current[`horizontal-${item.id}`] = el;
                  }}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls="settings-tabpanel"
                  onClick={() => onTabChange(item.id)}
                  onKeyDown={(e) => handleTabKeyDown(e, idx, "horizontal")}
                  className={`inline-flex items-center gap-1.5 whitespace-nowrap shrink-0 rounded-lg px-3 py-1.5 text-xs transition-colors cursor-pointer ${
                    isActive
                      ? "bg-accent-primary/14 text-text-primary font-semibold"
                      : "text-text-secondary hover:text-text-primary hover:bg-surface-hover font-medium"
                  }`}
                >
                  <Icon
                    name={item.icon}
                    size={14}
                    className={isActive ? "text-text-accent" : "text-text-muted"}
                  />
                  <span>{item.label}</span>
                </button>
              );
            })}
            {isLocal && (
              <button
                type="button"
                role="switch"
                aria-checked={showFullVpsControls}
                aria-label="VPS Mode"
                onClick={onToggleVpsControls}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap shrink-0 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors cursor-pointer ml-auto ${
                  showFullVpsControls
                    ? "border-accent-primary/40 bg-accent-primary/10 text-text-primary"
                    : "border-border-subtle bg-surface-card text-text-secondary"
                }`}
              >
                <Icon name="globe" size={13} className="text-text-muted" />
                <span>VPS Mode</span>
              </button>
            )}
          </div>
        </div>

        {/* Desktop & Tablet Left Rail (full-height border-r divider, sticky inner nav) */}
        <aside className="hidden md:block md:w-52 lg:w-60 shrink-0 md:border-r md:border-border-subtle md:pr-6">
          <div className="md:sticky md:top-6 flex flex-col gap-6">
            <div className="flex items-center justify-between gap-2 px-2">
              <h1 className="text-lg font-semibold tracking-tight text-text-primary">Settings</h1>
              {version ? (
                <span
                  data-testid="settings-version-pill"
                  className="rounded-md bg-surface-muted px-2 py-0.5 font-mono text-[11px] font-medium text-text-muted"
                >
                  v{version.replace(/^v/i, "")}
                </span>
              ) : null}
            </div>

            <nav
              role="tablist"
              aria-label="Settings navigation"
              aria-orientation="vertical"
              className="space-y-5"
            >
              <div className="space-y-1">
                <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Panel
                </div>
                {panelItems.map(renderDesktopButton)}
              </div>

              {teamItems.length > 0 && (
                <div className="space-y-1">
                  <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    Team &amp; Remote
                  </div>
                  {teamItems.map(renderDesktopButton)}
                </div>
              )}
            </nav>

            {isLocal && (
              <div className="mt-2 rounded-xl border border-border-subtle bg-surface-card/70 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-text-primary truncate">
                      VPS &amp; Team Controls
                    </p>
                    <p className="text-[11px] text-text-muted mt-0.5 truncate">
                      Remote &amp; multi-user
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={showFullVpsControls}
                    aria-label="VPS & Team Controls"
                    onClick={onToggleVpsControls}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus ${
                      showFullVpsControls ? "bg-accent-primary" : "bg-border-default"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-accent-contrast-text shadow-xs transition-transform ${
                        showFullVpsControls ? "translate-x-4" : "translate-x-0"
                      }`}
                    />
                  </button>
                </div>
              </div>
            )}
          </div>
        </aside>

        {/* Right Content Workspace */}
        <div
          id="settings-tabpanel"
          role="tabpanel"
          aria-labelledby={`settings-tab-${activeTab}`}
          className="min-w-0 flex-1 max-w-4xl 2xl:max-w-5xl"
        >
          {children}
        </div>
      </div>
    </div>
  );
}
