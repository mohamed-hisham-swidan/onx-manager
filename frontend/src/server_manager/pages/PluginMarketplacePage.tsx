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
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { ViewModeToggle } from "@/components/ui/ViewModeToggle";
import { InstallModal } from "@/server_manager/components/InstallModal";
import { ProjectCard } from "@/server_manager/components/ProjectCard";
import { getLoaderDisplay } from "@/server_manager/utils/compatibility";
import type { PluginSearchResultResponse } from "@/types";

export function PluginMarketplacePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlServerId = searchParams.get("server") ?? searchParams.get("serverId") ?? "";
  const urlBranch = searchParams.get("branch") ?? undefined;
  const urlQuery = searchParams.get("q") ?? "";
  const urlProjectType = (searchParams.get("type") as "plugin" | "mod") || "plugin";
  const urlLoader = searchParams.get("loader") ?? "";

  const [viewMode, setViewMode] = useState<"grid" | "list">(() => {
    try {
      const saved = localStorage.getItem("onx_marketplace_view_mode");
      if (saved === "grid" || saved === "list") return saved;
    } catch {
      // ignore
    }
    return "grid";
  });

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

  const serverId = urlServerId;
  const globalQuery = serverId ? "" : submitted;
  const urlPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const offset = (urlPage - 1) * MARKETPLACE_PAGE_SIZE;
  const loader = urlLoader || undefined;
  const searchGlobal = useMarketplaceSearchGlobal(globalQuery, {
    enabled: !serverId,
    projectType,
    offset,
    loader,
  });
  const searchScoped = useMarketplaceSearch(serverId, submitted, {
    enabled: !!serverId,
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
        description="Browse and install plugins from Modrinth"
        icon="plugin"
        actions={
          serverId ? (
            <button
              onClick={() => navigate("/plugins")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-4 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer"
            >
              <Icon name="chevron-left" size={16} />
              Back to Plugins
            </button>
          ) : undefined
        }
      />

      <div className="mb-5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className="relative inline-flex items-center shrink-0">
            <label htmlFor="discover-select" className="sr-only">
              Discover
            </label>
            <div className="relative">
              <select
                id="discover-select"
                aria-label="Discover type"
                value={projectType}
                onChange={(e) => handleProjectTypeChange(e.target.value as "plugin" | "mod")}
                className="h-9 appearance-none rounded-lg border border-border-default bg-surface-card pl-3 pr-8 text-sm font-medium text-text-primary focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
              >
                <option value="plugin">Plugins</option>
                <option value="mod">Mods</option>
              </select>
              <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted">
                <Icon name="chevron-down" size={14} />
              </div>
            </div>
          </div>

          <form onSubmit={handleSearch} className="flex-1 max-w-lg min-w-0">
            <div className="flex items-center gap-2">
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
                className="h-9 w-full rounded-lg border border-border-default bg-surface-card px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
              />
              <button
                type="submit"
                className="h-9 shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover disabled:opacity-40 cursor-pointer"
              >
                <Icon name="search" size={15} />
                <span>Search</span>
              </button>
            </div>
          </form>
        </div>

        <div className="shrink-0">
          <ViewModeToggle
            mode={viewMode}
            onChange={setViewMode}
            storageKey="onx_marketplace_view_mode"
          />
        </div>
      </div>

      {!serverId && (
        <p className="-mt-4 mb-6 text-sm text-text-muted">
          Browse the global marketplace without a server — you'll pick a destination when installing.
        </p>
      )}

      {urlLoader && (
        <div
          className="-mt-3 mb-6 flex flex-wrap items-center gap-2"
          data-testid="loader-filter-tag"
        >
          <span className="text-sm text-text-muted">Platform:</span>
          <span className="inline-flex items-center gap-1.5 rounded-md border border-status-info-border bg-status-info-bg px-2.5 py-1 text-xs font-medium text-status-info">
            <Icon name={getLoaderDisplay(urlLoader).icon} size={12} className="shrink-0" />
            {getLoaderDisplay(urlLoader).label}
            <button
              type="button"
              onClick={handleClearLoader}
              aria-label={`Remove ${getLoaderDisplay(urlLoader).label} platform filter`}
              className="text-status-info transition-colors hover:text-accent-hover"
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
        <div
          className={
            viewMode === "grid"
              ? "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
              : "space-y-3"
          }
          data-testid="marketplace-cards-loading"
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="space-y-3 rounded-xl border border-border-subtle bg-surface-card p-4"
            >
              <div className="flex items-start gap-3">
                <Skeleton className="h-12 w-12 rounded-xl" />
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
          <ul
            className={
              viewMode === "grid"
                ? "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
                : "space-y-3"
            }
            data-testid="project-card-list"
          >
            {search.data.items.map((p) => (
              <ProjectCard
                key={p.project_id}
                project={p}
                searchParams={searchParams}
                onInstall={setSelectedProject}
                viewMode={viewMode}
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
          branch={urlBranch}
          onClose={handleCloseVersions}
        />
      )}
    </div>
  );
}
