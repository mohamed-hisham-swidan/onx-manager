import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import * as pluginHooks from "@/server_manager/hooks/usePlugins";
import {
  MARKETPLACE_PAGE_SIZE,
  useMarketplaceSearch,
  useMarketplaceSearchGlobal,
} from "@/server_manager/hooks/usePlugins";
import * as serverHooks from "@/server_manager/hooks/useServers";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { Pagination } from "@/components/ui/Pagination";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { ViewModeToggle } from "@/components/ui/ViewModeToggle";
import { InstallModal } from "@/server_manager/components/InstallModal";
import { ProjectCard } from "@/server_manager/components/ProjectCard";
import { getLoaderDisplay } from "@/server_manager/utils/compatibility";
import { findInstalledAddon } from "@/server_manager/utils/installedAddons";
import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import type { ServerResponse } from "@/server_manager/types";
import type {
  MarketplaceSortOption,
  PluginResponse,
  PluginSearchResultResponse,
} from "@/types";

const PLUGIN_LOADER_OPTIONS = [
  "paper",
  "purpur",
  "spigot",
  "bukkit",
  "folia",
  "velocity",
  "bungeecord",
  "waterfall",
  "minestom",
] as const;

const MOD_LOADER_OPTIONS = ["fabric", "neoforge", "forge", "quilt"] as const;

const SORT_OPTIONS: { value: MarketplaceSortOption; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "downloads", label: "Downloads" },
  { value: "updated", label: "Recently Updated" },
  { value: "newest", label: "Newest" },
  { value: "follows", label: "Most Followed" },
];

const COMMON_MC_VERSIONS = [
  "26.3",
  "26.2",
  "26.1.2",
  "26.1.1",
  "26.1",
  "1.21.11",
  "1.21.10",
  "1.21.9",
  "1.21.8",
  "1.21.7",
  "1.21.6",
  "1.21.5",
  "1.21.4",
  "1.21.1",
  "1.20.4",
  "1.20.1",
  "1.19.4",
  "1.18.2",
  "1.16.5",
  "1.12.2",
] as const;

function useSafeMinecraftVersions(): string[] | undefined {
  const fn = (pluginHooks as Record<string, unknown>).useMinecraftVersions;
  const hook =
    typeof fn === "function"
      ? (fn as () => { data?: string[] })
      : () => ({ data: undefined });
  return hook()?.data;
}

function useSafeServersList(): ServerResponse[] | undefined {
  const fn = (serverHooks as Record<string, unknown>).useServersList;
  const hook =
    typeof fn === "function"
      ? (fn as () => { data?: ServerResponse[] })
      : () => ({ data: undefined });
  return hook()?.data;
}

function useSafePluginsList(serverId: string, branch?: string): PluginResponse[] | undefined {
  const fn = (pluginHooks as Record<string, unknown>).usePluginsList;
  const hook =
    typeof fn === "function"
      ? (fn as (sid: string, br?: string) => { data?: PluginResponse[] })
      : () => ({ data: undefined });
  return hook(serverId, branch)?.data;
}

export interface PluginMarketplacePageProps {
  lockedProjectType?: "plugin" | "mod";
}

