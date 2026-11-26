import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { Icon } from "@/components/ui/Icon";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ErrorState } from "@/components/ui/States";
import { CodeEditor } from "@/components/CodeEditor";
import { formatBytes } from "@/server_manager/utils/format";
import type { FileItem } from "@/server_manager/types";
import { extractApiErrorMessage, isImageFile } from "./filesUtils";

export interface FileEditorViewProps {
  serverId: string;
  editingFile: FileItem;
  activeBranch?: string;
  isLiveState: boolean;
  isReadOnly: boolean;
  displayedContent: string;
  isDirty: boolean;
  isContentLoading: boolean;
  contentError: unknown;
  isBinary: boolean;
  isSaving: boolean;
  reloadCommand: string;
  onReloadCommandChange: (cmd: string) => void;
  onChangeContent: (value: string) => void;
  onSave: () => void;
  onRetryLoad: () => void;
  onCloseEditor: () => void;
  onNavigateDirectory: (dirPath: string) => void;
  onDownload: (file: FileItem) => void;
  compact?: boolean;
}

type PendingNavigation =
  | { type: "close" }
  | { type: "dir"; dirPath: string };

export const FileEditorView: React.FC<FileEditorViewProps> = ({
  serverId,
  editingFile,
  activeBranch,
  isLiveState,
  isReadOnly,
  displayedContent,
  isDirty,
  isContentLoading,
  contentError,
  isBinary,
  isSaving,
  reloadCommand,
  onReloadCommandChange,
  onChangeContent,
  onSave,
  onRetryLoad,
  onCloseEditor,
  onNavigateDirectory,
  onDownload,
  compact = false,
}) => {
  const api = React.useMemo(() => createAuthenticatedApi(), []);
  const isImage = !isLiveState && isImageFile(editingFile.name);
  const [pixelated, setPixelated] = useState(true);
  const [imageDimensions, setImageDimensions] = useState<{ w: number; h: number } | null>(null);
  const [pendingNav, setPendingNav] = useState<PendingNavigation | null>(null);

  const imageQuery = useQuery({
    queryKey: [...queryKeys.files.content(serverId, editingFile.path, activeBranch), "image-preview"] as const,
    queryFn: () =>
      activeBranch
        ? api.downloadServerFile(serverId, editingFile.path, activeBranch)
        : api.downloadServerFile(serverId, editingFile.path),
    enabled: Boolean(serverId && editingFile.path && isImage),
  });

  const imageObjectUrl = React.useMemo(() => {
    if (!imageQuery.data) return null;
    return URL.createObjectURL(imageQuery.data);
  }, [imageQuery.data]);

  useEffect(() => {
    if (!imageObjectUrl) return;
    return () => {
      URL.revokeObjectURL(imageObjectUrl);
    };
  }, [imageObjectUrl]);

  const editorPathParts =
    editingFile.path && editingFile.path.includes("/")
      ? editingFile.path.split("/").filter(Boolean).slice(0, -1)
      : [];

  const requestClose = () => {
    if (isDirty && !isReadOnly) {
      setPendingNav({ type: "close" });
      return;
    }
    onCloseEditor();
  };

  const requestNavigateDir = (dirPath: string) => {
    if (isDirty && !isReadOnly) {
      setPendingNav({ type: "dir", dirPath });
      return;
    }
    onNavigateDirectory(dirPath);
  };

  const confirmDiscard = () => {
    const action = pendingNav;
    setPendingNav(null);
    if (!action) return;
    if (action.type === "close") {
      onCloseEditor();
    } else {
      onNavigateDirectory(action.dirPath);
    }
  };

  const isTooLargeError =
    contentError instanceof ApiError &&
    (contentError.status === 413 || contentError.code === "FILE_TOO_LARGE");

  const effectiveErrorMessage = contentError
    ? extractApiErrorMessage(contentError, "Unable to read file content")
    : "";

  return (
    <div className="flex flex-col flex-1 min-h-0 min-w-0 h-full bg-surface-card rounded-xl shadow-xs border border-border-subtle overflow-hidden">
      {/* Editor Header */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 p-4 border-b border-border-subtle bg-surface-card">
        <div className="flex items-center gap-3 min-w-0">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            icon="chevron-left"
            onClick={requestClose}
            aria-label="Back"
          />
          <div className="min-w-0">
            <nav
              aria-label="Editor breadcrumb"
              className="text-xs text-text-muted font-mono flex items-center gap-1.5 flex-wrap"
            >
              <button
                type="button"
                onClick={() => requestNavigateDir("")}
                className="hover:text-text-primary hover:underline cursor-pointer"
              >
                root
              </button>
              {editorPathParts.map((part, index) => {
                const pathUpTo = editorPathParts.slice(0, index + 1).join("/");
                return (
                  <span key={pathUpTo} className="flex items-center gap-1.5">
                    <span className="text-border-strong">/</span>
                    <button
                      type="button"
                      onClick={() => requestNavigateDir(pathUpTo)}
                      className="hover:text-text-primary hover:underline cursor-pointer"
                    >
                      {part}
                    </button>
                  </span>
                );
              })}
              <span className="text-border-strong">/</span>
              <span className="text-text-primary font-medium">{editingFile.name}</span>
            </nav>

            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-text-primary truncate">
                {isImage
                  ? `Preview: ${editingFile.name}`
                  : isReadOnly
                    ? `Viewing: ${editingFile.name}`
                    : `Editing: ${editingFile.name}`}
              </h2>
              {isDirty && !isReadOnly && !isImage && (
                <span
                  data-testid="editor-unsaved-badge"
                  className="inline-flex items-center gap-1.5 rounded-full border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[11px] font-medium text-status-warning"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-status-warning" />
                  Unsaved changes
                </span>
              )}
              {isReadOnly && !isImage && (
                <span
                  data-testid="editor-header-readonly-badge"
                  className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-muted"
                >
                  <Icon name="lock" size={11} />
                  Read-only
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={requestClose}
          >
            {isReadOnly || isImage ? "Close" : "Cancel"}
          </Button>

          {isImage && (
            <Button
              type="button"
              variant="primary"
              size="sm"
              icon="download"
              onClick={() => onDownload(editingFile)}
            >
              Download
            </Button>
          )}

          {!isImage && !isBinary && !isReadOnly && (
            <>
              {isLiveState && (
                <select
                  aria-label="RCON Reload Command"
                  value={reloadCommand}
                  onChange={(e) => onReloadCommandChange(e.target.value)}
                  className="rounded-lg border border-border-subtle hover:border-border-hover bg-surface-page px-2.5 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-1 focus:ring-border-focus"
                >
                  <option value="">Auto</option>
                  <option value="whitelist reload">whitelist reload</option>
                  <option value="minecraft:reload">minecraft:reload</option>
                  <option value="reload">reload</option>
                </select>
              )}
              <Button
                type="button"
                variant="primary"
                size="sm"
                icon="save"
                onClick={onSave}
                disabled={
                  !isDirty ||
                  isSaving ||
                  isContentLoading ||
                  Boolean(contentError)
                }
                loading={isSaving}
              >
                {isLiveState ? "Save Live State" : "Save"}
              </Button>
            </>
          )}

          {compact && (
            <button
              type="button"
              data-testid="editor-close-btn"
              aria-label="Close editor"
              onClick={requestClose}
              className="inline-flex items-center justify-center rounded-lg border border-border-subtle bg-surface-page p-1.5 text-text-muted hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
            >
              <Icon name="x" size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Editor / Preview Body */}
      <div className="flex-1 min-h-0 overflow-hidden p-4 flex flex-col">
        {isImage ? (
          imageQuery.isLoading ? (
            <div className="flex-1 min-h-0 flex items-center justify-center text-sm text-text-muted">
              Loading image preview...
            </div>
          ) : imageQuery.error || !imageObjectUrl ? (
            <div className="flex-1 min-h-0 overflow-y-auto">
              <ErrorState
                title="Failed to load image"
                message={extractApiErrorMessage(imageQuery.error, "Unable to load image preview")}
                onRetry={() => void imageQuery.refetch()}
              />
            </div>
          ) : (
            <div
              data-testid="image-preview-card"
              className="flex-1 min-h-0 overflow-y-auto flex flex-col items-center justify-center gap-4 rounded-xl border border-border-subtle bg-surface-page p-6"
            >
              <div className="flex items-center justify-center rounded-xl border border-border-default bg-surface-muted p-6 min-w-[200px] min-h-[200px]">
                <img
                  src={imageObjectUrl}
                  alt={editingFile.name}
                  onLoad={(e) => {
                    setImageDimensions({
                      w: e.currentTarget.naturalWidth,
                      h: e.currentTarget.naturalHeight,
                    });
                  }}
                  style={{ imageRendering: pixelated ? "pixelated" : "auto" }}
                  className="max-h-[360px] max-w-full object-contain rounded shadow-xs"
                />
              </div>

              <div className="flex flex-wrap items-center justify-center gap-3 text-xs text-text-muted">
                {imageDimensions && (
                  <span className="font-mono">
                    {imageDimensions.w} × {imageDimensions.h} px
                  </span>
                )}
                {imageQuery.data && (
                  <>
                    <span>•</span>
                    <span className="font-mono">{formatBytes(imageQuery.data.size)}</span>
                  </>
                )}
                <span>•</span>
                <label className="inline-flex items-center gap-1.5 cursor-pointer text-text-secondary">
                  <input
                    type="checkbox"
                    checked={pixelated}
                    onChange={(e) => setPixelated(e.target.checked)}
                    className="onx-checkbox"
                  />
                  <span>Crisp pixels</span>
                </label>
              </div>
            </div>
          )
        ) : isContentLoading ? (
          <div className="flex-1 min-h-0 flex items-center justify-center text-sm text-text-muted">
            Loading content...
          </div>
        ) : contentError ? (
          isTooLargeError ? (
            <div className="flex-1 min-h-0 overflow-y-auto flex flex-col items-center justify-center text-center p-8 bg-surface-page border border-border-subtle rounded-xl gap-3">
              <Icon name="alert" size={44} className="text-status-warning" />
              <div>
                <h3 className="text-base font-semibold text-text-primary">
                  File Too Large for Browser Editor
                </h3>
                <p className="mt-1 text-sm text-text-muted max-w-md">{effectiveErrorMessage}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  icon="download"
                  onClick={() => onDownload(editingFile)}
                >
                  Download File
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={onCloseEditor}
                >
                  Back to Files
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-4">
              <ErrorState
                title="Failed to load file"
                message={effectiveErrorMessage}
                onRetry={onRetryLoad}
              />
              <div className="flex justify-center">
                <Button type="button" variant="secondary" size="sm" onClick={onCloseEditor}>
                  Back to Files
                </Button>
              </div>
            </div>
          )
        ) : isBinary ? (
          <div className="flex-1 min-h-0 overflow-y-auto flex flex-col items-center justify-center text-center p-8 bg-surface-page border border-border-subtle rounded-xl">
            <Icon name="file" size={48} className="text-text-muted mb-3" />
            <h3 className="text-base font-semibold text-text-primary mb-1">Binary File</h3>
            <p className="text-sm text-text-muted mb-4 max-w-sm">
              This file cannot be displayed or edited as text because it contains binary data.
            </p>
            <Button
              type="button"
              variant="primary"
              icon="download"
              onClick={() => onDownload(editingFile)}
            >
              Download File
            </Button>
          </div>
        ) : (
          <CodeEditor
            value={displayedContent}
            filename={editingFile.name}
            readOnly={isReadOnly}
            onChange={onChangeContent}
            onSave={isDirty && !isReadOnly ? onSave : undefined}
            className="flex-1 min-h-0 h-full"
          />
        )}
      </div>

      <ConfirmDialog
        open={pendingNav !== null}
        title="Discard unsaved changes?"
        description={`You have unsaved edits to "${editingFile.name}". Leaving now will discard them.`}
        confirmLabel="Discard"
        cancelLabel="Keep Editing"
        variant="warning"
        onConfirm={confirmDiscard}
        onCancel={() => setPendingNav(null)}
      />
    </div>
  );
};
