import React from "react";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import type { SortDirection, SortField } from "./filesUtils";

export interface UploadProgressState {
  current: number;
  total: number;
  fileName: string;
}

export interface FilesToolbarProps {
  breadcrumbs: Array<{ name: string; path: string }>;
  currentPath: string;
  onNavigatePath: (path: string) => void;
  onCopyPath: () => void;
  copiedPath: boolean;
  filteredCount: number;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  sortField: SortField;
  sortDirection: SortDirection;
  onSortChange: (field: SortField, direction: SortDirection) => void;
  isLiveState: boolean;
  readOnly: boolean;
  activeBranch?: string;
  selectedCount: number;
  onClearSelection: () => void;
  onBulkDelete: () => void;
  bulkDeletePending: boolean;
  onOpenNewFile: () => void;
  onOpenNewFolder: () => void;
  onTriggerUpload: () => void;
  uploadPending: boolean;
  uploadProgress: UploadProgressState | null;
  onOpenCommit: () => void;
  splitView?: boolean;
  onToggleSplitView?: () => void;
  embedded?: boolean;
}

const SORT_OPTIONS: Array<{ value: string; label: string; field: SortField; dir: SortDirection }> = [
  { value: "name:asc", label: "Name (A–Z)", field: "name", dir: "asc" },
  { value: "name:desc", label: "Name (Z–A)", field: "name", dir: "desc" },
  { value: "modified:desc", label: "Modified (Newest)", field: "modified", dir: "desc" },
  { value: "size:desc", label: "Size (Largest)", field: "size", dir: "desc" },
  { value: "type:asc", label: "Type", field: "type", dir: "asc" },
];