export function PluginMarketplacePage({ lockedProjectType }: PluginMarketplacePageProps = {}) {
  const navigate = useNavigate();
  const location = useLocation();
  const { serverId: routeServerId } = useParams<{ serverId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlServerId = searchParams.get("server") ?? searchParams.get("serverId") ?? "";
  const isInServerShell = Boolean(routeServerId);
  const serverId = routeServerId || urlServerId;
  const branchCtx = useServerBranchContext();
  const urlBranch =
    searchParams.get("branch") ??
    (branchCtx?.gitBacked && branchCtx.branch !== "main" ? branchCtx.branch : undefined);
  const urlQuery = searchParams.get("q") ?? "";
  const rawTypeParam = searchParams.get("type");
  const urlLoader = searchParams.get("loader") ?? "";
  const urlMc = searchParams.get("mc") ?? "";
  const rawSort = (searchParams.get("sort") ?? "relevance") as MarketplaceSortOption;
  const urlSort: MarketplaceSortOption = SORT_OPTIONS.some((o) => o.value === rawSort)
    ? rawSort
    : "relevance";
  const compatibleOnly = Boolean(serverId) && searchParams.get("compat") !== "0";

  const servers = useSafeServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);
  const scopedServer = useMemo(
    () => (serverId ? servers?.find((s) => s.server_id === serverId) : undefined),
    [servers, serverId],
  );
  const scopedCaps = useMemo(
    () => (scopedServer ? getServerCapabilities(scopedServer.server_type) : null),
    [scopedServer],
  );
  const isProjectTypeLocked = Boolean(
    lockedProjectType ||
      isInServerShell ||
      (serverId && scopedCaps && scopedCaps.supportsMods !== scopedCaps.supportsPlugins),
  );

  const projectType: "plugin" | "mod" = useMemo(() => {
    if (lockedProjectType) {
      return lockedProjectType;
    }
    if (scopedCaps) {
      if (scopedCaps.supportsMods && !scopedCaps.supportsPlugins) {
        return "mod";
      }
      if (scopedCaps.supportsPlugins && !scopedCaps.supportsMods) {
        return "plugin";
      }
    }
    if (rawTypeParam === "mod" || rawTypeParam === "plugin") {
      return rawTypeParam;
    }
    return "plugin";
  }, [lockedProjectType, scopedCaps, rawTypeParam]);

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

  // Debounce live search input updates into ?q=
  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed === urlQuery) return;
    const timer = setTimeout(() => {
      setSearchParams(
        (prev) => {
          const nextParams = new URLSearchParams(prev);
          if (trimmed) {
            nextParams.set("q", trimmed);
          } else {
            nextParams.delete("q");
          }
          nextParams.delete("page");
          return nextParams;
        },
        { replace: true },
      );
    }, 350);
    return () => clearTimeout(timer);
  }, [query, urlQuery, setSearchParams]);

  const stateProject = (location.state as { selectedProject?: PluginSearchResultResponse })
    ?.selectedProject;
  const [selectedProject, setSelectedProject] = useState<PluginSearchResultResponse | null>(
    stateProject ?? null,
  );
  const [prevProjectState, setPrevProjectState] = useState(stateProject);
  if (stateProject && stateProject !== prevProjectState) {
    setPrevProjectState(stateProject);
    setSelectedProject(stateProject);
  }

  const globalQuery = serverId ? "" : submitted;
  const urlPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const offset = (urlPage - 1) * MARKETPLACE_PAGE_SIZE;
  const loader = urlLoader || undefined;
  const gameVersion = urlMc || undefined;

  const extraFilterOpts = {
    ...(loader ? { loader } : {}),
    ...(urlSort !== "relevance" ? { sort: urlSort } : {}),
    ...(gameVersion ? { gameVersion } : {}),
  };

  const searchGlobal = useMarketplaceSearchGlobal(globalQuery, {
    enabled: !serverId,
    projectType,
    offset,
    ...extraFilterOpts,
  });
  const searchScoped = useMarketplaceSearch(serverId, submitted, {
    enabled: !!serverId,
    projectType,
    offset,
    ...extraFilterOpts,
    ...(compatibleOnly ? { compatibleOnly: true } : {}),
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

  // Installed awareness against scoped server (or valid last-used server)
  const validLastUsedServerId = useMemo(() => {
    if (!lastUsedServerId || !servers) return "";
    return servers.some((s) => s.server_id === lastUsedServerId) ? lastUsedServerId : "";
  }, [lastUsedServerId, servers]);
  const activeInstalledServerId = serverId || validLastUsedServerId;
  const installedPlugins = useSafePluginsList(activeInstalledServerId, urlBranch);

  const loaderOptions = projectType === "mod" ? MOD_LOADER_OPTIONS : PLUGIN_LOADER_OPTIONS;
  const liveMcVersions = useSafeMinecraftVersions();
  const scopedMcVersion = scopedServer?.minecraft_version;
  const mcVersionOptions = useMemo(() => {
    const base =
      Array.isArray(liveMcVersions) && liveMcVersions.length > 0
        ? liveMcVersions
        : [...COMMON_MC_VERSIONS];
    const list: string[] = [];
    const seen = new Set<string>();
    const add = (v: string | undefined) => {
      const trimmed = v?.trim();
      if (trimmed && !seen.has(trimmed)) {
        seen.add(trimmed);
        list.push(trimmed);
      }
    };
    add(urlMc);
    add(scopedMcVersion);
    for (const v of base) add(v);
    return list;
  }, [liveMcVersions, scopedMcVersion, urlMc]);

  const hasActiveFilters = Boolean(
    urlQuery || urlLoader || urlMc || urlSort !== "relevance",
  );

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

  function handleClearQuery() {
    setQuery("");
    const newParams = new URLSearchParams(searchParams);
    newParams.delete("q");
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleProjectTypeChange(newType: "plugin" | "mod") {
    if (isProjectTypeLocked) return;
    const newParams = new URLSearchParams(searchParams);
    if (newType === "plugin") {
      newParams.delete("type");
    } else {
      newParams.set("type", newType);
    }
    const targetLoaders: readonly string[] =
      newType === "mod" ? MOD_LOADER_OPTIONS : PLUGIN_LOADER_OPTIONS;
    if (urlLoader && !targetLoaders.includes(urlLoader.toLowerCase())) {
      newParams.delete("loader");
    }
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleLoaderChange(nextLoader: string) {
    const newParams = new URLSearchParams(searchParams);
    if (nextLoader) {
      newParams.set("loader", nextLoader);
    } else {
      newParams.delete("loader");
    }
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleSortChange(nextSort: MarketplaceSortOption) {
    const newParams = new URLSearchParams(searchParams);
    if (nextSort === "relevance") {
      newParams.delete("sort");
    } else {
      newParams.set("sort", nextSort);
    }
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleMcVersionChange(nextMc: string) {
    const newParams = new URLSearchParams(searchParams);
    if (nextMc) {
      newParams.set("mc", nextMc);
    } else {
      newParams.delete("mc");
    }
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleToggleCompatibleOnly() {
    const newParams = new URLSearchParams(searchParams);
    if (compatibleOnly) {
      newParams.set("compat", "0");
    } else {
      newParams.delete("compat");
    }
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleClearAllFilters() {
    setQuery("");
    const newParams = new URLSearchParams(searchParams);
    newParams.delete("q");
    newParams.delete("loader");
    newParams.delete("mc");
    newParams.delete("sort");
    newParams.delete("page");
    setSearchParams(newParams);
  }

  function handleCloseVersions() {
    setSelectedProject(null);
    if (location.state) {
      navigate(location.pathname + location.search, { replace: true, state: {} });
    }
  }

  function handleBackToServer() {
    if (!serverId) return;
    const section = projectType === "mod" ? "mods" : "plugins";
    const branchSuffix =
      urlBranch && urlBranch !== "main" ? `?branch=${encodeURIComponent(urlBranch)}` : "";
    navigate(`/servers/${encodeURIComponent(serverId)}/${section}${branchSuffix}`);
  }

  const nounPlural = projectType === "mod" ? "mods" : "plugins";
  const detailBasePath =
    isInServerShell && routeServerId
      ? `/servers/${encodeURIComponent(routeServerId)}/${projectType === "mod" ? "mods" : "plugins"}/marketplace`
      : "/marketplace";
  const headerDescription = scopedServer
    ? `Browsing for ${scopedServer.name} (${getLoaderDisplay(scopedServer.server_type).label} · MC ${scopedServer.minecraft_version})`
    : "Browse and install plugins and mods from Modrinth.";

  return (
    <div
      className={
        isInServerShell
          ? "space-y-5"
          : "mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-6 space-y-5"
      }
    >
      <PageHeader
        title="Marketplace"
        description={headerDescription}
        icon="store"
        className="mb-0"
        actions={
          serverId ? (
            <button
              type="button"
              onClick={handleBackToServer}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3.5 py-2 text-sm font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary cursor-pointer"
            >
              <Icon name="chevron-left" size={16} />
              Back to {scopedServer?.name ?? (projectType === "mod" ? "Mods" : "Plugins")}
            </button>
          ) : undefined
        }
      />

      {/* Row 1: Type Switcher, Live Debounced Search, Sort, View Mode */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          {!isProjectTypeLocked && (
            <div
              role="group"
              aria-label="Discover type"
              className="inline-flex shrink-0 items-center rounded-lg border border-border-subtle bg-surface-elevated p-0.5"
            >
              <button
                type="button"
                onClick={() => handleProjectTypeChange("plugin")}
                aria-pressed={projectType === "plugin"}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                  projectType === "plugin"
                    ? "bg-surface-card text-text-primary shadow-2xs font-semibold"
                    : "text-text-muted hover:text-text-primary"
                }`}
              >
                Plugins
              </button>
              <button
                type="button"
                onClick={() => handleProjectTypeChange("mod")}
                aria-pressed={projectType === "mod"}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                  projectType === "mod"
                    ? "bg-surface-card text-text-primary shadow-2xs font-semibold"
                    : "text-text-muted hover:text-text-primary"
                }`}
              >
                Mods
              </button>
            </div>
          )}

          <form onSubmit={handleSearch} className="relative flex-1 min-w-[220px]">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-text-muted">
              <Icon name="search" size={15} />
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${nounPlural}...`}
              aria-label={`Search ${nounPlural}`}
              className="h-9 w-full rounded-lg border border-border-default bg-surface-card pl-9 pr-8 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus"
            />
            {query && (
              <button
                type="button"
                onClick={handleClearQuery}
                aria-label="Clear search"
                className="absolute inset-y-0 right-0 flex items-center pr-2.5 text-text-muted hover:text-text-primary cursor-pointer"
              >
                <Icon name="x" size={14} />
              </button>
            )}
          </form>

          <div className="flex items-center gap-2 shrink-0">
            <div className="relative">
              <label htmlFor="marketplace-sort" className="sr-only">
                Sort results
              </label>
              <select
                id="marketplace-sort"
                aria-label="Sort results"
                value={urlSort}
                onChange={(e) => handleSortChange(e.target.value as MarketplaceSortOption)}
                className="h-9 appearance-none rounded-lg border border-border-default bg-surface-card pl-3 pr-8 text-xs font-medium text-text-primary focus:border-border-focus focus:outline-none focus:ring-1 focus:ring-border-focus cursor-pointer"
              >
                {SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    Sort: {opt.label}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted">
                <Icon name="chevron-down" size={13} />
              </div>
            </div>

            <ViewModeToggle
              mode={viewMode}
              onChange={setViewMode}
              storageKey="onx_marketplace_view_mode"
            />
          </div>
        </div>

        {/* Row 2: Compact Filter Chips Bar */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {serverId && (
              <button
                type="button"
                data-testid="compatible-only-toggle"
                aria-pressed={compatibleOnly}
                onClick={handleToggleCompatibleOnly}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer ${
                  compatibleOnly
                    ? "border-accent-primary/40 bg-accent-primary/12 text-accent-primary"
                    : "border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover"
                }`}
              >
                <Icon name={compatibleOnly ? "check" : "filter"} size={12} />
                <span>Compatible with {scopedServer?.name ?? "this server"}</span>
              </button>
            )}

            <div className="relative">
              <label htmlFor="marketplace-loader-filter" className="sr-only">
                Filter by loader
              </label>
              <select
                id="marketplace-loader-filter"
                aria-label="Filter by loader"
                value={urlLoader}
                onChange={(e) => handleLoaderChange(e.target.value)}
                className="h-8 appearance-none rounded-lg border border-border-default bg-surface-card pl-2.5 pr-7 text-xs font-medium text-text-secondary focus:border-border-focus focus:outline-none cursor-pointer"
              >
                <option value="">All Loaders</option>
                {loaderOptions.map((ldr) => (
                  <option key={ldr} value={ldr}>
                    {getLoaderDisplay(ldr).label}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-text-muted">
                <Icon name="chevron-down" size={12} />
              </div>
            </div>

            <div className="relative">
              <label htmlFor="marketplace-mc-filter" className="sr-only">
                Filter by Minecraft version
              </label>
              <select
                id="marketplace-mc-filter"
                aria-label="Filter by Minecraft version"
                value={urlMc}
                onChange={(e) => handleMcVersionChange(e.target.value)}
                className="h-8 appearance-none rounded-lg border border-border-default bg-surface-card pl-2.5 pr-7 text-xs font-medium text-text-secondary focus:border-border-focus focus:outline-none cursor-pointer"
              >
                <option value="">All MC Versions</option>
                {mcVersionOptions.map((mc) => (
                  <option key={mc} value={mc}>
                    MC {mc}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-text-muted">
                <Icon name="chevron-down" size={12} />
              </div>
            </div>

            {urlLoader && (
              <span
                className="inline-flex items-center gap-1.5 rounded-md border border-status-info-border bg-status-info-bg px-2.5 py-1 text-xs font-medium text-status-info"
                data-testid="loader-filter-tag"
              >
                <Icon name={getLoaderDisplay(urlLoader).icon} size={12} className="shrink-0" />
                {getLoaderDisplay(urlLoader).label}
                <button
                  type="button"
                  onClick={() => handleLoaderChange("")}
                  aria-label={`Remove ${getLoaderDisplay(urlLoader).label} platform filter`}
                  className="text-status-info transition-colors hover:text-text-primary cursor-pointer"
                >
                  <Icon name="x" size={12} />
                </button>
              </span>
            )}

            {hasActiveFilters && (
              <button
                type="button"
                onClick={handleClearAllFilters}
                className="text-xs font-medium text-text-muted hover:text-text-primary underline-offset-2 hover:underline cursor-pointer"
              >
                Clear filters
              </button>
            )}
          </div>

          {search.data && (
            <span className="text-xs font-medium text-text-muted tabular-nums">
              {totalHits.toLocaleString()} {totalHits === 1 ? "result" : "results"}
            </span>
          )}
        </div>
      </div>

      {search.isError && (
        <ErrorState
          message={search.error instanceof Error ? search.error.message : "Search failed"}
          onRetry={
            typeof (search as { refetch?: () => unknown }).refetch === "function"
              ? () => void (search as { refetch: () => unknown }).refetch()
              : undefined
          }
        />
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
                detailBasePath={detailBasePath}
                isInstalled={Boolean(
                  findInstalledAddon(installedPlugins, {
                    project_id: p.project_id,
                    slug: p.slug,
                    title: p.title,
                  }),
                )}
              />
            ))}
          </ul>
          <Pagination totalItems={search.data.total_hits} />
        </>
      ) : (
        <EmptyState
          icon="search"
          title={projectType === "mod" ? "No mods found" : "No plugins found"}
          description={
            submitted.trim()
              ? `No ${nounPlural} matched "${submitted}". Try a different term or adjust your filters.`
              : `No ${nounPlural} available for the current filters.`
          }
          action={
            hasActiveFilters
              ? { label: "Clear filters", onClick: handleClearAllFilters }
              : undefined
          }
        />
      )}

      {selectedProject && (
        <InstallModal
          project={selectedProject}
          projectType={projectType}
          serverId={serverId || undefined}
          branch={urlBranch}
          onClose={handleCloseVersions}
        />
      )}
    </div>
  );
}
