import { useMemo, useState } from "react";
import { useParams, useLocation, Link } from "react-router-dom";
import * as pluginHooks from "@/server_manager/hooks/usePlugins";
import { useMarketplaceProject } from "@/server_manager/hooks/usePlugins";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { ApiError } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { Skeleton, ErrorState } from "@/components/ui/States";
import { CompatibilityCard } from "@/server_manager/components/CompatibilityCard";
import { ProjectVersionsList } from "@/server_manager/components/ProjectVersionsList";
import { ProjectChangelogList } from "@/server_manager/components/ProjectChangelogList";
import { MarketplaceMarkdown } from "@/server_manager/components/MarketplaceMarkdown";
import { InstallModal } from "@/server_manager/components/InstallModal";
import {
  inferProjectTypes,
  platformProjectType,
} from "@/server_manager/data/platforms";
import { findInstalledAddon } from "@/server_manager/utils/installedAddons";
import { formatDownloads } from "@/server_manager/utils/format";
import type {
  PluginResponse,
  PluginSearchResultResponse,
  PluginVersionResponse,
} from "@/types";

type DetailTab = "description" | "changelog" | "versions";

export interface PluginDetailPageProps {
  lockedProjectType?: "plugin" | "mod";
}

function useSafePluginsList(serverId: string, branch?: string): PluginResponse[] | undefined {
  const fn = (pluginHooks as Record<string, unknown>).usePluginsList;
  const hook =
    typeof fn === "function"
      ? (fn as (sid: string, br?: string) => { data?: PluginResponse[] })
      : () => ({ data: undefined });
  return hook(serverId, branch)?.data;
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="shrink-0 text-sm text-text-muted">{label}</dt>
      <dd className="text-right text-sm font-medium text-text-primary">{children}</dd>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="p-5 sm:p-6">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-muted">
        {title}
      </h3>
      <dl className="divide-y divide-border-subtle">{children}</dl>
    </section>
  );
}

interface DetailTabsProps {
  activeTab: DetailTab;
  onTabChange: (tab: DetailTab) => void;
}

