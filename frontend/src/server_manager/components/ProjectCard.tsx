import { Link, useNavigate } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import {
  environmentLabels,
  getLoaderDisplay,
} from "@/server_manager/utils/compatibility";
import { formatDownloads, formatRelativeTime } from "@/server_manager/utils/format";
import type { PluginSearchResultResponse } from "@/types";

export interface ProjectCardProps {
  project: PluginSearchResultResponse;
  searchParams: URLSearchParams;
  onInstall: (project: PluginSearchResultResponse) => void;
  viewMode?: "grid" | "list";
}

const MAX_VISIBLE_PILLS = 4;

export function ProjectCard({
  project,
  searchParams,
  onInstall,
  viewMode = "grid",
}: ProjectCardProps) {
  const navigate = useNavigate();
  const detailQuery = searchParams.toString();
  const loaders = project.loaders ?? [];
  const categories = project.categories ?? [];
  const envs = environmentLabels(project.client_side, project.server_side);
  const updatedLabel = formatRelativeTime(project.date_modified);
  const detailPath = `/marketplace/${project.project_id}${detailQuery ? `?${detailQuery}` : ""}`;

  const pillElements = [
    ...loaders.map((loader) => {
      const display = getLoaderDisplay(loader);
      return (
        <span
          key={loader}
          className="inline-flex shrink-0 items-center gap-1 rounded-[4px] bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-muted"
        >
          <Icon name={display.icon} size={11} className="shrink-0 text-text-muted" />
          <span>{display.label}</span>
        </span>
      );
    }),
    ...categories.map((category) => (
      <span
        key={category}
        className="shrink-0 rounded-[4px] bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-muted"
      >
        {category}
      </span>
    )),
    ...envs.map((env) => (
      <span
        key={env}
        className="inline-flex shrink-0 items-center gap-1 rounded-[4px] bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-muted"
      >
        <Icon name="globe" size={11} className="shrink-0 text-text-muted" />
        <span>{env}</span>
      </span>
    )),
  ];
  const visiblePills = pillElements.slice(0, MAX_VISIBLE_PILLS);
  const hiddenPillCount = pillElements.length - visiblePills.length;

  if (viewMode === "list") {
    return (
      <li
        data-testid={`project-card-${project.project_id}`}
        onClick={() => navigate(detailPath)}
        className="group relative flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-border-subtle bg-surface-card p-4 transition-colors duration-150 hover:border-border-default cursor-pointer"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-3">
            <Link
              to={detailPath}
              onClick={(e) => e.stopPropagation()}
              className="group/link flex min-w-0 flex-1 items-start gap-3"
            >
              {project.icon_url ? (
                <img
                  src={project.icon_url}
                  alt=""
                  className="h-11 w-11 shrink-0 rounded-lg bg-surface-muted object-cover"
                />
              ) : (
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-text-muted">
                  <Icon name="plugin" size={22} />
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-2">
                  <h3 className="truncate font-semibold text-[15px] text-text-primary group-hover/link:text-accent-primary transition-colors">
                    {project.title}
                  </h3>
                  <p className="text-xs text-text-muted">by {project.author}</p>
                </div>
                {project.description && (
                  <p className="mt-1 line-clamp-1 text-xs text-text-muted leading-relaxed">
                    {project.description}
                  </p>
                )}
              </div>
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 pt-2 ps-0 sm:ps-14">
            {visiblePills}
            {hiddenPillCount > 0 && (
              <Link
                to={detailPath}
                onClick={(e) => e.stopPropagation()}
                aria-label={`${hiddenPillCount} more tags`}
                className="shrink-0 rounded-[4px] bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
              >
                +{hiddenPillCount}
              </Link>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between sm:flex-col sm:items-end gap-3 shrink-0 pt-2 sm:pt-0 border-t sm:border-t-0 border-border-subtle">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onInstall(project);
            }}
            className="inline-flex shrink-0 items-center gap-1.5 h-[30px] px-3 text-[12.5px] font-medium rounded-md border border-accent-primary/30 bg-accent-primary/12 text-accent-primary transition-colors hover:bg-accent-primary hover:text-accent-contrast-text cursor-pointer"
          >
            <Icon name="plus" size={13} />
            <span>Install</span>
          </button>

          <div className="flex items-center gap-3.5 text-xs text-text-muted font-mono tabular-nums">
            <span className="inline-flex items-center gap-1" title={`${project.downloads.toLocaleString()} downloads`}>
              <Icon name="download" size={12} className="text-text-muted shrink-0" />
              <span>{formatDownloads(project.downloads)}</span>
            </span>
            <span className="inline-flex items-center gap-1" title={`${project.follows.toLocaleString()} likes`}>
              <Icon name="heart" size={12} className="text-status-danger shrink-0" />
              <span>{formatDownloads(project.follows)}</span>
            </span>
            {updatedLabel && (
              <span className="inline-flex items-center gap-1 font-sans text-[11px]">
                <Icon name="clock" size={12} className="shrink-0" />
                <span>Updated {updatedLabel}</span>
              </span>
            )}
          </div>
        </div>
      </li>
    );
  }

  return (
    <li
      data-testid={`project-card-${project.project_id}`}
      onClick={() => navigate(detailPath)}
      className="group relative flex h-full flex-col justify-between rounded-lg border border-border-subtle bg-surface-card p-4 transition-colors duration-150 hover:border-border-default cursor-pointer"
    >
      {/* Top Zone: Header */}
      <div>
        <div className="flex items-center gap-3">
          <Link
            to={detailPath}
            onClick={(e) => e.stopPropagation()}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-surface-muted overflow-hidden"
          >
            {project.icon_url ? (
              <img
                src={project.icon_url}
                alt=""
                className="h-11 w-11 shrink-0 rounded-lg bg-surface-muted object-cover"
              />
            ) : (
              <div className="flex h-11 w-11 shrink-0 items-center justify-center text-text-muted">
                <Icon name="plugin" size={22} />
              </div>
            )}
          </Link>
          <div className="min-w-0 flex-1">
            <Link
              to={detailPath}
              onClick={(e) => e.stopPropagation()}
              className="group/link block min-w-0"
            >
              <h3 className="truncate font-semibold text-[15px] text-text-primary group-hover/link:text-accent-primary transition-colors">
                {project.title}
              </h3>
              <p className="truncate text-xs text-text-muted mt-0.5">
                by {project.author}
              </p>
            </Link>
          </div>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onInstall(project);
            }}
            className="ml-auto inline-flex shrink-0 items-center gap-1.5 h-[30px] px-3 text-[12.5px] font-medium rounded-md border border-accent-primary/30 bg-accent-primary/12 text-accent-primary transition-colors hover:bg-accent-primary hover:text-accent-contrast-text cursor-pointer"
          >
            <Icon name="plus" size={13} />
            <span>Install</span>
          </button>
        </div>

        {/* Middle Zone: Description + Tags */}
        <p className="mt-3 text-[13px] text-text-muted leading-[1.45] line-clamp-2 min-h-[38px]">
          {project.description}
        </p>

        <div className="mt-3 flex flex-nowrap overflow-hidden gap-1.5">
          {visiblePills}
          {hiddenPillCount > 0 && (
            <Link
              to={detailPath}
              onClick={(e) => e.stopPropagation()}
              aria-label={`${hiddenPillCount} more tags`}
              className="shrink-0 rounded-[4px] bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
            >
              +{hiddenPillCount}
            </Link>
          )}
        </div>
      </div>

      {/* Bottom Zone: Metrics Footer */}
      <div className="mt-3.5 flex items-center justify-between border-t border-border-subtle pt-3 text-xs text-text-muted font-mono tabular-nums">
        <div className="flex items-center gap-3.5">
          <span className="inline-flex items-center gap-1" title={`${project.downloads.toLocaleString()} downloads`}>
            <Icon name="download" size={12} className="text-text-muted shrink-0" />
            <span>{formatDownloads(project.downloads)}</span>
          </span>
          <span className="inline-flex items-center gap-1" title={`${project.follows.toLocaleString()} likes`}>
            <Icon name="heart" size={12} className="text-status-danger shrink-0" />
            <span>{formatDownloads(project.follows)}</span>
          </span>
        </div>
        {updatedLabel && (
          <span className="inline-flex items-center gap-1 font-sans text-[11px] text-text-muted shrink-0">
            <Icon name="clock" size={12} className="shrink-0" />
            <span>Updated {updatedLabel}</span>
          </span>
        )}
      </div>
    </li>
  );
}
