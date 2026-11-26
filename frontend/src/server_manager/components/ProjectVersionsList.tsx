import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import * as pluginHooks from "@/server_manager/hooks/usePlugins";
import {
  MARKETPLACE_PAGE_SIZE,
  useMarketplaceProjectVersions,
} from "@/server_manager/hooks/usePlugins";
import { Pagination } from "@/components/ui/Pagination";
import { useServersList } from "@/server_manager/hooks/useServers";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import {
  formatBytes,
  formatDateTime,
  formatRelativeTime,
} from "@/server_manager/utils/format";
import { selectRecommendedVersion } from "@/server_manager/utils/versionMatching";
import {
  getLoaderDisplay,
  groupReleaseVersions,
  isSnapshotOrPreRelease,
  parseGameVersion,
  sortReleaseVersionsDesc,
} from "@/server_manager/utils/compatibility";
import { MarketplaceMarkdown } from "@/server_manager/components/MarketplaceMarkdown";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { Icon } from "@/components/ui/Icon";
import type { PluginVersionResponse } from "@/types";

export interface ProjectVersionsListProps {
  projectId: string;
  serverId?: string;
  onInstallVersion?: (version: PluginVersionResponse) => void;
}

type ChannelFilter = "all" | "release" | "beta" | "alpha";

const CHANNEL_META: Record<
  Exclude<ChannelFilter, "all">,
  { label: string; badgeClass: string }
> = {
  release: {
    label: "Release",
    badgeClass: "border-status-success-border bg-status-success-bg text-status-success",
  },
  beta: {
    label: "Beta",
    badgeClass: "border-status-warning-border bg-status-warning-bg text-status-warning",
  },
  alpha: {
    label: "Alpha",
    badgeClass: "border-status-danger-border bg-status-danger-bg text-status-danger",
  },
};

function getVersionChannel(v: PluginVersionResponse): Exclude<ChannelFilter, "all"> {
  const raw = (v.version_type || "release").trim().toLowerCase();
  if (raw === "alpha") return "alpha";
  if (raw === "beta") return "beta";
  return "release";
}

function isSnapshotOnlyVersion(v: PluginVersionResponse): boolean {
  if (!v.game_versions || v.game_versions.length === 0) return false;
  return v.game_versions.every((gv) => isSnapshotOrPreRelease(gv));
}

function releaseKey(version: string): string | null {
  const parsed = parseGameVersion(version);
  if (!parsed) return null;
  return `${parsed.major}.${parsed.minor}.${parsed.patch}`;
}

