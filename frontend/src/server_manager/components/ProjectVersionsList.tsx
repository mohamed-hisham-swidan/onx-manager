import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  MARKETPLACE_PAGE_SIZE,
  useMarketplaceProjectVersions,
} from "@/server_manager/hooks/usePlugins";
import { Pagination } from "@/components/ui/Pagination";
import { useServersList } from "@/server_manager/hooks/useServers";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import { formatBytes, formatDateTime } from "@/server_manager/utils/format";
import { selectRecommendedVersion } from "@/server_manager/utils/versionMatching";
import {
  getLoaderDisplay,
  groupReleaseVersions,
} from "@/server_manager/utils/compatibility";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/ui/Icon";

export interface ProjectVersionsListProps {
  projectId: string;
}

export function ProjectVersionsList({ projectId }: ProjectVersionsListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const offset = (urlPage - 1) * MARKETPLACE_PAGE_SIZE;
  const { data: versionsData, isLoading, error } = useMarketplaceProjectVersions(projectId, { offset });
  const { data: servers } = useServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);

  // G1: key on server_id, NOT id
  const lastUsedServer = servers?.find((s) => s.server_id === lastUsedServerId);

  const versions = useMemo(() => versionsData?.versions ?? [], [versionsData?.versions]);
  const totalVersions = versionsData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalVersions / MARKETPLACE_PAGE_SIZE));

  useEffect(() => {
    if (versionsData && urlPage > totalPages) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("page", String(totalPages));
      setSearchParams(nextParams, { replace: true });
    }
  }, [versionsData, urlPage, totalPages, searchParams, setSearchParams]);

  const recommendedVersion = useMemo(() => {
    if (!lastUsedServer || versions.length === 0) return null;
    return selectRecommendedVersion(
      lastUsedServer.server_type,
      lastUsedServer.minecraft_version,
      versions,
    );
  }, [lastUsedServer, versions]);

  const [expandedCards, setExpandedCards] = useState<Set<string>>(() => new Set());
  const toggleExpanded = (versionId: string) => {
    setExpandedCards((prev) => {
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
    <>
      <div className="space-y-3" data-testid="project-versions-list">
        {versions.map((v) => {
          const isRecommended = recommendedVersion?.version_id === v.version_id;
          const primary = v.files.find((f) => f.primary) ?? v.files[0];
          const { releasePills, snapshots } = groupReleaseVersions(v.game_versions);
          const primaryList = releasePills.length > 0 ? releasePills : snapshots;
          const isExpanded = expandedCards.has(v.version_id);
          const visiblePrimary = isExpanded ? primaryList : primaryList.slice(0, 5);
          const hiddenReleaseCount = Math.max(0, primaryList.length - 5);
          const hasHiddenSnapshots = releasePills.length > 0 && snapshots.length > 0;

          return (
            <div
              key={v.version_id}
              data-testid={`version-card-${v.version_id}`}
              className={`rounded-xl border p-4 transition-colors ${
                isRecommended
                  ? "border-accent-primary bg-accent-primary/10 shadow-xs"
                  : "border-border-subtle bg-surface-card shadow-2xs"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-bold text-text-primary">
                      {v.version_number}
                    </span>
                    {v.name && v.name !== v.version_number && (
                      <span className="truncate text-xs text-text-muted">
                        ({v.name})
                      </span>
                    )}
                    {isRecommended && (
                      <span
                        data-testid="recommended-badge"
                        className="inline-flex items-center gap-1 rounded-full bg-accent-primary/10 px-2.5 py-0.5 text-xs font-semibold text-accent-primary"
                      >
                        <Icon name="check" size={12} />
                        Recommended
                      </span>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    {/* Loaders */}
                    {v.loaders.map((loader) => {
                      const display = getLoaderDisplay(loader);
                      return (
                        <span
                          key={loader}
                          className="inline-flex items-center gap-1 rounded-md bg-accent-primary/10 px-2 py-0.5 text-xs font-medium text-accent-primary"
                        >
                          <Icon name={display.icon} size={11} className="shrink-0" />
                          {display.label}
                        </span>
                      );
                    })}

                    {/* Grouped game versions (releases first; snapshots expandable) */}
                    {visiblePrimary.map((gv) => (
                      <span
                        key={gv}
                        className="rounded-md bg-surface-muted px-2 py-0.5 text-xs font-medium text-text-secondary"
                      >
                        {gv}
                      </span>
                    ))}
                    {isExpanded &&
                      hasHiddenSnapshots &&
                      snapshots.map((snap) => (
                        <span
                          key={snap}
                          className="rounded-md border border-border-subtle bg-surface-muted/70 px-2 py-0.5 text-xs font-medium text-text-muted"
                        >
                          {snap}
                        </span>
                      ))}
                    {(hiddenReleaseCount > 0 || hasHiddenSnapshots) && (
                      <button
                        type="button"
                        onClick={() => toggleExpanded(v.version_id)}
                        className="rounded-md border border-border-subtle px-2 py-0.5 text-xs font-medium text-text-muted hover:border-border-hover hover:text-text-primary transition-colors cursor-pointer"
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

                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
                    {primary && (
                      <span className="inline-flex items-center gap-1">
                        <Icon name="file" size={12} />
                        {primary.filename || "file"} ({formatBytes(primary.size_bytes)})
                      </span>
                    )}
                    {v.date_published && (
                      <span className="inline-flex items-center gap-1">
                        <Icon name="clock" size={12} />
                        {formatDateTime(v.date_published)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {totalVersions > 0 && <Pagination totalItems={totalVersions} />}
    </>
  );
}
