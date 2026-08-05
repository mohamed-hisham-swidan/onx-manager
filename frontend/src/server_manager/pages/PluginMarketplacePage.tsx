import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useServersList } from "@/server_manager/hooks/useServers";
import {
  useMarketplaceSearch,
  useMarketplaceSearchGlobal,
  useProjectVersions,
  useInstallFromMarketplace,
} from "@/server_manager/hooks/usePlugins";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/EmptyState";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/Skeleton";
import { toast } from "@/stores/toastStore";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import { formatBytes } from "@/server_manager/utils/format";
import type { ServerResponse } from "@/server_manager/types";
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

function serverMatchesVersion(server: ServerResponse, version: PluginVersionResponse): boolean {
  const loaderMatch = version.loaders.some(
    (loader) => loader.toLowerCase() === server.server_type.toLowerCase(),
  );
  const mcMatch = version.game_versions.includes(server.minecraft_version);
  return loaderMatch && mcMatch;
}

export function PluginMarketplacePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlServerId = searchParams.get("server") ?? "";

  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [selectedProject, setSelectedProject] = useState<PluginSearchResultResponse | null>(null);
  const [chosenVersion, setChosenVersion] = useState<PluginVersionResponse | null>(null);
  const [targetServerId, setTargetServerId] = useState("");
  const [pendingInstall, setPendingInstall] = useState<{
    project: PluginSearchResultResponse;
    version: PluginVersionResponse;
  } | null>(null);

  const { data: servers } = useServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);
  const setLastUsedServer = useLastUsedServerStore((s) => s.setLastUsedServer);

  const serverId = urlServerId;

  const globalQuery = serverId ? "" : submitted;
  const searchGlobal = useMarketplaceSearchGlobal(globalQuery);
  const searchScoped = useMarketplaceSearch(serverId, submitted);
  const search = serverId ? searchScoped : searchGlobal;

  const contextServerId = useMemo(() => {
    if (serverId && servers?.some((s) => s.server_id === serverId)) return serverId;
    if (lastUsedServerId && servers?.some((s) => s.server_id === lastUsedServerId)) return lastUsedServerId;
    return servers?.[0]?.server_id ?? "";
  }, [serverId, lastUsedServerId, servers]);

  const versions = useProjectVersions(contextServerId, selectedProject?.project_id ?? "");
  const install = useInstallFromMarketplace(targetServerId);

  const compatibleServers = useMemo(() => {
    if (!chosenVersion || !servers) return [];
    return [...servers].sort(
      (a, b) =>
        Number(serverMatchesVersion(b, chosenVersion)) - Number(serverMatchesVersion(a, chosenVersion)),
    );
  }, [servers, chosenVersion]);

  const targetServer = useMemo(
    () => servers?.find((s) => s.server_id === targetServerId),
    [servers, targetServerId],
  );

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(query.trim());
  }

  function handleCloseVersions() {
    setSelectedProject(null);
    setChosenVersion(null);
    setTargetServerId("");
    setPendingInstall(null);
    install.reset();
  }

  function handleChooseVersion(version: PluginVersionResponse) {
    setChosenVersion(version);
    const deepLinkServer =
      urlServerId && servers?.some((s) => s.server_id === urlServerId) ? urlServerId : undefined;
    const lastUsedValid =
      lastUsedServerId && servers?.some((s) => s.server_id === lastUsedServerId)
        ? lastUsedServerId
        : undefined;
    const firstCompatible = servers?.find((s) => serverMatchesVersion(s, version));
    setTargetServerId(
      deepLinkServer || lastUsedValid || firstCompatible?.server_id || servers?.[0]?.server_id || "",
    );
  }

  function handleBackToVersions() {
    setChosenVersion(null);
    setPendingInstall(null);
  }

  function handleContinue() {
    if (!selectedProject || !chosenVersion || !targetServerId) return;
    setPendingInstall({ project: selectedProject, version: chosenVersion });
  }

  function handleConfirmInstall() {
    if (!pendingInstall || !targetServerId) return;
    install.mutate(
      {
        project_id: pendingInstall.project.project_id,
        version_id: pendingInstall.version.version_id,
      },
      {
        onSuccess: (result) => {
          setLastUsedServer(targetServerId);
          toast(
            "success",
            "Plugin installed",
            `"${pendingInstall.project.title}" ${result.version} installed into ${targetServer?.name ?? "this server"}.`,
          );
          setPendingInstall(null);
          setChosenVersion(null);
          setSelectedProject(null);
          setTargetServerId("");
        },
        onError: (err) => toast("error", "Install failed", errorMessage(err)),
      },
    );
  }

  const selectedVersionResponse: PluginVersionsResponse | undefined = versions.data;
  const hasServers = !!(servers && servers.length > 0);

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
            placeholder={serverId ? "Search plugins for this server..." : "Search the global marketplace..."}
            aria-label="Search plugins"
            className="w-full max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
          />
          <button
            type="submit"
            disabled={!query.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
          >
            <Icon name="search" size={16} />
            Search
          </button>
        </div>
        {!serverId && (
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            Browse the global marketplace without a server — you'll pick a destination when installing.
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
      ) : !chosenVersion ? (
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
                    return (
                      <tr
                        key={v.version_id}
                        className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                      >
                        <td className="px-4 py-3">
                          <p className="font-medium text-gray-900 dark:text-gray-100">{v.version_number}</p>
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
                              onClick={() => handleChooseVersion(v)}
                              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700"
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
      ) : (
        <div className="space-y-4">
          <button
            onClick={handleBackToVersions}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            <Icon name="chevron-left" size={14} />
            Back to versions
          </button>

          <div>
            <h3 className="mb-1 text-base font-semibold text-gray-900 dark:text-gray-100">
              Choose a target server
            </h3>
            <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
              Installing "{selectedProject.title}" {chosenVersion.version_number} — targeting{" "}
              {chosenVersion.loaders.join(" / ")} on Minecraft {chosenVersion.game_versions.join(", ")}.
            </p>
          </div>

          {!hasServers ? (
            <EmptyState
              icon="server"
              title="No servers available"
              description="You need a server to install this plugin into. Create one to continue."
              action={
                <button
                  onClick={() => navigate("/servers/create")}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                >
                  <Icon name="plus" size={16} />
                  Create a server
                </button>
              }
            />
          ) : (
            <div className="space-y-2">
              {compatibleServers.map((s) => {
                const matches = serverMatchesVersion(s, chosenVersion);
                return (
                  <label
                    key={s.server_id}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors ${
                      targetServerId === s.server_id
                        ? "border-blue-500 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-900/20"
                        : "border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800"
                    }`}
                  >
                    <input
                      type="radio"
                      name="install-server"
                      value={s.server_id}
                      checked={targetServerId === s.server_id}
                      onChange={() => setTargetServerId(s.server_id)}
                      className="mt-1 accent-blue-600"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="font-medium text-gray-900 dark:text-gray-100">{s.name}</p>
                        {matches ? (
                          <span className="inline-flex rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
                            Compatible
                          </span>
                        ) : (
                          <span className="inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                            May not work
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                        {s.server_type} / {s.minecraft_version}
                      </p>
                      {!matches && (
                        <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                          This server runs {s.server_type} {s.minecraft_version} — this plugin targets{" "}
                          {chosenVersion.loaders.join("/")} on Minecraft {chosenVersion.game_versions.join(", ")} and may not work.
                        </p>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          )}

          <div className="flex justify-end">
            <button
              onClick={handleContinue}
              disabled={!hasServers || !targetServerId}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
            >
              Continue
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={pendingInstall !== null}
        title="Install plugin?"
        description={
          pendingInstall
            ? `Install "${pendingInstall.project.title}" ${pendingInstall.version.version_number} into ${targetServer?.name ?? "this server"}?`
            : undefined
        }
        confirmLabel="Install"
        cancelLabel="Cancel"
        onConfirm={handleConfirmInstall}
        onCancel={() => setPendingInstall(null)}
      />
    </div>
  );
}
