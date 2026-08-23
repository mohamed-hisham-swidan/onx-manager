import { useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
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
import { Skeleton } from "@/components/Skeleton";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";
import { InstallModal } from "@/server_manager/components/InstallModal";
import { ProjectCard } from "@/server_manager/components/ProjectCard";
import { getLoaderDisplay } from "@/server_manager/components/CompatibilityCard";
import type { PluginSearchResultResponse } from "@/types";

export function PluginMarketplacePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlServerId = searchParams.get("server") ?? "";
  const urlQuery = searchParams.get("q") ?? "";
  const urlProjectType = (searchParams.get("type") as "plugin" | "mod") || "plugin";
  const urlLoader = searchParams.get("loader") ?? "";

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
  const loader = urlLoader || undefined;
  const searchGlobal = useMarketplaceSearchGlobal(globalQuery, {
    enabled: isModrinth,
    projectType,
    offset,
    loader,
  });
  const searchScoped = useMarketplaceSearch(serverId, submitted, {
    enabled: isModrinth,
    projectType,
    offset,
    loader,
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

  function handleClearLoader() {
    const newParams = new URLSearchParams(searchParams);
    newParams.delete("loader");
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

          {urlLoader && (
            <div
              className="-mt-3 mb-6 flex flex-wrap items-center gap-2"
              data-testid="loader-filter-tag"
            >
              <span className="text-sm text-gray-500 dark:text-gray-400">Platform:</span>
              <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                <Icon name={getLoaderDisplay(urlLoader).icon} size={12} className="shrink-0" />
                {getLoaderDisplay(urlLoader).label}
                <button
                  type="button"
                  onClick={handleClearLoader}
                  aria-label={`Remove ${getLoaderDisplay(urlLoader).label} platform filter`}
                  className="text-blue-500 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-200"
                >
                  <Icon name="x" size={12} />
                </button>
              </span>
            </div>
          )}

          {search.isError && (
            <ErrorState className="mb-6" message={search.error instanceof Error ? search.error.message : "Search failed"} />
          )}

          {search.isLoading ? (
            <div className="space-y-3" data-testid="marketplace-cards-loading">
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="space-y-3 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800"
                >
                  <div className="flex items-start gap-3">
                    <Skeleton className="h-11 w-11 rounded-lg" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-4 w-1/3" />
                      <Skeleton className="h-3 w-1/4" />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Skeleton className="h-4 w-16" />
                    <Skeleton className="h-4 w-20" />
                  </div>
                </div>
              ))}
            </div>
          ) : search.isError ? null : search.data && search.data.items.length > 0 ? (
            <>
              <ul className="space-y-3" data-testid="project-card-list">
                {search.data.items.map((p) => (
                  <ProjectCard
                    key={p.project_id}
                    project={p}
                    searchParams={searchParams}
                    onInstall={setSelectedProject}
                  />
                ))}
              </ul>
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
