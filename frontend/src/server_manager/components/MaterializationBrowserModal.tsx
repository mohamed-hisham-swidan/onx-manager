import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { CodeEditor } from "@/components/CodeEditor";
import { toast } from "@/stores/toastStore";
import type {
  MaterializationListItemResponse,
  MaterializationTreeEntry,
  RevisionType,
} from "@/server_manager/types";

const NON_EDITABLE_EXTENSIONS = new Set([
  "dat", "mca", "mcr", "sqlite", "db", "nbt", "jar", "zip", "tar", "gz", "png", "jpg", "jpeg", "gif", "ico", "class",
]);

function isBinaryFile(fileName: string): boolean {
  const ext = fileName.split(".").pop()?.toLowerCase();
  return !!ext && NON_EDITABLE_EXTENSIONS.has(ext);
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

interface MaterializationBrowserModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  initialRevision?: { revision_type: RevisionType; revision_ref: string };
}

export function MaterializationBrowserModal({
  isOpen,
  onClose,
  serverId,
  initialRevision,
}: MaterializationBrowserModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [materializations, setMaterializations] = useState<MaterializationListItemResponse[]>([]);
  const [activeMatId, setActiveMatId] = useState<string | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isTogglingMode, setIsTogglingMode] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const isDeletingRef = useRef(false);
  const [isConfirmDeleteOpen, setIsConfirmDeleteOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Creation form state
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newRevisionType, setNewRevisionType] = useState<RevisionType>(initialRevision?.revision_type || "branch");
  const [newRevisionRef, setNewRevisionRef] = useState(initialRevision?.revision_ref || "main");

  // Tree & file navigation state
  const [treeEntries, setTreeEntries] = useState<MaterializationTreeEntry[]>([]);
  const [isLoadingTree, setIsLoadingTree] = useState(false);
  const [currentDir, setCurrentDir] = useState<string>("");
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const [isSavingFile, setIsSavingFile] = useState(false);
  const [fileDirty, setFileDirty] = useState(false);

  // React 19 pattern: track open transition
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setError(null);
      setIsConfirmDeleteOpen(false);
      setSelectedFilePath(null);
      setFileContent("");
      setFileDirty(false);
      setCurrentDir("");
      if (initialRevision) {
        setNewRevisionType(initialRevision.revision_type);
        setNewRevisionRef(initialRevision.revision_ref);
      }
    }
  }

  // Load materializations list
  const loadMaterializations = useCallback(async () => {
    setIsLoadingList(true);
    setError(null);
    try {
      const data = await api.getMaterializations(serverId);
      setMaterializations(data);
      if (data.length > 0 && (!activeMatId || !data.some((m) => m.id === activeMatId))) {
        setActiveMatId(data[0].id);
      } else if (data.length === 0) {
        setActiveMatId(null);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load worktrees.";
      setError(msg);
    } finally {
      setIsLoadingList(false);
    }
  }, [api, serverId, activeMatId]);

  useEffect(() => {
    let alive = true;
    if (isOpen) {
      void Promise.resolve().then(() => {
        if (alive) {
          loadMaterializations();
        }
      });
    }
    return () => {
      alive = false;
    };
  }, [isOpen, loadMaterializations]);

  const activeMat = useMemo(() => {
    return materializations.find((m) => m.id === activeMatId) || null;
  }, [materializations, activeMatId]);

  // Load tree entries for active materialization
  const loadTree = useCallback(async (matId: string) => {
    setIsLoadingTree(true);
    setError(null);
    try {
      const resp = await api.getMaterializationTree(serverId, matId);
      setTreeEntries(resp.entries || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load worktree tree.";
      setError(msg);
      setTreeEntries([]);
    } finally {
      setIsLoadingTree(false);
    }
  }, [api, serverId]);

  useEffect(() => {
    let alive = true;
    if (activeMatId) {
      void Promise.resolve().then(() => {
        if (alive) {
          loadTree(activeMatId);
          setSelectedFilePath(null);
          setFileContent("");
          setFileDirty(false);
          setCurrentDir("");
        }
      });
    } else {
      void Promise.resolve().then(() => {
        if (alive) {
          setTreeEntries([]);
        }
      });
    }
    return () => {
      alive = false;
    };
  }, [activeMatId, loadTree]);

  // Load file content when selected
  const handleSelectFile = async (path: string) => {
    if (!activeMatId) return;
    if (isBinaryFile(path)) {
      setSelectedFilePath(path);
      setFileContent("");
      setFileDirty(false);
      return;
    }
    setIsLoadingFile(true);
    setError(null);
    try {
      const resp = await api.getMaterializationFile(serverId, activeMatId, path);
      setSelectedFilePath(path);
      setFileContent(resp.content || "");
      setFileDirty(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to read file.";
      setError(msg);
    } finally {
      setIsLoadingFile(false);
    }
  };

  const handleSaveFile = async () => {
    if (!activeMatId || !selectedFilePath) return;
    setIsSavingFile(true);
    setError(null);
    try {
      await api.writeMaterializationFile(serverId, activeMatId, selectedFilePath, fileContent);
      setFileDirty(false);
      toast("success", "File Saved", `Saved changes to ${selectedFilePath.split("/").pop()}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save file.";
      setError(msg);
    } finally {
      setIsSavingFile(false);
    }
  };

  const handleToggleMode = async () => {
    if (!activeMat) return;
    const targetMode = activeMat.mode === "readonly";
    setIsTogglingMode(true);
    setError(null);
    try {
      await api.setMaterializationMode(serverId, activeMat.id, targetMode);
      toast(
        "success",
        "Mode Updated",
        `Worktree '${activeMat.id}' set to ${targetMode ? "editable" : "readonly"}`
      );
      loadMaterializations();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to change worktree mode.";
      setError(msg);
    } finally {
      setIsTogglingMode(false);
    }
  };

  const handleDeleteMaterialization = async () => {
    if (!activeMat || isDeletingRef.current || isDeleting) return;
    isDeletingRef.current = true;
    setIsDeleting(true);
    setError(null);
    try {
      await api.deleteMaterialization(serverId, activeMat.id);
      toast("success", "Worktree Deleted", `Worktree '${activeMat.id}' removed.`);
      setIsConfirmDeleteOpen(false);
      loadMaterializations();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete worktree.";
      setError(msg);
      setIsConfirmDeleteOpen(false);
    } finally {
      isDeletingRef.current = false;
      setIsDeleting(false);
    }
  };

  const handleCreateMaterialization = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRevisionRef.trim()) return;
    setIsCreating(true);
    try {
      const resp = await api.createMaterialization(serverId, {
        revision_type: newRevisionType,
        ref: newRevisionRef.trim(),
      });
      const createdId = resp.materialization_id || resp.id || "";
      toast("success", "Worktree Created", `Materialized snapshot created (${createdId})`);
      setShowCreateForm(false);
      await loadMaterializations();
      if (createdId) setActiveMatId(createdId);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to materialize worktree.";
      setError(msg);
    } finally {
      setIsCreating(false);
    }
  };

  const isBusy = isSavingFile || isCreating || isDeleting;

  const handleClose = () => {
    if (isBusy) return;
    onClose();
  };

  // Compute directory contents based on currentDir
  const currentEntries = useMemo(() => {
    const prefix = currentDir ? (currentDir.endsWith("/") ? currentDir : `${currentDir}/`) : "";
    const itemsMap = new Map<string, { name: string; path: string; is_dir: boolean; size_bytes: number }>();

    for (const entry of treeEntries) {
      if (!entry.path.startsWith(prefix)) continue;
      const relative = entry.path.slice(prefix.length);
      if (!relative) continue;

      const slashIndex = relative.indexOf("/");
      if (slashIndex !== -1) {
        // It's a directory component under prefix
        const dirName = relative.slice(0, slashIndex);
        const dirPath = prefix + dirName;
        if (!itemsMap.has(dirName)) {
          itemsMap.set(dirName, {
            name: dirName,
            path: dirPath,
            is_dir: true,
            size_bytes: 0,
          });
        }
      } else {
        // Direct child entry
        itemsMap.set(relative, {
          name: relative,
          path: entry.path,
          is_dir: Boolean(entry.is_dir ?? (entry.classification === "directory")),
          size_bytes: entry.size_bytes,
        });
      }
    }

    return Array.from(itemsMap.values()).sort((a, b) => {
      if (a.is_dir && !b.is_dir) return -1;
      if (!a.is_dir && b.is_dir) return 1;
      return a.name.localeCompare(b.name);
    });
  }, [treeEntries, currentDir]);

  // Breadcrumbs
  const breadcrumbs = useMemo(() => {
    if (!currentDir) return [];
    const parts = currentDir.split("/").filter(Boolean);
    return parts.map((part, idx) => ({
      name: part,
      path: parts.slice(0, idx + 1).join("/"),
    }));
  }, [currentDir]);

  return (
    <>
      <Modal
        open={isOpen}
        onClose={handleClose}
        title="Worktree Materialization Explorer"
      ariaLabel="Worktree Materialization Explorer"
      description="Explore materialized commit worktree snapshots in isolated workspaces"
      size="full"
      className="max-w-6xl h-[90vh]"
      bodyClassName="flex flex-col overflow-hidden"
      closeOnBackdrop={!isBusy}
      closeOnEscape={!isBusy}
      closeButtonAriaLabel="Close modal"
    >
      <div className="flex-1 flex flex-col min-h-0 space-y-4">
        {/* Error Alert */}
        {error && (
          <div role="alert" className="flex items-center gap-2 rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger">
            <Icon name="alert" size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              aria-label="Dismiss error"
              className="text-status-danger hover:opacity-80 transition-opacity"
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        )}

        {/* Create Materialization Drawer */}
        {showCreateForm && (
          <form
            onSubmit={handleCreateMaterialization}
            className="flex flex-wrap items-end gap-3 p-4 bg-surface-card border border-border-default rounded-lg animate-fade-in"
          >
            <div>
              <label htmlFor="mat-revision-type" className="block text-xs font-medium text-text-secondary mb-1">
                Revision Type
              </label>
              <select
                id="mat-revision-type"
                value={newRevisionType}
                onChange={(e) => setNewRevisionType(e.target.value as RevisionType)}
                className="text-xs bg-surface-card border border-border-default text-text-primary rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-accent-primary focus:outline-none"
              >
                <option value="branch">Branch</option>
                <option value="commit">Commit</option>
                <option value="tag">Tag</option>
              </select>
            </div>
            <div className="flex-1 min-w-[200px]">
              <label htmlFor="mat-revision-ref" className="block text-xs font-medium text-text-secondary mb-1">
                Revision Ref (Branch / Commit ID / Tag)
              </label>
              <input
                id="mat-revision-ref"
                type="text"
                value={newRevisionRef}
                onChange={(e) => setNewRevisionRef(e.target.value)}
                placeholder="e.g. main or 3a9f1b2 or v1.0.0"
                className="w-full text-xs font-mono bg-surface-card border border-border-default text-text-primary rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-accent-primary focus:outline-none"
                required
              />
            </div>
            <button
              type="submit"
              disabled={isCreating || !newRevisionRef.trim()}
              className="px-4 py-1.5 text-xs font-medium text-accent-contrast-text bg-accent-primary hover:bg-accent-hover disabled:opacity-50 rounded-lg transition-colors"
            >
              {isCreating ? "Materializing..." : "Create Worktree"}
            </button>
          </form>
        )}

        {/* Active Worktree Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 bg-surface-card border border-border-default rounded-lg text-xs">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-text-secondary">Worktree:</span>
            {isLoadingList ? (
              <span className="text-text-muted italic">Loading worktrees...</span>
            ) : materializations.length === 0 ? (
              <span className="text-text-muted italic">No active worktrees found.</span>
            ) : (
              <select
                aria-label="Active worktree"
                value={activeMatId || ""}
                onChange={(e) => setActiveMatId(e.target.value)}
                className="font-mono text-xs bg-surface-card border border-border-default text-text-primary rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-accent-primary"
              >
                {materializations.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id} ({m.revision}) [{m.mode}]
                  </option>
                ))}
              </select>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowCreateForm(!showCreateForm)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-accent-contrast-text bg-accent-primary hover:bg-accent-hover border border-border-subtle rounded-lg transition-colors"
            >
              <Icon name="plus" size={14} />
              {showCreateForm ? "Cancel New" : "Materialize Revision"}
            </button>

            {activeMat && (
              <>
                <span
                  className={`px-2 py-0.5 rounded text-[11px] font-semibold uppercase tracking-wider ${
                    activeMat.mode === "editable"
                      ? "bg-status-warning-bg text-status-warning border border-status-warning-border"
                      : "bg-status-info-bg text-status-info border border-status-info-border"
                  }`}
                >
                  {activeMat.mode}
                </span>

                <button
                  type="button"
                  onClick={handleToggleMode}
                  disabled={isTogglingMode}
                  className="px-2.5 py-1 rounded bg-surface-card border border-border-default hover:bg-surface-hover font-medium text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
                >
                  {isTogglingMode
                    ? "Updating..."
                    : activeMat.mode === "readonly"
                    ? "Enable Edit Mode"
                    : "Make Read-Only"}
                </button>

                <button
                  type="button"
                  onClick={() => setIsConfirmDeleteOpen(true)}
                  disabled={isDeleting}
                  className="px-2 py-1 rounded bg-status-danger-bg border border-status-danger-border hover:bg-surface-hover text-status-danger transition-colors disabled:opacity-50"
                  title="Delete worktree"
                  aria-label="Delete worktree"
                >
                  <Icon name="trash" size={14} />
                </button>
              </>
            )}
          </div>
        </div>

        {/* Content Pane: Left File Tree, Right Editor */}
        {!activeMat ? (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-text-muted">
            <Icon name="folder" size={48} className="mb-3 opacity-40 text-text-muted" />
            <p className="text-sm font-medium text-text-primary">No Worktree Selected</p>
            <p className="text-xs max-w-sm mt-1 text-text-muted">
              Select or materialize a new worktree to browse filesystem contents at a specific revision.
            </p>
          </div>
        ) : (
          <div className="flex-1 flex gap-4 min-h-0">
            {/* Left: Tree Directory Explorer */}
            <div className="w-1/3 flex flex-col border border-border-default rounded-lg overflow-hidden bg-surface-card">
              {/* Breadcrumb Header */}
              <div className="flex items-center gap-1.5 px-3 py-2 border-b border-border-default bg-surface-card text-xs overflow-x-auto">
                <button
                  type="button"
                  onClick={() => setCurrentDir("")}
                  className={`font-semibold hover:text-accent-primary transition-colors ${
                    currentDir === "" ? "text-accent-primary" : "text-text-muted"
                  }`}
                >
                  root
                </button>
                {breadcrumbs.map((bc, idx) => (
                  <React.Fragment key={bc.path}>
                    <span className="text-text-muted">/</span>
                    <button
                      type="button"
                      onClick={() => setCurrentDir(bc.path)}
                      className={`hover:text-accent-primary transition-colors truncate max-w-[100px] ${
                        idx === breadcrumbs.length - 1
                          ? "font-semibold text-accent-primary"
                          : "text-text-muted"
                      }`}
                    >
                      {bc.name}
                    </button>
                  </React.Fragment>
                ))}
              </div>

              {/* Items List */}
              <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
                {isLoadingTree ? (
                  <div className="p-4 text-center text-xs text-text-muted italic">
                    Loading directory...
                  </div>
                ) : currentEntries.length === 0 ? (
                  <div className="p-4 text-center text-xs text-text-muted italic">
                    Directory is empty
                  </div>
                ) : (
                  <>
                    {currentDir && (
                      <button
                        type="button"
                        onClick={() => {
                          const parts = currentDir.split("/").filter(Boolean);
                          parts.pop();
                          setCurrentDir(parts.join("/"));
                        }}
                        className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded text-xs text-left text-text-secondary hover:bg-surface-hover transition-colors"
                      >
                        <Icon name="folder" size={14} className="text-text-muted" />
                        <span>.. (parent)</span>
                      </button>
                    )}
                    {currentEntries.map((item) => (
                      <button
                        key={item.path}
                        type="button"
                        onClick={() => {
                          if (item.is_dir) {
                            setCurrentDir(item.path);
                          } else {
                            handleSelectFile(item.path);
                          }
                        }}
                        className={`w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded text-xs text-left transition-colors ${
                          selectedFilePath === item.path
                            ? "bg-accent-primary/10 text-accent-primary font-medium"
                            : "hover:bg-surface-hover text-text-primary"
                        }`}
                      >
                        <div className="flex items-center gap-2 truncate">
                          <Icon
                            name={item.is_dir ? "folder" : "file"}
                            size={14}
                            className={item.is_dir ? "text-accent-primary" : "text-text-muted"}
                          />
                          <span className="truncate">{item.name}</span>
                        </div>
                        {!item.is_dir && (
                          <span className="text-[10px] text-text-muted font-mono shrink-0">
                            {formatBytes(item.size_bytes)}
                          </span>
                        )}
                      </button>
                    ))}
                  </>
                )}
              </div>
            </div>

            {/* Right: File Viewer / Code Editor */}
            <div className="flex-1 flex flex-col border border-border-default rounded-lg overflow-hidden bg-surface-card">
              {selectedFilePath ? (
                <>
                  <div className="flex items-center justify-between px-4 py-2 border-b border-border-default bg-surface-card text-xs">
                    <div className="flex items-center gap-2 truncate">
                      <Icon name="file" size={14} className="text-text-muted" />
                      <span className="font-mono font-medium text-text-primary truncate">
                        {selectedFilePath}
                      </span>
                      {fileDirty && (
                        <span className="text-status-warning font-bold text-xs" title="Unsaved changes">
                          ●
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      {activeMat.mode === "editable" && !isBinaryFile(selectedFilePath) && (
                        <button
                          type="button"
                          onClick={handleSaveFile}
                          disabled={isSavingFile || !fileDirty}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-accent-contrast-text bg-accent-primary hover:bg-accent-hover disabled:opacity-50 rounded transition-colors"
                        >
                          <Icon name="save" size={12} />
                          {isSavingFile ? "Saving..." : "Save"}
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="flex-1 min-h-0 p-2 overflow-hidden flex flex-col">
                    {isLoadingFile ? (
                      <div className="flex-1 flex items-center justify-center text-xs text-text-muted italic">
                        Loading file content...
                      </div>
                    ) : isBinaryFile(selectedFilePath) ? (
                      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-text-muted">
                        <Icon name="file" size={36} className="mb-2 opacity-40 text-text-muted" />
                        <p className="text-xs font-semibold text-text-primary">Binary File Detected</p>
                        <p className="text-[11px] text-text-muted mt-1 max-w-xs">
                          This binary file format cannot be rendered in the code editor.
                        </p>
                      </div>
                    ) : (
                      <CodeEditor
                        value={fileContent}
                        onChange={(val) => {
                          setFileContent(val);
                          setFileDirty(true);
                        }}
                        filename={selectedFilePath}
                        readOnly={activeMat.mode !== "editable"}
                        className="flex-1 h-full border border-border-default rounded"
                      />
                    )}
                  </div>
                </>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-text-muted">
                  <Icon name="file" size={36} className="mb-2 opacity-30 text-text-muted" />
                  <p className="text-xs font-medium text-text-primary">No File Selected</p>
                  <p className="text-[11px] text-text-muted mt-0.5">
                    Click any file from the explorer on the left to view or edit its content.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 pt-3 border-t border-border-default">
          <button
            type="button"
            onClick={handleClose}
            disabled={isBusy}
            className="px-4 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default rounded-lg transition-colors disabled:opacity-50"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>

    <ConfirmDialog
      open={isConfirmDeleteOpen}
      title="Delete Worktree Snapshot"
      description={
        activeMat
          ? `Delete worktree snapshot '${activeMat.id}'? This action cannot be undone.`
          : undefined
      }
      confirmLabel={isDeleting ? "Deleting..." : "Delete Snapshot"}
      variant="danger"
      isPending={isDeleting}
      onConfirm={handleDeleteMaterialization}
      onCancel={() => {
        if (isDeleting) return;
        setIsConfirmDeleteOpen(false);
      }}
    />
  </>
  );
}
