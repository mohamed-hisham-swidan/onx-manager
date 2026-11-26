import { useState, useMemo, useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useServersList } from "@/server_manager/hooks/useServers";
import {
  usePluginsList,
  useEnablePlugin,
  useDisablePlugin,
  useUninstallPlugin,
  useUploadPluginOrMod,
} from "@/server_manager/hooks/usePlugins";
import { useFleetPermissions } from "@/server_manager/components/servers/serversUtils";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Pagination } from "@/components/ui/Pagination";
import { TableSkeleton } from "@/components/Skeleton";
import { ViewModeToggle } from "@/components/ui/ViewModeToggle";
import { toast } from "@/stores/toastStore";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import type { PluginResponse } from "@/types";

const PAGE_SIZE = 15;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function isPluginEnabled(plugin: PluginResponse): boolean {
  if (plugin.is_disabled_on_disk) return false;
  const status = (plugin.status || "").toLowerCase();
  return status === "enabled" || status === "installed";
}

export interface ParsedPluginMetadata {
  title: string;
  version: string;
  author: string;
  loaders: string[];
}

function formatPluginTitle(raw: string): string {
  if (!raw) return "";
  const parts = raw.split(/[-_]+/).filter(Boolean);
  if (parts.length === 0) return raw;
  return parts
    .map((p) => {
      const lower = p.toLowerCase();
      if (lower === "veinminer") return "VeinMiner";
      if (lower === "viaversion") return "ViaVersion";
      if (lower === "worldedit") return "WorldEdit";
      if (lower === "worldguard") return "WorldGuard";
      if (lower === "essentialsx") return "EssentialsX";
      // If already mixed case (e.g. McMMO, ViaBackwards), preserve
      if (p !== lower && p !== p.toUpperCase()) {
        return p;
      }
      if (p === lower) {
        return p.charAt(0).toUpperCase() + p.slice(1);
      }
      return p;
    })
    .join(" ");
}

// eslint-disable-next-line react-refresh/only-export-components
export function parsePluginMetadata(plugin: PluginResponse): ParsedPluginMetadata {
  const rawName = plugin.name?.trim() || "";
  const rawFilename = plugin.filename || (plugin as { file_name?: string | null }).file_name || "";
  const isSemverLike = /^v?\d+(\.\d+)+/i.test(rawName);
  const endsWithJar = /\.jar(?:\.disabled)?$/i.test(rawName);
  const isSuspiciousName = !rawName || isSemverLike || endsWithJar;

  let title = rawName;
  let version = plugin.version || "";

  if (isSuspiciousName && rawFilename) {
    let clean = rawFilename.replace(/\.disabled$/i, "").replace(/\.jar$/i, "");
    clean = clean.replace(/[-_](spigot|paper|purpur|bukkit|fabric|forge)$/i, "");
    const match = clean.match(/^(.*?)[-_+ ]v?(\d+(?:\.\d+)*(?:-[\w.]+)?)$/i);
    if (match) {
      title = formatPluginTitle(match[1]);
      if (!version || version === "unknown") {
        version = match[2];
      }
    } else {
      title = formatPluginTitle(clean);
    }
  } else if (isSuspiciousName && !rawFilename) {
    if (endsWithJar) {
      let clean = rawName.replace(/\.disabled$/i, "").replace(/\.jar$/i, "");
      clean = clean.replace(/[-_](spigot|paper|purpur|bukkit|fabric|forge)$/i, "");
      const match = clean.match(/^(.*?)[-_+ ]v?(\d+(?:\.\d+)*(?:-[\w.]+)?)$/i);
      if (match) {
        title = formatPluginTitle(match[1]);
        if (!version || version === "unknown") version = match[2];
      } else {
        title = formatPluginTitle(clean);
      }
    } else if (isSemverLike) {
      title = `Plugin ${rawName}`;
      if (!version || version === "unknown") version = rawName;
    }
  }

  // Ensure title is never empty or bare semver
  if (!title || /^v?\d+(\.\d+)+$/i.test(title)) {
    title = rawFilename
      ? formatPluginTitle(rawFilename.replace(/\.disabled$/i, "").replace(/\.jar$/i, ""))
      : "Unnamed Plugin";
  }

  const author = plugin.author?.trim() || "";

  // Derive loaders
  const loaders: string[] = [];
  if (plugin.loader) {
    loaders.push(plugin.loader.charAt(0).toUpperCase() + plugin.loader.slice(1));
  }
  const searchStr = `${rawFilename} ${rawName}`.toLowerCase();
  if (searchStr.includes("paper") && !loaders.some((l) => l.toLowerCase() === "paper")) {
    loaders.push("Paper");
  }
  if (searchStr.includes("purpur") && !loaders.some((l) => l.toLowerCase() === "purpur")) {
    loaders.push("Purpur");
  }
  if (searchStr.includes("spigot") && !loaders.some((l) => l.toLowerCase() === "spigot")) {
    loaders.push("Spigot");
  }
  if (searchStr.includes("bukkit") && !loaders.some((l) => l.toLowerCase() === "bukkit")) {
    loaders.push("Bukkit");
  }

  return {
    title,
    version,
    author,
    loaders,
  };
}

