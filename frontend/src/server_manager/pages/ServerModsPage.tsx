import { useState, useRef, useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useServersList } from "@/server_manager/hooks/useServers";
import { useFleetPermissions } from "@/server_manager/components/servers/serversUtils";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import {
  isModpackSupportedLoader,
  isPluginLoader,
} from "@/server_manager/utils/loaderCapabilities";
import {
  usePluginsList,
  useUploadPluginOrMod,
  useToggleModState,
  useUninstallPlugin,
} from "@/server_manager/hooks/usePlugins";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Pagination } from "@/components/ui/Pagination";
import { TableSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { ModpackInstallWizardModal } from "@/server_manager/components/p55";
import type { PluginResponse } from "@/types";

const PAGE_SIZE = 15;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function ClientOnlyBadge({ warning }: { warning?: string | null }) {
  if (!warning) return null;
  return (
    <span
      role="status"
      title={warning}
      className="inline-flex items-center gap-1 rounded-full bg-status-warning-bg border border-status-warning/30 px-2.5 py-0.5 text-xs font-medium text-status-warning"
    >
      <Icon name="alert" size={12} />
      Client-only
    </span>
  );
}

function isModEnabled(mod: PluginResponse): boolean {
  if (mod.is_disabled_on_disk) return false;
  const st = (mod.status || "").toLowerCase();
  return st === "enabled" || st === "installed";
}

function ModStatusToggle({
  mod,
  onToggle,
  isPending,
}: {
  mod: PluginResponse;
  onToggle: () => void;
  isPending: boolean;
}) {
  const isEnabled = isModEnabled(mod);
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        role="switch"
        aria-checked={isEnabled}
        aria-label={`${isEnabled ? "Disable" : "Enable"} ${mod.name}`}
        onClick={onToggle}
        disabled={isPending}
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent-primary focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
          isEnabled ? "bg-accent-primary" : "bg-border-default"
        }`}
      >
        <span className="sr-only">{isEnabled ? "Enabled" : "Disabled"}</span>
        <span
          aria-hidden="true"
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-accent-contrast-text shadow-xs ring-0 transition duration-200 ease-in-out ${
            isEnabled ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </button>
      <span
        className={`text-xs font-medium ${
          isEnabled ? "text-status-success" : "text-text-muted"
        }`}
      >
        {isEnabled ? "Enabled" : "Disabled"}
      </span>
    </div>
  );
}

function ModUploadZone({
  onUpload,
  isUploading,
  disabled = false,
}: {
  onUpload: (file: File) => void;
  isUploading: boolean;
  disabled?: boolean;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isBlocked = isUploading || disabled;

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (!isBlocked) setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (isBlocked) return;
    const file = e.dataTransfer.files?.[0];
    if (file) {
      if (!file.name.toLowerCase().endsWith(".jar")) {
        toast("error", "Invalid file", "Only .jar mod files are supported.");
        return;
      }
      onUpload(file);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (isBlocked) return;
    const file = e.target.files?.[0];
    if (file) {
      if (!file.name.toLowerCase().endsWith(".jar")) {
        toast("error", "Invalid file", "Only .jar mod files are supported.");
        return;
      }
      onUpload(file);
      e.target.value = "";
    }
  };

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        aria-label="Choose custom mod jar file"
        accept=".jar"
        disabled={isBlocked}
        onChange={handleFileChange}
        className="hidden"
        data-testid="mod-file-input"
      />
      <div
        role="button"
        tabIndex={isBlocked ? -1 : 0}
        aria-disabled={isBlocked}
        aria-label="Upload custom mod jar file"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !isBlocked && fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if (!isBlocked && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus ${
          isDragging
            ? "border-accent-primary bg-accent-primary/15"
            : "border-border-default hover:border-accent-primary bg-surface-card hover:bg-surface-hover/50"
        } ${isBlocked ? "pointer-events-none opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
      >
        <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-accent-primary/20 text-accent-primary">
          <Icon name="upload" size={20} />
        </div>
        <p className="text-sm font-medium text-text-primary">
          {isUploading
            ? "Uploading mod..."
            : disabled
              ? "Mod uploads are currently disabled"
              : "Drop custom .jar mod file here, or browse"}
        </p>
        <p className="mt-1 text-xs text-text-muted">
          Supports Forge, NeoForge, Fabric, and Quilt mods (.jar)
        </p>
      </div>
    </>
  );
}

export function ServerModsPage() {
  const { serverId: routeServerId } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const { data: servers } = useServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);
  const [touched, setTouched] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [uninstallTarget, setUninstallTarget] = useState<PluginResponse | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [isModpackWizardOpen, setIsModpackWizardOpen] = useState(false);

  const modServers = useMemo(
    () => (servers ?? []).filter((s) => getServerCapabilities(s.server_type).supportsMods),
    [servers],
  );

  const effectiveServerId = routeServerId
    ? routeServerId
    : touched
      ? selectedServerId
      : lastUsedServerId && modServers.some((s) => s.server_id === lastUsedServerId)
        ? lastUsedServerId
        : selectedServerId;

  const activeServer = servers?.find((s) => s.server_id === effectiveServerId);
  const activeServerType = activeServer?.server_type;
  const supportsModpacks = activeServerType
    ? isModpackSupportedLoader(activeServerType)
    : true;
  const isNonModdedServer = Boolean(activeServerType) && !supportsModpacks;

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
        message: "Update branch mods lockfile",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.plugins.list(effectiveServerId, activeBranch),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.versioning.commits(effectiveServerId) });
      toast("success", "Changes committed", `Committed mod changes to "${activeBranch}".`);
    },
    onError: (err) => toast("error", "Commit failed", errorMessage(err)),
  });

  const { data: mods, isLoading, error } = usePluginsList(
    isNonModdedServer ? "" : effectiveServerId,
    activeBranch,
  );
  const uploadMod = useUploadPluginOrMod(effectiveServerId, activeBranch);
  const toggleMod = useToggleModState(effectiveServerId, activeBranch);
  const uninstallMod = useUninstallPlugin(effectiveServerId, activeBranch);
  const permissions = useFleetPermissions();
  const canManagePlugins = Boolean(
    effectiveServerId && permissions.canManagePlugins(effectiveServerId),
  );
  const hasUncommitted = Boolean(
    isWorkingBranch &&
      (mods?.some((m) => m.is_committed === false) ||
        Boolean((mods as { __hasUncommitted?: boolean } | undefined)?.__hasUncommitted)),
  );

  function handleServerChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setTouched(true);
    setSelectedServerId(e.target.value);
  }

  function handleBrowseMarketplace() {
    if (!canManagePlugins || isMainProtected) return;
    if (routeServerId) {
      const branchQuery =
        isWorkingBranch && activeBranch ? `?branch=${encodeURIComponent(activeBranch)}` : "";
      navigate(`/servers/${encodeURIComponent(effectiveServerId)}/mods/marketplace${branchQuery}`);
      return;
    }
    const branchSuffix = isWorkingBranch && activeBranch ? `&branch=${encodeURIComponent(activeBranch)}` : "";
    navigate(`/marketplace?server=${encodeURIComponent(effectiveServerId)}&type=mod${branchSuffix}`);
  }

  function handleUpload(file: File) {
    if (isMainProtected || !canManagePlugins) return;
    uploadMod.mutate(file, {
      onSuccess: () => {
        toast("success", "Mod uploaded", `"${file.name}" uploaded successfully.`);
      },
      onError: (err) => {
        toast("error", "Upload failed", errorMessage(err));
      },
    });
  }

  function handleToggle(mod: PluginResponse) {
    const isCurrentlyEnabled = isModEnabled(mod);
    const targetState = !isCurrentlyEnabled;

    toggleMod.mutate(
      {
        mod_id: mod.mod_id,
        plugin_id: mod.plugin_id,
        enabled: targetState,
      },
      {
        onSuccess: () => {
          toast(
            "success",
            targetState ? "Mod enabled" : "Mod disabled",
            `"${mod.name}" is now ${targetState ? "enabled" : "disabled"}. Restart the server to apply.`,
          );
        },
        onError: (err) => {
          toast("error", "Toggle failed", errorMessage(err));
        },
      },
    );
  }

  function handleConfirmUninstall() {
    if (!uninstallTarget) return;
    uninstallMod.mutate(uninstallTarget.plugin_id, {
      onSuccess: () => {
        toast(
          "success",
          "Removal requested",
          `"${uninstallTarget.name}" will be removed on next server restart.`,
        );
      },
      onError: (err) => {
        toast("error", "Remove failed", errorMessage(err));
      },
      onSettled: () => setUninstallTarget(null),
    });
  }

  const filteredMods = useMemo(() => {
    if (!mods) return [];
    return mods.filter((m) => {
      const matchesSearch =
        searchQuery === "" ||
        m.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (m.mod_id && m.mod_id.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (m.filename && m.filename.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (m.description && m.description.toLowerCase().includes(searchQuery.toLowerCase()));

      return matchesSearch;
    });
  }, [mods, searchQuery]);

  const paginatedMods = useMemo(() => {
    if (!filteredMods || filteredMods.length <= PAGE_SIZE) return filteredMods;
    const startIdx = (currentPage - 1) * PAGE_SIZE;
    return filteredMods.slice(startIdx, startIdx + PAGE_SIZE);
  }, [filteredMods, currentPage]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Mods"
        description={
          gitBacked && activeBranch
            ? `Manage mods, loaders, and custom addons for branch "${activeBranch}"`
            : "Manage mods, loaders, and custom addons for this server"
        }
        icon="plugin"
        actions={
          effectiveServerId ? (
            <>
              {supportsModpacks && (
                <button
                  type="button"
                  data-testid="open-modpack-wizard-btn"
                  disabled={isMainProtected || !canManagePlugins}
                  onClick={() => setIsModpackWizardOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                >
                  <Icon name="download" size={16} />
                  Install Modpack (.mrpack / CurseForge)
                </button>
              )}
              {!isNonModdedServer && (
                <button
                  type="button"
                  disabled={isMainProtected || !canManagePlugins}
                  onClick={handleBrowseMarketplace}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shadow-xs"
                >
                  <Icon name="plus" size={16} />
                  Browse Marketplace
                </button>
              )}
            </>
          ) : undefined
        }
      />

      {!routeServerId && (
        <div className="max-w-xs">
          <label className="sr-only" htmlFor="mods-server-select">
            Choose a server
          </label>
          <select
            id="mods-server-select"
            value={effectiveServerId}
            onChange={handleServerChange}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
          >
            <option value="">Select a server...</option>
            {modServers.map((s) => (
              <option key={s.server_id} value={s.server_id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {!effectiveServerId ? (
        <EmptyState
          icon="plugin"
          title="Select a server"
          description="Choose a server above to view and manage its installed mods."
        />
      ) : (
        <>
          {isNonModdedServer && (
            <div
              data-testid="non-modded-server-banner"
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-info-border bg-status-info-bg px-4 py-3 text-sm text-text-primary"
            >
              <div className="flex items-center gap-2">
                <Icon name="info" size={16} className="shrink-0 text-status-info" />
                <span>
                  This server runs <span className="font-semibold">{activeServerType}</span>, which
                  does not support Forge/Fabric/NeoForge/Quilt mods or modpacks.
                </span>
              </div>
              {isPluginLoader(activeServerType) && (
                <Link
                  to={
                    activeBranch
                      ? `/servers/${effectiveServerId}/plugins?branch=${encodeURIComponent(activeBranch)}`
                      : `/servers/${effectiveServerId}/plugins`
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover transition-colors"
                >
                  <Icon name="plugin" size={14} />
                  Manage Plugins
                </Link>
              )}
            </div>
          )}

          {isMainProtected && (
            <div
              data-testid="mods-main-protected-banner"
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-warning-border bg-status-warning-bg px-4 py-3 text-xs text-text-primary"
            >
              <div className="space-y-0.5">
                <p className="font-semibold text-status-warning">
                  Branch &ldquo;main&rdquo; is protected
                </p>
                <p className="text-text-secondary">
                  Mod uploads, toggles, and removals cannot mutate main directly. Switch to or create a working branch to edit mods.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {firstWorkingBranch && (
                  <button
                    type="button"
                    onClick={() => branchCtx?.setBranch(firstWorkingBranch)}
                    className="inline-flex items-center gap-1 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer"
                  >
                    Switch to {firstWorkingBranch}
                  </button>
                )}
                {canManagePlugins && (
                  <>
                    <input
                      type="text"
                      value={quickBranchName}
                      onChange={(e) => setQuickBranchName(e.target.value)}
                      placeholder="mod-test"
                      aria-label="New working branch name"
                      className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs text-text-primary focus:border-accent-primary focus:outline-none"
                    />
                    <button
                      type="button"
                      disabled={!quickBranchName.trim() || createBranchMutation.isPending}
                      onClick={() => createBranchMutation.mutate(quickBranchName.trim())}
                      className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs font-semibold text-text-primary hover:bg-surface-hover disabled:opacity-50 cursor-pointer"
                    >
                      {createBranchMutation.isPending ? "Creating..." : "Create Working Branch"}
                    </button>
                  </>
                )}
              </div>
            </div>
          )}

          {hasUncommitted && (
            <div
              data-testid="mods-uncommitted-banner"
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
                data-testid="mods-commit-btn"
                disabled={!canManagePlugins || commitLockfileMutation.isPending}
                onClick={() => commitLockfileMutation.mutate()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer"
              >
                <Icon name="check" size={14} />
                {commitLockfileMutation.isPending ? "Committing..." : "Save & Commit"}
              </button>
            </div>
          )}

          {/* Upload Zone */}
          <ModUploadZone
            onUpload={handleUpload}
            isUploading={uploadMod.isPending}
            disabled={isMainProtected || !canManagePlugins || isNonModdedServer}
          />

          {/* Search and Filters */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative max-w-sm flex-1">
              <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-text-muted">
                <Icon name="search" size={16} />
              </span>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setCurrentPage(1);
                }}
                placeholder="Search mods by name, ID, or file..."
                className="w-full rounded-lg border border-border-default bg-surface-page py-2 pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
              />
            </div>

          </div>

          {/* Content */}
          {isLoading ? (
            <TableSkeleton rows={4} cols={5} />
          ) : error ? (
            <ErrorState message={error instanceof Error ? error.message : "Failed to load mods"} />
          ) : filteredMods.length > 0 ? (
            <div className="overflow-hidden rounded-xl border border-border-default bg-surface-card shadow-xs">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-subtle bg-surface-page/50">
                    <th className="px-4 py-3 text-left font-medium text-text-muted">
                      Mod
                    </th>
                    <th className="hidden px-4 py-3 text-left font-medium text-text-muted sm:table-cell">
                      Loader
                    </th>
                    <th className="hidden px-4 py-3 text-left font-medium text-text-muted md:table-cell">
                      Version
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-text-muted">
                      Status
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-text-muted">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {paginatedMods.map((m) => (
                    <tr
                      key={m.plugin_id}
                      className="hover:bg-surface-hover/50 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-start gap-3">
                          {m.icon_url ? (
                            <img
                              src={m.icon_url}
                              alt={`${m.name} icon`}
                              className="h-10 w-10 shrink-0 rounded-lg bg-surface-page object-cover border border-border-subtle"
                            />
                          ) : (
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-page text-text-muted border border-border-subtle">
                              <Icon name="plugin" size={24} />
                            </div>
                          )}
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="font-medium text-text-primary">{m.name}</p>
                              {m.mod_id && (
                                <span className="rounded bg-surface-page px-1.5 py-0.5 font-mono text-[11px] text-text-muted border border-border-subtle">
                                  {m.mod_id}
                                </span>
                              )}
                              <ClientOnlyBadge warning={m.warning} />
                            </div>
                            {m.description && (
                              <p
                                className="mt-0.5 line-clamp-1 text-xs text-text-muted"
                                title={m.description}
                              >
                                {m.description}
                              </p>
                            )}
                            {m.filename && (
                              <p
                                className="mt-0.5 truncate font-mono text-xs text-text-muted opacity-80"
                                title={m.filename}
                              >
                                {m.filename}
                              </p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="hidden px-4 py-3 sm:table-cell">
                        <LoaderBadge loader={m.loader} />
                      </td>
                      <td className="hidden px-4 py-3 text-text-muted md:table-cell">
                        {m.version || "—"}
                      </td>
                      <td className="px-4 py-3">
                        <ModStatusToggle
                          mod={m}
                          onToggle={() => handleToggle(m)}
                          isPending={isMainProtected || !canManagePlugins || toggleMod.isPending}
                        />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => setUninstallTarget(m)}
                          disabled={isMainProtected || !canManagePlugins || uninstallMod.isPending}
                          aria-label={`Uninstall ${m.name}`}
                          title="Uninstall"
                          className="rounded-lg p-1.5 text-status-danger transition-colors hover:bg-status-danger-bg disabled:opacity-40 disabled:hover:bg-transparent cursor-pointer"
                        >
                          <Icon name="trash" size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {filteredMods.length > PAGE_SIZE && (
                <div className="border-t border-border-subtle p-3">
                  <Pagination
                    totalItems={filteredMods.length}
                    pageSize={PAGE_SIZE}
                    page={currentPage}
                    onPageChange={setCurrentPage}
                  />
                </div>
              )}
            </div>
          ) : (
            <EmptyState
              icon="plugin"
              title="No mods found"
              description={
                searchQuery
                  ? "No mods matched your filter criteria."
                  : "No mods are installed yet. Drop a .jar file in the upload zone above or browse the marketplace."
              }
              action={
                searchQuery ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSearchQuery("");
                    }}
                    className="inline-flex items-center gap-1 rounded-lg bg-surface-page border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
                  >
                    Clear Filters
                  </button>
                ) : canManagePlugins ? (
                  <button
                    type="button"
                    disabled={isMainProtected}
                    onClick={handleBrowseMarketplace}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shadow-xs"
                  >
                    <Icon name="plus" size={16} />
                    Browse Marketplace
                  </button>
                ) : undefined
              }
            />
          )}
        </>
      )}

      {effectiveServerId && supportsModpacks && (
        <ModpackInstallWizardModal
          serverId={effectiveServerId}
          isOpen={isModpackWizardOpen}
          onClose={() => setIsModpackWizardOpen(false)}
        />
      )}

      <ConfirmDialog
        open={uninstallTarget !== null}
        title="Uninstall mod?"
        description={
          uninstallTarget
            ? `This removes "${uninstallTarget.name}" from this server. The file ${
                uninstallTarget.filename ? `"${uninstallTarget.filename}" ` : ""
              }will be deleted on the next server restart.`
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