export function ProjectVersionsList({
  projectId,
  serverId,
  onInstallVersion,
}: ProjectVersionsListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const offset = (urlPage - 1) * MARKETPLACE_PAGE_SIZE;
  const { data: servers } = useServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);

  const targetServer = useMemo(() => {
    if (!servers || servers.length === 0) return undefined;
    if (serverId) {
      const explicit = servers.find((s) => s.server_id === serverId);
      if (explicit) return explicit;
    }
    if (lastUsedServerId) {
      return servers.find((s) => s.server_id === lastUsedServerId);
    }
    return undefined;
  }, [servers, serverId, lastUsedServerId]);

  const hasServerVersionsHook =
    Object.prototype.hasOwnProperty.call(pluginHooks, "useProjectVersions") &&
    typeof (pluginHooks as Record<string, unknown>).useProjectVersions === "function";
  const serverVersionsHook = hasServerVersionsHook
    ? (pluginHooks.useProjectVersions as typeof pluginHooks.useProjectVersions)
    : () => ({ data: undefined, isLoading: false, error: null, refetch: undefined });
  const useServerQuery = Boolean(targetServer?.server_id && hasServerVersionsHook);
  const serverVersionsQuery = serverVersionsHook(
    targetServer?.server_id ?? "",
    projectId,
    { enabled: useServerQuery, offset },
  );
  const globalVersionsQuery = useMarketplaceProjectVersions(
    projectId,
    useServerQuery ? { enabled: false, offset } : { offset },
  );
  const versionsQuery = useServerQuery ? serverVersionsQuery : globalVersionsQuery;
  const { data: versionsData, isLoading, error } = versionsQuery;

  const versions = useMemo(() => versionsData?.versions ?? [], [versionsData?.versions]);
  const totalVersions = versionsData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalVersions / MARKETPLACE_PAGE_SIZE));

  const [loaderFilter, setLoaderFilter] = useState<string>("all");
  const [mcFilter, setMcFilter] = useState<string>("all");
  const [channelFilter, setChannelFilter] = useState<ChannelFilter>("all");
  const [showSnapshots, setShowSnapshots] = useState<boolean>(false);
  const [expandedCards, setExpandedCards] = useState<Set<string>>(() => new Set());
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    if (versionsData && urlPage > totalPages) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("page", String(totalPages));
      setSearchParams(nextParams, { replace: true });
    }
  }, [versionsData, urlPage, totalPages, searchParams, setSearchParams]);

  const uniqueLoaders = useMemo(() => {
    const seen = new Set<string>();
    const list: string[] = [];
    for (const v of versions) {
      for (const l of v.loaders) {
        const key = l.trim().toLowerCase();
        if (key && !seen.has(key)) {
          seen.add(key);
          list.push(key);
        }
      }
    }
    return list.sort((a, b) =>
      getLoaderDisplay(a).label.localeCompare(getLoaderDisplay(b).label),
    );
  }, [versions]);

  const releaseVersionOptions = useMemo(
    () => sortReleaseVersionsDesc(versions.flatMap((v) => v.game_versions)),
    [versions],
  );

  const hasActiveFilters =
    loaderFilter !== "all" ||
    mcFilter !== "all" ||
    channelFilter !== "all" ||
    showSnapshots;

  const filteredVersions = useMemo(() => {
    const targetMcKey = mcFilter !== "all" ? releaseKey(mcFilter) : null;
    return versions.filter((v) => {
      if (!showSnapshots && isSnapshotOnlyVersion(v)) {
        return false;
      }
      if (
        loaderFilter !== "all" &&
        !v.loaders.some((l) => l.trim().toLowerCase() === loaderFilter)
      ) {
        return false;
      }
      if (channelFilter !== "all" && getVersionChannel(v) !== channelFilter) {
        return false;
      }
      if (
        targetMcKey !== null &&
        !v.game_versions.some((gv) => releaseKey(gv) === targetMcKey)
      ) {
        return false;
      }
      return true;
    });
  }, [versions, showSnapshots, loaderFilter, channelFilter, mcFilter]);

  const recommendedVersion = useMemo(() => {
    if (!targetServer || versions.length === 0) return null;
    if (useServerQuery && versionsData?.selected !== undefined) {
      return versionsData.selected;
    }
    return selectRecommendedVersion(
      targetServer.server_type,
      targetServer.minecraft_version,
      versions,
    );
  }, [targetServer, versions, useServerQuery, versionsData]);

  const resetFilters = () => {
    setLoaderFilter("all");
    setMcFilter("all");
    setChannelFilter("all");
    setShowSnapshots(false);
  };

  const toggleExpanded = (versionId: string) => {
    setExpandedCards((prev) => {
      const next = new Set(prev);
      if (next.has(versionId)) next.delete(versionId);
      else next.add(versionId);
      return next;
    });
  };

  const toggleNotes = (versionId: string) => {
    setExpandedNotes((prev) => {
      const next = new Set(prev);
      if (next.has(versionId)) next.delete(versionId);
      else next.add(versionId);
      return next;
    });
  };

  if (isLoading) {
    return (
      <div className="space-y-3" data-testid="project-versions-loading">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs space-y-2"
          >
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-4 w-24" />
            </div>
            <div className="flex gap-2">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 w-16" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load versions"}
        onRetry={
          typeof versionsQuery.refetch === "function"
            ? () => void versionsQuery.refetch()
            : undefined
        }
      />
    );
  }

  if (totalVersions === 0) {
    return (
      <div
        className="rounded-xl border border-border-subtle bg-surface-card p-8 shadow-2xs text-center"
        data-testid="no-versions-state"
      >
        <p className="text-sm text-text-muted">
          No versions available for this project.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Crisp Filter Bar */}
      <div
        className="rounded-xl border border-border-subtle bg-surface-card p-3 space-y-2.5"
        data-testid="versions-filter-bar"
      >
        <div className="flex flex-wrap items-center gap-2">
          {/* Platform / Loader filter */}
          <div className="relative">
            <label htmlFor="versions-platform-filter" className="sr-only">
              Filter by platform
            </label>
            <select
              id="versions-platform-filter"
              aria-label="Filter by platform"
              data-testid="versions-platform-select"
              value={loaderFilter}
              onChange={(e) => setLoaderFilter(e.target.value)}
              className="h-8 appearance-none rounded-lg border border-border-default bg-surface-elevated pl-2.5 pr-7 text-xs font-medium text-text-primary focus:border-border-focus focus:outline-none cursor-pointer"
            >
              <option value="all">All Platforms</option>
              {uniqueLoaders.map((loader) => (
                <option key={loader} value={loader}>
                  {getLoaderDisplay(loader).label}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-text-muted">
              <Icon name="chevron-down" size={12} />
            </div>
          </div>

          {/* Game Version filter */}
          <div className="relative">
            <label htmlFor="versions-mc-filter" className="sr-only">
              Filter by game version
            </label>
            <select
              id="versions-mc-filter"
              aria-label="Filter by game version"
              data-testid="versions-mc-select"
              value={mcFilter}
              onChange={(e) => setMcFilter(e.target.value)}
              className="h-8 appearance-none rounded-lg border border-border-default bg-surface-elevated pl-2.5 pr-7 text-xs font-medium text-text-primary focus:border-border-focus focus:outline-none cursor-pointer"
            >
              <option value="all">All Versions</option>
              {releaseVersionOptions.map((gv) => (
                <option key={gv} value={gv}>
                  MC {gv}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-text-muted">
              <Icon name="chevron-down" size={12} />
            </div>
          </div>

          {/* Channel segmented pills */}
          <div
            role="group"
            aria-label="Filter by release channel"
            data-testid="versions-channel-filter"
            className="inline-flex items-center rounded-lg border border-border-subtle bg-surface-muted p-0.5"
          >
            {(["all", "release", "beta", "alpha"] as const).map((channel) => {
              const active = channelFilter === channel;
              const label =
                channel === "all" ? "All" : CHANNEL_META[channel].label;
              return (
                <button
                  key={channel}
                  type="button"
                  onClick={() => setChannelFilter(channel)}
                  aria-pressed={active}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer ${
                    active
                      ? "bg-surface-card text-text-primary shadow-2xs font-semibold"
                      : "text-text-muted hover:text-text-primary"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>

          {/* Show snapshots toggle */}
          <button
            type="button"
            role="switch"
            aria-checked={showSnapshots}
            data-testid="versions-snapshots-toggle"
            onClick={() => setShowSnapshots((s) => !s)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer ${
              showSnapshots
                ? "border-accent-primary/40 bg-accent-primary/12 text-accent-primary"
                : "border-border-default bg-surface-elevated text-text-secondary hover:bg-surface-hover"
            }`}
          >
            <span
              aria-hidden="true"
              className={`h-2 w-2 rounded-full ${
                showSnapshots ? "bg-accent-primary" : "bg-text-muted"
              }`}
            />
            Show snapshots
          </button>

          <div className="ml-auto flex items-center gap-3 text-xs">
            <span
              data-testid="versions-result-count"
              className="font-medium text-text-muted tabular-nums"
            >
              {filteredVersions.length} of {versions.length}{" "}
              {versions.length === 1 ? "version" : "versions"}
            </span>
            {hasActiveFilters && (
              <button
                type="button"
                onClick={resetFilters}
                className="font-medium text-accent-primary hover:underline cursor-pointer"
              >
                Reset filters
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Version Rows */}
      {filteredVersions.length === 0 ? (
        <div
          className="rounded-xl border border-border-subtle bg-surface-card p-6 text-center space-y-2"
          data-testid="versions-filtered-empty"
        >
          <p className="text-sm text-text-muted">
            No versions match the selected filters.
          </p>
          <button
            type="button"
            onClick={resetFilters}
            className="inline-flex items-center rounded-lg border border-border-default bg-surface-elevated px-3 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            Reset filters
          </button>
        </div>
      ) : (
        <div
          className="overflow-hidden rounded-xl border border-border-subtle bg-surface-card divide-y divide-border-subtle"
          data-testid="project-versions-list"
        >
          {filteredVersions.map((v) => {
            const isRecommended = recommendedVersion?.version_id === v.version_id;
            const channel = getVersionChannel(v);
            const channelMeta = CHANNEL_META[channel];
            const primary = v.files.find((f) => f.primary) ?? v.files[0];
            const { releasePills, snapshots } = groupReleaseVersions(v.game_versions);
            const primaryList = releasePills.length > 0 ? releasePills : snapshots;
            const isExpanded = expandedCards.has(v.version_id);
            const isNotesOpen = expandedNotes.has(v.version_id);
            const hasNotes = Boolean(v.changelog && v.changelog.trim().length > 0);
            const visiblePrimary = isExpanded ? primaryList : primaryList.slice(0, 4);
            const hiddenReleaseCount = Math.max(0, primaryList.length - 4);
            const hasHiddenSnapshots =
              releasePills.length > 0 && snapshots.length > 0 && !showSnapshots;
            const visibleSnapshots =
              releasePills.length > 0 && (showSnapshots || isExpanded) ? snapshots : [];
            const relativeDate = formatRelativeTime(v.date_published);
            const fullDate = formatDateTime(v.date_published);

            return (
              <div
                key={v.version_id}
                data-testid={`version-card-${v.version_id}`}
                className={`p-3.5 sm:px-4 transition-colors ${
                  isRecommended ? "bg-accent-primary/5" : "hover:bg-surface-hover/40"
                }`}
              >
                <div className="flex flex-col gap-3 md:grid md:grid-cols-[minmax(0,1.1fr)_minmax(0,1.6fr)_auto] md:items-center md:gap-4">
                  {/* Left: Version number + Channel badge + Recommended */}
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-semibold text-text-primary break-words">
                        {v.version_number}
                      </span>
                      <span
                        data-testid={`channel-badge-${v.version_id}`}
                        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${channelMeta.badgeClass}`}
                      >
                        {channelMeta.label}
                      </span>
                      {isRecommended && (
                        <span
                          data-testid="recommended-badge"
                          className="inline-flex items-center gap-1 rounded-full bg-accent-primary/12 px-2 py-0.5 text-[10px] font-semibold text-accent-primary"
                        >
                          <Icon name="check" size={10} />
                          Recommended
                        </span>
                      )}
                    </div>
                    {v.name && v.name !== v.version_number && (
                      <p className="truncate text-xs text-text-muted">{v.name}</p>
                    )}
                  </div>

                  {/* Middle: Platforms, MC version range pills, file & date */}
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {v.loaders.map((loader) => {
                        const display = getLoaderDisplay(loader);
                        return (
                          <span
                            key={loader}
                            className="inline-flex items-center gap-1 rounded-md border border-border-subtle bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-primary"
                          >
                            <Icon name={display.icon} size={11} className="shrink-0 text-text-secondary" />
                            {display.label}
                          </span>
                        );
                      })}

                      {visiblePrimary.map((gv) => (
                        <span
                          key={gv}
                          className="rounded-md bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-secondary"
                        >
                          {gv}
                        </span>
                      ))}

                      {visibleSnapshots.map((snap) => (
                        <span
                          key={snap}
                          className="rounded-md border border-border-subtle bg-surface-muted/70 px-2 py-0.5 text-[11px] font-medium text-text-muted"
                        >
                          {snap}
                        </span>
                      ))}

                      {(hiddenReleaseCount > 0 || hasHiddenSnapshots) && (
                        <button
                          type="button"
                          onClick={() => toggleExpanded(v.version_id)}
                          className="rounded-md border border-border-subtle px-2 py-0.5 text-[11px] font-medium text-text-muted hover:border-border-hover hover:text-text-primary transition-colors cursor-pointer"
                        >
                          {isExpanded
                            ? "Show less"
                            : hiddenReleaseCount > 0 && hasHiddenSnapshots
                              ? `+${hiddenReleaseCount} more · +${snapshots.length} snapshots`
                              : hiddenReleaseCount > 0
                                ? `+${hiddenReleaseCount} more`
                                : `+${snapshots.length} snapshots`}
                        </button>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-muted">
                      {primary && (
                        <span className="inline-flex items-center gap-1 truncate max-w-full">
                          <Icon name="file" size={11} className="shrink-0" />
                          <span className="truncate">
                            {primary.filename || "file"} ({formatBytes(primary.size_bytes)})
                          </span>
                        </span>
                      )}
                      {v.date_published && (
                        <span
                          className="inline-flex items-center gap-1 shrink-0"
                          title={fullDate}
                        >
                          <Icon name="clock" size={11} className="shrink-0" />
                          <span>{relativeDate || fullDate}</span>
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Right: Notes + Install */}
                  {(hasNotes || onInstallVersion) && (
                    <div className="flex items-center justify-end gap-2 shrink-0">
                      {hasNotes && (
                        <button
                          type="button"
                          aria-expanded={isNotesOpen}
                          onClick={() => toggleNotes(v.version_id)}
                          className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-elevated px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                        >
                          <Icon
                            name="chevron-down"
                            size={13}
                            className={`transition-transform ${isNotesOpen ? "rotate-180" : ""}`}
                          />
                          Notes
                        </button>
                      )}
                      {onInstallVersion && (
                        <button
                          type="button"
                          onClick={() => onInstallVersion(v)}
                          aria-label={`Install version ${v.version_number}`}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text transition-colors hover:bg-accent-hover cursor-pointer"
                        >
                          <Icon name="plus" size={13} />
                          Install
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {hasNotes && isNotesOpen && (
                  <div
                    data-testid={`version-notes-${v.version_id}`}
                    className="mt-3 border-t border-border-subtle pt-3"
                  >
                    <MarketplaceMarkdown content={v.changelog!} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {totalVersions > 0 && <Pagination totalItems={totalVersions} />}
    </div>
  );
}
