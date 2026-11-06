import React, { useEffect } from "react";
import { Icon } from "./Icon";

export type ViewMode = "grid" | "list";

export interface ViewModeToggleProps {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
  storageKey?: string;
  className?: string;
}

export const ViewModeToggle: React.FC<ViewModeToggleProps> = ({
  mode,
  onChange,
  storageKey,
  className = "",
}) => {
  useEffect(() => {
    if (!storageKey || typeof window === "undefined") return;
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved === "grid" || saved === "list") {
        if (saved !== mode) {
          onChange(saved);
        }
      }
    } catch {
      // Ignore localStorage errors
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]); // run once per storageKey

  const handleSelect = (newMode: ViewMode) => {
    onChange(newMode);
    if (storageKey && typeof window !== "undefined") {
      try {
        localStorage.setItem(storageKey, newMode);
      } catch {
        // Ignore localStorage errors
      }
    }
  };

  return (
    <div
      role="group"
      aria-label="View layout mode"
      className={`inline-flex items-center rounded-lg border border-border-subtle bg-surface-elevated p-0.5 ${className}`}
    >
      <button
        type="button"
        onClick={() => handleSelect("grid")}
        aria-pressed={mode === "grid"}
        aria-label="Grid card view"
        title="Grid card view"
        className={`flex items-center justify-center rounded-md px-2.5 py-1.5 text-xs transition-colors cursor-pointer ${
          mode === "grid"
            ? "bg-surface-card text-text-primary shadow-2xs font-semibold"
            : "text-text-muted hover:text-text-secondary"
        }`}
      >
        <Icon name="grid" size={15} className="mr-1.5" />
        <span>Cards</span>
      </button>
      <button
        type="button"
        onClick={() => handleSelect("list")}
        aria-pressed={mode === "list"}
        aria-label="Compact list view"
        title="Compact list view"
        className={`flex items-center justify-center rounded-md px-2.5 py-1.5 text-xs transition-colors cursor-pointer ${
          mode === "list"
            ? "bg-surface-card text-text-primary shadow-2xs font-semibold"
            : "text-text-muted hover:text-text-secondary"
        }`}
      >
        <Icon name="list" size={15} className="mr-1.5" />
        <span>List</span>
      </button>
    </div>
  );
};
