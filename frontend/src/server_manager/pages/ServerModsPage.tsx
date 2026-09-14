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
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import type { PluginResponse } from "@/types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function LoaderBadge({ loader }: { loader?: string | null }) {
  const norm = loader?.toLowerCase() || "";
  if (norm.includes("fabric")) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-sky-200 bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700 dark:border-sky-800 dark:bg-sky-950/50 dark:text-sky-300">
        <Icon name="fabric" size={12} />
        Fabric
      </span>
    );
  }
  if (norm.includes("neoforge")) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-orange-200 bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700 dark:border-orange-800 dark:bg-orange-950/50 dark:text-orange-300">
        <Icon name="neoforge" size={12} />
        NeoForge
      </span>
    );
  }
  if (norm.includes("forge")) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
        <Icon name="forge" size={12} />
        Forge
      </span>
    );
  }
  if (norm.includes("quilt")) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-purple-200 bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-700 dark:border-purple-800 dark:bg-purple-950/50 dark:text-purple-300">
        <Icon name="quilt" size={12} />
        Quilt
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-gray-200 bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300">
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
      className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
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
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
          isEnabled ? "bg-blue-600" : "bg-gray-300 dark:bg-gray-600"
        }`}
      >
        <span className="sr-only">{isEnabled ? "Enabled" : "Disabled"}</span>
        <span
          aria-hidden="true"
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
            isEnabled ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </button>
      <span
        className={`text-xs font-medium ${
          isEnabled ? "text-emerald-600 dark:text-emerald-400" : "text-gray-500 dark:text-gray-400"
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
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => !isUploading && fileInputRef.current?.click()}
      className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-colors cursor-pointer ${
        isDragging
          ? "border-blue-500 bg-blue-50/50 dark:border-blue-400 dark:bg-blue-950/20"
          : "border-gray-300 hover:border-gray-400 bg-gray-50/50 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800/30 dark:hover:border-gray-600"
      } ${isUploading ? "pointer-events-none opacity-60" : ""}`}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".jar"
        onChange={handleFileChange}
        className="hidden"
        data-testid="mod-file-input"
      />
      <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400">
        <Icon name="upload" size={20} />
      </div>
      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
        {isUploading ? "Uploading mod..." : "Drop custom .jar mod file here, or browse"}
      </p>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        Supports Forge, NeoForge, Fabric, and Quilt mods (.jar)
      </p>
    </div>
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

  return (
    <div className="space-y-6">
      <PageHeader
        title="Mods"
        description="Manage mods, loaders, and custom addons for this server"
        icon="plugin"
        actions={
          effectiveServerId ? (
            <button
              onClick={handleBrowseMarketplace}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
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
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
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
              <span className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-gray-400">
                <Icon name="search" size={16} />
              </span>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search mods by name, ID, or file..."
                className="w-full rounded-lg border border-gray-300 bg-white py-2 pl-9 pr-3 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500"
              />
            </div>

            <div className="flex items-center gap-2">
              <label htmlFor="loader-filter" className="text-xs font-medium text-gray-500 dark:text-gray-400">
                Loader:
              </label>
              <select
                id="loader-filter"
                value={loaderFilter}
                onChange={(e) => setLoaderFilter(e.target.value)}
                className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
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
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
                    <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">
                      Mod
                    </th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 sm:table-cell">
                      Loader
                    </th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 md:table-cell">
                      Version
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">
                      Status
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-400">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredMods.map((m) => (
                    <tr
                      key={m.plugin_id}
                      className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-start gap-3">
                          {m.icon_url ? (
                            <img
                              src={m.icon_url}
                              alt={`${m.name} icon`}
                              className="h-10 w-10 shrink-0 rounded-md bg-gray-100 object-cover dark:bg-gray-800"
                            />
                          ) : (
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500">
                              <Icon name="plugin" size={24} />
                            </div>
                          )}
                          <div>
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="font-medium text-gray-900 dark:text-gray-100">{m.name}</p>
                              {m.mod_id && (
                                <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                                  {m.mod_id}
                                </span>
                              )}
                              <ClientOnlyBadge warning={m.warning} />
                            </div>
                            {m.description && (
                              <p
                                className="mt-0.5 line-clamp-1 text-xs text-gray-500 dark:text-gray-400"
                                title={m.description}
                              >
                                {m.description}
                              </p>
                            )}
                            {m.filename && (
                              <p
                                className="mt-0.5 truncate font-mono text-xs text-gray-400 dark:text-gray-500"
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
                      <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 md:table-cell">
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
                          onClick={() => setUninstallTarget(m)}
                          disabled={uninstallMod.isPending}
                          aria-label={`Uninstall ${m.name}`}
                          title="Uninstall"
                          className="rounded-lg p-1.5 text-red-600 transition-colors hover:bg-red-100 hover:text-red-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-red-400 dark:hover:bg-red-900/30 dark:hover:text-red-300"
                        >
                          <Icon name="trash" size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                    onClick={() => {
                      setSearchQuery("");
                      setLoaderFilter("all");
                    }}
                    className="inline-flex items-center gap-1 rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300"
                  >
                    Clear Filters
                  </button>
                ) : (
                  <button
                    onClick={handleBrowseMarketplace}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
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
        onConfirm={handleConfirmUninstall}
        onCancel={() => setUninstallTarget(null)}
      />
    </div>
  );
}

