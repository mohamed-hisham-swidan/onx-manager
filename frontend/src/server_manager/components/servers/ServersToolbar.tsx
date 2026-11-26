import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { ViewModeToggle, type ViewMode } from "@/components/ui/ViewModeToggle";
import { STATUS_MAP } from "@/server_manager/types";
import {
  SERVERS_VIEW_MODE_STORAGE_KEY,
  STATUS_FILTERS,
  type SortKey,
} from "./serversUtils";

interface MenuOption<T extends string> {
  value: T;
  label: string;
}

interface FilterMenuProps<T extends string> {
  label: string;
  value: T;
  options: MenuOption<T>[];
  onChange: (next: T) => void;
  active?: boolean;
}

function FilterMenu<T extends string>({
  label,
  value,
  options,
  onChange,
  active = false,
}: FilterMenuProps<T>) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onMouseDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onMouseDown);
    };
  }, [open]);

  const currentLabel = options.find((opt) => opt.value === value)?.label ?? value;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${label}: ${currentLabel}`}
        className={`inline-flex h-9 items-center gap-1.5 rounded-xl border px-3 text-xs font-medium transition-colors cursor-pointer ${
          active
            ? "border-accent-primary bg-accent-primary/10 text-text-accent font-semibold"
            : "border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary"
        }`}
      >
        <span className="text-text-muted">{label}:</span>
        <span className="truncate max-w-[120px]">{currentLabel}</span>
        <Icon name="chevron-down" size={13} className="text-text-muted shrink-0" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label={`${label} options`}
          className="absolute left-0 z-30 mt-1.5 min-w-[180px] max-h-64 overflow-y-auto rounded-xl border border-border-default bg-surface-elevated p-1 shadow-xl"
        >
          {options.map((opt) => {
            const selected = opt.value === value;
            return (
              <button
                key={opt.value}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors cursor-pointer ${
                  selected
                    ? "bg-accent-primary/15 text-text-accent font-semibold"
                    : "text-text-primary hover:bg-surface-hover"
                }`}
              >
                <span>{opt.label}</span>
                {selected && <Icon name="check" size={13} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export interface ServersToolbarProps {
  search: string;
  onSearchChange: (value: string) => void;
  statusFilter: string;
  onStatusFilterChange: (value: string) => void;
  loaderFilter: string;
  onLoaderFilterChange: (value: string) => void;
  availableLoaders: string[];
  modeFilter: string;
  onModeFilterChange: (value: string) => void;
  sortKey: SortKey;
  onSortKeyChange: (value: SortKey) => void;
  viewMode: ViewMode;
  onViewModeChange: (value: ViewMode) => void;
  totalCount: number;
  filteredCount: number;
  hasActiveFilters: boolean;
  onClearFilters: () => void;
}

const SORT_OPTIONS: MenuOption<SortKey>[] = [
  { value: "name", label: "Name (A–Z)" },
  { value: "status", label: "Status" },
  { value: "players", label: "Players Online" },
  { value: "memory", label: "Allocated RAM" },
  { value: "version", label: "MC Version" },
  { value: "created", label: "Newest" },
];

const MODE_OPTIONS: MenuOption<string>[] = [
  { value: "all", label: "All Modes" },
  { value: "simple", label: "Simple" },
  { value: "advanced", label: "Advanced" },
];

export function ServersToolbar({
  search,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  loaderFilter,
  onLoaderFilterChange,
  availableLoaders,
  modeFilter,
  onModeFilterChange,
  sortKey,
  onSortKeyChange,
  viewMode,
  onViewModeChange,
  totalCount,
  filteredCount,
  hasActiveFilters,
  onClearFilters,
}: ServersToolbarProps) {
  const statusOptions: MenuOption<string>[] = STATUS_FILTERS.map((s) => ({
    value: s,
    label:
      s === "all"
        ? "All Statuses"
        : s === "attention"
          ? "Needs Attention"
          : STATUS_MAP[s]?.label ?? s,
  }));

  const loaderOptions: MenuOption<string>[] = [
    { value: "all", label: "All Loaders" },
    ...availableLoaders.map((loader) => ({
      value: loader,
      label: loader.charAt(0).toUpperCase() + loader.slice(1),
    })),
  ];

  return (
    <div className="space-y-2.5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        {/* Search Input */}
        <div className="relative flex-1 min-w-0">
          <Icon
            name="search"
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
          />
          <input
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search by name, loader, version, port, or MOTD..."
            aria-label="Search servers"
            className="h-9 w-full rounded-xl border border-border-default bg-surface-card pl-9 pr-8 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus"
          />
          {search && (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              aria-label="Clear search"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-text-muted hover:bg-surface-hover hover:text-text-primary cursor-pointer"
            >
              <Icon name="x" size={14} />
            </button>
          )}
        </div>

        {/* Inline Filters, Sort & View Toggle */}
        <div className="flex flex-wrap items-center gap-2">
          <FilterMenu
            label="Status"
            value={statusFilter}
            options={statusOptions}
            onChange={onStatusFilterChange}
            active={statusFilter !== "all"}
          />

          {availableLoaders.length > 0 && (
            <FilterMenu
              label="Loader"
              value={loaderFilter}
              options={loaderOptions}
              onChange={onLoaderFilterChange}
              active={loaderFilter !== "all"}
            />
          )}

          <FilterMenu
            label="Mode"
            value={modeFilter}
            options={MODE_OPTIONS}
            onChange={onModeFilterChange}
            active={modeFilter !== "all"}
          />

          <FilterMenu
            label="Sort"
            value={sortKey}
            options={SORT_OPTIONS}
            onChange={onSortKeyChange}
            active={sortKey !== "name"}
          />

          <ViewModeToggle
            mode={viewMode}
            onChange={onViewModeChange}
            storageKey={SERVERS_VIEW_MODE_STORAGE_KEY}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-muted">
        <span>
          Showing <span className="font-mono font-semibold text-text-primary">{filteredCount}</span> of{" "}
          <span className="font-mono">{totalCount}</span> {totalCount === 1 ? "instance" : "instances"}
        </span>
        {hasActiveFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-text-accent hover:bg-accent-primary/10 transition-colors cursor-pointer"
          >
            <Icon name="x" size={12} />
            <span>Clear filters</span>
          </button>
        )}
      </div>
    </div>
  );
}
