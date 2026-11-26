import React, { useRef } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import {
  SERVER_SETTINGS_NAV_ITEMS,
  type ServerSettingsNavItem,
  type ServerSettingsTabId,
} from "./serverSettingsModel";

export interface ServerSettingsShellProps {
  serverId: string;
  activeTab: ServerSettingsTabId;
  onTabChange: (tab: ServerSettingsTabId) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  gitBacked: boolean;
  activeBranch?: string;
  canDelete: boolean;
  topNotice?: React.ReactNode;
  topBanners?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function ServerSettingsShell({
  serverId,
  activeTab,
  onTabChange,
  searchQuery,
  onSearchChange,
  gitBacked,
  activeBranch,
  canDelete,
  topNotice,
  topBanners,
  children,
  footer,
}: ServerSettingsShellProps) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const configItems = SERVER_SETTINGS_NAV_ITEMS.filter(
    (item) => item.group === "configuration",
  );
  const lifecycleItems = SERVER_SETTINGS_NAV_ITEMS.filter(
    (item) => item.group === "lifecycle",
  );
  const allItems = SERVER_SETTINGS_NAV_ITEMS;

  const isSearching = searchQuery.trim().length > 0;
  const isNonMainBranch = Boolean(
    gitBacked && activeBranch && activeBranch !== "main",
  );
  const serverPropsLink = isNonMainBranch
    ? `/servers/${serverId}/files?file=server.properties&branch=${encodeURIComponent(activeBranch!)}`
    : `/servers/${serverId}/files?file=server.properties`;

