import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { LoadingBar } from "@/components/ui/LoadingBar";
import { ErrorState, ForbiddenState } from "@/components/ui/States";
import { PageSkeleton } from "@/components/Skeleton";
import { FilesToolbar } from "@/server_manager/components/files/FilesToolbar";
import { FilesTable } from "@/server_manager/components/files/FilesTable";
import { FileEditorView } from "@/server_manager/components/files/FileEditorView";
import { LogsTabView } from "@/server_manager/components/files/LogsTabView";
import { LogFileViewer } from "@/server_manager/components/files/LogFileViewer";
import { NewFileModal } from "@/server_manager/components/files/NewFileModal";
import { NewFolderModal } from "@/server_manager/components/files/NewFolderModal";
import { CommitBranchModal } from "@/server_manager/components/files/CommitBranchModal";
import {
  extractApiErrorMessage,
  FILES_SPLIT_KEYBOARD_STEP,
  MAX_FILES_SPLIT_RATIO,
  MIN_FILES_SPLIT_RATIO,
} from "@/server_manager/components/files/filesUtils";
import {
  FILES_PAGE_SIZE,
  useServerFilesController,
} from "@/server_manager/components/files/useServerFilesController";

export function ServerFilesPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const splitContainerRef = useRef<HTMLDivElement>(null);
  const [isResizingSplit, setIsResizingSplit] = useState(false);
  const c = useServerFilesController();
  const { updateSplitRatio } = c;

  useEffect(() => {
    if (!isResizingSplit) return;

    const prevUserSelect = document.body.style.userSelect;
    const prevCursor = document.body.style.cursor;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";

    const handlePointerMove = (ev: PointerEvent) => {
      const container = splitContainerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      if (rect.width <= 0) return;
      const rawPercent = ((ev.clientX - rect.left) / rect.width) * 100;
      updateSplitRatio(rawPercent);
    };

    const handlePointerEnd = () => {
      setIsResizingSplit(false);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerEnd);
    window.addEventListener("pointercancel", handlePointerEnd);

    return () => {
      document.body.style.userSelect = prevUserSelect;
      document.body.style.cursor = prevCursor;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerEnd);
      window.removeEventListener("pointercancel", handlePointerEnd);
    };
  }, [isResizingSplit, updateSplitRatio]);

  if (!c.canAccessFiles) {
    return (
      <ForbiddenState
        title="Access Denied"
        message="You do not have permission to view or manage files on this server."
        onBack={() => navigate(`/servers/${c.serverId}/console`)}
      />
    );
  }

  const activeListQuery = c.isLogsView
    ? c.logsQuery
    : c.isLiveState
      ? c.liveStateQuery
      : c.filesQuery;
  if (activeListQuery.isLoading && !activeListQuery.data) return <PageSkeleton />;
  if (activeListQuery.error) {
    if (activeListQuery.error instanceof ApiError && activeListQuery.error.status === 403) {
      return (
        <ForbiddenState
          title="Access Denied"
          message={extractApiErrorMessage(activeListQuery.error, "Permission denied")}
          onBack={() => navigate(`/servers/${c.serverId}/console`)}
        />
      );
    }
    return (
      <ErrorState
        message={extractApiErrorMessage(activeListQuery.error, "Failed to load files")}
        onRetry={() => void activeListQuery.refetch()}
      />
    );
  }

  const renderEditorOrLogViewer = (compact: boolean) => {
    if (!c.editingFile) return null;
    if (c.activeEditorIsLogs) {
      return (
        <LogFileViewer
          file={c.editingFile}
          contentResponse={c.logContentQuery.data}
          isLoading={c.logContentQuery.isLoading}
          error={c.logContentQuery.error}
          compact={compact}
          onRetry={() => void c.logContentQuery.refetch()}
          onClose={c.handleCloseEditor}
          onDownload={(file) => c.handleDownload(file, "logs")}
        />
      );
    }
    const activeError = c.activeEditorIsLiveState
      ? c.liveStateContentQuery.error
      : c.fileContentQuery.error;
    const activeLoading = c.activeEditorIsLiveState
      ? c.liveStateContentQuery.isLoading
      : c.fileContentQuery.isLoading;
    return (
      <FileEditorView
        serverId={c.serverId!}
        editingFile={c.editingFile}
        activeBranch={c.activeBranch}
        isLiveState={c.activeEditorIsLiveState}
        isReadOnly={c.activeEditorReadOnly}
        displayedContent={c.displayedContent}
        isDirty={c.isDirty}
        isContentLoading={activeLoading}
        contentError={activeError}
        isBinary={c.isBinary}
        isSaving={
          c.activeEditorIsLiveState
            ? c.liveStateSaveMutation.isPending
            : c.saveMutation.isPending
        }
        reloadCommand={c.reloadCommand}
        onReloadCommandChange={c.setReloadCommand}
        onChangeContent={(val) => {
          c.setEditContent(val);
          c.setUserEdited(true);
        }}
        onSave={() =>
          c.activeEditorIsLiveState
            ? c.liveStateSaveMutation.mutate()
            : c.saveMutation.mutate()
        }
        onRetryLoad={() =>
          void (c.activeEditorIsLiveState
            ? c.liveStateContentQuery.refetch()
            : c.fileContentQuery.refetch())
        }
        onCloseEditor={c.handleCloseEditor}
        onNavigateDirectory={c.navigateToDirectory}
        onDownload={(file) =>
          c.handleDownload(file, c.activeEditorIsLiveState ? "live-state" : "branch")
        }
        compact={compact}
      />
    );
  };

  if (!c.splitView && c.editingFile) {
    return (
      <div className="flex flex-col min-h-0 h-[clamp(440px,calc(100dvh-16.5rem),680px)]">
        {renderEditorOrLogViewer(false)}
      </div>
    );
  }

  const renderLeftPaneContent = (embedded: boolean) => {
    if (c.isLogsView) {
      return (
        <LogsTabView
          entries={c.logsQuery.data ?? []}
          isLoading={c.logsQuery.isLoading}
          isFetching={c.logsQuery.isFetching}
          activeBranch={c.activeBranch}
          isAdvancedMode={c.isAdvancedMode}
          selectedPath={c.splitView ? (c.editingFile?.path ?? null) : null}
          splitView={c.splitView}
          embedded={embedded}
          onToggleSplitView={() => c.setSplitView((prev) => !prev)}
          onRefresh={() => void c.logsQuery.refetch()}
          onOpenLog={(item) => c.openFileEditor(item, "logs")}
          onDownload={(item) => c.handleDownload(item, "logs")}
        />
      );
    }

    return (
      <>
        {c.isLiveState && (
          <div
            data-testid="live-state-banner"
            className={`shrink-0 text-xs text-text-secondary space-y-2 ${
              embedded
                ? "border-b border-border-subtle bg-surface-card px-3 py-2"
                : "rounded-xl border border-border-subtle bg-surface-card px-4 py-2.5 shadow-2xs"
            }`}
          >
            <p>
              Live Data edits apply directly to runtime files on the live server directory (RCON flush + reload when running; atomic write when stopped).
            </p>
            {c.isNonMainLiveStateReadOnly && (
              <p
                data-testid="files-non-main-class-c-banner"
                className="rounded-lg border border-status-warning-border bg-status-warning-bg px-3 py-2 text-xs font-medium text-status-warning"
              >
                Live Data belongs to <code className="font-mono">main</code>. Viewing branch &ldquo;{c.activeBranch}&rdquo; is read-only here; switch to <code className="font-mono">main</code> to modify live world files.
              </p>
            )}
          </div>
        )}

        {!c.isLiveState && c.filesQuery.isFetching && <LoadingBar />}

        {!c.isLiveState && c.activeBranch && (
          <div
            data-testid="branch-context-banner"
            className={`shrink-0 flex flex-wrap items-center gap-2 text-xs text-text-secondary ${
              embedded
                ? "border-b border-border-subtle bg-surface-card px-3 py-2"
                : "rounded-xl border border-border-subtle bg-surface-card px-4 py-2.5 shadow-2xs"
            }`}
          >
            <Icon name="backup" size={14} className="text-text-muted" />
            <span>Branch: <strong className="font-mono text-text-primary">{c.activeBranch}</strong></span>
            <span className="text-border-subtle">•</span>
            {c.readOnlyBranch ? (
              <span className="text-status-warning font-medium">
                Viewing main (read-only). Switch to a working branch in the header to edit files.
              </span>
            ) : (
              <span>Changes stay uncommitted until Save &amp; Commit.</span>
            )}
          </div>
        )}

        <FilesToolbar
          breadcrumbs={c.breadcrumbs}
          currentPath={c.currentPath}
          onNavigatePath={c.updateCurrentPath}
          onCopyPath={c.copyCurrentPath}
          copiedPath={c.copiedPath}
          filteredCount={c.filteredAndSorted.length}
          searchQuery={c.searchQuery}
          onSearchChange={(q) => { c.setSearchQuery(q); c.setCurrentPage(1); }}
          sortField={c.sortField}
          sortDirection={c.sortDirection}
          onSortChange={(field, dir) => { c.setSortField(field); c.setSortDirection(dir); c.setCurrentPage(1); }}
          isLiveState={c.isLiveState}
          readOnly={c.readOnlyBranch}
          activeBranch={c.activeBranch}
          selectedCount={c.selectedPaths.size}
          onClearSelection={() => c.setSelectedPaths(new Set())}
          onBulkDelete={() => c.setShowBulkDelete(true)}
          bulkDeletePending={c.bulkDeleteMutation.isPending}
          onOpenNewFile={() => c.setShowNewFile(true)}
          onOpenNewFolder={() => c.setShowNewFolder(true)}
          onTriggerUpload={() => fileInputRef.current?.click()}
          uploadPending={c.uploadBatchMutation.isPending}
          uploadProgress={c.uploadProgress}
          onOpenCommit={() => c.setShowCommitDialog(true)}
          splitView={c.splitView}
          onToggleSplitView={() => c.setSplitView((prev) => !prev)}
          embedded={embedded}
        />

        <FilesTable
          rows={c.paginatedRows}
          totalFilteredCount={c.filteredAndSorted.length}
          pageSize={FILES_PAGE_SIZE}
          currentPage={c.currentPage}
          onPageChange={c.setCurrentPage}
          currentPath={c.currentPath}
          searchQuery={c.searchQuery}
          onClearSearch={() => { c.setSearchQuery(""); c.setCurrentPage(1); }}
          isLiveState={c.isLiveState}
          readOnly={c.isLiveState ? c.isNonMainLiveStateReadOnly : c.readOnlyBranch}
          isAdvancedMode={c.isAdvancedMode}
          activeBranch={c.activeBranch}
          dropBlockedReason={c.dropBlockedReason}
          activeFilePath={c.splitView ? (c.editingFile?.path ?? null) : null}
          embedded={embedded}
          selectedPaths={c.selectedPaths}
          onToggleSelect={(path) => {
            c.setSelectedPaths((prev) => {
              const next = new Set(prev);
              if (next.has(path)) next.delete(path); else next.add(path);
              return next;
            });
          }}
          onToggleSelectAll={() => c.setSelectedPaths(c.isAllSelected ? new Set() : new Set(c.allSelectablePaths))}
          isAllSelected={c.isAllSelected}
          onNavigateUp={() => {
            if (!c.currentPath) return;
            const parts = c.currentPath.split("/").filter(Boolean);
            parts.pop();
            c.updateCurrentPath(parts.join("/"));
          }}
          onNavigateFolder={(row) => c.updateCurrentPath(c.isLiveState ? row.path : (c.currentPath ? `${c.currentPath}/${row.name}` : row.name))}
          onOpenFile={(row) => c.openFileEditor(row, c.viewMode)}
          onDownload={(row) => c.handleDownload(row, c.isLiveState ? "live-state" : "branch")}
          onDelete={c.setFileToDelete}
          onOpenNewFile={() => c.setShowNewFile(true)}
          onTriggerUpload={() => fileInputRef.current?.click()}
          onDropFiles={c.handleUploadFiles}
        />
      </>
    );
  };

  return (
    <div className="flex flex-col flex-1 min-h-0 space-y-4">
      <input
        type="file"
        aria-label="Upload file"
        multiple
        ref={fileInputRef}
        className="hidden"
        onChange={(e) => {
          const selected = e.target.files ? Array.from(e.target.files) : [];
          if (selected.length > 0) c.handleUploadFiles(selected);
          e.target.value = "";
        }}
      />

      {c.showViewSwitcher && (
        <div
          data-testid="files-view-switcher"
          className="inline-flex flex-wrap self-start rounded-xl border border-border-subtle bg-surface-card p-1 shadow-2xs gap-1"
        >
          {c.isAdvancedMode ? (
            <>
              <button
                type="button"
                data-testid="files-tab-configs"
                onClick={() => c.switchView("branch")}
                className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors cursor-pointer ${
                  c.viewMode === "branch"
                    ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                    : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                }`}
              >
                Configs
              </button>
              <button
                type="button"
                data-testid="files-tab-live-state"
                onClick={() => c.switchView("live-state")}
                className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors cursor-pointer ${
                  c.viewMode === "live-state"
                    ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                    : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                }`}
              >
                Live Data
              </button>
            </>
          ) : (
            <button
              type="button"
              data-testid="files-tab-all"
              onClick={() => c.switchView("branch")}
              className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors cursor-pointer ${
                c.viewMode === "branch"
                  ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
              }`}
            >
              All Files
            </button>
          )}
          <button
            type="button"
            data-testid="files-tab-logs"
            onClick={() => c.switchView("logs")}
            className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors cursor-pointer ${
              c.viewMode === "logs"
                ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            Logs &amp; Crashes
          </button>
        </div>
      )}

      {c.splitView ? (
        <div
          ref={splitContainerRef}
          data-testid="files-split-workspace"
          className={`flex flex-col lg:flex-row gap-4 lg:gap-0 min-w-0 min-h-0 h-[clamp(440px,calc(100dvh-16.5rem),680px)] ${
            isResizingSplit ? "select-none" : ""
          }`}
        >
          <div
            data-testid="files-split-left-pane"
            style={{ width: `${c.splitRatio}%` }}
            className="flex flex-col min-h-0 min-w-0 max-lg:!w-full lg:shrink-0 overflow-hidden rounded-xl border border-border-subtle bg-surface-card shadow-xs"
          >
            {renderLeftPaneContent(true)}
          </div>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize file explorer and editor panes"
            aria-valuenow={Math.round(c.splitRatio)}
            aria-valuemin={MIN_FILES_SPLIT_RATIO}
            aria-valuemax={MAX_FILES_SPLIT_RATIO}
            tabIndex={0}
            title="Drag to resize panes · Double-click to reset"
            onPointerDown={(e) => {
              if (e.button !== 0) return;
              e.preventDefault();
              setIsResizingSplit(true);
            }}
            onDoubleClick={c.resetSplitRatio}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") {
                e.preventDefault();
                c.updateSplitRatio((r) => r - FILES_SPLIT_KEYBOARD_STEP);
              } else if (e.key === "ArrowRight") {
                e.preventDefault();
                c.updateSplitRatio((r) => r + FILES_SPLIT_KEYBOARD_STEP);
              } else if (e.key === "Home") {
                e.preventDefault();
                c.resetSplitRatio();
              }
            }}
            className="hidden lg:flex w-3 -mx-0.5 cursor-col-resize select-none items-center justify-center group shrink-0 focus-visible:outline-hidden"
          >
            <div
              className={`w-1 h-10 rounded-full transition-colors ${
                isResizingSplit
                  ? "bg-accent-primary"
                  : "bg-border-subtle group-hover:bg-accent-primary group-active:bg-accent-primary group-focus-visible:bg-accent-primary"
              }`}
            />
          </div>
          <div
            data-testid="files-split-right-pane"
            className="flex flex-col flex-1 min-h-0 min-w-0 overflow-hidden"
          >
            {c.editingFile ? (
              renderEditorOrLogViewer(true)
            ) : (
              <div
                data-testid="files-split-placeholder"
                className="flex flex-1 min-h-0 flex-col items-center justify-center rounded-xl border border-border-subtle bg-surface-card p-8 text-center shadow-xs"
              >
                <Icon name="columns" size={32} className="mb-3 text-text-muted" />
                <p className="text-sm font-medium text-text-primary">No file selected</p>
                <p className="mt-1 text-xs text-text-muted max-w-xs">
                  Select a file or log on the left to inspect or edit it here
                </p>
              </div>
            )}
          </div>
        </div>
      ) : (
        renderLeftPaneContent(false)
      )}

      <NewFileModal
        key={c.showNewFile ? "new-file-open" : "new-file-closed"}
        open={c.showNewFile}
        currentPath={c.currentPath}
        isPending={c.newFileMutation.isPending}
        onClose={() => c.setShowNewFile(false)}
        onCreate={(fileName, initialContent) => c.newFileMutation.mutate({ fileName, initialContent })}
      />
      <NewFolderModal
        key={c.showNewFolder ? "new-folder-open" : "new-folder-closed"}
        open={c.showNewFolder}
        currentPath={c.currentPath}
        isPending={c.mkdirMutation.isPending}
        onClose={() => c.setShowNewFolder(false)}
        onCreate={(folderName) => c.mkdirMutation.mutate(folderName)}
      />
      <CommitBranchModal
        key={c.showCommitDialog ? "commit-open" : "commit-closed"}
        open={c.showCommitDialog}
        activeBranch={c.activeBranch}
        isPending={c.commitMutation.isPending}
        onClose={() => c.setShowCommitDialog(false)}
        onCommit={(message) => c.commitMutation.mutate(message)}
      />

      <ConfirmDialog
        open={c.pendingOverwrite !== null}
        title="Overwrite Existing Files?"
        description={c.pendingOverwrite ? `${c.pendingOverwrite.collisions.join(", ")} already exist(s) in this folder. Overwrite?` : undefined}
        confirmLabel="Overwrite"
        variant="warning"
        isPending={c.uploadBatchMutation.isPending}
        onConfirm={() => {
          if (!c.pendingOverwrite) return;
          const toUpload = c.pendingOverwrite.files;
          c.setPendingOverwrite(null);
          c.uploadBatchMutation.mutate(toUpload);
        }}
        onCancel={() => c.setPendingOverwrite(null)}
      />
      <ConfirmDialog
        open={c.showBulkDelete}
        title="Delete Selected Items"
        description={`Are you sure you want to delete ${c.selectedPaths.size} selected item(s)? This action cannot be undone.`}
        confirmLabel={c.bulkDeleteMutation.isPending ? "Deleting..." : "Delete"}
        variant="danger"
        isPending={c.bulkDeleteMutation.isPending}
        onConfirm={() => c.bulkDeleteMutation.mutate(Array.from(c.selectedPaths))}
        onCancel={() => { if (!c.bulkDeleteMutation.isPending) c.setShowBulkDelete(false); }}
      />
      <ConfirmDialog
        open={c.pendingFileSwitch !== null || c.pendingViewSwitch !== null}
        title="Discard unsaved changes?"
        description={
          c.editingFile
            ? c.pendingViewSwitch !== null
              ? `You have unsaved edits to "${c.editingFile.name}". Switching views will discard them.`
              : `You have unsaved edits to "${c.editingFile.name}". Switching files will discard them.`
            : undefined
        }
        confirmLabel="Discard"
        cancelLabel="Keep Editing"
        variant="warning"
        onConfirm={() => {
          if (c.pendingViewSwitch !== null) c.confirmViewSwitch();
          else c.confirmFileSwitch();
        }}
        onCancel={() => {
          c.cancelViewSwitch();
          c.cancelFileSwitch();
        }}
      />
      <ConfirmDialog
        open={c.fileToDelete !== null}
        title={c.fileToDelete?.is_dir ? "Delete Folder" : "Delete File"}
        description={`Are you sure you want to delete ${c.fileToDelete?.name}? ${c.fileToDelete?.is_dir ? "All contents will be permanently deleted. " : ""}This action cannot be undone.`}
        confirmLabel={c.deleteMutation.isPending ? "Deleting..." : "Delete"}
        variant="danger"
        isPending={c.deleteMutation.isPending}
        onConfirm={() => c.fileToDelete && c.deleteMutation.mutate(c.fileToDelete.path)}
        onCancel={() => { if (!c.deleteMutation.isPending) c.setFileToDelete(null); }}
      />
    </div>
  );
}
