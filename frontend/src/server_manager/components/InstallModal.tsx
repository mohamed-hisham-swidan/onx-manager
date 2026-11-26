import { useContext, useEffect, useMemo, useState } from "react";
import { QueryClientContext } from "@tanstack/react-query";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { useServersList } from "@/server_manager/hooks/useServers";
import * as pluginHooks from "@/server_manager/hooks/usePlugins";
import {
  useInstallFromMarketplace,
  useProjectVersions,
} from "@/server_manager/hooks/usePlugins";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import { toast } from "@/stores/toastStore";
import {
  getLoaderDisplay,
  parseGameVersion,
  sortReleaseVersionsDesc,
} from "@/server_manager/utils/compatibility";
import { formatBytes } from "@/server_manager/utils/format";
import { findInstalledAddon } from "@/server_manager/utils/installedAddons";
import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";
import {
  LOADER_COMPATIBILITY,
  compareVersionNumbers,
  gameVersionMatches,
} from "@/server_manager/utils/versionMatching";
import type { ServerBranch, ServerResponse } from "@/server_manager/types";
import type {
  InstallModrinthPluginRequest,
  InstallModrinthPluginResponse,
  PluginResponse,
  PluginSearchResultResponse,
  PluginVersionResponse,
  PluginVersionsResponse,
} from "@/types";

type VersionChannel = "release" | "beta" | "alpha";

interface DependencyMeta {
  title: string;
  slug?: string;
}

const CHANNEL_RANK: Record<VersionChannel, number> = {
  release: 2,
  beta: 1,
  alpha: 0,
};

