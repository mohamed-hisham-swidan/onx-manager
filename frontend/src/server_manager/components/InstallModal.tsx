import { useState, useMemo } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { VersionList } from "@/server_manager/components/VersionList";
import { useServersList } from "@/server_manager/hooks/useServers";
import {
  useProjectVersions,
  useInstallFromMarketplace,
} from "@/server_manager/hooks/usePlugins";
import { useLastUsedServerStore } from "@/stores/lastUsedServerStore";
import { useMarketplaceSourceStore } from "@/stores/marketplaceSourceStore";
import { toast } from "@/stores/toastStore";
import type { ServerResponse } from "@/server_manager/types";
import type {
  PluginSearchResultResponse,
  PluginVersionResponse,
  PluginVersionsResponse,
} from "@/types";

import { getServerCapabilities } from "@/server_manager/utils/serverCapabilities";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

function isServerCompatibleWithType(server: ServerResponse, projectType: string): boolean {
  const caps = getServerCapabilities(server.server_type);
  if (projectType === "mod") {
    return caps.supportsMods;
  }
  return caps.supportsPlugins;
}

export interface InstallModalProps {
  project: PluginSearchResultResponse;
  projectType?: "plugin" | "mod";
  onClose: () => void;
  isOpen?: boolean;
}

export function InstallModal({ project, projectType, onClose, isOpen = true }: InstallModalProps) {
  const { data: servers } = useServersList();
  const lastUsedServerId = useLastUsedServerStore((s) => s.lastUsedServerId);
  const setLastUsedServer = useLastUsedServerStore((s) => s.setLastUsedServer);
  const source = useMarketplaceSourceStore((s) => s.source);
  const isModrinth = source === "modrinth";

  const effectiveType = projectType || (project.project_types?.[0] === "mod" ? "mod" : "plugin");

  const compatibleServers = useMemo(() => {
    if (!servers) return [];
    return servers.filter((s) => isServerCompatibleWithType(s, effectiveType));
  }, [servers, effectiveType]);

  const initialServerId = useMemo(() => {
    if (compatibleServers.length === 0) return "";
    const lastUsed = compatibleServers.find((s) => s.server_id === lastUsedServerId);
    if (lastUsed) return lastUsed.server_id;
    return compatibleServers[0].server_id;
  }, [compatibleServers, lastUsedServerId]);

  const [manuallyChosenServerId, setManuallyChosenServerId] = useState<string | null>(null);
  const [isChangingServer, setIsChangingServer] = useState<boolean>(false);

  const selectedServerId = useMemo(() => {
    if (manuallyChosenServerId && compatibleServers.some((s) => s.server_id === manuallyChosenServerId)) {
      return manuallyChosenServerId;
    }
    return initialServerId;
  }, [manuallyChosenServerId, compatibleServers, initialServerId]);

  const selectedServer = useMemo(
    () => compatibleServers.find((s) => s.server_id === selectedServerId),
    [compatibleServers, selectedServerId],
  );

  const versionsQuery = useProjectVersions(selectedServerId, project.project_id, {
    enabled: isModrinth && !!selectedServerId,
  });

  const versionsResponse: PluginVersionsResponse | undefined = versionsQuery.data;
  const recommendedVersion = versionsResponse?.selected ?? versionsResponse?.versions[0] ?? null;

  const [userChosenVersion, setUserChosenVersion] = useState<PluginVersionResponse | null>(null);
  const activeVersion = userChosenVersion ?? recommendedVersion;

  const [isVersionDropdownOpen, setIsVersionDropdownOpen] = useState(false);

  const install = useInstallFromMarketplace(selectedServerId);

  const handleClose = () => {
    if (install.isPending) return;
    onClose();
  };

  function handleSelectServer(serverId: string) {
    setManuallyChosenServerId(serverId);
    setUserChosenVersion(null);
    setIsChangingServer(false);
    setIsVersionDropdownOpen(false);
  }

  function handleSelectVersion(version: PluginVersionResponse) {
    setUserChosenVersion(version);
    setIsVersionDropdownOpen(false);
  }

  function handleInstall() {
    if (!selectedServerId || !activeVersion) return;
    install.mutate(
      {
        project_id: project.project_id,
        version_id: activeVersion.version_id,
      },
      {
        onSuccess: (result) => {
          setLastUsedServer(selectedServerId);
          toast(
            "success",
            "Plugin installed",
            `"${project.title}" ${result.version} installed into ${selectedServer?.name ?? "this server"}.`,
          );
          onClose();
        },
        onError: (err) => toast("error", "Install failed", errorMessage(err)),
      },
    );
  }

  return (
    <Modal
      open={isOpen}
      onClose={handleClose}
      ariaLabel={`Install ${project.title}`}
      size="lg"
      closeOnBackdrop={!install.isPending}
      closeOnEscape={!install.isPending}
      closeButtonAriaLabel="Close modal"
      title={
        <div className="flex items-center gap-3 min-w-0">
          {project.icon_url ? (
            <img
              src={project.icon_url}
              alt=""
              className="h-12 w-12 shrink-0 rounded-xl object-cover border border-gray-200 dark:border-gray-700"
            />
          ) : (
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gray-100 text-gray-400 dark:bg-gray-700 dark:text-gray-500 border border-gray-200 dark:border-gray-600">
              <Icon name="plugin" size={24} />
            </div>
          )}
          <div className="min-w-0">
            <span className="block truncate text-lg font-bold text-gray-900 dark:text-gray-100">
              {project.title}
            </span>
            <p className="text-xs text-gray-500 dark:text-gray-400 font-normal">
              By <span className="font-medium text-gray-700 dark:text-gray-300">{project.author}</span>
            </p>
          </div>
        </div>
      }
    >
      <div data-testid="install-modal">
        <div>
          <button
            type="button"
            onClick={handleInstall}
            disabled={!selectedServerId || !activeVersion || install.isPending || compatibleServers.length === 0}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Icon name="plus" size={18} />
            {install.isPending ? "Installing..." : "Install Now"}
          </button>
        </div>

        <hr className="my-5 border-gray-200 dark:border-gray-700" />

        {compatibleServers.length === 0 ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300">
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
        ) : (
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Target Server
                </label>
                {compatibleServers.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setIsChangingServer(!isChangingServer)}
                    disabled={install.isPending}
                    className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400 disabled:opacity-50"
                  >
                    {isChangingServer ? "Cancel" : "Change Server"}
                  </button>
                )}
              </div>

              {isChangingServer ? (
                <div className="space-y-1.5 max-h-40 overflow-y-auto rounded-xl border border-gray-200 p-2 dark:border-gray-700">
                  {compatibleServers.map((s) => (
                    <button
                      key={s.server_id}
                      type="button"
                      onClick={() => handleSelectServer(s.server_id)}
                      className={`w-full flex items-center justify-between rounded-lg p-2.5 text-left text-xs transition-colors ${
                        selectedServerId === s.server_id
                          ? "bg-blue-50 text-blue-900 font-medium dark:bg-blue-900/30 dark:text-blue-200"
                          : "hover:bg-gray-50 text-gray-700 dark:text-gray-300 dark:hover:bg-gray-700/50"
                      }`}
                    >
                      <div>
                        <span className="font-medium">{s.name}</span>
                        <span className="ml-2 text-gray-500 dark:text-gray-400">
                          ({s.server_type} / {s.minecraft_version})
                        </span>
                      </div>
                      {selectedServerId === s.server_id && (
                        <Icon name="check" size={14} className="text-blue-600 dark:text-blue-400" />
                      )}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs dark:border-gray-700 dark:bg-gray-700/40">
                  <div className="flex items-center gap-2 min-w-0">
                    <Icon name="server" size={16} className="text-gray-500 shrink-0" />
                    <span className="font-semibold text-gray-900 dark:text-gray-100 truncate">
                      {selectedServer?.name || "Select a server"}
                    </span>
                    {selectedServer && (
                      <span className="rounded-full bg-gray-200 px-2 py-0.5 text-[10px] font-medium text-gray-700 dark:bg-gray-600 dark:text-gray-300 shrink-0">
                        {selectedServer.server_type} {selectedServer.minecraft_version}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1.5">
                Version
              </label>

              {versionsQuery.isLoading ? (
                <div className="h-10 w-full animate-pulse rounded-xl bg-gray-100 dark:bg-gray-700" />
              ) : versionsQuery.isError ? (
                <p className="text-xs text-red-600 dark:text-red-400">
                  {errorMessage(versionsQuery.error)}
                </p>
              ) : (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setIsVersionDropdownOpen(!isVersionDropdownOpen)}
                    disabled={install.isPending}
                    className="w-full flex items-center justify-between rounded-xl border border-gray-300 bg-white p-3 text-xs font-medium text-gray-900 shadow-sm transition-colors hover:bg-gray-50 focus:border-blue-500 focus:outline-none dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
                  >
                    <div className="flex items-center gap-2 truncate">
                      {activeVersion ? (
                        <>
                          <span className="font-semibold">{activeVersion.version_number}</span>
                          {activeVersion.version_id === recommendedVersion?.version_id && (
                            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
                              Recommended
                            </span>
                          )}
                          {activeVersion.game_versions.length > 0 && (
                            <span className="text-gray-500 dark:text-gray-400">
                              (MC {activeVersion.game_versions.slice(0, 2).join(", ")})
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-gray-500">Select version...</span>
                      )}
                    </div>
                    <Icon
                      name="chevron-down"
                      size={16}
                      className={`transition-transform ${isVersionDropdownOpen ? "rotate-180" : ""}`}
                    />
                  </button>

                  {isVersionDropdownOpen && versionsResponse && (
                    <div className="mt-2 max-h-60 overflow-y-auto rounded-xl border border-gray-200 bg-white p-2 shadow-lg dark:border-gray-700 dark:bg-gray-800">
                      <VersionList
                        versions={versionsResponse.versions}
                        selectedVersion={activeVersion}
                        notice={versionsResponse.notice}
                        noticeKind={versionsResponse.notice_kind}
                        onSelectVersion={handleSelectVersion}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
