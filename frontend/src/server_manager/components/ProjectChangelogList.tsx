import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  MARKETPLACE_PAGE_SIZE,
  useProjectVersionsGlobal,
} from "@/server_manager/hooks/usePlugins";
import { Pagination } from "@/components/ui/Pagination";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { Icon } from "@/components/ui/Icon";
import { MarketplaceMarkdown } from "@/server_manager/components/MarketplaceMarkdown";
import {
  getLoaderDisplay,
  groupReleaseVersions,
} from "@/server_manager/utils/compatibility";
import { formatDateTime, formatRelativeTime } from "@/server_manager/utils/format";
import type { PluginVersionResponse } from "@/types";

export interface ProjectChangelogListProps {
  projectId: string;
  onInstallVersion?: (version: PluginVersionResponse) => void;
}

export function ProjectChangelogList({
  projectId,
  onInstallVersion,
}: ProjectChangelogListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlPage = Math.max(1, Number(searchParams.get("page")) || 1);
  const offset = (urlPage - 1) * MARKETPLACE_PAGE_SIZE;

  const versionsQuery = useProjectVersionsGlobal(projectId, { offset });
  const { data: versionsData, isLoading, error } = versionsQuery;

  const versions = useMemo(() => versionsData?.versions ?? [], [versionsData?.versions]);
  const totalVersions = versionsData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalVersions / MARKETPLACE_PAGE_SIZE));

  const [showEmptyNotes, setShowEmptyNotes] = useState(false);

  useEffect(() => {
    if (versionsData && urlPage > totalPages) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("page", String(totalPages));
      setSearchParams(nextParams, { replace: true });
    }
  }, [versionsData, urlPage, totalPages, searchParams, setSearchParams]);

  const versionsWithNotes = useMemo(
    () => versions.filter((v) => Boolean(v.changelog && v.changelog.trim().length > 0)),
    [versions],
  );
  const hasAnyWithoutNotes = versions.length > versionsWithNotes.length;
  const displayedVersions =
    showEmptyNotes || versionsWithNotes.length === 0 ? versions : versionsWithNotes;

  if (isLoading) {
    return (
      <div className="space-y-4" data-testid="project-changelog-loading">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="rounded-xl border border-border-subtle bg-surface-card p-5 space-y-3"
          >
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-4 w-24" />
            </div>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load changelog"}
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
        className="rounded-xl border border-border-subtle bg-surface-card p-8 text-center"
        data-testid="no-changelog-state"
      >
        <p className="text-sm text-text-muted">
          No release history available for this project.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {hasAnyWithoutNotes && versionsWithNotes.length > 0 && (
        <div className="flex items-center justify-between rounded-lg border border-border-subtle bg-surface-card px-3.5 py-2 text-xs">
          <span className="text-text-muted">
            Showing {versionsWithNotes.length} of {versions.length} releases with notes
          </span>
          <label className="inline-flex items-center gap-2 font-medium text-text-secondary cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showEmptyNotes}
              onChange={(e) => setShowEmptyNotes(e.target.checked)}
              className="onx-checkbox"
            />
            Show versions without notes
          </label>
        </div>
      )}

      <div
        className="relative space-y-4 before:absolute before:left-4 before:top-4 before:bottom-4 before:w-px before:bg-border-subtle"
        data-testid="project-changelog-list"
      >
        {displayedVersions.map((v) => {
          const { releasePills, snapshots } = groupReleaseVersions(v.game_versions);
          const mcPills = (releasePills.length > 0 ? releasePills : snapshots).slice(0, 3);
          const extraMcCount = Math.max(
            0,
            (releasePills.length > 0 ? releasePills : snapshots).length - 3,
          );
          const relativeDate = formatRelativeTime(v.date_published);
          const fullDate = formatDateTime(v.date_published);
          const hasNotes = Boolean(v.changelog && v.changelog.trim().length > 0);

          return (
            <article
              key={v.version_id}
              data-testid={`changelog-entry-${v.version_id}`}
              className="relative pl-10"
            >
              <span
                aria-hidden="true"
                className="absolute left-[11px] top-5 h-2.5 w-2.5 rounded-full border-2 border-accent-primary bg-surface-card"
              />
              <div className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center rounded-md border border-accent-primary/30 bg-accent-primary/10 px-2 py-0.5 font-mono text-xs font-semibold text-accent-primary">
                        {v.version_number}
                      </span>
                      {v.name && v.name !== v.version_number && (
                        <h4 className="text-sm font-semibold text-text-primary truncate">
                          {v.name}
                        </h4>
                      )}
                      {v.date_published && (
                        <span
                          title={fullDate}
                          className="inline-flex items-center gap-1 text-xs text-text-muted"
                        >
                          <Icon name="clock" size={12} />
                          {relativeDate || fullDate}
                        </span>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5">
                      {v.loaders.map((loader) => {
                        const display = getLoaderDisplay(loader);
                        return (
                          <span
                            key={loader}
                            className="inline-flex items-center gap-1 rounded bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-secondary"
                          >
                            <Icon name={display.icon} size={11} />
                            {display.label}
                          </span>
                        );
                      })}
                      {mcPills.map((gv) => (
                        <span
                          key={gv}
                          className="rounded bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-muted"
                        >
                          MC {gv}
                        </span>
                      ))}
                      {extraMcCount > 0 && (
                        <span className="text-[11px] text-text-muted">
                          +{extraMcCount} more
                        </span>
                      )}
                    </div>
                  </div>

                  {onInstallVersion && (
                    <button
                      type="button"
                      onClick={() => onInstallVersion(v)}
                      aria-label={`Install version ${v.version_number}`}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-accent-primary/30 bg-accent-primary/10 px-3 py-1.5 text-xs font-semibold text-accent-primary transition-colors hover:bg-accent-primary hover:text-accent-contrast-text cursor-pointer"
                    >
                      <Icon name="plus" size={13} />
                      Install
                    </button>
                  )}
                </div>

                <div className="border-t border-border-subtle pt-3">
                  {hasNotes ? (
                    <MarketplaceMarkdown content={v.changelog!} />
                  ) : (
                    <p className="text-xs italic text-text-muted">
                      No release notes provided for this version.
                    </p>
                  )}
                </div>
              </div>
            </article>
          );
        })}
      </div>

      {totalVersions > 0 && <Pagination totalItems={totalVersions} />}
    </div>
  );
}
