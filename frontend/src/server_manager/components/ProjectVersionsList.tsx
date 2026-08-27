import { useEffect, useMemo } from "react";
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
import { getLoaderDisplay } from "@/server_manager/utils/compatibility";
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

  if (isLoading) {
    return (
      <div className="space-y-3" data-testid="project-versions-loading">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800 space-y-2"
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
        className="rounded-xl border border-gray-200 bg-white p-8 text-center dark:border-gray-700 dark:bg-gray-800"
        data-testid="no-versions-state"
      >
        <p className="text-sm text-gray-500 dark:text-gray-400">
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

          return (
            <div
              key={v.version_id}
              data-testid={`version-card-${v.version_id}`}
              className={`rounded-xl border p-4 transition-colors ${
                isRecommended
                  ? "border-blue-500 bg-blue-50/50 dark:border-blue-500 dark:bg-blue-900/20"
                  : "border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-base font-bold text-gray-900 dark:text-gray-100">
                      {v.version_number}
                    </span>
                    {v.name && v.name !== v.version_number && (
                      <span className="truncate text-xs text-gray-500 dark:text-gray-400">
                        ({v.name})
                      </span>
                    )}
                    {isRecommended && (
                      <span
                        data-testid="recommended-badge"
                        className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
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
                          className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                        >
                          <Icon name={display.icon} size={11} className="shrink-0" />
                          {display.label}
                        </span>
                      );
                    })}

                    {/* Game versions (raw) */}
                    {v.game_versions.map((gv) => (
                      <span
                        key={gv}
                        className="rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-700/60 dark:text-gray-300"
                      >
                        {gv}
                      </span>
                    ))}
                  </div>

                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
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
