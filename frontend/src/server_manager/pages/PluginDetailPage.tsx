import { useState } from "react";
import { useParams, useNavigate, useLocation, Link } from "react-router-dom";
import { useMarketplaceProject } from "@/server_manager/hooks/usePlugins";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ErrorState";
import { ComingSoonState } from "@/components/ComingSoonState";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";
import { CompatibilityCard } from "@/server_manager/components/CompatibilityCard";
import { ProjectVersionsList } from "@/server_manager/components/ProjectVersionsList";
import type { PluginSearchResultResponse } from "@/types";

type DetailTab = "description" | "changelog" | "versions";

function fmtDownloads(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="shrink-0 text-sm text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="text-right text-sm font-medium text-gray-900 dark:text-gray-100">{children}</dd>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="p-5 sm:p-6">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
        {title}
      </h3>
      <dl className="divide-y divide-gray-100 dark:divide-gray-700/50">{children}</dl>
    </section>
  );
}

interface DetailTabsProps {
  activeTab: DetailTab;
  onTabChange: (tab: DetailTab) => void;
}

function DetailTabs({ activeTab, onTabChange }: DetailTabsProps) {
  return (
    <div className="flex border-b border-gray-200 dark:border-gray-700" data-testid="detail-tabs">
      <button
        type="button"
        onClick={() => onTabChange("description")}
        className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
          activeTab === "description"
            ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400"
            : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        }`}
      >
        Description
      </button>
      <button
        type="button"
        disabled
        aria-disabled="true"
        title="Coming soon"
        className="px-4 py-2.5 text-sm font-medium border-b-2 -mb-px border-transparent text-gray-300 dark:text-gray-600 cursor-not-allowed inline-flex items-center gap-1.5"
      >
        Changelog
        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-400 dark:bg-gray-800 dark:text-gray-500">
          Soon
        </span>
      </button>
      <button
        type="button"
        onClick={() => onTabChange("versions")}
        className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
          activeTab === "versions"
            ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-400"
            : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        }`}
      >
        Versions
      </button>
    </div>
  );
}

export function PluginDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  const [activeTab, setActiveTab] = useState<DetailTab>("description");

  const source = useMarketplaceSourceStore((s) => s.source);
  const setSource = useMarketplaceSourceStore((s) => s.setSource);
  const isModrinth = source === "modrinth";

  const { data: project, isLoading, error } = useMarketplaceProject(projectId ?? "", {
    enabled: isModrinth,
  });

  const backUrl = `/marketplace${location.search}`;

  function handleInstall() {
    if (!project) return;
    const searchResult: PluginSearchResultResponse = {
      project_id: project.project_id,
      slug: project.slug,
      title: project.title,
      description: project.description,
      author: project.author,
      project_types: project.project_types,
      downloads: project.downloads,
      follows: project.follows,
      icon_url: project.icon_url,
      latest_version_id: "",
      categories: [],
      loaders: project.loaders,
      client_side: project.client_side ?? null,
      server_side: project.server_side ?? null,
      date_modified: "",
      color: null,
    };
    navigate(backUrl, { state: { selectedProject: searchResult } });
  }

  if (source === "curseforge") {
    return (
      <div>
        <Link
          to={backUrl}
          className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-gray-600 transition-colors hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
        >
          <Icon name="chevron-left" size={16} />
          Back to Marketplace
        </Link>
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
      </div>
    );
  }

  if (!projectId) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400">
        No project ID specified.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-96" />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-4">
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800 space-y-3">
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800 space-y-3">
            <Skeleton className="h-4 w-24 mb-2" />
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-6 w-32" />
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <Link
          to={backUrl}
          className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-gray-600 transition-colors hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
        >
          <Icon name="chevron-left" size={16} />
          Back to Marketplace
        </Link>
        <ErrorState message={error instanceof Error ? error.message : "Failed to load project details"} />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-6 text-center dark:border-gray-700 dark:bg-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Project not found</h2>
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
          This project does not exist or could not be loaded from Modrinth.
        </p>
        <Link
          to={backUrl}
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          <Icon name="chevron-left" size={16} />
          Back to Marketplace
        </Link>
      </div>
    );
  }

  const primaryType = project.project_types[0] || "plugin";
  const modrinthUrl = `https://modrinth.com/${primaryType}/${project.slug || project.project_id}`;

  return (
    <div>
      <Link
        to={backUrl}
        className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 transition-colors hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
      >
        <Icon name="chevron-left" size={16} />
        Back to Marketplace
      </Link>

      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          {project.icon_url ? (
            <img
              src={project.icon_url}
              alt=""
              className="h-14 w-14 shrink-0 rounded-xl object-cover border border-gray-200 dark:border-gray-700"
            />
          ) : (
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
              <Icon name="plugin" size={28} />
            </div>
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-2xl font-bold text-gray-900 dark:text-gray-100">
                {project.title}
              </h2>
              {project.project_types.map((type) => (
                <span
                  key={type}
                  className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold capitalize text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
                >
                  {type}
                </span>
              ))}
            </div>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
              By <span className="font-medium text-gray-700 dark:text-gray-300">{project.author}</span>
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {project.wiki_url && (
            <a
              href={project.wiki_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              Wiki
            </a>
          )}
          {project.source_url && (
            <a
              href={project.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              Source Code
            </a>
          )}
          <a
            href={modrinthUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            <Icon name="modrinth" size={14} />
            Modrinth
          </a>
          <button
            type="button"
            onClick={handleInstall}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <Icon name="plus" size={16} />
            Install
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <DetailTabs activeTab={activeTab} onTabChange={setActiveTab} />

          {activeTab === "description" && (
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800" data-testid="about-section">
              <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">About</h3>
              {project.description && (
                <p className="mb-4 text-sm font-medium text-gray-700 dark:text-gray-300">
                  {project.description}
                </p>
              )}
              {project.body ? (
                <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-sm text-gray-600 dark:text-gray-300 leading-relaxed border-t border-gray-100 pt-4 dark:border-gray-700/50">
                  {project.body}
                </div>
              ) : (
                <p className="text-sm text-gray-500 dark:text-gray-400 italic">
                  No additional description provided.
                </p>
              )}
            </div>
          )}

          {activeTab === "versions" && (
            <ProjectVersionsList projectId={project.project_id} />
          )}
        </div>

        <div className="space-y-6">
          <CompatibilityCard
            gameVersions={project.game_versions}
            loaders={project.loaders}
            clientSide={project.client_side}
            serverSide={project.server_side}
          />

          <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
            <DetailSection title="Information">
              <DetailRow label="Author">{project.author}</DetailRow>
              <DetailRow label="Downloads">{fmtDownloads(project.downloads)}</DetailRow>
              <DetailRow label="Follows">{project.follows}</DetailRow>
              <DetailRow label="Types">
                <span className="capitalize">{project.project_types.join(", ") || "—"}</span>
              </DetailRow>
              <DetailRow label="Loaders">
                <span>{project.loaders.length > 0 ? project.loaders.join(", ") : "—"}</span>
              </DetailRow>
              <DetailRow label="Game Versions">
                <span className="block max-w-xs text-right truncate" title={project.game_versions.join(", ")}>
                  {project.game_versions.length > 0 ? project.game_versions.join(", ") : "—"}
                </span>
              </DetailRow>
            </DetailSection>
          </div>
        </div>
      </div>
    </div>
  );
}
