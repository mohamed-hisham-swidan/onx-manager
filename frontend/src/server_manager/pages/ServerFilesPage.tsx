import React, { useState, useRef, useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { Icon } from "@/components/ui/Icon";
import { toast } from "@/stores/toastStore";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { LoadingBar } from "@/components/ui/LoadingBar";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { PageSkeleton } from "@/components/Skeleton";
import type { FileItem } from "@/server_manager/types";
import { CodeEditor } from "@/components/CodeEditor";

const NON_EDITABLE_EXTENSIONS = new Set([
  "dat", "mca", "mcr", "sqlite", "db", "nbt", "jar", "zip", "tar", "gz", "png", "jpg", "jpeg", "gif", "ico", "class"
]);

function isBinaryFile(fileName: string): boolean {
  const ext = fileName.split(".").pop()?.toLowerCase();
  return !!ext && NON_EDITABLE_EXTENSIONS.has(ext);
}

// Helper to format bytes
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
      <div className="flex flex-col h-full bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-3">
            <button
              onClick={handleCloseEditor}
              className="p-1 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700 rounded transition-colors"
            >
              <Icon name="chevron-left" />
            </button>
            <div>
              <nav
                aria-label="Editor breadcrumb"
                className={
                  "text-xs text-gray-500 dark:text-gray-400 font-mono " +
                  "flex items-center gap-1.5 flex-wrap"
                }
              >
                <button
                  type="button"
                  onClick={() => navigateToDirectory("")}
                  className="hover:text-blue-600 dark:hover:text-blue-400 hover:underline"
                >
                  /files
                </button>
                {editorPathParts.map((part, index) => {
                  const pathUpTo = editorPathParts.slice(0, index + 1).join("/");
                  return (
                    <span key={pathUpTo} className="flex items-center gap-1.5">
                      <span className="text-gray-400 dark:text-gray-600">/</span>
                      <button
                        type="button"
                        onClick={() => navigateToDirectory(pathUpTo)}
                        className="hover:text-blue-600 dark:hover:text-blue-400 hover:underline"
                      >
                        {part}
                      </button>
                    </span>
                  );
                })}
                <span className="text-gray-400 dark:text-gray-600">/</span>
                <span className="text-gray-700 dark:text-gray-300 font-medium">
                  {editingFile.name}
                </span>
              </nav>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Editing: {editingFile.name}
              </h2>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCloseEditor}
              className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700 transition-colors"
            >
              Cancel
            </button>
            {!isBinary && (
              <button
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending || isContentLoading || !!fileContentError}
                className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 transition-colors"
              >
                <Icon name="save" size={16} />
                {saveMutation.isPending ? "Saving..." : "Save"}
              </button>
            )}
          </div>
        </div>
        <div className="flex-1 p-4">
          {isContentLoading ? (
            <div className="h-64 flex items-center justify-center text-gray-500">Loading content...</div>
          ) : fileContentError ? (
            <div className="h-64 flex flex-col items-center justify-center text-center p-8 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg">
              <Icon name="alert" size={48} className="text-red-500 mb-3" />
              <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-1">
                Failed to load file
              </h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4 max-w-sm">
                {fileContentError instanceof Error ? fileContentError.message : "Unable to read file content"}
              </p>
              <button
                onClick={handleCloseEditor}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700 transition-colors"
              >
                Back to Files
              </button>
            </div>
          ) : isBinary ? (
            <div className="h-64 flex flex-col items-center justify-center text-center p-8 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg">
              <Icon name="file" size={48} className="text-gray-400 mb-3" />
              <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-1">Binary File</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4 max-w-sm">
                This file cannot be displayed or edited as text because it contains binary data.
              </p>
              <button
                onClick={() => handleDownload(editingFile)}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 transition-colors"
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

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="flex items-center overflow-x-auto whitespace-nowrap text-sm font-medium text-gray-600 dark:text-gray-300">
          {breadcrumbs.map((crumb, idx) => (
            <React.Fragment key={crumb.path}>
              <button
                onClick={() => updateCurrentPath(crumb.path)}
                className={`flex items-center gap-1 hover:text-blue-600 ` +
                  `dark:hover:text-blue-400 transition-colors ${
                    idx === breadcrumbs.length - 1
                      ? "font-semibold text-gray-900 dark:text-white"
                      : ""
                  }`}
              >
                {idx === 0 && <Icon name="folder" size={16} className="text-blue-500" />}
                <span>{crumb.name}</span>
              </button>
              {idx < breadcrumbs.length - 1 && (
                <span className="mx-2 text-gray-400">/</span>
              )}
            </React.Fragment>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            onChange={(e) => {
              if (e.target.files && e.target.files[0]) {
                uploadMutation.mutate(e.target.files[0]);
              }
              // Reset input so the same file can be uploaded again if needed
              e.target.value = "";
            }}
          />
          <button
            onClick={() => setShowNewFolder(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700 transition-colors"
          >
            <Icon name="folder" size={16} />
            New Folder
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 transition-colors"
          >
            <Icon name="upload" size={16} />
            {uploadMutation.isPending ? "Uploading..." : "Upload File"}
          </button>
        </div>
      </div>

      {showNewFolder && (
        <div className="flex items-center gap-2 p-4 bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
          <Icon name="folder" className="text-gray-400" />
          <input
            type="text"
            placeholder="Folder name"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500 dark:bg-gray-900 dark:border-gray-600 dark:text-white"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && newFolderName) mkdirMutation.mutate(newFolderName);
              if (e.key === "Escape") {
                setShowNewFolder(false);
                setNewFolderName("");
              }
            }}
          />
          <button
            onClick={() => mkdirMutation.mutate(newFolderName)}
            disabled={!newFolderName || mkdirMutation.isPending}
            className="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded disabled:opacity-50"
          >
            Create
          </button>
          <button
            onClick={() => {
              setShowNewFolder(false);
              setNewFolderName("");
            }}
            className="px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700 rounded transition-colors"
          >
            Cancel
          </button>
        </div>
      )}

      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
        {files?.length === 0 && !currentPath ? (
          <EmptyState
            title="Empty Directory"
            description="No files found in this folder."
            icon="folder"
            action={
              <button
                onClick={() => fileInputRef.current?.click()}
                className="mt-4 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              >
                Upload File
              </button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-gray-500 dark:text-gray-400">
              <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700/50 dark:text-gray-300 border-b border-gray-200 dark:border-gray-700">
                <tr>
                  <th scope="col" className="px-6 py-3 font-medium">Name</th>
                  <th scope="col" className="px-6 py-3 font-medium w-32">Size</th>
                  <th scope="col" className="px-6 py-3 font-medium w-32 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {currentPath && (
                  <tr
                    className="hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors cursor-pointer"
                    onClick={navigateUp}
                  >
                    <td className="px-6 py-4 flex items-center gap-3">
                      <Icon name="folder" className="text-blue-500" />
                      <span className="font-medium text-gray-900 dark:text-white">..</span>
                    </td>
                    <td className="px-6 py-4">-</td>
                    <td className="px-6 py-4 text-right"></td>
                  </tr>
                )}
                {files?.map((file) => (
                  <tr key={file.path} className="hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors group">
                    <td className="px-6 py-4">
                      <div
                        className="flex items-center gap-3 cursor-pointer"
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
                          className={file.is_dir ? "text-blue-500" : "text-gray-400"}
                        />
                        <span className="font-medium text-gray-900 dark:text-white truncate max-w-[200px] sm:max-w-xs md:max-w-sm">
                          {file.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {file.is_dir ? "-" : formatBytes(file.size)}
                    </td>
                    <td className="px-6 py-4 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                        {!file.is_dir && (
                          <button
                            onClick={() => handleDownload(file)}
                            className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:text-blue-400 dark:hover:bg-blue-900/30 rounded transition-colors"
                            title="Download"
                          >
                            <Icon name="download" size={16} />
                          </button>
                        )}
                        {!file.is_dir && !isBinaryFile(file.name) && (
                          <button
                            onClick={() => openFileEditor(file)}
                            className="p-1.5 text-gray-500 hover:text-green-600 hover:bg-green-50 dark:hover:text-green-400 dark:hover:bg-green-900/30 rounded transition-colors"
                            title="Edit"
                          >
                            <Icon name="edit" size={16} />
                          </button>
                        )}
                        <button
                          onClick={() => setFileToDelete(file)}
                          className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 dark:hover:text-red-400 dark:hover:bg-red-900/30 rounded transition-colors"
                          title="Delete"
                        >
                          <Icon name="trash" size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!fileToDelete}
        title={fileToDelete?.is_dir ? "Delete Folder" : "Delete File"}
        description={`Are you sure you want to delete ${fileToDelete?.name}? ${fileToDelete?.is_dir ? "All contents will be permanently deleted. " : ""}This action cannot be undone.`}
        confirmLabel={deleteMutation.isPending ? "Deleting..." : "Delete"}
        onConfirm={() => fileToDelete && deleteMutation.mutate(fileToDelete.path)}
        onCancel={() => setFileToDelete(null)}
      />
    </div>
  );
}
