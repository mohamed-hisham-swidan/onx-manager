import React, { useRef } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";

export interface TabItem {
  id: string;
  label: React.ReactNode;
  icon?: IconName;
  count?: number;
  disabled?: boolean;
}

export interface TabsProps {
  value: string;
  onChange: (id: string) => void;
  items: TabItem[];
  ariaLabel?: string;
  size?: "sm" | "md";
  className?: string;
}

export const Tabs: React.FC<TabsProps> = ({
  value,
  onChange,
  items,
  ariaLabel = "Navigation Tabs",
  size = "md",
  className = "",
}) => {
  const tabListRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    const enabledItems = items.filter((item) => !item.disabled);
    const enabledCurrentIndex = enabledItems.findIndex((item) => item.id === items[currentIndex].id);

    let nextIndex = -1;
    if (e.key === "ArrowRight") {
      nextIndex = (enabledCurrentIndex + 1) % enabledItems.length;
    } else if (e.key === "ArrowLeft") {
      nextIndex = (enabledCurrentIndex - 1 + enabledItems.length) % enabledItems.length;
    } else if (e.key === "Home") {
      nextIndex = 0;
    } else if (e.key === "End") {
      nextIndex = enabledItems.length - 1;
    }

    if (nextIndex !== -1) {
      e.preventDefault();
      const targetItem = enabledItems[nextIndex];
      onChange(targetItem.id);

      // Focus target button
      const buttons = tabListRef.current?.querySelectorAll<HTMLButtonElement>('button[role="tab"]:not([disabled])');
      if (buttons && buttons[nextIndex]) {
        buttons[nextIndex].focus();
      }
    }
  };

  const paddingStyle = size === "sm" ? "px-3 py-2 text-xs" : "px-4 py-2.5 text-sm";

  return (
    <div
      ref={tabListRef}
      role="tablist"
      aria-label={ariaLabel}
      className={`flex items-center gap-1 border-b border-border-subtle overflow-x-auto no-scrollbar ${className}`}
    >
      {items.map((tab, idx) => {
        const isSelected = tab.id === value;

        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            id={`tab-${tab.id}`}
            aria-selected={isSelected}
            tabIndex={isSelected ? 0 : -1}
            disabled={tab.disabled}
            onClick={() => !tab.disabled && onChange(tab.id)}
            onKeyDown={(e) => handleKeyDown(e, idx)}
            className={`group relative inline-flex items-center gap-2 font-medium transition-colors border-b-2 -mb-px focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus disabled:pointer-events-none disabled:opacity-40 cursor-pointer ${paddingStyle} ${
              isSelected
                ? "border-accent-primary text-text-primary"
                : "border-transparent text-text-muted hover:text-text-secondary hover:border-border-default"
            }`}
          >
            {tab.icon && (
              <Icon
                name={tab.icon}
                size={size === "sm" ? 14 : 16}
                className={isSelected ? "text-accent-primary" : "text-text-muted group-hover:text-text-secondary"}
              />
            )}
            <span>{tab.label}</span>
            {tab.count !== undefined && (
              <span
                className={`ml-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold leading-none ${
                  isSelected
                    ? "bg-accent-primary/15 text-accent-primary"
                    : "bg-surface-hover text-text-muted"
                }`}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
};