function DetailTabs({ activeTab, onTabChange }: DetailTabsProps) {
  const tabs: { id: DetailTab; label: string }[] = [
    { id: "description", label: "Description" },
    { id: "changelog", label: "Changelog" },
    { id: "versions", label: "Versions" },
  ];

  return (
    <div className="flex border-b border-border-subtle gap-1" data-testid="detail-tabs">
      {tabs.map((tab) => {
        const active = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onTabChange(tab.id)}
            className={`px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors cursor-pointer focus:outline-hidden focus-visible:text-text-primary ${
              active
                ? "border-accent-primary text-text-primary font-semibold"
                : "border-transparent text-text-muted font-medium hover:text-text-primary"
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export function PluginDetailPage({ lockedProjectType }: PluginDetailPageProps = {}) {
  const { projectId, serverId: routeServerId } = useParams<{
    projectId: string;
    serverId?: string;
  }>();
  const location = useLocation();
  const searchParams = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const urlServerId = searchParams.get("server") ?? searchParams.get("serverId") ?? "";
  const isInServerShell = Boolean(routeServerId);
  const effectiveServerId = routeServerId || urlServerId;
  const branchCtx = useServerBranchContext();
  const urlBranch = searchParams.get("branch") ?? undefined;
  const effectiveBranch =
    urlBranch ?? (branchCtx?.gitBacked && branchCtx.branch !== "main" ? branchCtx.branch : undefined);

  const effectiveSection: "plugin" | "mod" =
    lockedProjectType ?? (location.pathname.includes("/mods/marketplace") ? "mod" : "plugin");

  const [activeTab, setActiveTab] = useState<DetailTab>("description");
  const [installModalState, setInstallModalState] = useState<{
    open: boolean;
    initialVersionId?: string;
    initialVersion?: PluginVersionResponse;
  }>({ open: false });

  const projectQuery = useMarketplaceProject(projectId ?? "");
  const { data: project, isLoading, error } = projectQuery;

  const installedPlugins = useSafePluginsList(effectiveServerId, effectiveBranch);
  const installedAddon = useMemo(() => {
    if (!project) return null;
    return findInstalledAddon(installedPlugins, {
      project_id: project.project_id,
      slug: project.slug,
      title: project.title,
    });
  }, [installedPlugins, project]);

  const backUrl =
    isInServerShell && routeServerId
      ? `/servers/${encodeURIComponent(routeServerId)}/${effectiveSection === "mod" ? "mods" : "plugins"}/marketplace${location.search}`
      : `/marketplace${location.search}`;

  const effectiveTypes = useMemo(
    () => (project ? inferProjectTypes(project.project_types, project.loaders) : []),
    [project],
  );
  const isDualModAndPlugin =
    effectiveTypes.includes("mod") && effectiveTypes.includes("plugin");
  const projectType: "plugin" | "mod" = isInServerShell
    ? effectiveSection
    : effectiveTypes.includes("mod") && !effectiveTypes.includes("plugin")
      ? "mod"
      : "plugin";

  const containerClass = isInServerShell
    ? "space-y-6"
    : "mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-6 space-y-6";

  function buildPlatformHref(loader: string): string {
    const params = new URLSearchParams(location.search);
    const targetType = platformProjectType(loader, projectType);
    params.delete("page");
    if (isInServerShell && routeServerId) {
      params.delete("type");
      params.set("loader", loader.toLowerCase());
      const sectionSegment = targetType === "mod" ? "mods" : "plugins";
      return `/servers/${encodeURIComponent(routeServerId)}/${sectionSegment}/marketplace?${params.toString()}`;
    }
    params.set("type", targetType);
    params.set("loader", loader.toLowerCase());
    return `/marketplace?${params.toString()}`;
  }

  function openInstallModal(version?: PluginVersionResponse) {
    setInstallModalState({
      open: true,
      initialVersionId: version?.version_id,
      initialVersion: version,
    });
  }

  if (!projectId) {
    return (
      <div className={containerClass}>
        <div className="rounded-xl border border-status-danger-border bg-status-danger-bg p-6 text-sm text-status-danger">
          No project ID specified.
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className={containerClass}>
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-96" />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-4">
            <div className="rounded-xl border border-border-subtle bg-surface-card p-6 space-y-3">
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          </div>
          <div className="rounded-xl border border-border-subtle bg-surface-card p-6 space-y-3">
            <Skeleton className="h-4 w-24 mb-2" />
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-6 w-32" />
          </div>
        </div>
      </div>
    );
  }

  const isNotFound = error instanceof ApiError && error.status === 404;

  if (error && !isNotFound) {
    return (
      <div className={containerClass}>
        <Link
          to={backUrl}
          className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-text-muted transition-colors hover:text-text-primary"
        >
          <Icon name="chevron-left" size={16} />
          Back to Marketplace
        </Link>
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load project details"}
          onRetry={
            typeof (projectQuery as { refetch?: () => unknown }).refetch === "function"
              ? () => void (projectQuery as { refetch: () => unknown }).refetch()
              : undefined
          }
        />
      </div>
    );
  }

  if (isNotFound || !project) {
    return (
      <div className={containerClass}>
        <div className="rounded-xl border border-border-subtle bg-surface-card p-8 text-center">
          <h2 className="text-lg font-semibold text-text-primary">Project not found</h2>
          <p className="mt-2 text-sm text-text-muted">
            This project does not exist or could not be loaded from Modrinth.
          </p>
          <Link
            to={backUrl}
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover"
          >
            <Icon name="chevron-left" size={16} />
            Back to Marketplace
          </Link>
        </div>
      </div>
    );
  }

  const primaryType = effectiveTypes[0] || project.project_types[0] || "plugin";
  const modrinthUrl = `https://modrinth.com/${primaryType}/${project.slug || project.project_id}`;
  const formattedTypesLabel =
    effectiveTypes.map((t) => (t === "mod" ? "Mod" : "Plugin")).join(" · ") || "—";

  const modalProject: PluginSearchResultResponse = {
    project_id: project.project_id,
    slug: project.slug,
    title: project.title,
    description: project.description,
    author: project.author,
    project_types: effectiveTypes.length > 0 ? effectiveTypes : project.project_types,
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

  return (
    <div className={containerClass}>
      <div>
        <Link
          to={backUrl}
          className="mb-4 inline-flex items-center gap-1 text-sm text-text-muted transition-colors hover:text-text-primary"
        >
          <Icon name="chevron-left" size={16} />
          Back to Marketplace
        </Link>

        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-4 min-w-0">
            {project.icon_url ? (
              <img
                src={project.icon_url}
                alt=""
                className="h-16 w-16 shrink-0 rounded-xl object-cover border border-border-subtle"
              />
            ) : (
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl bg-status-info-bg text-status-info">
                <Icon name="plugin" size={28} />
              </div>
            )}
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-2xl font-bold text-text-primary">
                  {project.title}
                </h2>
                {effectiveTypes.map((type) => {
                  const isActiveShellRole = isInServerShell && type === effectiveSection;
                  return (
                    <span
                      key={type}
                      data-testid={`project-type-badge-${type}`}
                      className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold capitalize ${
                        isActiveShellRole
                          ? "border-accent-primary/40 bg-accent-primary/12 text-accent-primary"
                          : "border-status-info-border bg-status-info-bg text-status-info"
                      }`}
                    >
                      {type}
                    </span>
                  );
                })}
                {installedAddon && (
                  <span
                    data-testid="detail-installed-badge"
                    className="inline-flex items-center gap-1 rounded-full border border-status-success-border bg-status-success-bg px-2.5 py-0.5 text-xs font-semibold text-status-success"
                  >
                    <Icon name="check" size={12} />
                    Installed
                  </span>
                )}
              </div>
              {project.description && (
                <p
                  data-testid="hero-summary"
                  className="mt-1.5 text-sm text-text-secondary leading-relaxed"
                >
                  {project.description}
                </p>
              )}
              <p className="mt-1 text-xs text-text-muted">
                By <span className="font-medium text-text-primary">{project.author}</span>
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2.5 shrink-0">
            {project.wiki_url && (
              <a
                href={project.wiki_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-card px-3 py-2 text-xs font-medium text-text-secondary shadow-2xs transition-colors hover:border-border-hover hover:bg-surface-hover hover:text-text-primary"
              >
                Wiki
              </a>
            )}
            {project.source_url && (
              <a
                href={project.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-card px-3 py-2 text-xs font-medium text-text-secondary shadow-2xs transition-colors hover:border-border-hover hover:bg-surface-hover hover:text-text-primary"
              >
                Source Code
              </a>
            )}
            <a
              href={modrinthUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-card px-3 py-2 text-xs font-medium text-text-secondary shadow-2xs transition-colors hover:border-border-hover hover:bg-surface-hover hover:text-text-primary"
            >
              <Icon name="modrinth" size={14} />
              Modrinth
            </a>
            <button
              type="button"
              onClick={() => openInstallModal()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-medium text-accent-contrast-text transition-colors hover:bg-accent-hover cursor-pointer"
            >
              <Icon name="plus" size={16} />
              Install
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6 min-w-0">
          <DetailTabs activeTab={activeTab} onTabChange={setActiveTab} />

          {activeTab === "description" && (
            <div
              className="rounded-xl border border-border-subtle bg-surface-card p-6"
              data-testid="description-section"
            >
              {project.body ? (
                <MarketplaceMarkdown content={project.body} />
              ) : (
                <p className="text-sm text-text-muted italic">
                  No additional description provided.
                </p>
              )}
            </div>
          )}

          {activeTab === "changelog" && (
            <ProjectChangelogList
              projectId={project.project_id}
              onInstallVersion={openInstallModal}
            />
          )}

          {activeTab === "versions" && (
            <ProjectVersionsList
              projectId={project.project_id}
              serverId={effectiveServerId || undefined}
              onInstallVersion={openInstallModal}
            />
          )}
        </div>

        <div className="space-y-6">
          <CompatibilityCard
            gameVersions={project.game_versions}
            loaders={project.loaders}
            clientSide={project.client_side}
            serverSide={project.server_side}
            buildPlatformHref={buildPlatformHref}
          />

          <div className="rounded-xl border border-border-subtle bg-surface-card">
            <DetailSection title="Details">
              <DetailRow label="Author">{project.author || "—"}</DetailRow>
              <DetailRow label="Downloads">{formatDownloads(project.downloads)}</DetailRow>
              <DetailRow label="Follows">{formatDownloads(project.follows)}</DetailRow>
              <DetailRow label="Type">
                <span data-testid="detail-type-value">{formattedTypesLabel}</span>
              </DetailRow>
            </DetailSection>
          </div>
        </div>
      </div>

      {installModalState.open && (
        <InstallModal
          project={modalProject}
          projectType={isInServerShell ? effectiveSection : isDualModAndPlugin ? undefined : projectType}
          serverId={effectiveServerId || undefined}
          branch={effectiveBranch}
          initialVersionId={installModalState.initialVersionId}
          initialVersion={installModalState.initialVersion}
          onClose={() => setInstallModalState({ open: false })}
        />
      )}
    </div>
  );
}