export const FilesToolbar: React.FC<FilesToolbarProps> = ({
  breadcrumbs,
  currentPath,
  onNavigatePath,
  onCopyPath,
  copiedPath,
  filteredCount,
  searchQuery,
  onSearchChange,
  sortField,
  sortDirection,
  onSortChange,
  isLiveState,
  readOnly,
  activeBranch,
  selectedCount,
  onClearSelection,
  onBulkDelete,
  bulkDeletePending,
  onOpenNewFile,
  onOpenNewFolder,
  onTriggerUpload,
  uploadPending,
  uploadProgress,
  onOpenCommit,
  splitView = false,
  onToggleSplitView,
  embedded = false,
}) => {
  const sortValue = `${sortField}:${sortDirection}`;

  return (
    <div
      className={
        embedded
          ? "flex flex-col gap-2.5 shrink-0 border-b border-border-subtle bg-surface-card p-3"
          : "flex flex-col gap-3 rounded-xl border border-border-subtle bg-surface-card p-4 shadow-xs"
      }
    >
      {/* Row 1: Breadcrumbs + Copy Path + Item Count */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 overflow-x-auto whitespace-nowrap text-sm font-medium text-text-secondary min-w-0">
          {breadcrumbs.map((crumb, idx) => (
            <React.Fragment key={crumb.path}>
              <button
                type="button"
                onClick={() => onNavigatePath(crumb.path)}
                className={`flex items-center gap-1.5 rounded px-1 py-0.5 hover:text-text-primary transition-colors cursor-pointer ${
                  idx === breadcrumbs.length - 1
                    ? "font-semibold text-text-primary"
                    : ""
                }`}
              >
                {idx === 0 && <Icon name="folder" size={15} className="text-text-muted shrink-0" />}
                <span>{crumb.name}</span>
              </button>
              {idx < breadcrumbs.length - 1 && (
                <span className="text-border-strong select-none">/</span>
              )}
            </React.Fragment>
          ))}
          <button
            type="button"
            onClick={onCopyPath}
            aria-label="Copy current path"
            title={copiedPath ? "Copied!" : `Copy path (${currentPath || "/"})`}
            className="ml-1 inline-flex items-center gap-1 rounded-md border border-transparent px-1.5 py-0.5 text-xs text-text-muted hover:border-border-subtle hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
          >
            <Icon name={copiedPath ? "check" : "copy"} size={13} />
          </button>
        </div>

        <span
          data-testid="files-item-count"
          className="inline-flex items-center rounded-full border border-border-subtle bg-surface-muted px-2.5 py-0.5 text-xs font-medium text-text-muted tabular-nums"
        >
          {filteredCount} {filteredCount === 1 ? "item" : "items"}
        </span>
      </div>

      {/* Row 2: Filter + Sort + Primary Actions */}
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-2 flex-1 min-w-[220px]">
          <div className="relative flex-1 min-w-[180px] max-w-xs">
            <span className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-text-muted">
              <Icon name="search" size={15} />
            </span>
            <input
              type="text"
              aria-label="Filter current directory"
              placeholder="Filter in this folder..."
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              className="w-full rounded-lg border border-border-subtle hover:border-border-hover bg-surface-page py-1.5 ps-9 pe-8 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-hidden focus:ring-1 focus:ring-border-focus transition-colors"
            />
            {searchQuery && (
              <button
                type="button"
                aria-label="Clear search filter"
                onClick={() => onSearchChange("")}
                className="absolute inset-y-0 end-0 flex items-center pe-2.5 text-text-muted hover:text-text-primary cursor-pointer"
              >
                <Icon name="x" size={14} />
              </button>
            )}
          </div>

          <div className="relative inline-flex items-center">
            <select
              aria-label="Sort files"
              value={sortValue}
              onChange={(e) => {
                const match = SORT_OPTIONS.find((o) => o.value === e.target.value);
                if (match) onSortChange(match.field, match.dir);
              }}
              className="appearance-none rounded-lg border border-border-subtle hover:border-border-hover bg-surface-page py-1.5 ps-3 pe-8 text-sm text-text-secondary focus:border-border-focus focus:outline-hidden focus:ring-1 focus:ring-border-focus cursor-pointer transition-colors"
            >
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  Sort: {opt.label}
                </option>
              ))}
            </select>
            <span className="pointer-events-none absolute end-2.5 text-text-muted">
              <Icon name="chevron-down" size={13} />
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {onToggleSplitView && (
            <button
              type="button"
              data-testid="files-split-view-toggle"
              aria-pressed={splitView}
              onClick={onToggleSplitView}
              className={`hidden lg:inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                splitView
                  ? "border-accent-primary bg-accent-primary text-accent-contrast-text"
                  : "border-border-subtle bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary"
              }`}
            >
              <Icon name="columns" size={14} />
              <span>Split View</span>
            </button>
          )}

          {!isLiveState && activeBranch && !readOnly && (
            <Button
              variant="secondary"
              size="sm"
              icon="save"
              onClick={onOpenCommit}
            >
              Save &amp; Commit
            </Button>
          )}

          {!isLiveState && !readOnly && (
            <>
              <Button
                variant="secondary"
                size="sm"
                icon="plus"
                onClick={onOpenNewFile}
              >
                New File
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon="folder"
                onClick={onOpenNewFolder}
              >
                New Folder
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon="upload"
                loading={uploadPending}
                onClick={onTriggerUpload}
              >
                Upload File
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Bulk Selection Bar */}
      {selectedCount > 0 && !readOnly && !isLiveState && (
        <div
          data-testid="files-bulk-bar"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-default bg-surface-muted px-3 py-2 text-xs"
        >
          <span className="font-medium text-text-primary">
            {selectedCount} selected
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="xs"
              onClick={onClearSelection}
              disabled={bulkDeletePending}
            >
              Clear selection
            </Button>
            <Button
              variant="danger"
              size="xs"
              icon="trash"
              loading={bulkDeletePending}
              onClick={onBulkDelete}
            >
              Delete Selected ({selectedCount})
            </Button>
          </div>
        </div>
      )}

      {/* Multi-File Upload Progress Bar */}
      {uploadProgress && (
        <div
          data-testid="files-upload-progress"
          className="flex flex-col gap-1.5 rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-xs"
        >
          <div className="flex items-center justify-between gap-2 text-text-secondary">
            <span className="truncate font-medium">
              Uploading {uploadProgress.current} of {uploadProgress.total}: {uploadProgress.fileName}
            </span>
            <span className="font-mono tabular-nums text-text-muted shrink-0">
              {Math.round((uploadProgress.current / uploadProgress.total) * 100)}%
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-card">
            <div
              className="h-full rounded-full bg-accent-primary transition-all duration-200"
              style={{
                width: `${Math.min(100, Math.round((uploadProgress.current / uploadProgress.total) * 100))}%`,
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
};
