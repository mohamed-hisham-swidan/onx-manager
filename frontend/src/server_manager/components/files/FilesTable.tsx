import React, { useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { IconButton } from "@/components/ui/Button";
import { Pagination } from "@/components/ui/Pagination";
import { EmptyState } from "@/components/ui/States";
import { formatBytes, formatDateTime, formatRelativeTime } from "@/server_manager/utils/format";
import {
  getFileClassBadge,
  getFileIconName,
  isBinaryFile,
  isImageFile,
  type UnifiedFileRow,
} from "./filesUtils";

export interface FilesTableProps {
  rows: UnifiedFileRow[];
  totalFilteredCount: number;
  pageSize: number;
  currentPage: number;
  onPageChange: (page: number) => void;
  currentPath: string;
  searchQuery: string;
  onClearSearch: () => void;
  isLiveState: boolean;
  readOnly: boolean;
  isAdvancedMode?: boolean;
  activeBranch?: string;
  dropBlockedReason?: string | null;
  activeFilePath?: string | null;
  embedded?: boolean;
  selectedPaths: Set<string>;
  onToggleSelect: (path: string) => void;
  onToggleSelectAll: () => void;
  isAllSelected: boolean;
  onNavigateUp: () => void;
  onNavigateFolder: (row: UnifiedFileRow) => void;
  onOpenFile: (row: UnifiedFileRow) => void;
  onDownload: (row: UnifiedFileRow) => void;
  onDelete: (row: UnifiedFileRow) => void;
  onOpenNewFile: () => void;
  onTriggerUpload: () => void;
  onDropFiles: (files: File[]) => void;
}

const BADGE_TONE_CLASSES: Record<"neutral" | "info" | "warning" | "accent", string> = {
  neutral: "border-border-subtle bg-surface-muted text-text-muted",
  info: "border-status-info-border bg-status-info-bg text-status-info",
  warning: "border-status-warning-border bg-status-warning-bg text-status-warning",
  accent: "border-border-default bg-accent-primary/10 text-text-accent",
};

export const FilesTable: React.FC<FilesTableProps> = ({
  rows,
  totalFilteredCount,
  pageSize,
  currentPage,
  onPageChange,
  currentPath,
  searchQuery,
  onClearSearch,
  isLiveState,
  readOnly,
  isAdvancedMode = false,
  activeBranch,
  dropBlockedReason,
  activeFilePath,
  embedded = false,
  selectedPaths,
  onToggleSelect,
  onToggleSelectAll,
  isAllSelected,
  onNavigateUp,
  onNavigateFolder,
  onOpenFile,
  onDownload,
  onDelete,
  onOpenNewFile,
  onTriggerUpload,
  onDropFiles,
}) => {
  const dragCounterRef = useRef(0);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [isBlockedDragOver, setIsBlockedDragOver] = useState(false);

  const canMutateInTable = !readOnly && !isLiveState;
  const showCheckboxes = canMutateInTable && rows.length > 0;

  const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    if (canMutateInTable) {
      setIsDraggingOver(true);
    } else if (dropBlockedReason) {
      setIsBlockedDragOver(true);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = canMutateInTable ? "copy" : "none";
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
    if (dragCounterRef.current === 0) {
      setIsDraggingOver(false);
      setIsBlockedDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDraggingOver(false);
    setIsBlockedDragOver(false);
    if (!canMutateInTable) return;
    const dropped = e.dataTransfer.files ? Array.from(e.dataTransfer.files) : [];
    if (dropped.length > 0) {
      onDropFiles(dropped);
    }
  };

  const isEmptyDir = totalFilteredCount === 0 && !searchQuery;
  const isEmptySearch = totalFilteredCount === 0 && Boolean(searchQuery);

  return (
    <div
      data-testid="files-dropzone"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`relative flex flex-col flex-1 min-h-0 min-w-0 bg-surface-card overflow-hidden transition-colors ${
        embedded
          ? isDraggingOver
            ? "ring-2 ring-inset ring-accent-primary/30 bg-accent-primary/5"
            : ""
          : isDraggingOver
            ? "rounded-xl border border-accent-primary ring-2 ring-accent-primary/25 bg-accent-primary/5 shadow-xs"
            : "rounded-xl border border-border-subtle shadow-xs"
      }`}
    >
      {isDraggingOver && (
        <div
          data-testid="files-drop-indicator"
          className="pointer-events-none flex items-center justify-center gap-2 border-b border-accent-primary/40 bg-accent-primary/10 px-4 py-2 text-xs font-semibold text-text-accent"
        >
          <Icon name="upload" size={14} />
          <span>
            Drop files to upload into {currentPath || "root"}
            {activeBranch ? ` (branch: ${activeBranch})` : ""}
          </span>
        </div>
      )}

      {!isDraggingOver && isBlockedDragOver && dropBlockedReason && (
        <div
          data-testid="files-drop-blocked-notice"
          className="pointer-events-none flex items-center justify-center gap-2 border-b border-status-warning-border bg-status-warning-bg px-4 py-2 text-xs font-medium text-status-warning"
        >
          <Icon name="lock" size={14} />
          <span>{dropBlockedReason}</span>
        </div>
      )}

      {isEmptySearch ? (
        <EmptyState
          title="No matching files"
          description={`No files match "${searchQuery}".`}
          icon="search"
          className="border-0 rounded-none flex-1"
          action={{
            label: "Clear filter",
            onClick: onClearSearch,
          }}
        />
      ) : isEmptyDir && !currentPath ? (
        <EmptyState
          title="Empty Directory"
          description={
            isLiveState
              ? "No editable live data files found in this directory."
              : "No files found in this folder yet."
          }
          icon="folder"
          className="border-0 rounded-none flex-1"
          action={
            canMutateInTable ? (
              <div className="flex flex-wrap items-center justify-center gap-2">
                <button
                  type="button"
                  onClick={onOpenNewFile}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-card px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
                >
                  <Icon name="plus" size={14} />
                  New File
                </button>
                <button
                  type="button"
                  onClick={onTriggerUpload}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-medium text-accent-contrast-text hover:bg-accent-hover transition-colors cursor-pointer"
                >
                  <Icon name="upload" size={14} />
                  Upload File
                </button>
              </div>
            ) : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto flex-1 min-h-0 overflow-y-auto">
          <table className="w-full text-sm text-left">
            <thead className="sticky top-0 z-10 text-xs uppercase bg-surface-muted/90 backdrop-blur-xs text-text-muted border-b border-border-subtle tracking-wider font-semibold">
              <tr>
                {canMutateInTable && (
                  <th scope="col" className="w-10 px-4 py-2.5">
                    {showCheckboxes && (
                      <input
                        type="checkbox"
                        aria-label="Select all"
                        checked={isAllSelected}
                        onChange={onToggleSelectAll}
                        className="onx-checkbox"
                      />
                    )}
                  </th>
                )}
                <th scope="col" className="px-4 py-2.5">Name</th>
                <th scope="col" className="hidden md:table-cell px-4 py-2.5 w-40">Modified</th>
                <th scope="col" className="hidden sm:table-cell px-4 py-2.5 w-28 text-right">Size</th>
                <th scope="col" className="px-4 py-2.5 w-36 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {currentPath && (
                <tr className="hover:bg-surface-hover/50 transition-colors">
                  {canMutateInTable && <td className="w-10 px-4 py-2.5" />}
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      onClick={onNavigateUp}
                      className="flex items-center gap-2.5 cursor-pointer text-left focus:outline-hidden focus-visible:ring-1 focus-visible:ring-border-focus rounded font-medium text-text-primary hover:text-text-accent transition-colors"
                      aria-label="Navigate to parent directory"
                    >
                      <Icon name="folder" className="text-text-muted shrink-0" size={16} />
                      <span>..</span>
                    </button>
                  </td>
                  <td className="hidden md:table-cell px-4 py-2.5 text-text-muted">—</td>
                  <td className="hidden sm:table-cell px-4 py-2.5 text-right text-text-muted">—</td>
                  <td className="px-4 py-2.5 text-right" />
                </tr>
              )}

              {rows.map((file) => {
                const isImg = !isLiveState && !file.is_dir && isImageFile(file.name);
                const isBin = !file.is_dir && isBinaryFile(file.name);
                const isTextLike = !file.is_dir && !isBin && !isImg;
                const badge = getFileClassBadge(file, isLiveState, isAdvancedMode);
                const relativeMod = formatRelativeTime(file.modified_at);
                const exactMod = file.modified_at ? formatDateTime(file.modified_at) : undefined;
                const isRowReadOnly =
                  readOnly ||
                  (isLiveState ? file.writable === false : file.editable === false);

                const isRowSelectedInSplit = Boolean(activeFilePath && activeFilePath === file.path);

                return (
                  <tr
                    key={file.path}
                    className={`transition-colors ${
                      isRowSelectedInSplit
                        ? "bg-accent-primary/10"
                        : "hover:bg-surface-hover/50"
                    }`}
                  >
                    {canMutateInTable && (
                      <td className="w-10 px-4 py-2.5">
                        <input
                          type="checkbox"
                          aria-label={`Select ${file.name}`}
                          checked={selectedPaths.has(file.path)}
                          onChange={() => onToggleSelect(file.path)}
                          className="onx-checkbox"
                        />
                      </td>
                    )}

                    <td className="px-4 py-2.5 min-w-0">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <button
                          type="button"
                          className="flex items-center gap-2.5 cursor-pointer text-left focus:outline-hidden focus-visible:ring-1 focus-visible:ring-border-focus rounded min-w-0"
                          onClick={() => {
                            if (file.is_dir) {
                              onNavigateFolder(file);
                            } else if (isImg || isTextLike) {
                              onOpenFile(file);
                            } else if (!isLiveState) {
                              onDownload(file);
                            } else {
                              onOpenFile(file);
                            }
                          }}
                        >
                          <Icon
                            name={getFileIconName(file.name, file.is_dir)}
                            size={16}
                            className="text-text-muted shrink-0"
                          />
                          <span className="font-medium text-text-primary truncate hover:text-text-accent transition-colors">
                            {file.name}
                          </span>
                        </button>

                        {badge && (
                          <span
                            title={badge.title}
                            className={`hidden sm:inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium shrink-0 ${BADGE_TONE_CLASSES[badge.tone]}`}
                          >
                            {badge.label}
                          </span>
                        )}

                        {!file.is_dir && isRowReadOnly && !readOnly && (
                          <span
                            title={
                              isLiveState
                                ? "Read-only binary live-state file"
                                : isAdvancedMode
                                  ? "Read-only on this branch"
                                  : "Read-only file"
                            }
                            className="inline-flex items-center text-text-muted shrink-0"
                          >
                            <Icon name="lock" size={12} />
                          </span>
                        )}
                      </div>

                      {/* Mobile metadata subline */}
                      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-text-muted sm:hidden">
                        <span>{file.is_dir ? "Folder" : formatBytes(file.size)}</span>
                        {relativeMod && (
                          <>
                            <span>•</span>
                            <span>{relativeMod}</span>
                          </>
                        )}
                      </div>
                    </td>

                    <td
                      className="hidden md:table-cell px-4 py-2.5 whitespace-nowrap text-xs text-text-muted"
                      title={exactMod}
                    >
                      {relativeMod || "—"}
                    </td>

                    <td className="hidden sm:table-cell px-4 py-2.5 whitespace-nowrap text-right text-xs font-mono tabular-nums text-text-muted">
                      {file.is_dir ? "—" : formatBytes(file.size)}
                    </td>

                    <td className="px-4 py-2.5 text-right whitespace-nowrap">
                      <div className="inline-flex items-center justify-end gap-1">
                        {file.is_dir ? (
                          <>
                            <IconButton
                              icon="folder"
                              aria-label={`Open ${file.name}`}
                              title={`Open ${file.name}`}
                              size="sm"
                              variant="ghost"
                              className="text-text-muted hover:text-text-primary hover:bg-surface-muted"
                              onClick={() => onNavigateFolder(file)}
                            />
                            {canMutateInTable && (
                              <IconButton
                                icon="trash"
                                aria-label={`Delete ${file.name}`}
                                title={`Delete ${file.name}`}
                                size="sm"
                                variant="ghost"
                                className="text-text-muted hover:text-status-danger hover:bg-surface-muted"
                                onClick={() => onDelete(file)}
                              />
                            )}
                          </>
                        ) : (
                          <>
                            {!isLiveState && (
                              <IconButton
                                icon="download"
                                aria-label="Download"
                                title={`Download ${file.name}`}
                                size="sm"
                                variant="ghost"
                                className="text-text-muted hover:text-text-primary hover:bg-surface-muted"
                                onClick={() => onDownload(file)}
                              />
                            )}
                            {isImg && (
                              <IconButton
                                icon="eye"
                                aria-label={`Preview ${file.name}`}
                                title={`Preview ${file.name}`}
                                size="sm"
                                variant="ghost"
                                className="text-text-muted hover:text-text-primary hover:bg-surface-muted"
                                onClick={() => onOpenFile(file)}
                              />
                            )}
                            {isTextLike && (
                              isRowReadOnly ? (
                                <IconButton
                                  icon="eye"
                                  aria-label="View"
                                  title={`View ${file.name}`}
                                  size="sm"
                                  variant="ghost"
                                  className="text-text-muted hover:text-text-primary hover:bg-surface-muted"
                                  onClick={() => onOpenFile(file)}
                                />
                              ) : (
                                <IconButton
                                  icon="edit"
                                  aria-label="Edit"
                                  title={`Edit ${file.name}`}
                                  size="sm"
                                  variant="ghost"
                                  className="text-text-muted hover:text-text-primary hover:bg-surface-muted"
                                  onClick={() => onOpenFile(file)}
                                />
                              )
                            )}
                            {canMutateInTable && (
                              <IconButton
                                icon="trash"
                                aria-label="Delete"
                                title={`Delete ${file.name}`}
                                size="sm"
                                variant="ghost"
                                className="text-text-muted hover:text-status-danger hover:bg-surface-muted"
                                onClick={() => onDelete(file)}
                              />
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}

              {isEmptyDir && currentPath && (
                <tr>
                  <td colSpan={canMutateInTable ? 5 : 4} className="p-0">
                    <EmptyState
                      title="Empty Directory"
                      description={
                        isLiveState
                          ? "No live data files in this subfolder."
                          : "This folder is empty."
                      }
                      icon="folder"
                      className="border-0 rounded-none"
                      action={
                        canMutateInTable ? (
                          <div className="flex flex-wrap items-center justify-center gap-2">
                            <button
                              type="button"
                              onClick={onOpenNewFile}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-card px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
                            >
                              <Icon name="plus" size={14} />
                              New File
                            </button>
                            <button
                              type="button"
                              onClick={onTriggerUpload}
                              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-medium text-accent-contrast-text hover:bg-accent-hover transition-colors cursor-pointer"
                            >
                              <Icon name="upload" size={14} />
                              Upload File
                            </button>
                          </div>
                        ) : undefined
                      }
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          {totalFilteredCount > pageSize && (
            <div className="border-t border-border-subtle p-3">
              <Pagination
                totalItems={totalFilteredCount}
                pageSize={pageSize}
                page={currentPage}
                onPageChange={onPageChange}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};