  const handleTabKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
    orientation: "vertical" | "horizontal",
  ) => {
    const prevKey = orientation === "vertical" ? "ArrowUp" : "ArrowLeft";
    const nextKey = orientation === "vertical" ? "ArrowDown" : "ArrowRight";
    if (
      e.key !== prevKey &&
      e.key !== nextKey &&
      e.key !== "Home" &&
      e.key !== "End"
    ) {
      return;
    }
    e.preventDefault();
    let targetIndex = currentIndex;
    if (e.key === prevKey) {
      targetIndex = (currentIndex - 1 + allItems.length) % allItems.length;
    } else if (e.key === nextKey) {
      targetIndex = (currentIndex + 1) % allItems.length;
    } else if (e.key === "Home") {
      targetIndex = 0;
    } else if (e.key === "End") {
      targetIndex = allItems.length - 1;
    }
    const target = allItems[targetIndex];
    if (target) {
      onSearchChange("");
      onTabChange(target.id);
      tabRefs.current[`${orientation}-${target.id}`]?.focus();
    }
  };

  const renderDesktopButton = (item: ServerSettingsNavItem) => {
    const isActive = !isSearching && activeTab === item.id;
    const idx = allItems.findIndex((i) => i.id === item.id);
    const locked = item.id === "danger" && !canDelete;

    return (
      <button
        key={item.id}
        ref={(el) => {
          tabRefs.current[`vertical-${item.id}`] = el;
        }}
        id={`server-settings-tab-${item.id}`}
        type="button"
        role="tab"
        aria-selected={isActive}
        aria-controls="server-settings-tabpanel"
        tabIndex={isActive ? 0 : -1}
        onClick={() => {
          onSearchChange("");
          onTabChange(item.id);
        }}
        onKeyDown={(e) => handleTabKeyDown(e, idx, "vertical")}
        className={`relative w-full flex items-center justify-between gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors cursor-pointer text-left focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus ${
          isActive
            ? item.danger
              ? "bg-status-danger-bg text-status-danger font-medium"
              : "bg-accent-primary/10 text-accent-primary font-medium"
            : item.danger
              ? "text-text-secondary hover:text-status-danger hover:bg-status-danger-bg/40 font-medium"
              : "text-text-secondary hover:text-text-primary hover:bg-surface-hover font-medium"
        }`}
      >
        {isActive && (
          <span
            aria-hidden="true"
            className={`absolute left-0 top-1/2 -translate-y-1/2 h-4 w-[3px] rounded-full ${
              item.danger ? "bg-status-danger" : "bg-accent-primary"
            }`}
          />
        )}
        <span className="flex items-center gap-2.5 min-w-0">
          <Icon
            name={item.icon}
            size={16}
            className={
              isActive
                ? item.danger
                  ? "text-status-danger shrink-0"
                  : "text-accent-primary shrink-0"
                : "text-text-muted shrink-0"
            }
          />
          <span className="truncate">{item.label}</span>
        </span>
        {locked && <Icon name="lock" size={13} className="text-text-muted shrink-0" />}
      </button>
    );
  };

  return (
    <div className="mx-auto w-full max-w-6xl xl:max-w-[80rem] space-y-4">
      <div className="flex flex-col lg:flex-row lg:items-stretch gap-6 lg:gap-8">
        {/* Mobile & Tablet Search + Single-Row Scrollable Pill Bar */}
        <div className="lg:hidden space-y-2.5">
          <div className="relative">
            <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-text-muted">
              <Icon name="search" size={14} />
            </span>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder="Search settings..."
              aria-label="Search server settings"
              className="w-full rounded-lg border border-border-subtle bg-surface-card py-2 pl-9 pr-8 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus"
            />
            {searchQuery && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => onSearchChange("")}
                className="absolute inset-y-0 right-0 flex items-center pr-2.5 text-text-muted hover:text-text-primary cursor-pointer"
              >
                <Icon name="x" size={13} />
              </button>
            )}
          </div>

          <div
            role="tablist"
            aria-label="Server settings sections"
            className="flex items-center gap-1.5 overflow-x-auto pb-1"
          >
            {allItems.map((item, idx) => {
              const isActive = !isSearching && activeTab === item.id;
              return (
                <button
                  key={item.id}
                  ref={(el) => {
                    tabRefs.current[`horizontal-${item.id}`] = el;
                  }}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls="server-settings-tabpanel"
                  onClick={() => {
                    onSearchChange("");
                    onTabChange(item.id);
                  }}
                  onKeyDown={(e) => handleTabKeyDown(e, idx, "horizontal")}
                  className={`inline-flex items-center gap-1.5 whitespace-nowrap shrink-0 rounded-lg px-3 py-1.5 text-xs transition-colors cursor-pointer ${
                    isActive
                      ? item.danger
                        ? "bg-status-danger-bg text-status-danger font-semibold"
                        : "bg-accent-primary/12 text-accent-primary font-semibold"
                      : "text-text-secondary hover:text-text-primary hover:bg-surface-hover font-medium"
                  }`}
                >
                  <Icon
                    name={item.icon}
                    size={13}
                    className={
                      isActive
                        ? item.danger
                          ? "text-status-danger"
                          : "text-accent-primary"
                        : "text-text-muted"
                    }
                  />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center justify-end">
            <Link
              to={serverPropsLink}
              data-testid="edit-server-properties-link-mobile"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-text-secondary hover:text-accent-primary transition-colors"
            >
              <Icon name="file" size={13} />
              <span>Edit server.properties →</span>
            </Link>
          </div>
        </div>

        {/* Desktop Left Rail */}
        <aside className="hidden lg:block lg:w-60 shrink-0 lg:border-r lg:border-border-subtle lg:pr-6">
          <div className="lg:sticky lg:top-6 flex flex-col gap-5">
            {/* Compact Rail Search */}
            <div className="relative">
              <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-text-muted">
                <Icon name="search" size={14} />
              </span>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Search settings..."
                aria-label="Search server settings"
                className="w-full rounded-lg border border-border-subtle bg-surface-card py-2 pl-9 pr-8 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              />
              {searchQuery && (
                <button
                  type="button"
                  aria-label="Clear search"
                  onClick={() => onSearchChange("")}
                  className="absolute inset-y-0 right-0 flex items-center pr-2.5 text-text-muted hover:text-text-primary cursor-pointer"
                >
                  <Icon name="x" size={13} />
                </button>
              )}
            </div>

            <nav
              role="tablist"
              aria-label="Server settings navigation"
              aria-orientation="vertical"
              className="space-y-5"
            >
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-2 px-3 pb-1">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    Configuration
                  </span>
                  {gitBacked && activeBranch && (
                    <span
                      data-testid="settings-branch-pill"
                      className="rounded-md bg-surface-muted px-1.5 py-0.5 font-mono text-[10px] font-medium text-text-secondary truncate max-w-[100px]"
                    >
                      {activeBranch === "main" ? "main" : `branch: ${activeBranch}`}
                    </span>
                  )}
                </div>
                {configItems.map(renderDesktopButton)}
              </div>

              <div className="space-y-1">
                <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Lifecycle &amp; System
                </div>
                {lifecycleItems.map(renderDesktopButton)}
              </div>
            </nav>

            <div className="border-t border-border-subtle pt-3 px-2">
              <Link
                to={serverPropsLink}
                data-testid="edit-server-properties-link"
                className="inline-flex items-center gap-1.5 text-xs font-medium text-text-secondary hover:text-accent-primary transition-colors"
              >
                <Icon name="file" size={13} />
                <span>Edit server.properties →</span>
              </Link>
            </div>
          </div>
        </aside>

        {/* Right Content Workspace */}
        <div
          id="server-settings-tabpanel"
          role="tabpanel"
          aria-labelledby={
            isSearching ? undefined : `server-settings-tab-${activeTab}`
          }
          className="min-w-0 flex-1 max-w-4xl xl:max-w-5xl space-y-5"
        >
          {topNotice}
          {topBanners}
          {children}
          {footer}
        </div>
      </div>
    </div>
  );
}
