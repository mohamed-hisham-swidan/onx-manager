import { Link } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import {
  environmentLabels,
  getLoaderDisplay,
} from "@/server_manager/components/CompatibilityCard";
import { formatDownloads, formatRelativeTime } from "@/server_manager/utils/format";
import type { PluginSearchResultResponse } from "@/types";

export interface ProjectCardProps {
  project: PluginSearchResultResponse;
  searchParams: URLSearchParams;
  onInstall: (project: PluginSearchResultResponse) => void;
}

export function ProjectCard({ project, searchParams, onInstall }: ProjectCardProps) {
  const detailQuery = searchParams.toString();
  const loaders = project.loaders ?? [];
  const categories = project.categories ?? [];
  const envs = environmentLabels(project.client_side, project.server_side);
  const updatedLabel = formatRelativeTime(project.date_modified);

  return (
    <li
      data-testid={`project-card-${project.project_id}`}
      className="flex flex-col gap-3 rounded-xl border border-gray-200 bg-white p-4 transition-colors hover:border-gray-300 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-gray-600"
    >
      <div className="flex items-start justify-between gap-4">
        <Link
          to={`/marketplace/${project.project_id}${detailQuery ? `?${detailQuery}` : ""}`}
          className="group flex min-w-0 flex-1 items-start gap-3"
        >
          {project.icon_url ? (
            <img
              src={project.icon_url}
              alt=""
              className="h-11 w-11 shrink-0 rounded-lg object-cover"
            />
          ) : (
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500">
              <Icon name="plugin" size={22} />
            </div>
          )}
          <div className="min-w-0">
            <h3 className="truncate font-semibold text-gray-900 group-hover:text-blue-600 group-hover:underline dark:text-gray-100 dark:group-hover:text-blue-400">
              {project.title}
            </h3>
            <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
              by {project.author}
            </p>
            {project.description && (
              <p className="mt-1 line-clamp-2 text-xs text-gray-500 dark:text-gray-400">
                {project.description}
              </p>
            )}
          </div>
        </Link>
        <button
          type="button"
          onClick={() => onInstall(project)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-700"
        >
          <Icon name="plus" size={14} />
          Install
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {loaders.map((loader) => {
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
        {categories.map((category) => (
          <span
            key={category}
            className="rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700 dark:bg-gray-700/60 dark:text-gray-300"
          >
            {category}
          </span>
        ))}
        {envs.map((env) => (
          <span
            key={env}
            className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
          >
            <Icon name="globe" size={11} className="shrink-0" />
            {env}
          </span>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-gray-100 pt-3 text-xs text-gray-500 dark:border-gray-700/50 dark:text-gray-400">
        <span className="inline-flex items-center gap-1">
          <Icon name="download" size={12} />
          {formatDownloads(project.downloads)}
        </span>
        <span className="inline-flex items-center gap-1">
          <Icon name="heart" size={12} />
          {formatDownloads(project.follows)}
        </span>
        {updatedLabel && (
          <span className="inline-flex items-center gap-1">
            <Icon name="clock" size={12} />
            Updated {updatedLabel}
          </span>
        )}
      </div>
    </li>
  );
}