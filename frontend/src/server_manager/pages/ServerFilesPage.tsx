import React, { useState, useRef, useMemo, useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { Icon } from "@/components/ui/Icon";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Modal } from "@/components/ui/Modal";
import { Pagination } from "@/components/ui/Pagination";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { LoadingBar } from "@/components/ui/LoadingBar";
import { PageSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import type { FileItem } from "@/server_manager/types";
import { CodeEditor } from "@/components/CodeEditor";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";

const PAGE_SIZE = 50;

const NON_EDITABLE_EXTENSIONS = new Set([
  "dat", "mca", "mcr", "sqlite", "db", "nbt", "jar", "zip", "tar", "gz", "png", "jpg", "jpeg", "gif", "ico", "class"
]);

function isBinaryFile(fileName: string): boolean {
  const ext = fileName.split(".").pop()?.toLowerCase();
  return !!ext && NON_EDITABLE_EXTENSIONS.has(ext);
}

function formatBytes(bytes: number) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

export function ServerFilesPage() {
  const { serverId } = useParams<{ serverId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const branchContext = useServerBranchContext();
  const urlBranch = searchParams.get("branch") || undefined;
  const activeBranch = branchContext
    ? branchContext.gitBacked
      ? urlBranch || branchContext.branch
      : undefined
    : urlBranch;
  const readOnlyBranch = activeBranch === "main";
  const currentPath = searchParams.get("path") || "";
  const fileParam = searchParams.get("file") || searchParams.get("edit");
  const [editContent, setEditContent] = useState("");
  const [userEdited, setUserEdited] = useState(false);
  const [fileToDelete, setFileToDelete] = useState<FileItem | null>(null);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [showBulkDelete, setShowBulkDelete] = useState(false);
  const [showCommitDialog, setShowCommitDialog] = useState(false);
  const [reloadCommand, setReloadCommand] = useState("");
  const [commitMessage, setCommitMessage] = useState("");
  const [prevCurrentPath, setPrevCurrentPath] = useState(currentPath);
  if (currentPath !== prevCurrentPath) {
    setPrevCurrentPath(currentPath);
    setSelectedPaths(new Set());
  }
  const previousBranchRef = useRef(activeBranch);

  useEffect(() => {
    if (previousBranchRef.current === activeBranch) return;
    previousBranchRef.current = activeBranch;
    setUserEdited(false);
    setEditContent("");
    setSelectedPaths(new Set());
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("file");
        next.delete("edit");
        return next;
      },
      { replace: true },
    );
  }, [activeBranch, setSearchParams]);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const editingFile = useMemo<FileItem | null>(() => {
    if (!fileParam) return null;
    const fileName = fileParam.split("/").pop() || fileParam;
    return {
      name: fileName,
      path: fileParam,
      is_dir: false,
      size: 0,
    };
  }, [fileParam]);

  const [prevFileParam, setPrevFileParam] = useState<string | null>(fileParam);
  if (fileParam !== prevFileParam) {
    setPrevFileParam(fileParam);
    setUserEdited(false);
    setEditContent("");
  }

  const switchView = (mode: "branch" | "live-state") => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (mode === "live-state") next.set("view", "live-state");
      else next.delete("view");
      next.delete("mode");
      next.delete("file");
      next.delete("edit");
      return next;
    });
  };

  const updateCurrentPath = (newPath: string) => {
    setCurrentPage(1);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (newPath) {
        next.set("path", newPath);
      } else {
        next.delete("path");
      }
      return next;
    });
  };

  const openFileEditor = (file: FileItem) => {
    setUserEdited(false);
    setEditContent("");
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("file", file.path);
      return next;
    });
  };

  const handleCloseEditor = () => {
    setUserEdited(false);
    setEditContent("");
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("file");
        next.delete("edit");
        if (!next.get("path") && fileParam && fileParam.includes("/")) {
          const parentDir = fileParam.substring(0, fileParam.lastIndexOf("/"));
          if (parentDir) {
            next.set("path", parentDir);
          }
        }
        return next;
      },
      { replace: true },
    );
  };

  const navigateToDirectory = (dirPath: string) => {
    setUserEdited(false);
    setEditContent("");
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("file");
      next.delete("edit");
      if (dirPath) {
        next.set("path", dirPath);
      } else {
        next.delete("path");
      }
      return next;
    });
  };

  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();

  const viewParam = searchParams.get("view") || searchParams.get("mode");
  const viewMode = viewParam === "live-state" || viewParam === "live_state" ? "live-state" : "branch";
  const isLiveState = viewMode === "live-state";
  const showViewSwitcher = branchContext?.gitBacked === true || viewParam === "live-state" || viewParam === "live_state";

  const { data: files, isLoading, error } = useQuery({
    queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch),
    queryFn: () =>
      activeBranch
        ? api.listServerFiles(serverId!, currentPath, activeBranch)
        : api.listServerFiles(serverId!, currentPath),
    enabled: !!serverId && !isLiveState,
  });

  const { data: fileContentData, isLoading: isContentLoading, error: fileContentError } = useQuery({
    queryKey: queryKeys.files.content(serverId!, editingFile?.path ?? "", activeBranch),
    queryFn: async () => {
      const res = activeBranch
        ? await api.readServerFileContent(serverId!, editingFile!.path, activeBranch)
        : await api.readServerFileContent(serverId!, editingFile!.path);
      return typeof res === "string"
        ? { path: editingFile!.path, content: res, is_binary: false }
        : res;
    },
    enabled: !!serverId && !!editingFile,
  });

  const isBinary = fileContentData?.is_binary === true;
  const rawTextContent =
    typeof fileContentData === "string" ? fileContentData : (fileContentData?.content ?? "");
  const displayedContent = userEdited ? editContent : rawTextContent;

  const liveStatePath = currentPath || "/";

  const { data: liveStateFiles, isLoading: isLiveStateLoading, error: liveStateError } = useQuery({
    queryKey: queryKeys.files.liveStateList(serverId!, liveStatePath),
    queryFn: () => (api.listLiveStateFiles ? api.listLiveStateFiles(serverId!, liveStatePath) : Promise.resolve({ items: [] })),
    enabled: !!serverId && isLiveState,
  });

  const { data: liveStateContentData, isLoading: isLiveStateContentLoading, error: liveStateContentError } = useQuery({
    queryKey: queryKeys.files.liveStateContent(serverId!, editingFile?.path ?? ""),
    queryFn: async () => {
      const res = await (api.readLiveStateFileContent
        ? api.readLiveStateFileContent(serverId!, editingFile!.path)
        : Promise.resolve({ content: "" }));
      return res;
    },
    enabled: !!serverId && isLiveState && !!editingFile,
  });

  const liveStateRawContent =
    (liveStateContentData as { content?: string } | undefined)?.content ?? "";
  const liveStateDisplayedContent = userEdited ? editContent : liveStateRawContent;

  const effectiveDisplayedContent = isLiveState ? liveStateDisplayedContent : displayedContent;
  const effectiveContentLoading = isLiveState ? isLiveStateContentLoading : isContentLoading;
  const effectiveContentError = isLiveState ? liveStateContentError : fileContentError;

  const liveStateSaveMutation = useMutation({
    mutationFn: () =>
      api.writeLiveStateFileContent
        ? api.writeLiveStateFileContent(serverId!, {
            path: editingFile!.path,
            content: liveStateDisplayedContent,
            reload_command: reloadCommand || null,
          })
        : Promise.resolve({ status: "ok", rcon_reloaded: false, reload_command: null } as any),
    onSuccess: (res: any) => {
      toast(
        "success",
        res?.rcon_reloaded ? `Saved & reloaded (${res?.reload_command})` : "Saved to stopped server live state",
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.files.liveStateContent(serverId!, editingFile!.path) });
      handleCloseEditor();
    },
    onError: (err: Error) => {
      handleMutationError("Failed to save file", err);
    },
  });

  const handleMutationError = (defaultTitle: string, err: Error) => {
    if (err instanceof ApiError && err.status === 403) {
      toast("error", "Permission Denied", "You do not have permission to perform this action on this server.");
    } else {
      toast("error", defaultTitle, err.message);
    }
  };

  const deleteMutation = useMutation({
    mutationFn: (path: string) =>
      activeBranch
        ? api.deleteServerFile(serverId!, path, activeBranch)
        : api.deleteServerFile(serverId!, path),
    onSuccess: () => {
      toast("success", "File deleted");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      setFileToDelete(null);
    },
    onError: (err: Error) => {
      handleMutationError("Failed to delete file", err);
    },
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: async (paths: string[]) => {
      for (const p of paths) {
        if (activeBranch) {
          await api.deleteServerFile(serverId!, p, activeBranch);
        } else {
          await api.deleteServerFile(serverId!, p);
        }
      }
    },
    onSuccess: () => {
      toast("success", "Files deleted", `Successfully deleted ${selectedPaths.size} item(s).`);
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      setSelectedPaths(new Set());
      setShowBulkDelete(false);
    },
    onError: (err: Error) => {
      handleMutationError("Failed to delete files", err);
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      activeBranch
        ? api.uploadServerFile(serverId!, currentPath, file, activeBranch)
        : api.uploadServerFile(serverId!, currentPath, file),
    onSuccess: () => {
      toast("success", "File uploaded");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
    },
    onError: (err: Error) => {
      handleMutationError("Failed to upload file", err);
    },
  });

  const mkdirMutation = useMutation({
    mutationFn: (folderName: string) => {
      const fullPath = currentPath ? `${currentPath}/${folderName}` : folderName;
      return activeBranch
        ? api.mkdirServerDirectory(serverId!, fullPath, undefined, activeBranch)
        : api.mkdirServerDirectory(serverId!, fullPath);
    },
    onSuccess: () => {
      toast("success", "Folder created");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      setShowNewFolder(false);
      setNewFolderName("");
    },
    onError: (err: Error) => {
      handleMutationError("Failed to create folder", err);
    },
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      activeBranch
        ? api.writeServerFileContent(serverId!, editingFile!.path, displayedContent, activeBranch)
        : api.writeServerFileContent(serverId!, editingFile!.path, displayedContent),
    onSuccess: () => {
      toast("success", "File saved");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.content(serverId!, editingFile!.path, activeBranch) });
      handleCloseEditor();
    },
    onError: (err: Error) => {
      handleMutationError("Failed to save file", err);
    },
  });

  const commitMutation = useMutation({
    mutationFn: () =>
      api.createServerCommit(serverId!, {
        message: commitMessage.trim(),
        branch_name: activeBranch,
      }),
    onSuccess: (result) => {
      const commitId =
        typeof result.commit_id === "string" ? result.commit_id.slice(0, 12) : "new commit";
      const routed = Array.isArray(result.routed_to_cas) ? result.routed_to_cas.length : 0;
      const quarantined = Array.isArray(result.quarantined) ? result.quarantined.length : 0;
      const suffix =
        routed || quarantined
          ? ` · ${routed} routed to CAS · ${quarantined} quarantined`
          : "";
      toast("success", "Changes committed", `${commitId} on ${activeBranch}${suffix}`);
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      queryClient.invalidateQueries({ queryKey: queryKeys.files.content(serverId!, editingFile?.path ?? "", activeBranch) });
      queryClient.invalidateQueries({ queryKey: queryKeys.versioning.branches(serverId!) });
      setShowCommitDialog(false);
      setCommitMessage("");
    },
    onError: (err: Error) => {
      handleMutationError("Failed to commit changes", err);
    },
  });

  const handleDownload = async (file: FileItem) => {
    try {
      const blob = activeBranch
        ? await api.downloadServerFile(serverId!, file.path, activeBranch)
        : await api.downloadServerFile(serverId!, file.path);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: unknown) {
      toast("error", "Download failed", err instanceof Error ? err.message : "Download failed");
    }
  };

  const navigateUp = () => {
    if (!currentPath) return;
    const parts = currentPath.split("/").filter(Boolean);
    parts.pop();
    updateCurrentPath(parts.join("/"));
  };

  const navigateTo = (folder: string) => {
    const newPath = currentPath ? `${currentPath}/${folder}` : folder;
    updateCurrentPath(newPath);
  };


  const filteredFiles = useMemo(() => {
    if (!files) return [];
    if (!searchQuery.trim()) return files;
    const q = searchQuery.trim().toLowerCase();
    return files.filter((f) => f.name.toLowerCase().includes(q));
  }, [files, searchQuery]);

  const paginatedFiles = useMemo(() => {
    if (filteredFiles.length <= PAGE_SIZE) return filteredFiles;
    const startIdx = (currentPage - 1) * PAGE_SIZE;
    return filteredFiles.slice(startIdx, startIdx + PAGE_SIZE);
  }, [filteredFiles, currentPage]);

  const allSelectablePaths = useMemo(
    () => paginatedFiles.map((f) => f.path),
    [paginatedFiles],
  );
  const isAllSelected =
    allSelectablePaths.length > 0 &&
    allSelectablePaths.every((p) => selectedPaths.has(p));

  const toggleSelectAll = () => {
    if (isAllSelected) {
      setSelectedPaths(new Set());
    } else {
      setSelectedPaths(new Set(allSelectablePaths));
    }
  };

  const toggleSelect = (path: string) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  if (isLiveState) {
    if (isLiveStateLoading && !liveStateFiles) return <PageSkeleton />;
    if (liveStateError) return <ErrorState message={liveStateError instanceof Error ? liveStateError.message : "Failed to load"} />;
  } else {
    if (isLoading && !files) return <PageSkeleton />;
    if (error) return <ErrorState message={error.message} />;
  }

  const pathParts = currentPath.split("/").filter(Boolean);
  const breadcrumbs = [
    { name: "root", path: "" },
    ...pathParts.map((part, index) => ({
      name: part,
      path: pathParts.slice(0, index + 1).join("/"),
    })),
  ];

  const editorPathParts =
    editingFile?.path && editingFile.path.includes("/")
      ? editingFile.path.split("/").slice(0, -1)
      : [];

  if (editingFile) {
    return (
      <div className="flex flex-col h-full bg-surface-card rounded-xl shadow-sm border border-border-default overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-border-subtle bg-surface-card">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleCloseEditor}
              aria-label="Back"
              className="p-1.5 text-text-muted hover:text-text-primary hover:bg-surface-hover rounded-lg transition-colors cursor-pointer"
            >
              <Icon name="chevron-left" />
            </button>
            <div>
              <nav
                aria-label="Editor breadcrumb"
                className="text-xs text-text-muted font-mono flex items-center gap-1.5 flex-wrap"
              >
                <button
                  type="button"
                  onClick={() => navigateToDirectory("")}
                  className="hover:text-accent-primary hover:underline cursor-pointer"
                >
                  root
                </button>
                {editorPathParts.map((part, index) => {
                  const pathUpTo = editorPathParts.slice(0, index + 1).join("/");
                  return (
                    <span key={pathUpTo} className="flex items-center gap-1.5">
                      <span className="text-border-default">/</span>
                      <button
                        type="button"
                        onClick={() => navigateToDirectory(pathUpTo)}
                        className="hover:text-accent-primary hover:underline cursor-pointer"
                      >
                        {part}
                      </button>
                    </span>
                  );
                })}
                <span className="text-border-default">/</span>
                <span className="text-text-primary font-medium">
                  {editingFile.name}
                </span>
              </nav>
              <h2 className="text-lg font-semibold text-text-primary">
                Editing: {editingFile.name}
              </h2>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCloseEditor}
              className="px-3 py-1.5 text-sm font-medium text-text-secondary bg-surface-page border border-border-default rounded-lg hover:bg-surface-hover transition-colors cursor-pointer"
            >
              Cancel
            </button>
            {!isBinary && (isLiveState || !readOnlyBranch) && (
              <>
                {isLiveState && (
                  <select
                    aria-label="RCON Reload Command"
                    value={reloadCommand}
                    onChange={(e) => setReloadCommand(e.target.value)}
                    className="rounded-lg border border-border-default bg-surface-card px-2 py-1.5 text-sm"
                  >
                    <option value="">Auto</option>
                    <option value="whitelist reload">whitelist reload</option>
                    <option value="minecraft:reload">minecraft:reload</option>
                    <option value="reload">reload</option>
                  </select>
                )}
                <Button
                  variant="primary"
                  onClick={() => (isLiveState ? liveStateSaveMutation.mutate() : saveMutation.mutate())}
                  disabled={(isLiveState ? liveStateSaveMutation.isPending : saveMutation.isPending) || effectiveContentLoading || !!effectiveContentError}
                  loading={isLiveState ? liveStateSaveMutation.isPending : saveMutation.isPending}
                  icon="save"
                >
                  {isLiveState ? "Save Live State" : "Save"}
                </Button>
              </>
            )}
          </div>
        </div>
        <div className="flex-1 p-4">
          {effectiveContentLoading ? (
            <div className="h-64 flex items-center justify-center text-text-muted">Loading content...</div>
          ) : effectiveContentError ? (
            <div className="h-64 flex flex-col items-center justify-center text-center p-8 bg-surface-page border border-border-default rounded-xl">
              <Icon name="alert" size={48} className="text-status-danger mb-3" />
              <h3 className="text-base font-semibold text-text-primary mb-1">
                Failed to load file
              </h3>
              <p className="text-sm text-text-muted mb-4 max-w-sm">
                {fileContentError instanceof Error ? fileContentError.message : "Unable to read file content"}
              </p>
              <button
                type="button"
                onClick={handleCloseEditor}
                className="px-4 py-2 text-sm font-medium text-text-secondary bg-surface-card border border-border-default rounded-lg hover:bg-surface-hover transition-colors cursor-pointer"
              >
                Back to Files
              </button>
            </div>
          ) : isBinary ? (
            <div className="h-64 flex flex-col items-center justify-center text-center p-8 bg-surface-page border border-border-default rounded-xl">
              <Icon name="file" size={48} className="text-text-muted mb-3" />
              <h3 className="text-base font-semibold text-text-primary mb-1">Binary File</h3>
              <p className="text-sm text-text-muted mb-4 max-w-sm">
                This file cannot be displayed or edited as text because it contains binary data.
              </p>
              <button
                type="button"
                onClick={() => handleDownload(editingFile)}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-accent-primary hover:bg-accent-hover rounded-lg transition-colors cursor-pointer"
              >
                <Icon name="download" size={16} />
                Download File
              </button>
            </div>
          ) : (
            <CodeEditor
              value={effectiveDisplayedContent}
              filename={editingFile.name}
              onChange={(val) => {
                setEditContent(val);
                setUserEdited(true);
              }}
            />
          )}
        </div>
      </div>
    );
  }

  // File browser view
  return (
    <div className="flex flex-col flex-1 min-h-0 space-y-4">
      {showViewSwitcher && (
        <div data-testid="files-view-switcher" className="flex gap-2">
          <button
            type="button"
            onClick={() => switchView("branch")}
            className={`px-3 py-1.5 text-sm rounded-lg border ${viewMode === "branch" ? "bg-accent-primary text-white" : "bg-surface-card"}`}
          >
            Branch Config Files (Class B)
          </button>
          <button
            type="button"
            onClick={() => switchView("live-state")}
            className={`px-3 py-1.5 text-sm rounded-lg border ${viewMode === "live-state" ? "bg-accent-primary text-white" : "bg-surface-card"}`}
          >
            Live State Files (Class C)
          </button>
        </div>
      )}

      {isLiveState && (
        <div data-testid="live-state-banner" className="rounded-xl border border-border-default bg-surface-card px-4 py-3 text-sm text-text-secondary">
          Live State edits apply directly to Class-C runtime files on the live server directory. If the server is RUNNING, saving triggers an automatic RCON save-all flush + reload; if STOPPED, saving writes atomically after checking world/session.lock.
        </div>
      )}

      {!isLiveState && isLoading && <LoadingBar />}

      {!isLiveState && activeBranch && (
        <div
          data-testid="branch-context-banner"
          className="flex flex-wrap items-center gap-2 rounded-xl border border-border-default bg-surface-card px-4 py-2.5 text-xs text-text-secondary"
        >
          <Icon name="backup" size={14} className="text-accent-primary" />
          <span>
            Branch: <strong className="font-mono text-text-primary">{activeBranch}</strong>
          </span>
          <span className="text-border-subtle">•</span>
          {readOnlyBranch ? (
            <span className="text-status-warning">
              Saved state is read-only. Select a working branch to edit files.
            </span>
          ) : (
            <span>Changes stay uncommitted until Save &amp; Commit.</span>
          )}
        </div>
      )}

      {/* Toolbar & Breadcrumbs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 bg-surface-card rounded-xl shadow-sm border border-border-default">
        <div className="flex items-center overflow-x-auto whitespace-nowrap text-sm font-medium text-text-secondary">
          {breadcrumbs.map((crumb, idx) => (
            <React.Fragment key={crumb.path}>
              <button
                type="button"
                onClick={() => updateCurrentPath(crumb.path)}
                className={`flex items-center gap-1 hover:text-accent-primary transition-colors cursor-pointer ${
                  idx === breadcrumbs.length - 1
                    ? "font-semibold text-text-primary"
                    : ""
                }`}
              >
                {idx === 0 && <Icon name="folder" size={16} className="text-accent-primary" />}
                <span>{crumb.name}</span>
              </button>
              {idx < breadcrumbs.length - 1 && (
                <span className="mx-2 text-border-default">/</span>
              )}
            </React.Fragment>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Client-side filter search */}
          <div className="relative min-w-[180px] max-w-xs">
            <span className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-text-muted">
              <Icon name="search" size={15} />
            </span>
            <input
              type="text"
              aria-label="Filter current directory"
              placeholder="Filter files in folder..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setCurrentPage(1);
              }}
              className="w-full rounded-lg border border-border-default bg-surface-page py-1.5 ps-9 pe-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
            />
          </div>

          <input
            type="file"
            aria-label="Upload file"
            ref={fileInputRef}
            className="hidden"
            onChange={(e) => {
              if (e.target.files && e.target.files[0]) {
                uploadMutation.mutate(e.target.files[0]);
              }
              e.target.value = "";
            }}
          />
          {selectedPaths.size > 0 && !readOnlyBranch && (
            <Button
              variant="danger"
              icon="trash"
              loading={bulkDeleteMutation.isPending}
              onClick={() => setShowBulkDelete(true)}
            >
              Delete Selected ({selectedPaths.size})
            </Button>
          )}
          {!isLiveState && activeBranch && !readOnlyBranch && (
            <Button
              variant="secondary"
              icon="save"
              onClick={() => setShowCommitDialog(true)}
            >
              Save &amp; Commit
            </Button>
          )}
          {!isLiveState && !readOnlyBranch && (
            <>
              <Button
                variant="secondary"
                icon="folder"
                onClick={() => setShowNewFolder(true)}
              >
                New Folder
              </Button>
              <Button
                variant="primary"
                icon="upload"
                loading={uploadMutation.isPending}
                onClick={() => fileInputRef.current?.click()}
              >
                Upload File
              </Button>
            </>
          )}
        </div>
      </div>

      {showNewFolder && (
        <div className="flex items-center gap-2 p-4 bg-surface-card rounded-xl shadow-sm border border-border-default">
          <Icon name="folder" className="text-text-muted" />
          <input
            type="text"
            placeholder="Folder name"
            aria-label="Folder name"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            className="flex-1 px-3 py-1.5 text-sm border border-border-default rounded-lg focus:outline-none focus:ring-1 focus:ring-accent-primary bg-surface-page text-text-primary placeholder:text-text-muted"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && newFolderName) mkdirMutation.mutate(newFolderName);
              if (e.key === "Escape") {
                setShowNewFolder(false);
                setNewFolderName("");
              }
            }}
          />
          <Button
            variant="primary"
            onClick={() => mkdirMutation.mutate(newFolderName)}
            disabled={!newFolderName || mkdirMutation.isPending}
            loading={mkdirMutation.isPending}
          >
            Create
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setShowNewFolder(false);
              setNewFolderName("");
            }}
          >
            Cancel
          </Button>
        </div>
      )}

      {isLiveState && (
        <div className="flex flex-col gap-2">
          {(liveStateFiles?.items ?? []).map((f: any) => (
            <button
              key={f.path}
              type="button"
              onClick={() => {
                if (f.is_dir) updateCurrentPath(f.path);
                else openFileEditor({ name: f.name, path: f.path, is_dir: false, size: f.size });
              }}
              className="flex items-center justify-between rounded-lg border border-border-default bg-surface-card px-4 py-2 text-sm"
            >
              <span>{f.name}</span>
              <span className="text-xs text-text-muted">
                {f.size ? `${f.size} B` : ""}
                {f.is_dynamic_class_c ? " · Dynamic Class-C" : ""}
                {f.writable ? " · Editable" : " · Read-Only Binary"}
              </span>
            </button>
          ))}
        </div>
      )}

      {!isLiveState && (
      /* File Browser Table */
      <div className="flex flex-col flex-1 min-h-0 bg-surface-card rounded-xl shadow-xs border border-border-default overflow-hidden">
        {files?.length === 0 && !currentPath ? (
          <EmptyState
            title="Empty Directory"
            description="No files found in this folder."
            icon="folder"
            action={readOnlyBranch ? undefined : {
              label: "Upload File",
              icon: "upload",
              onClick: () => fileInputRef.current?.click(),
            }}
          />
        ) : filteredFiles.length === 0 && searchQuery ? (
          <EmptyState
            title="No matching files"
            description={`No files match "${searchQuery}".`}
            icon="search"
            action={{
              label: "Clear filter",
              onClick: () => {
                setSearchQuery("");
                setCurrentPage(1);
              },
            }}
          />
        ) : (
          <div className="overflow-x-auto flex-1 min-h-0 overflow-y-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs uppercase bg-surface-page/50 text-text-muted border-b border-border-subtle tracking-wider font-semibold">
                <tr>
                  <th scope="col" className="w-10 px-4 py-2.5">
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      checked={isAllSelected}
                      onChange={toggleSelectAll}
                      className="rounded border-border-default accent-accent-primary cursor-pointer"
                    />
                  </th>
                  <th scope="col" className="px-4 py-2.5">Name</th>
                  <th scope="col" className="px-4 py-2.5 w-32">Size</th>
                  <th scope="col" className="px-4 py-2.5 w-32 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {currentPath && (
                  <tr className="hover:bg-surface-hover/50 transition-colors">
                    <td className="w-10 px-4 py-2"></td>
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        onClick={navigateUp}
                        className="flex items-center gap-2.5 cursor-pointer text-left focus:outline-hidden focus-visible:ring-1 focus-visible:ring-border-focus rounded font-medium text-text-primary"
                        aria-label="Navigate to parent directory"
                      >
                        <Icon name="folder" className="text-accent-primary" size={16} />
                        <span>..</span>
                      </button>
                    </td>
                    <td className="px-4 py-2 text-text-muted">-</td>
                    <td className="px-4 py-2 text-right"></td>
                  </tr>
                )}
                {paginatedFiles.map((file) => (
                  <tr
                    key={file.path}
                    className="hover:bg-surface-hover/50 transition-colors group"
                  >
                    <td className="w-10 px-4 py-2">
                      <input
                        type="checkbox"
                        aria-label={`Select ${file.name}`}
                        checked={selectedPaths.has(file.path)}
                        onChange={() => toggleSelect(file.path)}
                        className="rounded border-border-default accent-accent-primary cursor-pointer"
                      />
                    </td>
                    <td className="px-4 py-2">
                      <button
                        type="button"
                        className="flex items-center gap-2.5 cursor-pointer text-left focus:outline-hidden focus-visible:ring-1 focus-visible:ring-border-focus rounded"
                        onClick={() => {
                          if (file.is_dir) {
                            navigateTo(file.name);
                          } else if (isBinaryFile(file.name)) {
                            handleDownload(file);
                          } else {
                            openFileEditor(file);
                          }
                        }}
                      >
                        <Icon
                          name={file.is_dir ? "folder" : "file"}
                          size={16}
                          className={file.is_dir ? "text-accent-primary" : "text-text-muted"}
                        />
                        <span className="font-medium text-text-primary truncate max-w-[200px] sm:max-w-xs md:max-w-sm hover:text-accent-primary transition-colors">
                          {file.name}
                        </span>
                      </button>
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-xs font-mono text-text-muted">
                      {file.is_dir ? "-" : formatBytes(file.size)}
                    </td>
                    <td className="px-4 py-2 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                        {file.is_dir ? (
                          <>
                            <IconButton
                              icon="folder"
                              aria-label={`Open ${file.name}`}
                              title={`Open ${file.name}`}
                              size="sm"
                              variant="ghost"
                              onClick={() => navigateTo(file.name)}
                            />
                            {!readOnlyBranch && (
                              <IconButton
                                icon="trash"
                                aria-label={`Delete ${file.name}`}
                                title={`Delete ${file.name}`}
                                size="sm"
                                variant="ghost"
                                onClick={() => setFileToDelete(file)}
                              />
                            )}
                          </>
                        ) : (
                          <>
                            <IconButton
                              icon="download"
                              aria-label="Download"
                              title={`Download ${file.name}`}
                              size="sm"
                              variant="ghost"
                              onClick={() => handleDownload(file)}
                            />
                            {!readOnlyBranch && !isBinaryFile(file.name) && (
                              <IconButton
                                icon="edit"
                                aria-label="Edit"
                                title={`Edit ${file.name}`}
                                size="sm"
                                variant="ghost"
                                onClick={() => openFileEditor(file)}
                              />
                            )}
                            {!readOnlyBranch && (
                              <IconButton
                                icon="trash"
                                aria-label="Delete"
                                title={`Delete ${file.name}`}
                                size="sm"
                                variant="ghost"
                                onClick={() => setFileToDelete(file)}
                              />
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {filteredFiles.length > PAGE_SIZE && (
              <div className="border-t border-border-subtle p-3">
                <Pagination
                  totalItems={filteredFiles.length}
                  pageSize={PAGE_SIZE}
                  page={currentPage}
                  onPageChange={setCurrentPage}
                />
              </div>
            )}
          </div>
        )}
      </div>
      )}

      <Modal
        open={showCommitDialog}
        onClose={() => {
          if (!commitMutation.isPending) setShowCommitDialog(false);
        }}
        title="Save & Commit"
        description={
          activeBranch
            ? `Commit validated Class-B changes on branch "${activeBranch}".`
            : "Commit validated Class-B changes."
        }
        size="sm"
        closeOnBackdrop={!commitMutation.isPending}
        closeOnEscape={!commitMutation.isPending}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (commitMessage.trim() && !commitMutation.isPending) {
              commitMutation.mutate();
            }
          }}
        >
          <label
            htmlFor="commit-message"
            className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-text-muted"
          >
            Commit message
          </label>
          <input
            id="commit-message"
            type="text"
            aria-label="Commit message"
            placeholder="Describe this change"
            value={commitMessage}
            onChange={(e) => setCommitMessage(e.target.value)}
            autoFocus
            maxLength={500}
            disabled={commitMutation.isPending}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
          />
          <div className="mt-4 flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setShowCommitDialog(false)}
              disabled={commitMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              icon="save"
              loading={commitMutation.isPending}
              disabled={!commitMessage.trim()}
            >
              Commit
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={showBulkDelete}
        title="Delete Selected Items"
        description={`Are you sure you want to delete ${selectedPaths.size} selected item(s)? This action cannot be undone.`}
        confirmLabel={bulkDeleteMutation.isPending ? "Deleting..." : "Delete"}
        variant="danger"
        isPending={bulkDeleteMutation.isPending}
        onConfirm={() => bulkDeleteMutation.mutate(Array.from(selectedPaths))}
        onCancel={() => {
          if (bulkDeleteMutation.isPending) return;
          setShowBulkDelete(false);
        }}
      />

      <ConfirmDialog
        open={!!fileToDelete}
        title={fileToDelete?.is_dir ? "Delete Folder" : "Delete File"}
        description={`Are you sure you want to delete ${fileToDelete?.name}? ${fileToDelete?.is_dir ? "All contents will be permanently deleted. " : ""}This action cannot be undone.`}
        confirmLabel={deleteMutation.isPending ? "Deleting..." : "Delete"}
        variant="danger"
        isPending={deleteMutation.isPending}
        onConfirm={() => fileToDelete && deleteMutation.mutate(fileToDelete.path)}
        onCancel={() => {
          if (deleteMutation.isPending) return;
          setFileToDelete(null);
        }}
      />
    </div>
  );
}
