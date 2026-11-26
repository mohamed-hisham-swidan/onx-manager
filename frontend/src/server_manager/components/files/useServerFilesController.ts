import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import { useClipboard } from "@/hooks/useClipboard";
import { useFleetPermissions } from "@/server_manager/components/servers/serversUtils";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import type { FileContentResponse, FileItem, LiveStateWriteResponse } from "@/server_manager/types";
import type { UploadProgressState } from "./FilesToolbar";
import {
  clampSplitRatio,
  DEFAULT_FILES_SPLIT_RATIO,
  extractApiErrorMessage,
  isBinaryFile,
  isImageFile,
  joinRelativePath,
  readStoredSplitRatio,
  sortFileRows,
  toUnifiedFromLiveState,
  toUnifiedFromStandard,
  writeStoredSplitRatio,
  type SortDirection,
  type SortField,
  type UnifiedFileRow,
} from "./filesUtils";

export const FILES_PAGE_SIZE = 50;

export type FilesViewMode = "branch" | "live-state" | "logs";

export function useServerFilesController() {
  const { serverId } = useParams<{ serverId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const branchContext = useServerBranchContext();
  const permissions = useFleetPermissions();
  const { copy } = useClipboard();
  const queryClient = useQueryClient();
  const api = useMemo(() => createAuthenticatedApi(), []);

  const canAccessFiles = serverId ? permissions.canFiles(serverId) : false;
  const urlBranch = searchParams.get("branch") || undefined;
  const activeBranch = branchContext
    ? branchContext.gitBacked
      ? urlBranch || branchContext.branch
      : undefined
    : urlBranch;
  const readOnlyBranch = activeBranch === "main";
  const currentPath = searchParams.get("path") || "";
  const fileParam = searchParams.get("file") || searchParams.get("edit");
  const tabParam = searchParams.get("tab");
  const viewParam = searchParams.get("view") || searchParams.get("mode");
  const viewMode: FilesViewMode =
    tabParam === "logs"
      ? "logs"
      : tabParam === "live-state" || viewParam === "live-state" || viewParam === "live_state"
        ? "live-state"
        : "branch";
  const isLiveState = viewMode === "live-state";
  const isLogsView = viewMode === "logs";
  const isNonMainLiveStateReadOnly = Boolean(isLiveState && activeBranch && activeBranch !== "main");
  const isAdvancedMode =
    branchContext?.serverMode === "simple"
      ? false
      : branchContext?.serverMode === "advanced" ||
        branchContext?.gitBacked === true ||
        isLiveState;
  const showViewSwitcher = true;

  const [splitView, setSplitView] = useState(false);
  const [splitRatio, setSplitRatio] = useState<number>(() => readStoredSplitRatio());

  const updateSplitRatio = useCallback((next: number | ((prev: number) => number)) => {
    setSplitRatio((prev) => {
      const resolved = typeof next === "function" ? next(prev) : next;
      const clamped = clampSplitRatio(resolved);
      writeStoredSplitRatio(clamped);
      return clamped;
    });
  }, []);

  const resetSplitRatio = useCallback(() => {
    updateSplitRatio(DEFAULT_FILES_SPLIT_RATIO);
  }, [updateSplitRatio]);
  const [activeFileSource, setActiveFileSource] = useState<FilesViewMode>(viewMode);
  const [openedFileMeta, setOpenedFileMeta] = useState<{
    path: string;
    source: FilesViewMode;
    editable?: boolean | null;
    writable?: boolean;
  } | null>(null);
  const [pendingFileSwitch, setPendingFileSwitch] = useState<{
    row: Pick<FileItem, "name" | "path" | "is_dir" | "editable"> & { writable?: boolean };
    source: FilesViewMode;
  } | null>(null);
  const [pendingViewSwitch, setPendingViewSwitch] = useState<FilesViewMode | null>(null);
  const [editContent, setEditContent] = useState("");
  const [userEdited, setUserEdited] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [fileToDelete, setFileToDelete] = useState<UnifiedFileRow | null>(null);
  const [showBulkDelete, setShowBulkDelete] = useState(false);
  const [showNewFile, setShowNewFile] = useState(false);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [showCommitDialog, setShowCommitDialog] = useState(false);
  const [reloadCommand, setReloadCommand] = useState("");
  const [copiedPath, setCopiedPath] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null);
  const [pendingOverwrite, setPendingOverwrite] = useState<{ files: File[]; collisions: string[] } | null>(null);

  const [prevPath, setPrevPath] = useState(currentPath);
  if (currentPath !== prevPath) {
    setPrevPath(currentPath);
    setSelectedPaths(new Set());
  }

  const [prevFileParam, setPrevFileParam] = useState<string | null>(fileParam);
  if (fileParam !== prevFileParam) {
    setPrevFileParam(fileParam);
    setUserEdited(false);
    setEditContent("");
    if (fileParam && !splitView) {
      setActiveFileSource(viewMode);
    }
  }

  const previousBranchRef = useRef(activeBranch);
  useEffect(() => {
    if (previousBranchRef.current === activeBranch) return;
    previousBranchRef.current = activeBranch;
    setUserEdited(false);
    setEditContent("");
    setOpenedFileMeta(null);
    setPendingFileSwitch(null);
    setPendingViewSwitch(null);
    setSelectedPaths(new Set());
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("file");
      next.delete("edit");
      return next;
    }, { replace: true });
  }, [activeBranch, setSearchParams]);

  const editingFile = useMemo<FileItem | null>(() => {
    if (!fileParam) return null;
    return { name: fileParam.split("/").pop() || fileParam, path: fileParam, is_dir: false, size: 0 };
  }, [fileParam]);

  const filesQuery = useQuery({
    queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch),
    queryFn: () =>
      activeBranch
        ? api.listServerFiles(serverId!, currentPath, activeBranch)
        : api.listServerFiles(serverId!, currentPath),
    enabled: Boolean(serverId && canAccessFiles && !isLiveState && !isLogsView),
  });

  const liveStatePath = currentPath || "/";
  const liveStateQuery = useQuery({
    queryKey: queryKeys.files.liveStateList(serverId!, liveStatePath),
    queryFn: () => api.listLiveStateFiles(serverId!, liveStatePath),
    enabled: Boolean(serverId && canAccessFiles && isLiveState),
  });

  const logsQuery = useQuery({
    queryKey: queryKeys.files.logsList(serverId!, activeBranch),
    queryFn: () => api.listServerFiles(serverId!, "", activeBranch, "logs"),
    enabled: Boolean(serverId && canAccessFiles && isLogsView),
  });

  const activeEditorIsLiveState = activeFileSource === "live-state";
  const activeEditorIsLogs = activeFileSource === "logs";

  const matchedEditorRow = useMemo(() => {
    if (!editingFile || activeEditorIsLogs) return null;
    if (activeEditorIsLiveState) {
      const found = (liveStateQuery.data?.items ?? []).find(
        (item) => item.path === editingFile.path,
      );
      return found ? toUnifiedFromLiveState(found) : null;
    }
    const found = (filesQuery.data ?? []).find((item) => item.path === editingFile.path);
    return found ? toUnifiedFromStandard(found) : null;
  }, [
    editingFile,
    activeEditorIsLogs,
    activeEditorIsLiveState,
    liveStateQuery.data?.items,
    filesQuery.data,
  ]);

  const activeRowEditable =
    openedFileMeta &&
    openedFileMeta.path === editingFile?.path &&
    openedFileMeta.source === activeFileSource
      ? openedFileMeta.editable
      : matchedEditorRow?.editable;
  const activeRowWritable =
    openedFileMeta &&
    openedFileMeta.path === editingFile?.path &&
    openedFileMeta.source === activeFileSource
      ? openedFileMeta.writable
      : matchedEditorRow?.writable;
  const isRowReadOnly = activeRowEditable === false || activeRowWritable === false;

  const activeEditorReadOnly = activeEditorIsLogs
    ? true
    : activeEditorIsLiveState
      ? isNonMainLiveStateReadOnly || isRowReadOnly
      : readOnlyBranch || isRowReadOnly;

  const isEditingImage = Boolean(
    editingFile && activeFileSource === "branch" && isImageFile(editingFile.name),
  );
  const fileContentQuery = useQuery<FileContentResponse>({
    queryKey: queryKeys.files.content(serverId!, editingFile?.path ?? "", activeBranch),
    queryFn: async () => {
      const res: FileContentResponse | string = activeBranch
        ? await api.readServerFileContent(serverId!, editingFile!.path, activeBranch)
        : await api.readServerFileContent(serverId!, editingFile!.path);
      return typeof res === "string" ? { path: editingFile!.path, content: res, is_binary: false } : res;
    },
    enabled: Boolean(
      serverId &&
        canAccessFiles &&
        editingFile &&
        activeFileSource === "branch" &&
        !isEditingImage,
    ),
  });

  const liveStateContentQuery = useQuery({
    queryKey: queryKeys.files.liveStateContent(serverId!, editingFile?.path ?? ""),
    queryFn: () => api.readLiveStateFileContent(serverId!, editingFile!.path),
    enabled: Boolean(serverId && canAccessFiles && editingFile && activeFileSource === "live-state"),
  });

  const logContentQuery = useQuery<FileContentResponse>({
    queryKey: queryKeys.files.logsContent(serverId!, editingFile?.path ?? "", activeBranch),
    queryFn: () => api.readServerFileContent(serverId!, editingFile!.path, activeBranch, "logs"),
    enabled: Boolean(serverId && canAccessFiles && editingFile && activeFileSource === "logs"),
  });

  const savedContent = activeEditorIsLogs
    ? ""
    : activeEditorIsLiveState
      ? (liveStateContentQuery.data?.content ?? "")
      : (fileContentQuery.data?.content ?? "");
  const displayedContent = userEdited ? editContent : savedContent;
  const isDirty = !activeEditorIsLogs && userEdited && editContent !== savedContent;
  const isBinary = activeFileSource === "branch" && fileContentQuery.data?.is_binary === true;

  const handleMutationError = (title: string, err: unknown) => {
    toast("error", title, extractApiErrorMessage(err, title));
  };

  const applySwitchView = (mode: FilesViewMode) => {
    setSearchQuery("");
    setCurrentPage(1);
    setSelectedPaths(new Set());
    if (!splitView) {
      setUserEdited(false);
      setEditContent("");
      setReloadCommand("");
      setOpenedFileMeta(null);
      setActiveFileSource(mode);
    }
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (mode === "logs") {
        next.set("tab", "logs");
        next.delete("view");
        next.delete("path");
      } else if (mode === "live-state") {
        next.set("view", "live-state");
        next.delete("tab");
      } else {
        next.delete("tab");
        next.delete("view");
      }
      next.delete("mode");
      if (!splitView) {
        next.delete("file");
        next.delete("edit");
      }
      return next;
    });
  };

  const switchView = (mode: FilesViewMode) => {
    if (mode === viewMode) return;
    if (!splitView && editingFile && isDirty && !activeEditorReadOnly) {
      setPendingViewSwitch(mode);
      return;
    }
    applySwitchView(mode);
  };

  const confirmViewSwitch = () => {
    if (!pendingViewSwitch) return;
    const mode = pendingViewSwitch;
    setPendingViewSwitch(null);
    applySwitchView(mode);
  };

  const cancelViewSwitch = () => {
    setPendingViewSwitch(null);
  };

  const updateCurrentPath = (newPath: string) => {
    setCurrentPage(1);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (newPath) next.set("path", newPath);
      else next.delete("path");
      return next;
    });
  };

  const applyOpenFile = (
    row: Pick<FileItem, "name" | "path" | "editable"> & { writable?: boolean },
    source: FilesViewMode,
  ) => {
    setActiveFileSource(source);
    setOpenedFileMeta({
      path: row.path,
      source,
      editable: row.editable,
      writable: row.writable,
    });
    setUserEdited(false);
    setEditContent("");
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("file", row.path);
      return next;
    });
  };

  const openFileEditor = (
    row: Pick<FileItem, "name" | "path" | "is_dir" | "editable"> & { writable?: boolean },
    sourceOverride?: FilesViewMode,
  ) => {
    const targetSource = sourceOverride ?? viewMode;
    if (
      editingFile &&
      isDirty &&
      !activeEditorReadOnly &&
      (row.path !== editingFile.path || targetSource !== activeFileSource)
    ) {
      setPendingFileSwitch({ row, source: targetSource });
      return;
    }
    applyOpenFile(row, targetSource);
  };

  const confirmFileSwitch = () => {
    if (!pendingFileSwitch) return;
    const { row, source } = pendingFileSwitch;
    setPendingFileSwitch(null);
    applyOpenFile(row, source);
  };

  const cancelFileSwitch = () => {
    setPendingFileSwitch(null);
  };

  const handleCloseEditor = () => {
    setUserEdited(false);
    setEditContent("");
    setReloadCommand("");
    setOpenedFileMeta(null);
    setPendingFileSwitch(null);
    setPendingViewSwitch(null);
    setSplitView(false);
    const closedSource = activeFileSource;
    setActiveFileSource(viewMode);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("file");
      next.delete("edit");
      if (
        !next.get("path") &&
        fileParam &&
        fileParam.includes("/") &&
        closedSource === viewMode &&
        closedSource !== "logs"
      ) {
        const parentDir = fileParam.substring(0, fileParam.lastIndexOf("/"));
        if (parentDir) next.set("path", parentDir);
      }
      return next;
    }, { replace: true });
  };

  const navigateToDirectory = (dirPath: string) => {
    setUserEdited(false);
    setEditContent("");
    setCurrentPage(1);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("file");
      next.delete("edit");
      if (dirPath) next.set("path", dirPath);
      else next.delete("path");
      return next;
    });
  };

  const deleteMutation = useMutation({
    mutationFn: (path: string) =>
      activeBranch ? api.deleteServerFile(serverId!, path, activeBranch) : api.deleteServerFile(serverId!, path),
    onSuccess: () => {
      toast("success", "Item deleted");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      setFileToDelete(null);
    },
    onError: (err) => handleMutationError("Failed to delete item", err),
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: async (paths: string[]) => {
      for (const p of paths) {
        if (activeBranch) await api.deleteServerFile(serverId!, p, activeBranch);
        else await api.deleteServerFile(serverId!, p);
      }
      return paths.length;
    },
    onSuccess: (count) => {
      toast("success", "Items deleted", `Successfully deleted ${count} item(s).`);
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      setSelectedPaths(new Set());
      setShowBulkDelete(false);
    },
    onError: (err) => handleMutationError("Failed to delete selected items", err),
  });

  const uploadBatchMutation = useMutation({
    mutationFn: async (selectedFiles: File[]) => {
      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        setUploadProgress({ current: i + 1, total: selectedFiles.length, fileName: file.name });
        if (activeBranch) await api.uploadServerFile(serverId!, currentPath, file, activeBranch);
        else await api.uploadServerFile(serverId!, currentPath, file);
      }
      return selectedFiles.length;
    },
    onSuccess: (count) => {
      toast("success", count === 1 ? "File uploaded" : `${count} files uploaded`);
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
    },
    onError: (err) => handleMutationError("Failed to upload file", err),
    onSettled: () => {
      setUploadProgress(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
    },
  });

  const mkdirMutation = useMutation({
    mutationFn: (folderName: string) => {
      const fullPath = joinRelativePath(currentPath, folderName);
      return activeBranch
        ? api.mkdirServerDirectory(serverId!, fullPath, undefined, activeBranch)
        : api.mkdirServerDirectory(serverId!, fullPath);
    },
    onSuccess: () => {
      toast("success", "Folder created");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      setShowNewFolder(false);
    },
    onError: (err) => handleMutationError("Failed to create folder", err),
  });

  const newFileMutation = useMutation({
    mutationFn: async ({ fileName, initialContent }: { fileName: string; initialContent: string }) => {
      const fullPath = joinRelativePath(currentPath, fileName);
      if (activeBranch) await api.writeServerFileContent(serverId!, fullPath, initialContent, activeBranch);
      else await api.writeServerFileContent(serverId!, fullPath, initialContent);
      return fullPath;
    },
    onSuccess: (fullPath) => {
      toast("success", "File created");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      setShowNewFile(false);
      setUserEdited(false);
      setEditContent("");
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("file", fullPath);
        return next;
      });
    },
    onError: (err) => handleMutationError("Failed to create file", err),
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      activeBranch
        ? api.writeServerFileContent(serverId!, editingFile!.path, displayedContent, activeBranch)
        : api.writeServerFileContent(serverId!, editingFile!.path, displayedContent),
    onSuccess: () => {
      const targetPath = editingFile!.path;
      queryClient.setQueryData(queryKeys.files.content(serverId!, targetPath, activeBranch), {
        path: targetPath,
        content: displayedContent,
        is_binary: false,
      });
      setUserEdited(false);
      setEditContent(displayedContent);
      toast("success", `Saved ${editingFile!.name}`);
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
    },
    onError: (err) => handleMutationError("Failed to save file", err),
  });

  const liveStateSaveMutation = useMutation({
    mutationFn: () =>
      api.writeLiveStateFileContent(serverId!, {
        path: editingFile!.path,
        content: displayedContent,
        reload_command: reloadCommand || null,
      }),
    onSuccess: (res: LiveStateWriteResponse) => {
      const targetPath = editingFile!.path;
      queryClient.setQueryData(queryKeys.files.liveStateContent(serverId!, targetPath), (prev: unknown) => ({
        ...(typeof prev === "object" && prev !== null ? prev : {}),
        server_id: serverId,
        path: targetPath,
        content: displayedContent,
      }));
      setUserEdited(false);
      setEditContent(displayedContent);
      toast("success", res.rcon_reloaded ? `Saved & reloaded (${res.reload_command})` : "Saved to live state");
    },
    onError: (err) => handleMutationError("Failed to save file", err),
  });

  const commitMutation = useMutation({
    mutationFn: (message: string) => api.createServerCommit(serverId!, { message, branch_name: activeBranch }),
    onSuccess: (result) => {
      const commitId = typeof result.commit_id === "string" ? result.commit_id.slice(0, 12) : "new commit";
      const routed = Array.isArray(result.routed_to_cas) ? result.routed_to_cas.length : 0;
      const quarantined = Array.isArray(result.quarantined) ? result.quarantined.length : 0;
      const suffix = routed || quarantined ? ` · ${routed} routed to shared storage · ${quarantined} quarantined` : "";
      toast("success", "Changes committed", `${commitId} on ${activeBranch}${suffix}`);
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath, activeBranch) });
      queryClient.invalidateQueries({ queryKey: queryKeys.versioning.branches(serverId!) });
      setShowCommitDialog(false);
    },
    onError: (err) => handleMutationError("Failed to commit changes", err),
  });

  const handleDownload = async (
    file: Pick<FileItem, "name" | "path">,
    scopeOverride?: FilesViewMode,
  ) => {
    try {
      const effectiveScope = scopeOverride ?? viewMode;
      let blob: Blob;
      if (effectiveScope === "logs") {
        blob = await api.downloadServerFile(serverId!, file.path, activeBranch, "logs");
      } else if (effectiveScope === "live-state") {
        if (isBinaryFile(file.name)) {
          blob = await api.downloadServerFile(serverId!, file.path);
        } else {
          try {
            const liveContent = await api.readLiveStateFileContent(serverId!, file.path);
            blob = new Blob([liveContent.content], { type: "text/plain;charset=utf-8" });
          } catch {
            blob = await api.downloadServerFile(serverId!, file.path);
          }
        }
      } else {
        blob = activeBranch
          ? await api.downloadServerFile(serverId!, file.path, activeBranch)
          : await api.downloadServerFile(serverId!, file.path);
      }
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      handleMutationError("Download failed", err);
    }
  };

  const dropBlockedReason = isLogsView
    ? "Logs & Crashes is read-only — file upload is disabled here."
    : isNonMainLiveStateReadOnly
      ? "Live Data is read-only on non-main branches. Switch to 'main' or open Configs on a working branch."
      : isLiveState
        ? "Drag-and-drop upload is disabled in Live Data. Edit files inline instead."
        : readOnlyBranch
          ? "Branch 'main' is protected in Advanced Mode. Switch to a working branch to upload files."
          : null;

  const handleUploadFiles = (selected: File[]) => {
    if (selected.length === 0) return;
    if (dropBlockedReason) {
      toast("error", "Upload disabled", dropBlockedReason);
      return;
    }
    const existingNames = new Set((filesQuery.data ?? []).map((f) => f.name));
    const collisions = selected.filter((f) => existingNames.has(f.name)).map((f) => f.name);
    if (collisions.length > 0) {
      setPendingOverwrite({ files: selected, collisions });
      return;
    }
    uploadBatchMutation.mutate(selected);
  };

  const unifiedRows = useMemo<UnifiedFileRow[]>(() => {
    if (isLiveState) return (liveStateQuery.data?.items ?? []).map(toUnifiedFromLiveState);
    return (filesQuery.data ?? []).map(toUnifiedFromStandard);
  }, [isLiveState, liveStateQuery.data?.items, filesQuery.data]);

  const filteredAndSorted = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const filtered = q ? unifiedRows.filter((f) => f.name.toLowerCase().includes(q)) : unifiedRows;
    return sortFileRows(filtered, sortField, sortDirection);
  }, [unifiedRows, searchQuery, sortField, sortDirection]);

  const paginatedRows = useMemo(() => {
    if (filteredAndSorted.length <= FILES_PAGE_SIZE) return filteredAndSorted;
    const startIdx = (currentPage - 1) * FILES_PAGE_SIZE;
    return filteredAndSorted.slice(startIdx, startIdx + FILES_PAGE_SIZE);
  }, [filteredAndSorted, currentPage]);

  const allSelectablePaths = useMemo(() => paginatedRows.map((f) => f.path), [paginatedRows]);
  const isAllSelected = allSelectablePaths.length > 0 && allSelectablePaths.every((p) => selectedPaths.has(p));

  const pathParts = currentPath.split("/").filter(Boolean);
  const breadcrumbs = [
    { name: "root", path: "" },
    ...pathParts.map((part, idx) => ({ name: part, path: pathParts.slice(0, idx + 1).join("/") })),
  ];

  return {
    serverId,
    canAccessFiles,
    activeBranch,
    readOnlyBranch,
    currentPath,
    viewMode,
    isLiveState,
    isLogsView,
    isAdvancedMode,
    isNonMainLiveStateReadOnly,
    showViewSwitcher,
    splitView,
    setSplitView,
    splitRatio,
    updateSplitRatio,
    resetSplitRatio,
    activeFileSource,
    activeEditorIsLiveState,
    activeEditorIsLogs,
    activeEditorReadOnly,
    pendingFileSwitch,
    confirmFileSwitch,
    cancelFileSwitch,
    pendingViewSwitch,
    confirmViewSwitch,
    cancelViewSwitch,
    dropBlockedReason,
    editingFile,
    filesQuery,
    liveStateQuery,
    logsQuery,
    fileContentQuery,
    liveStateContentQuery,
    logContentQuery,
    displayedContent,
    isDirty,
    isBinary,
    searchQuery,
    setSearchQuery,
    sortField,
    setSortField,
    sortDirection,
    setSortDirection,
    currentPage,
    setCurrentPage,
    selectedPaths,
    setSelectedPaths,
    allSelectablePaths,
    isAllSelected,
    paginatedRows,
    filteredAndSorted,
    breadcrumbs,
    fileToDelete,
    setFileToDelete,
    showBulkDelete,
    setShowBulkDelete,
    showNewFile,
    setShowNewFile,
    showNewFolder,
    setShowNewFolder,
    showCommitDialog,
    setShowCommitDialog,
    reloadCommand,
    setReloadCommand,
    copiedPath,
    copyCurrentPath: () => {
      void copy(currentPath || "/", "Path copied to clipboard");
      setCopiedPath(true);
      setTimeout(() => setCopiedPath(false), 1800);
    },
    uploadProgress,
    pendingOverwrite,
    setPendingOverwrite,
    setEditContent,
    setUserEdited,
    switchView,
    updateCurrentPath,
    openFileEditor,
    handleCloseEditor,
    navigateToDirectory,
    handleDownload,
    handleUploadFiles,
    deleteMutation,
    bulkDeleteMutation,
    uploadBatchMutation,
    mkdirMutation,
    newFileMutation,
    saveMutation,
    liveStateSaveMutation,
    commitMutation,
  };
}
