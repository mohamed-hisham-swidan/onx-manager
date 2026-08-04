import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useServersList } from "@/server_manager/hooks/useServers";
import {
  useMarketplaceSearch,
  useProjectVersions,
  useInstallFromMarketplace,
} from "@/server_manager/hooks/usePlugins";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/EmptyState";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import { formatBytes } from "@/server_manager/utils/format";
import type {
  PluginSearchResultResponse,
  PluginVersionResponse,
  PluginVersionsResponse,
} from "@/types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function fmtDownloads(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function noticeKindLabel(kind: string): string {
  switch (kind) {
    case "loader_fallback":
      return "Compatibility note";
    case "version_mismatch":
      return "Version mismatch";
    case "incompatible":
      return "Incompatible";
    default:
      return "Notice";
  }
}

export function PluginMarketplacePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const serverId = searchParams.get("server") ?? "";
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [selectedProject, setSelectedProject] = useState<PluginSearchResultResponse | null>(null);
  const [installTarget, setInstallTarget] = useState<{
    project: PluginSearchResultResponse;
    version: PluginVersionResponse;
  } | null>(null);

  const { data: servers } = useServersList();
  const search = useMarketplaceSearch(serverId, submitted);
  const versions = useProjectVersions(serverId, selectedProject?.project_id ?? "");
  const install = useInstallFromMarketplace(serverId);

  const serverName = useMemo(
    () => servers?.find((s) => s.server_id === serverId)?.name ?? "",
    [servers, serverId],
  );

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(query.trim());
  }

  function handleCloseVersions() {
    setSelectedProject(null);
    install.reset();
  }

  function handleInstallSelected() {
    if (!installTarget) return;
    install.mutate(
      {
        project_id: installTarget.project.project_id,
        version_id: installTarget.version.version_id,
      },
      {
        onSuccess: (result) => {
          toast(
            "success",
            "Plugin installed",
            `"${installTarget.project.title}" ${result.version} installed.`,
          );
          setInstallTarget(null);
          setSelectedProject(null);
        },
        onError: (err) => toast("error", "Install failed", errorMessage(err)),
      },
    );
  }

  const selectedVersionResponse: PluginVersionsResponse | undefined = versions.data;

  return (
    <div>
      <PageHeader
        title="Plugin Marketplace"
        description="Browse and install plugins from Modrinth"
        icon="plugin"
        actions={
          serverId ? (
            <button
              onClick={() => navigate("/plugins")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              <Icon name="chevron-left" size={16} />
              Back to Plugins
            </button>
          ) : undefined
        }
      />

      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={serverId ? `Search plugins for ${serverName || "this server"}...` : "Select a server to search plugins..."}
            disabled={!serverId}
            aria-label="Search plugins"
            className="w-full max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
          />
          <button
            type="submit"
            disabled={!serverId || !query.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
          >
            <Icon name="search" size={16} />
            Search
          </button>
        </div>
        {!serverId && (
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            Open this page from a server's plugins tab to install into that server.
          </p>
        )}
      </form>

      {search.isError && (
        <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400">
          {search.error instanceof Error ? search.error.message : "Search failed"}
        </div>
      )}

      {!selectedProject ? (
        search.isLoading ? (
          <TableSkeleton rows={4} cols={4} />
        ) : submitted && search.data && search.data.length === 0 ? (
          <EmptyState
            icon="search"
            title="No plugins found"
            description={`No results for "${submitted}". Try a different search term.`}
          />
        ) : search.data && search.data.length > 0 ? (
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
                  <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">Plugin</th>
                  <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 sm:table-cell">Author</th>
                  <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 md:table-cell">Downloads</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-400">Action</th>
                </tr>
              </thead>
              <tbody>
                {search.data.map((p) => (
                  <tr
                    key={p.project_id}
                    className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        {p.icon_url ? (
                          <img
                            src={p.icon_url}
                            alt=""
                            className="h-9 w-9 shrink-0 rounded-lg object-cover"
                          />
                        ) : (
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 dark:bg-gray-700">
                            <Icon name="plugin" size={18} />
                          </div>
                        )}
                        <div>
                          <p className="font-medium text-gray-900 dark:text-gray-100">{p.title}</p>
                          {p.description && (
                            <p className="mt-0.5 max-w-md truncate text-xs text-gray-500 dark:text-gray-400" title={p.description}>
                              {p.description}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 sm:table-cell">{p.author}</td>
                    <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 md:table-cell">
                      {fmtDownloads(p.downloads)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => setSelectedProject(p)}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700"
                        >
                          <Icon name="plus" size={14} />
                          Install
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon="search"
            title="Search the marketplace"
            description="Find plugins by name, like EssentialsX or WorldEdit."
          />
        )
      ) : (
        <div className="space-y-4">
          <button
            onClick={handleCloseVersions}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            <Icon name="chevron-left" size={14} />
            Back to results
          </button>

          {versions.isLoading ? (
            <TableSkeleton rows={3} cols={3} />
          ) : versions.isError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400">
              {versions.error instanceof Error ? versions.error.message : "Failed to load versions"}
            </div>
          ) : selectedVersionResponse && selectedVersionResponse.versions.length > 0 ? (
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
              {selectedVersionResponse.notice && (
                <div className="border-b border-gray-200 bg-blue-50 px-4 py-3 text-sm text-blue-700 dark:border-gray-700 dark:bg-blue-900/20 dark:text-blue-300">
                  <span className="mr-1.5 font-medium">{noticeKindLabel(selectedVersionResponse.notice_kind)}:</span>
                  {selectedVersionResponse.notice}
                </div>
              )}
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
                    <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">Version</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 sm:table-cell">Game versions</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 md:table-cell">Loaders</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 lg:table-cell">Size</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-400">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedVersionResponse.versions.map((v) => {
                    const primary = v.files.find((f) => f.primary) ?? v.files[0];
                    const isRecommended =
                      selectedVersionResponse.selected?.version_id === v.version_id;
                    return (
                      <tr
                        key={v.version_id}
                        className={`border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30 ${
                          isRecommended ? "bg-green-50/50 dark:bg-green-900/10" : ""
                        }`}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <p className="font-medium text-gray-900 dark:text-gray-100">{v.version_number}</p>
                            {isRecommended && (
                              <span className="inline-flex rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
                                Recommended
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 sm:table-cell">
                          {v.game_versions.slice(0, 3).join(", ")}
                          {v.game_versions.length > 3 ? ` +${v.game_versions.length - 3}` : ""}
                        </td>
                        <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 md:table-cell">
                          {v.loaders.join(", ")}
                        </td>
                        <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 lg:table-cell">
                          {primary ? formatBytes(primary.size_bytes) : "-"}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() => setInstallTarget({ project: selectedProject, version: v })}
                              disabled={install.isPending}
                              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
                            >
                              <Icon name="plus" size={14} />
                              Install
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="plugin"
              title="No versions available"
              description="This project has no downloadable versions."
            />
          )}
        </div>
      )}

      <ConfirmDialog
        open={installTarget !== null}
        title="Install plugin?"
        description={
          installTarget
            ? `Install "${installTarget.project.title}" ${installTarget.version.version_number} into ${serverName || "this server"}?`
            : undefined
        }
        confirmLabel="Install"
        cancelLabel="Cancel"
        onConfirm={handleInstallSelected}
        onCancel={() => setInstallTarget(null)}
      />
    </div>
  );
}
