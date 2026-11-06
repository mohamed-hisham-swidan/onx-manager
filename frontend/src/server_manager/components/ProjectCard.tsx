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
}

const MAX_VISIBLE_PILLS = 4;

export function ProjectCard({ project, searchParams, onInstall }: ProjectCardProps) {
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
          className="inline-flex items-center gap-1 rounded-md border border-accent-primary/20 bg-accent-primary/10 px-2 py-0.5 text-xs font-medium text-accent-primary"
        >
          <Icon name={display.icon} size={11} className="shrink-0" />
          {display.label}
        </span>
      );
    }),
    ...categories.map((category) => (
      <span
        key={category}
        className="rounded-md border border-border-subtle bg-surface-elevated px-2 py-0.5 text-xs font-medium text-text-secondary"
      >
        {category}
      </span>
    )),
    ...envs.map((env) => (
      <span
        key={env}
        className="inline-flex items-center gap-1 rounded-md border border-status-success-border bg-status-success-bg px-2 py-0.5 text-xs font-medium text-status-success"
      >
        <Icon name="globe" size={11} className="shrink-0" />
        {env}
      </span>
    )),
  ];
  const visiblePills = pillElements.slice(0, MAX_VISIBLE_PILLS);
  const hiddenPillCount = pillElements.length - visiblePills.length;

  return (
    <li
      data-testid={`project-card-${project.project_id}`}
      onClick={() => navigate(detailPath)}
      className="group relative flex flex-col justify-between gap-3 rounded-xl border border-border-subtle bg-surface-card p-4.5 shadow-2xs transition-all duration-150 hover:-translate-y-0.5 hover:border-border-default hover:bg-surface-hover/30 hover:shadow-md cursor-pointer"
    >
      <div className="flex items-start justify-between gap-3.5">
        <Link
          to={detailPath}
          onClick={(e) => e.stopPropagation()}
          className="group/link flex min-w-0 flex-1 items-start gap-3"
        >
          {project.icon_url ? (
            <img
              src={project.icon_url}
              alt=""
              className="h-12 w-12 shrink-0 rounded-xl object-cover border border-border-subtle shadow-2xs"
            />
          ) : (
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-surface-elevated text-accent-primary shadow-2xs">
              <Icon name="plugin" size={24} />
            </div>
          )}
          <div className="min-w-0">
            <h3 className="truncate font-bold text-base text-text-primary group-hover/link:text-accent-primary">
              {project.title}
            </h3>
            <p className="mt-0.5 text-xs text-text-muted">
              by {project.author}
            </p>
            {project.description && (
              <p className="mt-1 line-clamp-2 text-xs text-text-secondary leading-relaxed">
                {project.description}
              </p>
            )}
          </div>
        </Link>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onInstall(project);
          }}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-bold text-accent-contrast-text transition-colors hover:bg-accent-hover shadow-2xs cursor-pointer"
        >
          <Icon name="plus" size={14} />
          Install
        </button>
      </div>

      {/* Tags & Loaders */}
      <div className="flex flex-wrap items-center gap-1.5 pt-1">
        {visiblePills}
        {hiddenPillCount > 0 && (
          <Link
            to={detailPath}
            onClick={(e) => e.stopPropagation()}
            aria-label={`${hiddenPillCount} more tags`}
            className="rounded-md border border-border-subtle bg-surface-elevated px-2 py-0.5 text-xs font-medium text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
          >
            +{hiddenPillCount}
          </Link>
        )}
      </div>

      {/* Metrics Footer */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-subtle/60 pt-3 text-xs text-text-muted font-mono tabular-nums">
        <span className="inline-flex items-center gap-1">
          <Icon name="download" size={12} className="text-text-muted" />
          {formatDownloads(project.downloads)}
        </span>
        <span className="inline-flex items-center gap-1">
          <Icon name="heart" size={12} className="text-status-danger" />
          {formatDownloads(project.follows)}
        </span>
        {updatedLabel && (
          <span className="inline-flex items-center gap-1 ml-auto font-sans text-[11px]">
            <Icon name="clock" size={12} />
            Updated {updatedLabel}
          </span>
        )}
      </div>
    </li>
  );
}