const CHANNEL_BADGE: Record<VersionChannel, { label: string; className: string }> = {
  release: {
    label: "Release",
    className: "border-status-success-border bg-status-success-bg text-status-success",
  },
  beta: {
    label: "Beta",
    className: "border-status-warning-border bg-status-warning-bg text-status-warning",
  },
  alpha: {
    label: "Alpha",
    className: "border-status-danger-border bg-status-danger-bg text-status-danger",
  },
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function getVersionChannel(version: PluginVersionResponse): VersionChannel {
  const raw = (version.version_type || "release").trim().toLowerCase();
  if (raw === "alpha") return "alpha";
  if (raw === "beta") return "beta";
  return "release";
}

function releaseKey(version: string): string | null {
  const parsed = parseGameVersion(version);
  if (!parsed) return null;
  return `${parsed.major}.${parsed.minor}.${parsed.patch}`;
}

function isServerCompatibleWithProject(
  server: ServerResponse,
  projectTypes: string[] | undefined,
  explicitProjectType?: "plugin" | "mod",
): boolean {
  const caps = getServerCapabilities(server.server_type);
  if (explicitProjectType === "mod") return caps.supportsMods;
  if (explicitProjectType === "plugin") return caps.supportsPlugins;
  const types = (projectTypes ?? []).map((t) => t.toLowerCase());
  const hasMod = types.includes("mod");
  const hasPlugin = types.includes("plugin");
  if (hasMod && hasPlugin) return caps.supportsMods || caps.supportsPlugins;
  if (hasMod) return caps.supportsMods;
  return caps.supportsPlugins;
}

function useSafePluginsList(serverId: string, branch?: string): PluginResponse[] | undefined {
  const fn = (pluginHooks as Record<string, unknown>).usePluginsList;
  const hook =
    typeof fn === "function"
      ? (fn as (sid: string, br?: string) => { data?: PluginResponse[] })
      : () => ({ data: undefined });
  return hook(serverId, branch)?.data;
}

function resolveVersionForPair(
  versions: PluginVersionResponse[],
  gameVersion: string,
  loader: string,
): PluginVersionResponse | null {
  if (versions.length === 0) return null;
  const targetLoader = loader.trim().toLowerCase();
  const targetReleaseKey = gameVersion ? releaseKey(gameVersion) : null;

  const matches = versions.filter((v) => {
    const hasLoader =
      !targetLoader ||
      v.loaders.some((l) => l.trim().toLowerCase() === targetLoader);
    if (!hasLoader) return false;
    if (!targetReleaseKey) return true;
    return v.game_versions.some((gv) => releaseKey(gv) === targetReleaseKey);
  });

  if (matches.length === 0) return null;

  return [...matches].sort((a, b) => {
    const channelDiff =
      CHANNEL_RANK[getVersionChannel(b)] - CHANNEL_RANK[getVersionChannel(a)];
    if (channelDiff !== 0) return channelDiff;

    const dateA = a.date_published ? Date.parse(a.date_published) : 0;
    const dateB = b.date_published ? Date.parse(b.date_published) : 0;
    const safeDateA = Number.isNaN(dateA) ? 0 : dateA;
    const safeDateB = Number.isNaN(dateB) ? 0 : dateB;
    if (safeDateB !== safeDateA) return safeDateB - safeDateA;

    return compareVersionNumbers(b.version_number || "", a.version_number || "");
  })[0];
}

function pickInitialGameVersion(
  version: PluginVersionResponse | null,
  serverMc: string | undefined,
  releaseOptions: string[],
): string {
  if (!version) return releaseOptions[0] ?? "";
  const versionReleases = sortReleaseVersionsDesc(version.game_versions);
  if (versionReleases.length === 0) return "";
  if (serverMc) {
    const serverKey = releaseKey(serverMc);
    const exactMatch = versionReleases.find(
      (gv) => serverKey !== null && releaseKey(gv) === serverKey,
    );
    if (exactMatch) return exactMatch;
    const lineMatch = versionReleases.find((gv) => gameVersionMatches(serverMc, gv));
    if (lineMatch) return lineMatch;
  }
  return versionReleases[0];
}

function pickInitialLoader(
  version: PluginVersionResponse | null,
  serverType: string | undefined,
  loaderOptions: string[],
): string {
  const normalizedServerType = serverType?.trim().toLowerCase() ?? "";
  const compatChain = normalizedServerType
    ? LOADER_COMPATIBILITY[normalizedServerType] ?? [normalizedServerType]
    : [];

  if (version && version.loaders.length > 0) {
    const versionLoaders = version.loaders.map((l) => l.trim().toLowerCase());
    for (const candidate of compatChain) {
      if (versionLoaders.includes(candidate)) return candidate;
    }
    return versionLoaders[0];
  }

  for (const candidate of compatChain) {
    if (loaderOptions.includes(candidate)) return candidate;
  }
  return loaderOptions[0] ?? "";
}

function runInstallMutation(
  installHook: ReturnType<typeof useInstallFromMarketplace>,
  body: InstallModrinthPluginRequest,
): Promise<InstallModrinthPluginResponse> {
  if (typeof installHook.mutateAsync === "function") {
    return installHook.mutateAsync(body);
  }
  return new Promise((resolve, reject) => {
    installHook.mutate(body, {
      onSuccess: (res) => resolve(res),
      onError: (err) => reject(err),
    });
  });
}

export interface InstallModalProps {
  project: PluginSearchResultResponse;
  projectType?: "plugin" | "mod";
  serverId?: string;
  branch?: string;
  initialVersionId?: string;
  initialVersion?: PluginVersionResponse;
  onClose: () => void;
  isOpen?: boolean;
}

export function InstallModal({
  project,
  projectType,
  serverId: requestedServerId,
  branch,
  initialVersionId,
  initialVersion,
  onClose,
  isOpen = true,
}: InstallModalProps) {
  const queryClient = useContext(QueryClientContext);
  const { data: servers } = useServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);
  const setLastUsedServer = useLastUsedServerStore((s) => s.setLastUsedServer);

  const isDualProject = Boolean(
    !projectType &&
      project.project_types?.includes("mod") &&
      project.project_types?.includes("plugin"),
  );
  const baseEffectiveType =
    projectType || (project.project_types?.[0] === "mod" && !isDualProject ? "mod" : "plugin");

  const compatibleServers = useMemo(() => {
    if (!servers) return [];
    return servers.filter((s) =>
      isServerCompatibleWithProject(s, project.project_types, projectType),
    );
  }, [servers, project.project_types, projectType]);

  const incompatibleRequestedServer = useMemo(() => {
    if (!requestedServerId || !servers) return null;
    const found = servers.find((s) => s.server_id === requestedServerId);
    if (!found) return null;
    return isServerCompatibleWithProject(found, project.project_types, projectType) ? null : found;
  }, [requestedServerId, servers, project.project_types, projectType]);

  const initialServerId = useMemo(() => {
    if (compatibleServers.length === 0) return "";
    if (requestedServerId) {
      const requested = compatibleServers.find((s) => s.server_id === requestedServerId);
      if (requested) return requested.server_id;
    }
    const lastUsed = compatibleServers.find((s) => s.server_id === lastUsedServerId);
    if (lastUsed) return lastUsed.server_id;
    return compatibleServers[0].server_id;
  }, [compatibleServers, requestedServerId, lastUsedServerId]);

  const [manuallyChosenServerId, setManuallyChosenServerId] = useState<string | null>(null);
  const [isChangingServer, setIsChangingServer] = useState(false);

  const selectedServerId = useMemo(() => {
    if (
      manuallyChosenServerId &&
      compatibleServers.some((s) => s.server_id === manuallyChosenServerId)
    ) {
      return manuallyChosenServerId;
    }
    return initialServerId;
  }, [manuallyChosenServerId, compatibleServers, initialServerId]);

  const selectedServer = useMemo(
    () => compatibleServers.find((s) => s.server_id === selectedServerId),
    [compatibleServers, selectedServerId],
  );

  const effectiveType: "plugin" | "mod" = useMemo(() => {
    if (isDualProject && selectedServer) {
      return getServerCapabilities(selectedServer.server_type).supportsMods ? "mod" : "plugin";
    }
    return baseEffectiveType;
  }, [isDualProject, selectedServer, baseEffectiveType]);
  const typeLabel = effectiveType === "mod" ? "Mod" : "Plugin";

  const versionsQuery = useProjectVersions(selectedServerId, project.project_id, {
    enabled: isOpen && !!selectedServerId,
    limit: 50,
  });

  const versionsResponse: PluginVersionsResponse | undefined = versionsQuery.data;
  const allVersions = useMemo(
    () => versionsResponse?.versions ?? [],
    [versionsResponse?.versions],
  );

  const isIncompatibleProject =
    versionsResponse?.notice_kind === "incompatible" ||
    (versionsResponse != null && versionsResponse.selected === null);
  const recommendedVersion = isIncompatibleProject
    ? null
    : (versionsResponse?.selected ?? null);

  const preselectedVersion = useMemo(() => {
    if (!initialVersionId) return null;
    const fromPage = allVersions.find((v) => v.version_id === initialVersionId);
    if (fromPage) return fromPage;
    if (initialVersion && initialVersion.version_id === initialVersionId) {
      return initialVersion;
    }
    return null;
  }, [initialVersionId, initialVersion, allVersions]);

  const releaseVersionOptions = useMemo(() => {
    const raw = allVersions.flatMap((v) => v.game_versions);
    return sortReleaseVersionsDesc(raw);
  }, [allVersions]);

  const loaderOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const v of allVersions) {
      for (const l of v.loaders) {
        const key = l.trim().toLowerCase();
        if (key) seen.add(key);
      }
    }
    if (seen.size === 0) {
      for (const l of project.loaders ?? []) {
        const key = l.trim().toLowerCase();
        if (key) seen.add(key);
      }
    }
    const serverType = selectedServer?.server_type?.trim().toLowerCase() ?? "";
    const compatOrder = serverType
      ? LOADER_COMPATIBILITY[serverType] ?? [serverType]
      : [];

    return [...seen].sort((a, b) => {
      const idxA = compatOrder.indexOf(a);
      const idxB = compatOrder.indexOf(b);
      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;
      return getLoaderDisplay(a).label.localeCompare(getLoaderDisplay(b).label);
    });
  }, [allVersions, project.loaders, selectedServer?.server_type]);

  const [manualGameVersion, setManualGameVersion] = useState<string | null>(null);
  const [manualLoader, setManualLoader] = useState<string | null>(null);
  const [hasUserChangedPickers, setHasUserChangedPickers] = useState(false);

  const pinnedVersion = !hasUserChangedPickers ? preselectedVersion : null;
  const seedVersion = pinnedVersion ?? recommendedVersion;

  const autoGameVersion = useMemo(
    () =>
      pickInitialGameVersion(
        seedVersion,
        selectedServer?.minecraft_version,
        releaseVersionOptions,
      ),
    [seedVersion, selectedServer?.minecraft_version, releaseVersionOptions],
  );

  const autoLoader = useMemo(
    () =>
      pickInitialLoader(
        seedVersion,
        selectedServer?.server_type,
        loaderOptions,
      ),
    [seedVersion, selectedServer?.server_type, loaderOptions],
  );

  const selectedGameVersion =
    manualGameVersion !== null ? manualGameVersion : autoGameVersion;
  const selectedLoader =
    manualLoader !== null ? manualLoader : autoLoader;

  const activeVersion = useMemo(() => {
    if (pinnedVersion) return pinnedVersion;
    if (!hasUserChangedPickers && recommendedVersion) return recommendedVersion;
    return resolveVersionForPair(allVersions, selectedGameVersion, selectedLoader);
  }, [
    pinnedVersion,
    hasUserChangedPickers,
    recommendedVersion,
    allVersions,
    selectedGameVersion,
    selectedLoader,
  ]);

  const [branchState, setBranchState] = useState<{
    serverId: string | null;
    branches: ServerBranch[];
    error: string | null;
  }>({ serverId: null, branches: [], error: null });
  const [branchFetchNonce, setBranchFetchNonce] = useState(0);
  const [manualBranch, setManualBranch] = useState<string | null>(null);
  const isAdvancedServer = selectedServer?.mode === "advanced";

  const api = useMemo(() => createAuthenticatedApi(), []);
  const hasBranchesApi = typeof api.getServerBranches === "function";

  useEffect(() => {
    let cancelled = false;
    if (!isOpen || !selectedServerId || !isAdvancedServer || !hasBranchesApi) {
      return;
    }
    api
      .getServerBranches(selectedServerId)
      .then((res) => {
        if (!cancelled) {
          setBranchState({
            serverId: selectedServerId,
            branches: Array.isArray(res) ? res : [],
            error: null,
          });
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setBranchState({
            serverId: selectedServerId,
            branches: [],
            error: errorMessage(err),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, hasBranchesApi, isOpen, selectedServerId, isAdvancedServer, branchFetchNonce]);

  const branchesLoading = Boolean(
    isOpen &&
      selectedServerId &&
      isAdvancedServer &&
      hasBranchesApi &&
      branchState.serverId !== selectedServerId,
  );
  const branchesError =
    isAdvancedServer && branchState.serverId === selectedServerId ? branchState.error : null;
  const branches = useMemo(
    () =>
      isAdvancedServer && branchState.serverId === selectedServerId ? branchState.branches : [],
    [isAdvancedServer, branchState.serverId, branchState.branches, selectedServerId],
  );

  const gitBacked = isAdvancedServer && branches.some((b) => b.worktree_path != null);
  const targetBranch = useMemo(() => {
    if (!gitBacked) return undefined;
    if (manualBranch && branches.some((b) => b.name === manualBranch)) {
      return manualBranch;
    }
    if (branch && branch !== "main" && branches.some((b) => b.name === branch)) {
      return branch;
    }
    return branches.find((b) => b.name !== "main")?.name ?? "main";
  }, [gitBacked, manualBranch, branch, branches]);

  const isMainBlocked = Boolean(
    isAdvancedServer &&
      !branchesLoading &&
      !branchesError &&
      ((gitBacked && targetBranch === "main") ||
        (hasBranchesApi && branches.length > 0 && !gitBacked && targetBranch === undefined)),
  );

  // Fail-closed gate: block Advanced installs while branch state is loading or errored.
  const isBranchGateBlocked = Boolean(
    isAdvancedServer && hasBranchesApi && (branchesLoading || branchesError || isMainBlocked),
  );

  const installedPlugins = useSafePluginsList(
    isOpen ? selectedServerId : "",
    isAdvancedServer ? targetBranch : undefined,
  );
  const installedMatch = useMemo(
    () =>
      findInstalledAddon(installedPlugins, {
        project_id: project.project_id,
        slug: project.slug,
        title: project.title,
      }),
    [installedPlugins, project.project_id, project.slug, project.title],
  );

  const requiredDependencies = useMemo(() => {
    if (!activeVersion) return [];
    const req = activeVersion.required_dependencies;
    if (Array.isArray(req)) return req.filter(Boolean);
    return (activeVersion.dependencies ?? []).filter(Boolean);
  }, [activeVersion]);

  const [depMetaMap, setDepMetaMap] = useState<Record<string, DependencyMeta>>({});
  useEffect(() => {
    if (
      !isOpen ||
      requiredDependencies.length === 0 ||
      typeof api.getMarketplaceProject !== "function"
    ) {
      return;
    }
    let cancelled = false;
    for (const depId of requiredDependencies) {
      if (depMetaMap[depId]) continue;
      const fetchProject = queryClient
        ? () =>
            queryClient.fetchQuery({
              queryKey: queryKeys.plugins.marketplace.project(depId),
              queryFn: () => api.getMarketplaceProject(depId),
              staleTime: 5 * 60 * 1000,
            })
        : () => api.getMarketplaceProject(depId);

      fetchProject()
        .then((proj) => {
          if (!cancelled && proj?.title) {
            setDepMetaMap((prev) =>
              prev[depId]?.title === proj.title
                ? prev
                : { ...prev, [depId]: { title: proj.title, slug: proj.slug } },
            );
          }
        })
        .catch(() => {
          // Graceful fallback to depId when upstream metadata is unavailable
        });
    }
    return () => {
      cancelled = true;
    };
  }, [isOpen, requiredDependencies, api, queryClient, depMetaMap]);

  const dependencyEntries = useMemo(
    () =>
      requiredDependencies.map((depId) => {
        const meta = depMetaMap[depId];
        const installed = Boolean(
          findInstalledAddon(installedPlugins, {
            project_id: depId,
            slug: meta?.slug,
            title: meta?.title,
          }),
        );
        return {
          id: depId,
          title: meta?.title || depId,
          installed,
        };
      }),
    [requiredDependencies, depMetaMap, installedPlugins],
  );
  const missingDependencies = useMemo(
    () => dependencyEntries.filter((d) => !d.installed),
    [dependencyEntries],
  );

  const compatibilityNotice = useMemo(() => {
    if (!selectedServer || versionsQuery.isLoading || versionsQuery.isError) return null;
    if (allVersions.length > 0 && !activeVersion) {
      const loaderLabel = selectedLoader ? getLoaderDisplay(selectedLoader).label : "selected platform";
      const mcLabel = selectedGameVersion || "selected version";
      return {
        kind: "missing" as const,
        text: `No build published for ${loaderLabel} on MC ${mcLabel}.`,
      };
    }
    if (!activeVersion) return null;

    const serverType = selectedServer.server_type.trim().toLowerCase();
    const serverLabel = getLoaderDisplay(serverType).label;
    const serverMc = selectedServer.minecraft_version;
    const compatChain = LOADER_COMPATIBILITY[serverType] ?? [serverType];

    const mcCompatible = selectedGameVersion
      ? gameVersionMatches(serverMc, selectedGameVersion)
      : activeVersion.game_versions.some((gv) => gameVersionMatches(serverMc, gv));
    const effectiveLoader = selectedLoader || activeVersion.loaders[0]?.trim().toLowerCase() || "";
    const loaderIsExact =
      effectiveLoader === serverType &&
      activeVersion.loaders.some((l) => l.trim().toLowerCase() === serverType);
    const loaderIsCompatible =
      compatChain.includes(effectiveLoader) &&
      activeVersion.loaders.some((l) => compatChain.includes(l.trim().toLowerCase()));

    if (!mcCompatible || !loaderIsCompatible) {
      return {
        kind: "mismatch" as const,
        text: `Not officially listed for ${serverLabel} ${serverMc} — install at your own risk`,
      };
    }

    if (!loaderIsExact) {
      const fallbackLabel = getLoaderDisplay(effectiveLoader).label;
      return {
        kind: "fallback" as const,
        text: `No ${serverLabel}-tagged build for MC ${serverMc} — using the ${fallbackLabel} build, which ${serverLabel} supports.`,
      };
    }

    return null;
  }, [
    selectedServer,
    versionsQuery.isLoading,
    versionsQuery.isError,
    allVersions.length,
    activeVersion,
    selectedLoader,
    selectedGameVersion,
  ]);

  const install = useInstallFromMarketplace(selectedServerId, targetBranch);
  const [isBatchInstalling, setIsBatchInstalling] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{
    current: number;
    total: number;
    label: string;
  } | null>(null);

  const isBusy = install.isPending || isBatchInstalling;

  const handleClose = () => {
    if (isBusy) return;
    onClose();
  };

  function handleSelectServer(nextServerId: string) {
    setManuallyChosenServerId(nextServerId);
    setManualGameVersion(null);
    setManualLoader(null);
    setHasUserChangedPickers(false);
    setManualBranch(null);
    setBranchState({ serverId: null, branches: [], error: null });
    setIsChangingServer(false);
  }

  function handleGameVersionChange(nextVersion: string) {
    setManualGameVersion(nextVersion);
    if (manualLoader === null) setManualLoader(selectedLoader);
    setHasUserChangedPickers(true);
  }

  function handleLoaderChange(nextLoader: string) {
    setManualLoader(nextLoader);
    if (manualGameVersion === null) setManualGameVersion(selectedGameVersion);
    setHasUserChangedPickers(true);
  }

  function handleInstallOnlyThis() {
    if (!selectedServerId || !activeVersion || isBranchGateBlocked || isBusy) return;
    install.mutate(
      {
        project_id: project.project_id,
        version_id: activeVersion.version_id,
      },
      {
        onSuccess: (result) => {
          setLastUsedServer(selectedServerId);
          const branchSuffix = targetBranch ? ` (branch ${targetBranch})` : "";
          toast(
            "success",
            `${typeLabel} installed`,
            `"${project.title}" ${result.version} installed on ${selectedServer?.name ?? "this server"}${branchSuffix}.`,
          );
          onClose();
        },
        onError: (err) => toast("error", "Install failed", errorMessage(err)),
      },
    );
  }

  async function handleInstallWithDependencies() {
    if (!selectedServerId || !activeVersion || isBranchGateBlocked || isBusy) return;
    if (missingDependencies.length === 0) {
      handleInstallOnlyThis();
      return;
    }
    setIsBatchInstalling(true);
    try {
      for (let i = 0; i < missingDependencies.length; i++) {
        const dep = missingDependencies[i];
        setBatchProgress({
          current: i + 1,
          total: missingDependencies.length,
          label: dep.title,
        });
        await runInstallMutation(install, {
          project_id: dep.id,
        });
      }

      setBatchProgress(null);
      const result = await runInstallMutation(install, {
        project_id: project.project_id,
        version_id: activeVersion.version_id,
      });

      if (queryClient) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.plugins.list(selectedServerId, targetBranch),
        });
        void queryClient.invalidateQueries({
          queryKey: queryKeys.plugins.list(selectedServerId),
        });
      }

      setLastUsedServer(selectedServerId);
      const branchSuffix = targetBranch ? ` (branch ${targetBranch})` : "";
      const depCount = missingDependencies.length;
      toast(
        "success",
        `${typeLabel} installed`,
        `"${project.title}" ${result.version} and ${depCount} required ${
          depCount === 1 ? "dependency" : "dependencies"
        } installed on ${selectedServer?.name ?? "this server"}${branchSuffix}.`,
      );
      onClose();
    } catch (err) {
      toast("error", "Install failed", errorMessage(err));
    } finally {
      setIsBatchInstalling(false);
      setBatchProgress(null);
    }
  }

  const activeChannel = activeVersion ? getVersionChannel(activeVersion) : null;
  const activeChannelMeta = activeChannel ? CHANNEL_BADGE[activeChannel] : null;
  const primaryFile = activeVersion
    ? (activeVersion.files.find((f) => f.primary) ?? activeVersion.files[0])
    : undefined;

  const isSnapshotOnlySelection = Boolean(
    activeVersion && releaseVersionOptions.length === 0,
  );
  const isPinnedSnapshotSelection = Boolean(
    pinnedVersion &&
      sortReleaseVersionsDesc(pinnedVersion.game_versions).length === 0,
  );

  const installDisabled =
    !selectedServerId ||
    !activeVersion ||
    isBusy ||
    compatibleServers.length === 0 ||
    isBranchGateBlocked;

  const primaryBusyLabel = batchProgress
    ? `Installing dependency ${batchProgress.current}/${batchProgress.total}...`
    : "Installing...";

  return (
    <Modal
      open={isOpen}
      onClose={handleClose}
      ariaLabel={`Install ${project.title}`}
      size="lg"
      closeOnBackdrop={!isBusy}
      closeOnEscape={!isBusy}
      closeButtonAriaLabel="Close modal"
      title={
        <div className="flex items-center gap-3 min-w-0">
          {project.icon_url ? (
            <img
              src={project.icon_url}
              alt=""
              className="h-12 w-12 shrink-0 rounded-xl object-cover border border-border-default"
            />
          ) : (
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-surface-muted text-text-muted border border-border-default">
              <Icon name="plugin" size={24} />
            </div>
          )}
          <div className="min-w-0">
            <span className="block truncate text-lg font-bold text-text-primary">
              {project.title}
            </span>
            <p className="text-xs text-text-muted font-normal">
              By <span className="font-medium text-text-secondary">{project.author}</span>
            </p>
          </div>
        </div>
      }
    >
      <div data-testid="install-modal" className="space-y-4">
        {incompatibleRequestedServer && (
          <div
            data-testid="incompatible-server-notice"
            className="flex items-start gap-2 rounded-xl border border-status-warning-border bg-status-warning-bg p-3 text-xs text-status-warning"
          >
            <Icon name="alert" size={15} className="mt-0.5 shrink-0" />
            <span>
              &ldquo;{incompatibleRequestedServer.name}&rdquo; ({incompatibleRequestedServer.server_type}) does not support {effectiveType}s. Choose another server below.
            </span>
          </div>
        )}

        {compatibleServers.length === 0 ? (
          <div className="space-y-4">
            <div className="rounded-xl border border-status-warning-border bg-status-warning-bg p-4 text-xs text-status-warning">
              <div className="flex items-start gap-2">
                <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
                <div>
                  <p className="font-semibold">No compatible servers available</p>
                  <p className="mt-0.5">
                    This project is a {effectiveType}, but none of your servers support {effectiveType}s. Create a compatible server to proceed.
                  </p>
                </div>
              </div>
            </div>
            <button
              type="button"
              disabled
              className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-accent-primary px-4 py-3 text-sm font-semibold text-accent-contrast-text opacity-40 cursor-not-allowed"
            >
              <Icon name="plus" size={18} />
              Install Now
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Target Server */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                  Target Server
                </label>
                {compatibleServers.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setIsChangingServer(!isChangingServer)}
                    disabled={isBusy}
                    className="text-xs font-medium text-accent-primary hover:underline disabled:opacity-50 cursor-pointer"
                  >
                    {isChangingServer ? "Cancel" : "Change Server"}
                  </button>
                )}
              </div>

              {isChangingServer ? (
                <div className="space-y-1.5 max-h-40 overflow-y-auto rounded-xl border border-border-subtle p-2">
                  {compatibleServers.map((s) => (
                    <button
                      key={s.server_id}
                      type="button"
                      onClick={() => handleSelectServer(s.server_id)}
                      className={`w-full flex items-center justify-between rounded-lg p-2.5 text-left text-xs transition-colors cursor-pointer ${
                        selectedServerId === s.server_id
                          ? "bg-accent-primary/10 text-accent-primary font-medium"
                          : "hover:bg-surface-hover text-text-secondary"
                      }`}
                    >
                      <div>
                        <span className="font-medium">{s.name}</span>
                        <span className="ml-2 text-text-muted">
                          ({getLoaderDisplay(s.server_type).label} / {s.minecraft_version})
                        </span>
                      </div>
                      {selectedServerId === s.server_id && (
                        <Icon name="check" size={14} className="text-accent-primary" />
                      )}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="flex items-center justify-between rounded-xl border border-border-subtle bg-surface-muted p-3 text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <Icon name="server" size={16} className="text-text-muted shrink-0" />
                    <span className="font-semibold text-text-primary truncate">
                      {selectedServer?.name || "Select a server"}
                    </span>
                    {selectedServer && (
                      <span className="rounded-full bg-surface-card px-2 py-0.5 text-[10px] font-medium text-text-secondary shrink-0">
                        {getLoaderDisplay(selectedServer.server_type).label} {selectedServer.minecraft_version}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>

            {isAdvancedServer && hasBranchesApi && branchesLoading && (
              <div
                data-testid="install-modal-branches-loading"
                className="flex items-center gap-2 rounded-xl border border-border-subtle bg-surface-muted px-3 py-2 text-xs text-text-muted"
              >
                <Icon name="clock" size={14} className="shrink-0 animate-pulse" />
                <span>Checking working branches...</span>
              </div>
            )}

            {isAdvancedServer && hasBranchesApi && branchesError && (
              <div
                data-testid="install-modal-branches-error"
                className="flex items-center justify-between gap-2 rounded-xl border border-status-danger-border bg-status-danger-bg px-3 py-2 text-xs text-status-danger"
              >
                <span>Failed to verify branches: {branchesError}</span>
                <button
                  type="button"
                  onClick={() => {
                    setBranchState({ serverId: null, branches: [], error: null });
                    setBranchFetchNonce((n) => n + 1);
                  }}
                  className="shrink-0 rounded-md border border-status-danger-border px-2 py-0.5 font-semibold hover:bg-surface-card cursor-pointer"
                >
                  Retry
                </button>
              </div>
            )}

            {gitBacked && !branchesLoading && !branchesError && (
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-text-muted mb-1.5">
                  Target Branch
                </label>
                <select
                  aria-label="Target branch"
                  data-testid="install-modal-branch-select"
                  value={targetBranch ?? "main"}
                  onChange={(e) => setManualBranch(e.target.value)}
                  disabled={isBusy}
                  className="w-full rounded-xl border border-border-subtle bg-surface-card p-2.5 text-xs font-medium text-text-primary focus:border-border-focus focus:outline-none"
                >
                  {branches.map((b) => (
                    <option key={b.name} value={b.name}>
                      {b.name} {b.name === "main" ? "(protected)" : ""}
                    </option>
                  ))}
                </select>
                {isMainBlocked && (
                  <p className="mt-1.5 text-xs text-status-warning">
                    &ldquo;main&rdquo; is protected. Create or choose a working branch under Versioning before installing {effectiveType}s.
                  </p>
                )}
              </div>
            )}

            {installedMatch && selectedServer && (
              <div
                data-testid="already-installed-notice"
                className="flex items-start gap-2 rounded-xl border border-status-info-border bg-status-info-bg p-3 text-xs text-status-info"
              >
                <Icon name="info" size={15} className="mt-0.5 shrink-0" />
                <span>
                  Already installed on <strong>{selectedServer.name}</strong> (
                  <span className="font-mono">{installedMatch.version || "installed"}</span>). Select another version or server if needed.
                </span>
              </div>
            )}

            {/* Two Clean Pickers: Game Version + Platform / Loader */}
            {versionsQuery.isLoading ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="h-16 animate-pulse rounded-xl bg-surface-muted" />
                <div className="h-16 animate-pulse rounded-xl bg-surface-muted" />
              </div>
            ) : versionsQuery.isError ? (
              <div className="flex items-center justify-between gap-2 rounded-xl border border-status-danger-border bg-status-danger-bg px-3 py-2.5 text-xs text-status-danger">
                <span>{errorMessage(versionsQuery.error)}</span>
                {typeof (versionsQuery as { refetch?: () => unknown }).refetch === "function" && (
                  <button
                    type="button"
                    onClick={() => void (versionsQuery as { refetch: () => unknown }).refetch()}
                    className="shrink-0 rounded-md border border-status-danger-border px-2 py-0.5 font-semibold hover:bg-surface-card cursor-pointer"
                  >
                    Retry
                  </button>
                )}
              </div>
            ) : (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" data-testid="install-pickers">
                  <div>
                    <label
                      htmlFor="install-game-version-select"
                      className="block text-xs font-semibold uppercase tracking-wider text-text-muted mb-1.5"
                    >
                      Game Version
                    </label>
                    <div className="relative">
                      <select
                        id="install-game-version-select"
                        aria-label="Game Version"
                        value={selectedGameVersion}
                        onChange={(e) => handleGameVersionChange(e.target.value)}
                        disabled={isBusy || (releaseVersionOptions.length === 0 && !isPinnedSnapshotSelection)}
                        className="h-10 w-full appearance-none rounded-xl border border-border-default bg-surface-card pl-3 pr-8 text-xs font-medium text-text-primary focus:border-border-focus focus:outline-none disabled:opacity-50 cursor-pointer"
                      >
                        {(isPinnedSnapshotSelection || isSnapshotOnlySelection) && (
                          <option value="">
                            {pinnedVersion?.game_versions[0]
                              ? `${pinnedVersion.game_versions[0]} (Snapshot)`
                              : "Snapshot / Pre-release"}
                          </option>
                        )}
                        {releaseVersionOptions.map((gv) => (
                          <option key={gv} value={gv}>
                            {gv}
                          </option>
                        ))}
                      </select>
                      <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted">
                        <Icon name="chevron-down" size={14} />
                      </div>
                    </div>
                  </div>

                  <div>
                    <label
                      htmlFor="install-loader-select"
                      className="block text-xs font-semibold uppercase tracking-wider text-text-muted mb-1.5"
                    >
                      Platform / Loader
                    </label>
                    <div className="relative">
                      <select
                        id="install-loader-select"
                        aria-label="Platform / Loader"
                        value={selectedLoader}
                        onChange={(e) => handleLoaderChange(e.target.value)}
                        disabled={isBusy || loaderOptions.length === 0}
                        className="h-10 w-full appearance-none rounded-xl border border-border-default bg-surface-card pl-3 pr-8 text-xs font-medium text-text-primary focus:border-border-focus focus:outline-none disabled:opacity-50 cursor-pointer"
                      >
                        {loaderOptions.length === 0 && (
                          <option value="">No platforms available</option>
                        )}
                        {loaderOptions.map((ldr) => (
                          <option key={ldr} value={ldr}>
                            {getLoaderDisplay(ldr).label}
                          </option>
                        ))}
                      </select>
                      <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted">
                        <Icon name="chevron-down" size={14} />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Calm non-blocking compatibility / fallback amber notices */}
                {compatibilityNotice && (
                  <div
                    data-testid={
                      compatibilityNotice.kind === "fallback"
                        ? "install-fallback-notice"
                        : compatibilityNotice.kind === "mismatch"
                          ? "install-mismatch-warning"
                          : "install-missing-build-notice"
                    }
                    className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 text-xs ${
                      compatibilityNotice.kind === "missing"
                        ? "border-status-danger-border bg-status-danger-bg text-status-danger"
                        : "border-status-warning-border bg-status-warning-bg text-status-warning"
                    }`}
                  >
                    <Icon name="alert" size={15} className="mt-0.5 shrink-0" />
                    <span>{compatibilityNotice.text}</span>
                  </div>
                )}

                {/* Compact Resolved Build Summary */}
                {activeVersion && (
                  <div
                    data-testid="install-resolved-summary"
                    className="rounded-xl border border-border-subtle bg-surface-muted px-3.5 py-2.5 space-y-1"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2 min-w-0">
                        <span className="text-xs font-semibold text-text-primary">
                          {activeVersion.version_number}
                        </span>
                        {activeChannelMeta && (
                          <span
                            data-testid="install-channel-pill"
                            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${activeChannelMeta.className}`}
                          >
                            {activeChannelMeta.label}
                          </span>
                        )}
                        {activeVersion.version_id === recommendedVersion?.version_id && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-accent-primary/10 px-2 py-0.5 text-[10px] font-semibold text-accent-primary">
                            <Icon name="check" size={10} />
                            Recommended
                          </span>
                        )}
                      </div>
                      {activeChannel && activeChannel !== "release" && (
                        <span
                          data-testid="install-prerelease-note"
                          className="text-[11px] font-medium text-status-warning"
                        >
                          Pre-release build
                        </span>
                      )}
                    </div>
                    {primaryFile && (
                      <div className="flex items-center gap-1.5 text-[11px] text-text-muted truncate">
                        <Icon name="file" size={12} className="shrink-0" />
                        <span className="truncate font-mono">{primaryFile.filename}</span>
                        <span className="shrink-0">&middot; {formatBytes(primaryFile.size_bytes)}</span>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}

            {/* Required Dependencies Callout */}
            {requiredDependencies.length > 0 && (
              <div
                data-testid="install-modal-dependencies"
                className="rounded-xl border border-status-warning-border bg-status-warning-bg p-3 text-xs space-y-2"
              >
                <div className="flex items-center justify-between gap-2 font-semibold text-status-warning">
                  <span className="inline-flex items-center gap-1.5">
                    <Icon name="alert" size={14} className="shrink-0" />
                    <span>Required Dependencies ({requiredDependencies.length})</span>
                  </span>
                  {missingDependencies.length === 0 && (
                    <span className="text-[11px] font-medium text-status-success">
                      All installed
                    </span>
                  )}
                </div>
                <ul className="space-y-1.5">
                  {dependencyEntries.map((dep) => (
                    <li
                      key={dep.id}
                      className="flex items-center justify-between gap-2 rounded-lg border border-border-subtle bg-surface-card px-2.5 py-1.5"
                    >
                      <span className="font-medium text-text-primary truncate">
                        {dep.title}
                      </span>
                      {dep.installed ? (
                        <span
                          data-testid={`dep-installed-${dep.id}`}
                          className="inline-flex shrink-0 items-center gap-1 rounded-full border border-status-success-border bg-status-success-bg px-2 py-0.5 text-[10px] font-semibold text-status-success"
                        >
                          <Icon name="check" size={10} />
                          Installed
                        </span>
                      ) : (
                        <span className="shrink-0 text-[11px] font-medium text-text-muted">
                          Required
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Primary Actions (1 button when no missing deps; 2-option Modrinth choice when missing deps exist) */}
            {missingDependencies.length > 0 ? (
              <div className="space-y-2 pt-1">
                <button
                  type="button"
                  onClick={() => void handleInstallWithDependencies()}
                  disabled={installDisabled}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-accent-primary px-4 py-3 text-sm font-semibold text-accent-contrast-text shadow-xs transition-colors hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                >
                  <Icon name="plus" size={18} />
                  {isBusy
                    ? primaryBusyLabel
                    : branchesLoading
                      ? "Checking branches..."
                      : "Install with Dependencies"}
                </button>
                <button
                  type="button"
                  onClick={handleInstallOnlyThis}
                  disabled={installDisabled}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-xl border border-border-default bg-surface-card px-4 py-2.5 text-xs font-semibold text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                >
                  Install Only This
                </button>
              </div>
            ) : (
              <div className="pt-1">
                <button
                  type="button"
                  onClick={handleInstallOnlyThis}
                  disabled={installDisabled}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-accent-primary px-4 py-3 text-sm font-semibold text-accent-contrast-text shadow-xs transition-colors hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                >
                  <Icon name="plus" size={18} />
                  {isBusy
                    ? "Installing..."
                    : branchesLoading
                      ? "Checking branches..."
                      : "Install Now"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
