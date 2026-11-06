import React, { useState, useRef, useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { Icon } from "@/components/ui/Icon";
import { Button, IconButton } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Pagination } from "@/components/ui/Pagination";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { LoadingBar } from "@/components/ui/LoadingBar";
import { PageSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import type { FileItem } from "@/server_manager/types";
import { CodeEditor } from "@/components/CodeEditor";

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
  const currentPath = searchParams.get("path") || "";
  const fileParam = searchParams.get("file") || searchParams.get("edit");
  const [editContent, setEditContent] = useState("");
  const [userEdited, setUserEdited] = useState(false);
  const [fileToDelete, setFileToDelete] = useState<FileItem | null>(null);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
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

  const { data: files, isLoading, error } = useQuery({
    queryKey: queryKeys.files.list(serverId!, currentPath),
    queryFn: () => api.listServerFiles(serverId!, currentPath),
    enabled: !!serverId,
  });

  const { data: fileContentData, isLoading: isContentLoading, error: fileContentError } = useQuery({
    queryKey: queryKeys.files.content(serverId!, editingFile?.path ?? ""),
    queryFn: async () => {
      const res = await api.readServerFileContent(serverId!, editingFile!.path);
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

  const handleMutationError = (defaultTitle: string, err: Error) => {
    if (err instanceof ApiError && err.status === 403) {
      toast("error", "Permission Denied", "You do not have permission to perform this action on this server.");
    } else {
      toast("error", defaultTitle, err.message);
    }
  };

  const deleteMutation = useMutation({
    mutationFn: (path: string) => api.deleteServerFile(serverId!, path),
    onSuccess: () => {
      toast("success", "File deleted");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath) });
      setFileToDelete(null);
    },
    onError: (err: Error) => {
      handleMutationError("Failed to delete file", err);
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.uploadServerFile(serverId!, currentPath, file),
    onSuccess: () => {
      toast("success", "File uploaded");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath) });
    },
    onError: (err: Error) => {
      handleMutationError("Failed to upload file", err);
    },
  });

  const mkdirMutation = useMutation({
    mutationFn: (folderName: string) => {
      const fullPath = currentPath ? `${currentPath}/${folderName}` : folderName;
      return api.mkdirServerDirectory(serverId!, fullPath);
    },
    onSuccess: () => {
      toast("success", "Folder created");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.list(serverId!, currentPath) });
      setShowNewFolder(false);
      setNewFolderName("");
    },
    onError: (err: Error) => {
      handleMutationError("Failed to create folder", err);
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => api.writeServerFileContent(serverId!, editingFile!.path, displayedContent),
    onSuccess: () => {
      toast("success", "File saved");
      queryClient.invalidateQueries({ queryKey: queryKeys.files.content(serverId!, editingFile!.path) });
      handleCloseEditor();
    },
    onError: (err: Error) => {
      handleMutationError("Failed to save file", err);
    },
  });

  const handleDownload = async (file: FileItem) => {
    try {
      const blob = await api.downloadServerFile(serverId!, file.path);
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

  if (isLoading && !files) return <PageSkeleton />;
  if (error) return <ErrorState message={error.message} />;

  const pathParts = currentPath.split("/").filter(Boolean);
  const breadcrumbs = [
    { name: "/files", path: "" },
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
                  /files
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
            {!isBinary && (
              <Button
                variant="primary"
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending || isContentLoading || !!fileContentError}
                loading={saveMutation.isPending}
                icon="save"
              >
                Save
              </Button>
            )}
          </div>
        </div>
        <div className="flex-1 p-4">
          {isContentLoading ? (
            <div className="h-64 flex items-center justify-center text-text-muted">Loading content...</div>
          ) : fileContentError ? (
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
              value={displayedContent}
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
    <div className="flex flex-col space-y-4">
      {isLoading && <LoadingBar />}

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
        </div>
      </div>

      {showNewFolder && (
        <div className="flex items-center gap-2 p-4 bg-surface-card rounded-xl shadow-sm border border-border-default">
          <Icon name="folder" className="text-text-muted" />
          <input
            type="text"
            placeholder="Folder name"
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

      {/* File Browser Table */}
      <div className="bg-surface-card rounded-xl shadow-sm border border-border-default overflow-hidden">
        {files?.length === 0 && !currentPath ? (
          <EmptyState
            title="Empty Directory"
            description="No files found in this folder."
            icon="folder"
            action={{
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
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="text-xs uppercase bg-surface-page/50 text-text-muted border-b border-border-subtle tracking-wider font-semibold">
                <tr>
                  <th scope="col" className="px-4 py-2.5">Name</th>
                  <th scope="col" className="px-4 py-2.5 w-32">Size</th>
                  <th scope="col" className="px-4 py-2.5 w-32 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {currentPath && (
                  <tr className="hover:bg-surface-hover/50 transition-colors">
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
                        {!file.is_dir && (
                          <IconButton
                            icon="download"
                            aria-label="Download"
                            size="sm"
                            variant="ghost"
                            onClick={() => handleDownload(file)}
                          />
                        )}
                        {!file.is_dir && !isBinaryFile(file.name) && (
                          <IconButton
                            icon="edit"
                            aria-label="Edit"
                            size="sm"
                            variant="ghost"
                            onClick={() => openFileEditor(file)}
                          />
                        )}
                        <IconButton
                          icon="trash"
                          aria-label="Delete"
                          size="sm"
                          variant="ghost"
                          onClick={() => setFileToDelete(file)}
                        />
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
