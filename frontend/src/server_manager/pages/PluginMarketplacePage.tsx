import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  MARKETPLACE_PAGE_SIZE,
  useMarketplaceSearch,
  useMarketplaceSearchGlobal,
} from "@/server_manager/hooks/usePlugins";
import { Pagination } from "@/components/ui/Pagination";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { ComingSoonState } from "@/components/ComingSoonState";
import { TableSkeleton } from "@/components/Skeleton";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";
import { InstallModal } from "@/server_manager/components/InstallModal";
import type { PluginSearchResultResponse } from "@/types";

function fmtDownloads(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function PluginMarketplacePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlServerId = searchParams.get("server") ?? "";
  const urlQuery = searchParams.get("q") ?? "";
  const urlProjectType = (searchParams.get("type") as "plugin" | "mod") || "plugin";

  const [query, setQuery] = useState(urlQuery);
  const [prevUrlQuery, setPrevUrlQuery] = useState(urlQuery);
  if (urlQuery !== prevUrlQuery) {
    setPrevUrlQuery(urlQuery);
    setQuery(urlQuery);
  }

  const submitted = urlQuery;
  const projectType = urlProjectType;

  const stateProject = (location.state as { selectedProject?: PluginSearchResultResponse })?.selectedProject;
  const [selectedProject, setSelectedProject] = useState<PluginSearchResultResponse | null>(stateProject ?? null);
  const [prevProjectState, setPrevProjectState] = useState(stateProject);
  if (stateProject && stateProject !== prevProjectState) {
    setPrevProjectState(stateProject);
    setSelectedProject(stateProject);
  }

  const source = useMarketplaceSourceStore((s) => s.source);
  const setSource = useMarketplaceSourceStore((s) => s.setSource);

  const serverId = urlServerId;
  const isModrinth = source === "modrinth";

  const globalQuery = serverId ? "" : submitted;
  const urlPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const offset = (urlPage - 1) * MARKETPLACE_PAGE_SIZE;
  const searchGlobal = useMarketplaceSearchGlobal(globalQuery, {
    enabled: isModrinth,
    projectType,
    offset,
  });
  const searchScoped = useMarketplaceSearch(serverId, submitted, {
    enabled: isModrinth,
    projectType,
    offset,
  });
  const search = serverId ? searchScoped : searchGlobal;

  const totalHits = search.data?.total_hits ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalHits / MARKETPLACE_PAGE_SIZE));
  useEffect(() => {
    if (search.data && urlPage > totalPages) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("page", String(totalPages));
      setSearchParams(nextParams, { replace: true });
    }
  }, [search.data, urlPage, totalPages, searchParams, setSearchParams]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const newParams = new URLSearchParams(searchParams);
    const trimmed = query.trim();
    if (trimmed) {
      newParams.set("q", trimmed);
    } else {
      newParams.delete("q");
    }
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleProjectTypeChange(newType: "plugin" | "mod") {
    const newParams = new URLSearchParams(searchParams);
    if (newType === "plugin") {
      newParams.delete("type");
    } else {
      newParams.set("type", newType);
    }
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleCloseVersions() {
    setSelectedProject(null);
    if (location.state) {
      navigate(location.pathname + location.search, { replace: true, state: {} });
    }
  }

  return (
    <div>
      <PageHeader
        title="Plugin Marketplace"
        description={
          source === "curseforge"
            ? "Browse projects from CurseForge"
            : "Browse and install plugins from Modrinth"
        }
        icon="plugin"
        actions={
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1 dark:border-gray-700 dark:bg-gray-800/80">
              <button
                type="button"
                onClick={() => setSource("modrinth")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  source === "modrinth"
                    ? "bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100"
                    : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
                }`}
              >
                <Icon name="modrinth" size={14} />
                Modrinth
              </button>
              <button
                type="button"
                onClick={() => setSource("curseforge")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  source === "curseforge"
                    ? "bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100"
                    : "text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
                }`}
              >
                <Icon name="curseforge" size={14} />
                CurseForge
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                  Soon
                </span>
              </button>
            </div>
            {serverId && (
              <button
                onClick={() => navigate("/plugins")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                <Icon name="chevron-left" size={16} />
                Back to Plugins
              </button>
            )}
          </div>
        }
      />

      {source === "curseforge" ? (
        <ComingSoonState
          icon="curseforge"
          title="CurseForge Integration Coming Soon"
          description="Backend support for discovering and installing projects from CurseForge is planned for a future update. Select Modrinth to browse available plugins."
          badge="Coming Soon"
          action={
            <button
              type="button"
              onClick={() => setSource("modrinth")}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              <Icon name="modrinth" size={16} />
              Switch to Modrinth
            </button>
          }
        />
      ) : (
        <>
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <div className="relative inline-flex items-center">
              <label htmlFor="discover-select" className="sr-only">
                Discover
              </label>
              <div className="relative">
                <select
                  id="discover-select"
                  aria-label="Discover type"
                  value={projectType}
                  onChange={(e) => handleProjectTypeChange(e.target.value as "plugin" | "mod")}
                  className="appearance-none rounded-lg border border-gray-300 bg-white py-2 pl-3 pr-8 text-sm font-medium text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
                >
                  <option value="plugin">Plugins</option>
                  <option value="mod">Mods</option>
                </select>
                <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 dark:text-gray-400">
                  <Icon name="chevron-down" size={14} />
                </div>
              </div>
            </div>

            <form onSubmit={handleSearch} className="flex-1">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={
                    serverId
                      ? `Search ${projectType === "mod" ? "mods" : "plugins"} for this server...`
                      : `Search ${projectType === "mod" ? "mods" : "plugins"} in the global marketplace...`
                  }
                  aria-label="Search plugins"
                  className="w-full max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
                />
                <button
                  type="submit"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-40"
                >
                  <Icon name="search" size={16} />
                  Search
                </button>
              </div>
            </form>
          </div>
          {!serverId && (
            <p className="-mt-4 mb-6 text-sm text-gray-500 dark:text-gray-400">
              Browse the global marketplace without a server — you'll pick a destination when installing.
            </p>
          )}

          {search.isError && (
            <ErrorState className="mb-6" message={search.error instanceof Error ? search.error.message : "Search failed"} />
          )}

          {search.isLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : search.isError ? null : search.data && search.data.items.length > 0 ? (
            <>
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
                  {search.data.items.map((p) => (
                    <tr
                      key={p.project_id}
                      className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                    >
                      <td className="px-4 py-3">
                        <Link
                          to={`/marketplace/${p.project_id}${searchParams.toString() ? `?${searchParams.toString()}` : ""}`}
                          className="flex items-center gap-3 group"
                        >
                          {p.icon_url ? (
                            <img
                              src={p.icon_url}
                              alt=""
                              className="h-9 w-9 shrink-0 rounded-lg object-cover"
                            />
                          ) : (
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500">
                              <Icon name="plugin" size={18} />
                            </div>
                          )}
                          <div>
                            <p className="font-medium text-gray-900 group-hover:text-blue-600 group-hover:underline dark:text-gray-100 dark:group-hover:text-blue-400">
                              {p.title}
                            </p>
                            {p.description && (
                              <p className="mt-0.5 max-w-md truncate text-xs text-gray-500 dark:text-gray-400" title={p.description}>
                                {p.description}
                              </p>
                            )}
                          </div>
                        </Link>
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
              <Pagination totalItems={search.data.total_hits} />
            </>
          ) : (
            <EmptyState
              icon="search"
              title="No plugins found"
              description={
                submitted.trim()
                  ? `No results for "${submitted}". Try a different search term.`
                  : "No plugins available in the marketplace right now."
              }
            />
          )}

          {selectedProject && (
            <InstallModal
              project={selectedProject}
              projectType={projectType}
              onClose={handleCloseVersions}
            />
          )}
        </>
      )}
    </div>
  );
}
