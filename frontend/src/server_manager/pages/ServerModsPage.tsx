import { useState, useRef, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useServersList } from "@/server_manager/hooks/useServers";
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
import type { PluginResponse } from "@/types";

const PAGE_SIZE = 15;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function LoaderBadge({ loader }: { loader?: string | null }) {
  const norm = loader?.toLowerCase() || "";
  if (norm.includes("fabric")) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-status-info-border bg-status-info-bg px-2 py-0.5 text-xs font-medium text-status-info">
        <Icon name="fabric" size={12} />
        Fabric
      </span>
    );
  }
  if (norm.includes("neoforge")) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-xs font-medium text-status-warning">
        <Icon name="neoforge" size={12} />
        NeoForge
      </span>
    );
  }
  if (norm.includes("forge")) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-xs font-medium text-status-warning">
        <Icon name="forge" size={12} />
        Forge
      </span>
    );
  }
  if (norm.includes("quilt")) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-border-default bg-surface-muted px-2 py-0.5 text-xs font-medium text-text-secondary">
        <Icon name="quilt" size={12} />
        Quilt
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border-default bg-surface-page px-2 py-0.5 text-xs font-medium text-text-secondary">
      <Icon name="plugin" size={12} />
      {loader || "Universal"}
    </span>
  );
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

function ModStatusToggle({
  mod,
  onToggle,
  isPending,
}: {
  mod: PluginResponse;
  onToggle: () => void;
  isPending: boolean;
}) {
  const isEnabled = mod.status === "enabled" && !mod.is_disabled_on_disk;
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
}: {
  onUpload: (file: File) => void;
  isUploading: boolean;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
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
        onChange={handleFileChange}
        className="hidden"
        data-testid="mod-file-input"
      />
      <div
        role="button"
        tabIndex={isUploading ? -1 : 0}
        aria-label="Upload custom mod jar file"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !isUploading && fileInputRef.current?.click()}
        onKeyDown={(e) => {
          if (!isUploading && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-colors cursor-pointer focus:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus ${
          isDragging
            ? "border-accent-primary bg-accent-primary/15"
            : "border-border-default hover:border-accent-primary bg-surface-card hover:bg-surface-hover/50"
        } ${isUploading ? "pointer-events-none opacity-60" : ""}`}
      >
        <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-accent-primary/20 text-accent-primary">
        <Icon name="upload" size={20} />
      </div>
      <p className="text-sm font-medium text-text-primary">
        {isUploading ? "Uploading mod..." : "Drop custom .jar mod file here, or browse"}
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
  const [loaderFilter, setLoaderFilter] = useState("all");
  const [uninstallTarget, setUninstallTarget] = useState<PluginResponse | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  const effectiveServerId = routeServerId
    ? routeServerId
    : touched
      ? selectedServerId
      : lastUsedServerId && servers?.some((s) => s.server_id === lastUsedServerId)
        ? lastUsedServerId
        : selectedServerId;

  const { data: mods, isLoading, error } = usePluginsList(effectiveServerId);
  const uploadMod = useUploadPluginOrMod(effectiveServerId);
  const toggleMod = useToggleModState(effectiveServerId);
  const uninstallMod = useUninstallPlugin(effectiveServerId);

  function handleServerChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setTouched(true);
    setSelectedServerId(e.target.value);
  }

  function handleBrowseMarketplace() {
    navigate(`/marketplace?server=${encodeURIComponent(effectiveServerId)}`);
  }

  function handleUpload(file: File) {
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
    const isCurrentlyEnabled = mod.status === "enabled" && !mod.is_disabled_on_disk;
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
            `"${mod.name}" is now ${targetState ? "enabled" : "disabled"}.`,
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

      const matchesLoader =
        loaderFilter === "all" ||
        (m.loader && m.loader.toLowerCase() === loaderFilter.toLowerCase());

      return matchesSearch && matchesLoader;
    });
  }, [mods, searchQuery, loaderFilter]);

  const paginatedMods = useMemo(() => {
    if (!filteredMods || filteredMods.length <= PAGE_SIZE) return filteredMods;
    const startIdx = (currentPage - 1) * PAGE_SIZE;
    return filteredMods.slice(startIdx, startIdx + PAGE_SIZE);
  }, [filteredMods, currentPage]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Mods"
        description="Manage mods, loaders, and custom addons for this server"
        icon="plugin"
        actions={
          effectiveServerId ? (
            <button
              type="button"
              onClick={handleBrowseMarketplace}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover cursor-pointer shadow-xs"
            >
              <Icon name="plus" size={16} />
              Browse Marketplace
            </button>
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
            {servers?.map((s) => (
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
          {/* Upload Zone */}
          <ModUploadZone onUpload={handleUpload} isUploading={uploadMod.isPending} />

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

            <div className="flex items-center gap-2">
              <label htmlFor="loader-filter" className="text-xs font-medium text-text-muted">
                Loader:
              </label>
              <select
                id="loader-filter"
                value={loaderFilter}
                onChange={(e) => {
                  setLoaderFilter(e.target.value);
                  setCurrentPage(1);
                }}
                className="rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
              >
                <option value="all">All Loaders</option>
                <option value="fabric">Fabric</option>
                <option value="forge">Forge</option>
                <option value="neoforge">NeoForge</option>
                <option value="quilt">Quilt</option>
              </select>
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
                          isPending={toggleMod.isPending}
                        />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => setUninstallTarget(m)}
                          disabled={uninstallMod.isPending}
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
                searchQuery || loaderFilter !== "all"
                  ? "No mods matched your filter criteria."
                  : "No mods are installed yet. Drop a .jar file in the upload zone above or browse the marketplace."
              }
              action={
                searchQuery || loaderFilter !== "all" ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSearchQuery("");
                      setLoaderFilter("all");
                    }}
                    className="inline-flex items-center gap-1 rounded-lg bg-surface-page border border-border-default px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
                  >
                    Clear Filters
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleBrowseMarketplace}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover cursor-pointer shadow-xs"
                  >
                    <Icon name="plus" size={16} />
                    Browse Marketplace
                  </button>
                )
              }
            />
          )}
        </>
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