function SourceBadge({ plugin }: { plugin: PluginResponse }) {
  if (plugin.source === "modrinth") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-accent-primary/20 px-2 py-0.5 text-xs font-medium text-accent-primary border border-accent-primary/30">
        <Icon name="external" size={12} />
        Marketplace
      </span>
    );
  }
  if (plugin.source === "detected") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-surface-page px-2 py-0.5 text-xs font-medium text-text-secondary border border-border-default">
        Detected on disk
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-status-warning-bg px-2 py-0.5 text-xs font-medium text-status-warning border border-status-warning/30">
      Manual
    </span>
  );
}

export function PluginListPage() {
  const { serverId: routeServerId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const { data: servers } = useServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);
  const [touched, setTouched] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState("");
  const [uninstallTarget, setUninstallTarget] = useState<PluginResponse | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "list">(() => {
    try {
      const saved = localStorage.getItem("onx_plugins_view_mode");
      if (saved === "grid" || saved === "list") return saved;
    } catch {
      // ignore
    }
    return "grid";
  });

  const pluginServers = useMemo(
    () => (servers ?? []).filter((s) => getServerCapabilities(s.server_type).supportsPlugins),
    [servers],
  );

  const effectiveServerId = routeServerId
    ? routeServerId
    : touched
      ? selectedServerId
      : lastUsedServerId && pluginServers.some((s) => s.server_id === lastUsedServerId)
        ? lastUsedServerId
        : selectedServerId;

  const activeServer = servers?.find((s) => s.server_id === effectiveServerId);
  const activeServerType = activeServer?.server_type;
  const capabilities = getServerCapabilities(activeServerType);
  const isNonPluginServer = Boolean(activeServerType) && !capabilities.supportsPlugins;

  const branchCtx = useServerBranchContext();
  const gitBacked = Boolean(branchCtx?.gitBacked);
  const activeBranch = gitBacked ? branchCtx?.branch : undefined;
  const isMainProtected = Boolean(gitBacked && activeBranch === "main");
  const isWorkingBranch = Boolean(gitBacked && activeBranch && activeBranch !== "main");

  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useQueryClient();
  const branchesQuery = useQuery({
    queryKey: queryKeys.versioning.branches(effectiveServerId),
    queryFn: () => api.getServerBranches(effectiveServerId),
    enabled: Boolean(effectiveServerId && gitBacked),
  });
  const firstWorkingBranch = useMemo(
    () => (branchesQuery.data ?? []).find((b) => b.name !== "main")?.name ?? null,
    [branchesQuery.data],
  );

  const [quickBranchName, setQuickBranchName] = useState("");
  const createBranchMutation = useMutation({
    mutationFn: (name: string) =>
      api.createServerBranch(effectiveServerId, { name }),
    onSuccess: (_created, branchName) => {
      setQuickBranchName("");
      queryClient.invalidateQueries({ queryKey: queryKeys.versioning.branches(effectiveServerId) });
      branchCtx?.setBranch(branchName);
      toast("success", "Branch created", `Switched to working branch "${branchName}".`);
    },
    onError: (err) => toast("error", "Create branch failed", errorMessage(err)),
  });

  const commitLockfileMutation = useMutation({
    mutationFn: () =>
      api.createServerCommit(effectiveServerId, {
        branch_name: activeBranch!,
        message: "Update branch plugins lockfile",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.plugins.list(effectiveServerId, activeBranch),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.versioning.commits(effectiveServerId) });
      toast("success", "Changes committed", `Committed plugin changes to "${activeBranch}".`);
    },
    onError: (err) => toast("error", "Commit failed", errorMessage(err)),
  });

  const { data: plugins, isLoading, error } = usePluginsList(
    isNonPluginServer ? "" : effectiveServerId,
    activeBranch,
  );
  const enablePlugin = useEnablePlugin(effectiveServerId, activeBranch);
  const disablePlugin = useDisablePlugin(effectiveServerId, activeBranch);
  const uninstallPlugin = useUninstallPlugin(effectiveServerId, activeBranch);
  const uploadPlugin = useUploadPluginOrMod(effectiveServerId, activeBranch);
  const permissions = useFleetPermissions();
  const canManagePlugins = Boolean(effectiveServerId && permissions.canManagePlugins(effectiveServerId));
  const canDropUploadJar = Boolean(
    effectiveServerId && canManagePlugins && !isMainProtected && !isNonPluginServer,
  );
  const jarInputRef = useRef<HTMLInputElement>(null);
  const dragCounterRef = useRef(0);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [isBlockedDragOver, setIsBlockedDragOver] = useState(false);
  const [uploadBatchState, setUploadBatchState] = useState<{
    current: number;
    total: number;
    fileName: string;
  } | null>(null);
  const hasUncommitted = Boolean(
    isWorkingBranch &&
      (plugins?.some((p) => p.is_committed === false) ||
        Boolean((plugins as { __hasUncommitted?: boolean } | undefined)?.__hasUncommitted)),
  );

  const filteredPlugins = useMemo(() => {
    if (!plugins) return [];
    if (!searchQuery.trim()) return plugins;
    const q = searchQuery.toLowerCase().trim();
    return plugins.filter((p) => {
      const meta = parsePluginMetadata(p);
      const matchName = p.name.toLowerCase().includes(q) || meta.title.toLowerCase().includes(q);
      const matchDesc = p.description?.toLowerCase().includes(q);
      const matchFile = (p.filename || (p as { file_name?: string | null }).file_name)?.toLowerCase().includes(q);
      const matchAuthor = p.author?.toLowerCase().includes(q) || meta.author.toLowerCase().includes(q);
      return matchName || matchDesc || matchFile || matchAuthor;
    });
  }, [plugins, searchQuery]);

  const paginatedPlugins = useMemo(() => {
    if (!filteredPlugins || filteredPlugins.length <= PAGE_SIZE) return filteredPlugins;
    const startIdx = (currentPage - 1) * PAGE_SIZE;
    return filteredPlugins.slice(startIdx, startIdx + PAGE_SIZE);
  }, [filteredPlugins, currentPage]);

  function handleServerChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setTouched(true);
    setSelectedServerId(e.target.value);
    setCurrentPage(1);
  }

  function handleInstall() {
    if (!canManagePlugins || isMainProtected) return;
    if (routeServerId) {
      const branchQuery =
        isWorkingBranch && activeBranch ? `?branch=${encodeURIComponent(activeBranch)}` : "";
      navigate(`/servers/${encodeURIComponent(effectiveServerId)}/plugins/marketplace${branchQuery}`);
      return;
    }
    const branchSuffix = isWorkingBranch && activeBranch ? `&branch=${encodeURIComponent(activeBranch)}` : "";
    navigate(`/marketplace?server=${encodeURIComponent(effectiveServerId)}${branchSuffix}`);
  }

  function handleConfirmUninstall() {
    if (!uninstallTarget || isMainProtected) return;
    uninstallPlugin.mutate(uninstallTarget.plugin_id, {
      onSuccess: () =>
        toast(
          "success",
          "Removal requested",
          `"${uninstallTarget.name}" will be removed on the next server restart.`,
        ),
      onError: (err) => toast("error", "Remove failed", errorMessage(err)),
      onSettled: () => setUninstallTarget(null),
    });
  }

  async function handleJarFiles(files: File[]) {
    if (!effectiveServerId || files.length === 0) return;
    if (isMainProtected) {
      toast("error", "Branch protected", "Switch to a working branch before uploading plugins.");
      return;
    }
    if (!canManagePlugins) return;

    const jarFiles: File[] = [];
    for (const file of files) {
      if (file.name.toLowerCase().endsWith(".jar")) {
        jarFiles.push(file);
      } else {
        toast(
          "error",
          "Invalid file type",
          `"${file.name}" is not a .jar file. Drop valid Minecraft plugin .jar files here.`,
        );
      }
    }
    if (jarFiles.length === 0) return;

    try {
      for (let i = 0; i < jarFiles.length; i++) {
        const file = jarFiles[i];
        setUploadBatchState({ current: i + 1, total: jarFiles.length, fileName: file.name });
        try {
          const res = await uploadPlugin.mutateAsync(file);
          const installedName = typeof res?.name === "string" && res.name ? res.name : file.name;
          toast(
            "success",
            "Plugin uploaded",
            isWorkingBranch && activeBranch
              ? `Validated & staged "${installedName}" on branch "${activeBranch}".`
              : `Validated & installed "${installedName}".`,
          );
        } catch (err) {
          toast("error", `Failed to upload ${file.name}`, errorMessage(err));
        }
      }
    } finally {
      setUploadBatchState(null);
    }
  }

  function handleDragEnter(e: React.DragEvent<HTMLDivElement>) {
    if (!effectiveServerId || !e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    if (canDropUploadJar) {
      setIsDraggingOver(true);
    } else if (isMainProtected && canManagePlugins) {
      setIsBlockedDragOver(true);
    }
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    if (!effectiveServerId || !e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = canDropUploadJar ? "copy" : "none";
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
    if (dragCounterRef.current === 0) {
      setIsDraggingOver(false);
      setIsBlockedDragOver(false);
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    if (!effectiveServerId || !e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDraggingOver(false);
    setIsBlockedDragOver(false);
    if (!canDropUploadJar) return;
    const dropped = e.dataTransfer.files ? Array.from(e.dataTransfer.files) : [];
    if (dropped.length > 0) {
      void handleJarFiles(dropped);
    }
  }

  return (
    <div
      data-testid="plugins-dropzone"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className="relative space-y-6"
    >
      <input
        type="file"
        accept=".jar"
        multiple
        ref={jarInputRef}
        aria-label="Upload plugin JAR"
        className="hidden"
        onChange={(e) => {
          const selected = e.target.files ? Array.from(e.target.files) : [];
          if (selected.length > 0) void handleJarFiles(selected);
          e.target.value = "";
        }}
      />

      {isDraggingOver && canDropUploadJar && (
        <div
          data-testid="plugins-jar-drop-overlay"
          className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-accent-primary bg-surface-card/95 p-8 text-center backdrop-blur-xs"
        >
          <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-accent-primary/15 text-accent-primary">
            <Icon name="upload" size={24} />
          </div>
          <p className="text-sm font-semibold text-text-primary">
            Drop .jar plugin file(s) to validate &amp; install
            {isWorkingBranch && activeBranch ? ` on branch "${activeBranch}"` : ""}
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Validates plugin.yml, paper-plugin.yml, bungee.yml, or velocity-plugin.json before installing
          </p>
        </div>
      )}

      <PageHeader
        title="Plugins"
        description={
          gitBacked && activeBranch
            ? `Manage plugins for branch "${activeBranch}"`
            : "Manage plugins for your servers"
        }
        icon="plugin"
        actions={
          effectiveServerId ? (
            <div className="flex flex-wrap items-center gap-2">
              {!isNonPluginServer && canManagePlugins && (
                <button
                  type="button"
                  data-testid="plugins-upload-jar-btn"
                  disabled={isMainProtected || uploadBatchState !== null}
                  onClick={() => jarInputRef.current?.click()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3.5 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shadow-xs"
                >
                  <Icon name="upload" size={16} />
                  <span>Upload .jar</span>
                </button>
              )}
              {!isNonPluginServer && (
                <button
                  type="button"
                  disabled={isMainProtected || !canManagePlugins}
                  onClick={handleInstall}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-semibold text-accent-contrast-text transition-colors hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shadow-xs"
                >
                  <Icon name="plus" size={16} />
                  Install Plugin
                </button>
              )}
            </div>
          ) : undefined
        }
      />

      {isBlockedDragOver && isMainProtected && effectiveServerId && (
        <div
          data-testid="plugins-drop-main-blocked-notice"
          className="flex items-center gap-2 rounded-xl border border-status-warning-border bg-status-warning-bg px-4 py-2.5 text-xs font-medium text-status-warning"
        >
          <Icon name="lock" size={14} />
          <span>
            Uploading plugins is disabled on protected branch &ldquo;main&rdquo;. Switch to or create a working branch first.
          </span>
        </div>
      )}

      {uploadBatchState && (
        <div
          data-testid="plugins-upload-progress"
          className="flex flex-col gap-1.5 rounded-xl border border-border-subtle bg-surface-muted px-4 py-2.5 text-xs"
        >
          <div className="flex items-center justify-between gap-2 text-text-secondary">
            <span className="truncate font-medium">
              Validating &amp; uploading {uploadBatchState.current} of {uploadBatchState.total}: {uploadBatchState.fileName}
            </span>
            <span className="font-mono tabular-nums text-text-muted shrink-0">
              {Math.round((uploadBatchState.current / uploadBatchState.total) * 100)}%
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-card">
            <div
              className="h-full rounded-full bg-accent-primary transition-all duration-200"
              style={{
                width: `${Math.min(100, Math.round((uploadBatchState.current / uploadBatchState.total) * 100))}%`,
              }}
            />
          </div>
        </div>
      )}

      {isMainProtected && effectiveServerId && (
        <div
          data-testid="plugins-main-protected-banner"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-warning-border bg-status-warning-bg px-4 py-3 text-xs text-text-primary"
        >
          <div className="space-y-0.5">
            <p className="font-semibold text-status-warning">
              Branch &ldquo;main&rdquo; is protected
            </p>
            <p className="text-text-secondary">
              Plugin installs, toggles, and removals cannot mutate main directly. Switch to or create a working branch to edit plugins, then merge via Versioning.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {firstWorkingBranch && (
              <button
                type="button"
                data-testid="plugins-switch-working-branch-btn"
                onClick={() => branchCtx?.setBranch(firstWorkingBranch)}
                className="inline-flex items-center gap-1 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer"
              >
                Switch to {firstWorkingBranch}
              </button>
            )}
            <input
              type="text"
              value={quickBranchName}
              onChange={(e) => setQuickBranchName(e.target.value)}
              placeholder="plugin-test"
              aria-label="New working branch name"
              className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs text-text-primary focus:border-accent-primary focus:outline-none"
            />
            <button
              type="button"
              data-testid="plugins-create-working-branch-btn"
              disabled={!quickBranchName.trim() || createBranchMutation.isPending}
              onClick={() => createBranchMutation.mutate(quickBranchName.trim())}
              className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs font-semibold text-text-primary hover:bg-surface-hover disabled:opacity-50 cursor-pointer"
            >
              {createBranchMutation.isPending ? "Creating..." : "Create Working Branch"}
            </button>
          </div>
        </div>
      )}

      {hasUncommitted && effectiveServerId && (
        <div
          data-testid="plugins-uncommitted-banner"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-info-border bg-status-info-bg px-4 py-3 text-xs text-text-primary"
        >
          <div>
            <p className="font-semibold text-status-info">
              Uncommitted changes on &ldquo;{activeBranch}&rdquo;
            </p>
            <p className="text-text-secondary">
              Save &amp; commit your changes before testing or merging this branch.
            </p>
          </div>
          <button
            type="button"
            data-testid="plugins-commit-btn"
            disabled={commitLockfileMutation.isPending}
            onClick={() => commitLockfileMutation.mutate()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer"
          >
            <Icon name="check" size={14} />
            {commitLockfileMutation.isPending ? "Committing..." : "Save & Commit"}
          </button>
        </div>
      )}

      {!routeServerId && (
        <div className="max-w-xs">
          <label className="sr-only" htmlFor="plugin-server-select">
            Choose a server
          </label>
          <select
            id="plugin-server-select"
            value={effectiveServerId}
            onChange={handleServerChange}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
          >
            <option value="">Select a server...</option>
            {pluginServers.map((s) => (
              <option key={s.server_id} value={s.server_id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {effectiveServerId && !isNonPluginServer && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle pb-3">
          {/* Segmented Tabs */}
          <div className="flex items-center gap-1 rounded-lg border border-border-subtle bg-surface-page p-1">
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md bg-surface-card px-3 py-1.5 text-xs font-semibold text-text-primary shadow-2xs border border-border-subtle"
            >
              <Icon name="plugin" size={14} className="text-accent-primary" />
              <span>Installed Plugins</span>
              {plugins && (
                <span className="rounded-full bg-surface-elevated px-1.5 py-0.2 text-[10px] font-mono text-text-secondary border border-border-subtle">
                  {plugins.length}
                </span>
              )}
            </button>
          </div>

          {/* Controls: Search & ViewMode */}
          <div className="flex items-center gap-2">
            <div className="relative min-w-[200px] sm:min-w-[260px]">
              <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-2.5 text-text-muted">
                <Icon name="search" size={13} />
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setCurrentPage(1);
                }}
                placeholder="Filter installed plugins..."
                aria-label="Filter installed plugins"
                className="h-8.5 w-full rounded-lg border border-border-default bg-surface-page ps-8 pe-3 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute inset-y-0 end-0 flex items-center pe-2.5 text-text-muted hover:text-text-primary cursor-pointer"
                  aria-label="Clear filter"
                >
                  <Icon name="x" size={12} />
                </button>
              )}
            </div>

            <ViewModeToggle
              mode={viewMode}
              onChange={setViewMode}
              storageKey="onx_plugins_view_mode"
            />
          </div>
        </div>
      )}

      {!effectiveServerId ? (
        <EmptyState
          icon="plugin"
          title="Select a server"
          description="Choose a server above to view its plugins."
        />
      ) : isNonPluginServer ? (
        <div
          data-testid="non-plugin-server-guard"
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-info-border bg-status-info-bg px-4 py-4 text-sm text-text-primary"
        >
          <div className="flex items-center gap-2.5">
            <Icon name="info" size={18} className="shrink-0 text-status-info" />
            <span>
              {capabilities.supportsMods ? (
                <>
                  This server runs <span className="font-semibold">{activeServerType}</span>, which
                  supports mods instead of Bukkit/Paper plugins.
                </>
              ) : (
                <>
                  This server runs <span className="font-semibold">{activeServerType}</span>, which
                  does not support plugins or mods.
                </>
              )}
            </span>
          </div>
          {capabilities.supportsMods && (
            <Link
              to={`/servers/${encodeURIComponent(effectiveServerId)}/mods${
                isWorkingBranch && activeBranch ? `?branch=${encodeURIComponent(activeBranch)}` : ""
              }`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover transition-colors"
            >
              <Icon name="plugin" size={14} />
              Manage Mods
            </Link>
          )}
        </div>
      ) : isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : error ? (
        <ErrorState message={error instanceof Error ? error.message : "Failed to load plugins"} />
      ) : plugins && plugins.length > 0 ? (
        filteredPlugins.length === 0 ? (
          <EmptyState
            icon="search"
            title="No matching plugins"
            description={`No installed plugins matched "${searchQuery}".`}
            action={{
              label: "Clear Filter",
              onClick: () => setSearchQuery(""),
            }}
          />
        ) : viewMode === "grid" ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {paginatedPlugins.map((p) => {
                const meta = parsePluginMetadata(p);
                const isEnabled = isPluginEnabled(p);
                const filename = p.filename || (p as { file_name?: string | null }).file_name;
                const toggleLabel = isEnabled ? `Disable ${p.name}` : `Enable ${p.name}`;
                const uninstallLabel = `Uninstall ${p.name}`;

                return (
                  <div
                    key={p.plugin_id}
                    className="group relative flex h-full flex-col justify-between rounded-lg border border-border-subtle bg-surface-card p-4 transition-colors duration-150 hover:border-border-default"
                  >
                    <div>
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 flex-1 items-start gap-3">
                          {p.icon_url ? (
                            <img
                              src={p.icon_url}
                              alt={`${p.name} icon`}
                              className="h-11 w-11 shrink-0 rounded-lg bg-surface-page object-cover border border-border-subtle"
                            />
                          ) : (
                            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-border-subtle bg-surface-page text-text-muted font-bold text-sm select-none">
                              {meta.title.slice(0, 2).toUpperCase()}
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <h3 className="truncate text-[15px] font-semibold text-text-primary" title={meta.title}>
                              {meta.title}
                            </h3>
                            <div className="mt-1 flex flex-wrap items-center gap-1.5">
                              {meta.version && meta.version !== "unknown" && (
                                <span
                                  className="font-mono text-xs text-text-muted"
                                  title={isWorkingBranch && p.checksum ? `sha256:${p.checksum}` : undefined}
                                >
                                  v{meta.version}
                                </span>
                              )}
                              {p.author && (
                                <span className="text-xs text-text-muted">by {p.author}</span>
                              )}
                              {isWorkingBranch && p.is_committed === false && (
                                <span
                                  data-testid={`plugin-commit-badge-${p.plugin_id}`}
                                  className="inline-flex items-center rounded-full border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[10px] font-medium text-status-warning"
                                >
                                  Uncommitted
                                </span>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Interactive Enable / Disable Toggle Switch */}
                        <div className="flex items-center gap-2 shrink-0">
                          <button
                            type="button"
                            role="switch"
                            aria-checked={isEnabled}
                            onClick={() => {
                              if (isEnabled) {
                                disablePlugin.mutate(p.plugin_id, {
                                  onSuccess: () =>
                                    toast(
                                      "success",
                                      "Plugin disabled",
                                      `"${p.name}" is disabled. Restart the server to apply.`,
                                    ),
                                  onError: (err) => toast("error", "Disable failed", errorMessage(err)),
                                });
                              } else {
                                enablePlugin.mutate(p.plugin_id, {
                                  onSuccess: () =>
                                    toast(
                                      "success",
                                      "Plugin enabled",
                                      `"${p.name}" is enabled. Restart the server to apply.`,
                                    ),
                                  onError: (err) => toast("error", "Enable failed", errorMessage(err)),
                                });
                              }
                            }}
                            disabled={
                              isMainProtected ||
                              !canManagePlugins ||
                              disablePlugin.isPending ||
                              enablePlugin.isPending
                            }
                            aria-label={toggleLabel}
                            title={toggleLabel}
                            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent-primary focus:ring-offset-2 disabled:opacity-40 ${
                              isEnabled ? "bg-status-success" : "bg-border-strong"
                            }`}
                          >
                            <span className="sr-only">{toggleLabel}</span>
                            <span
                              aria-hidden="true"
                              className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-surface-card shadow-sm ring-0 transition duration-200 ease-in-out ${
                                isEnabled ? "translate-x-4" : "translate-x-0"
                              }`}
                            />
                          </button>
                        </div>
                      </div>

                      {p.description && (
                        <p className="mt-3 line-clamp-2 text-[13px] text-text-muted leading-[1.45] min-h-[38px]">
                          {p.description}
                        </p>
                      )}

                      {filename && (
                        <div
                          className="mt-2.5 truncate rounded bg-surface-page px-2 py-1 font-mono text-[11px] text-text-muted border border-border-subtle/50"
                          title={filename}
                        >
                          {filename}
                        </div>
                      )}
                    </div>

                    {/* Action Footer */}
                    <div className="mt-3.5 flex items-center justify-between border-t border-border-subtle pt-3">
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => {
                            const branchSuffix =
                              isWorkingBranch && activeBranch
                                ? `&branch=${encodeURIComponent(activeBranch)}`
                                : "";
                            navigate(
                              `/servers/${encodeURIComponent(effectiveServerId)}/files?path=plugins${branchSuffix}`,
                            );
                          }}
                          className="inline-flex items-center gap-1 rounded-md border border-border-subtle bg-surface-elevated px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                          title={`Configure ${meta.title}`}
                        >
                          <Icon name="settings" size={13} />
                          <span>Config</span>
                        </button>
                      </div>

                      <button
                        type="button"
                        onClick={() => setUninstallTarget(p)}
                        disabled={isMainProtected || !canManagePlugins || uninstallPlugin.isPending}
                        aria-label={uninstallLabel}
                        title={uninstallLabel}
                        className="inline-flex items-center gap-1 rounded-md border border-status-danger/20 bg-status-danger-bg px-2.5 py-1 text-xs font-medium text-status-danger hover:bg-status-danger/20 transition-colors disabled:opacity-40 cursor-pointer"
                      >
                        <Icon name="trash" size={13} />
                        Uninstall
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            {filteredPlugins.length > PAGE_SIZE && (
              <div className="pt-2">
                <Pagination
                  totalItems={filteredPlugins.length}
                  pageSize={PAGE_SIZE}
                  page={currentPage}
                  onPageChange={setCurrentPage}
                />
              </div>
            )}
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border-default bg-surface-card shadow-xs">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-subtle bg-surface-page/50">
                  <th scope="col" className="px-4 py-3 text-left font-medium text-text-muted">Name</th>
                  <th scope="col" className="hidden px-4 py-3 text-left font-medium text-text-muted sm:table-cell">Version</th>
                  <th scope="col" className="hidden px-4 py-3 text-left font-medium text-text-muted md:table-cell">Author</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium text-text-muted">Status</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium text-text-muted">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {paginatedPlugins.map((p) => {
                  const meta = parsePluginMetadata(p);
                  const isEnabled = isPluginEnabled(p);
                  const filename = p.filename || (p as { file_name?: string | null }).file_name;
                  const toggleLabel = isEnabled ? `Disable ${p.name}` : `Enable ${p.name}`;
                  const uninstallLabel = `Uninstall ${p.name}`;

                  return (
                    <tr
                      key={p.plugin_id}
                      className="hover:bg-surface-hover/50 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-start gap-3">
                          {p.icon_url ? (
                            <img
                              src={p.icon_url}
                              alt={`${p.name} icon`}
                              className="h-10 w-10 shrink-0 rounded-lg bg-surface-page object-cover border border-border-subtle"
                            />
                          ) : (
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-page text-text-muted border border-border-subtle">
                              <Icon name="plugin" size={24} />
                            </div>
                          )}
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="font-medium text-text-primary">{meta.title}</p>
                              <SourceBadge plugin={p} />
                              {isWorkingBranch && p.is_committed === false && (
                                <span className="inline-flex items-center rounded-full border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[10px] font-medium text-status-warning">
                                  Uncommitted
                                </span>
                              )}
                            </div>
                            {p.description && (
                              <p className="mt-0.5 truncate text-xs text-text-muted" title={p.description}>
                                {p.description}
                              </p>
                            )}
                            {filename && (
                              <p className="mt-0.5 truncate font-mono text-xs text-text-muted opacity-80" title={filename}>
                                {filename}
                              </p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="hidden px-4 py-3 text-text-muted sm:table-cell">
                        {meta.version === "unknown" || !meta.version ? (
                          <span className="text-text-muted opacity-50">unknown</span>
                        ) : (
                          <span className="inline-flex items-center gap-0.5 font-mono text-xs">
                            <span className="text-text-muted">v</span>
                            <span>{meta.version}</span>
                          </span>
                        )}
                      </td>
                      <td className="hidden px-4 py-3 text-text-muted md:table-cell">
                        {p.author || "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium border ${
                            isEnabled
                              ? "bg-status-success-bg text-status-success border-status-success/30"
                              : "bg-surface-page text-text-muted border-border-default"
                          }`}
                        >
                          <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />
                          {p.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => {
                              const branchSuffix =
                                isWorkingBranch && activeBranch
                                  ? `&branch=${encodeURIComponent(activeBranch)}`
                                  : "";
                              navigate(
                                `/servers/${encodeURIComponent(effectiveServerId)}/files?path=plugins${branchSuffix}`,
                              );
                            }}
                            className="inline-flex items-center gap-1 rounded-lg border border-border-subtle bg-surface-elevated px-2 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                            title={`Configure ${meta.title}`}
                          >
                            <Icon name="settings" size={13} />
                            <span>Config</span>
                          </button>
                          {isEnabled ? (
                            <button
                              type="button"
                              onClick={() =>
                                disablePlugin.mutate(p.plugin_id, {
                                  onSuccess: () =>
                                    toast(
                                      "success",
                                      "Plugin disabled",
                                      `"${p.name}" is disabled. Restart the server to apply.`,
                                    ),
                                  onError: (err) => toast("error", "Disable failed", errorMessage(err)),
                                })
                              }
                              disabled={
                                isMainProtected || !canManagePlugins || disablePlugin.isPending
                              }
                              aria-label={toggleLabel}
                              title={toggleLabel}
                              className="rounded-lg p-1.5 text-status-warning transition-colors hover:bg-status-warning-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                            >
                              <Icon name="stop" size={16} />
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() =>
                                enablePlugin.mutate(p.plugin_id, {
                                  onSuccess: () =>
                                    toast(
                                      "success",
                                      "Plugin enabled",
                                      `"${p.name}" is enabled. Restart the server to apply.`,
                                    ),
                                  onError: (err) => toast("error", "Enable failed", errorMessage(err)),
                                })
                              }
                              disabled={
                                isMainProtected || !canManagePlugins || enablePlugin.isPending
                              }
                              aria-label={toggleLabel}
                              title={toggleLabel}
                              className="rounded-lg p-1.5 text-status-success transition-colors hover:bg-status-success-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                            >
                              <Icon name="play" size={16} />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => setUninstallTarget(p)}
                            disabled={
                              isMainProtected || !canManagePlugins || uninstallPlugin.isPending
                            }
                            aria-label={uninstallLabel}
                            title={uninstallLabel}
                            className="rounded-lg p-1.5 text-status-danger transition-colors hover:bg-status-danger-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                          >
                            <Icon name="trash" size={16} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {filteredPlugins.length > PAGE_SIZE && (
              <div className="border-t border-border-subtle p-3">
                <Pagination
                  totalItems={filteredPlugins.length}
                  pageSize={PAGE_SIZE}
                  page={currentPage}
                  onPageChange={setCurrentPage}
                />
              </div>
            )}
          </div>
        )
      ) : (
        <EmptyState
          icon="plugin"
          title="No plugins installed"
          description="Install a plugin from the marketplace, or drop a .jar file directly into the server's plugins/ folder — it will appear here automatically."
          action={
            canManagePlugins ? (
              <button
                type="button"
                disabled={isMainProtected}
                onClick={handleInstall}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-semibold text-accent-contrast-text transition-colors hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shadow-xs"
              >
                <Icon name="plus" size={16} />
                Install Plugin
              </button>
            ) : undefined
          }
        />
      )}

      <ConfirmDialog
        open={uninstallTarget !== null}
        title="Uninstall plugin?"
        description={
          uninstallTarget
            ? `This removes "${uninstallTarget.name}" from the list now. The ${uninstallTarget.filename || (uninstallTarget as { file_name?: string | null }).file_name ? `file ${uninstallTarget.filename || (uninstallTarget as { file_name?: string | null }).file_name} ` : "file "}will be deleted from disk the next time this server restarts.`
            : undefined
        }
        confirmLabel="Uninstall"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmUninstall}
        onCancel={() => setUninstallTarget(null)}
      />
    </div>
  );
}
