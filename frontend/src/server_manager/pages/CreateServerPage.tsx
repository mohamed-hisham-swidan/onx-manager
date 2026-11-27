import { useState, useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { useCreateServer } from "@/server_manager/hooks/useServers";
import { SoftwareStep } from "@/server_manager/components/wizard/SoftwareStep";
import { VersionStep } from "@/server_manager/components/wizard/VersionStep";
import { ConfigStep } from "@/server_manager/components/wizard/ConfigStep";
import { PropertiesStep } from "@/server_manager/components/wizard/PropertiesStep";
import { AddonsStep } from "@/server_manager/components/wizard/AddonsStep";
import { ReviewStep } from "@/server_manager/components/wizard/ReviewStep";
import {
  INITIAL_DATA,
  generateNextServerName,
  getWizardSteps,
  type Step,
  type WizardData,
} from "@/server_manager/components/wizard/types";
import { SoftwareInfo, type ProvisioningSnapshot } from "@/server_manager/types";
import { Icon } from "@/components/ui/Icon";
import { ModpackInstallWizardModal } from "@/server_manager/components/p55";
import { ProvisioningProgress } from "@/server_manager/components/ProvisioningProgress";
import { useProvisionProgressStore } from "@/stores/provisionProgressStore";
import { isModpackSupportedLoader } from "@/server_manager/utils/loaderCapabilities";

export function CreateServerPage() {
  const navigate = useNavigate();
  const createServer = useCreateServer();
  const api = useMemo(() => createAuthenticatedApi(), []);

  const [step, setStep] = useState<Step>("software");
  const [softwareList, setSoftwareList] = useState<SoftwareInfo[]>([]);
  const [data, setData] = useState<WizardData>(INITIAL_DATA);
  const [versionsState, setVersionsState] = useState<{
    serverType: string;
    versions: string[];
    error: boolean;
  }>({
    serverType: "",
    versions: [],
    error: false,
  });
  const versionsLoading = versionsState.serverType !== data.serverType;
  const [error, setError] = useState("");
  const [createdId, setCreatedId] = useState("");
  const [createdSnapshot, setCreatedSnapshot] = useState<ProvisioningSnapshot | null>(null);
  const [dockerAvailable, setDockerAvailable] = useState<boolean | null>(null);
  const [advancedEnabled, setAdvancedEnabled] = useState(false);
  const [creationMode, setCreationMode] = useState<"standard" | "modpack">("standard");
  const [isModpackWizardOpen, setIsModpackWizardOpen] = useState(false);
  const [modpackInstalled, setModpackInstalled] = useState(false);
  const [installingAddons, setInstallingAddons] = useState(false);
  const [addonInstallStatus, setAddonInstallStatus] = useState<string | null>(null);
  const [installedAddonTitles, setInstalledAddonTitles] = useState<string[]>([]);
  const [failedAddonTitles, setFailedAddonTitles] = useState<{ title: string; error: string }[]>([]);
  const nameTouchedRef = useRef(false);

  const wizardSteps = useMemo(() => getWizardSteps(data.serverType), [data.serverType]);
  const hasAddonsStep = wizardSteps.some((s) => s.key === "addons");

  const visibleSoftwareList = useMemo(
    () =>
      creationMode === "modpack"
        ? softwareList.filter((s) => isModpackSupportedLoader(s.type))
        : softwareList,
    [creationMode, softwareList]
  );

  const handleSelectCreationMode = (mode: "standard" | "modpack") => {
    setCreationMode(mode);
    if (
      mode === "modpack" &&
      data.serverType &&
      !isModpackSupportedLoader(data.serverType)
    ) {
      setData((d) => ({ ...d, serverType: "", minecraftVersion: "", selectedAddons: [] }));
    }
  };

  useEffect(() => {
    if (!api.listServers) return;
    let cancelled = false;
    api
      .listServers()
      .then((list) => {
        if (cancelled || nameTouchedRef.current) return;
        const names = (Array.isArray(list) ? list : []).map((s) => s.name).filter(Boolean);
        const suggested = generateNextServerName(names);
        setData((d) => (nameTouchedRef.current ? d : { ...d, name: suggested }));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [api]);

  useEffect(() => {
    if (api.getSetupStatus) {
      api
        .getSetupStatus()
        .then((s) => {
          setAdvancedEnabled(s?.advanced_mode_enabled === true);
        })
        .catch(() => {
          setAdvancedEnabled(false);
        });
    }
  }, [api]);

  useEffect(() => {
    api
      .health?.()
      .then((h) => {
        setDockerAvailable(h.docker ?? false);
      })
      .catch(() => {
        setDockerAvailable(false);
      });
  }, [api]);

  useEffect(() => {
    api.listSoftware().then(setSoftwareList).catch(() => {});
  }, [api]);

  useEffect(() => {
    const serverType = data.serverType;
    if (!serverType) return;
    let cancelled = false;
    api
      .listSoftwareVersions(serverType)
      .then((v) => {
        if (cancelled) return;
        setVersionsState({ serverType, versions: v, error: false });
        if (v.length > 0) {
          setData((d) => (d.minecraftVersion ? d : { ...d, minecraftVersion: v[0] }));
        }
      })
      .catch(() => {
        if (cancelled) return;
        setVersionsState({ serverType, versions: [], error: true });
      });
    return () => {
      cancelled = true;
    };
  }, [api, data.serverType]);

  const portFetchedRef = useRef(false);
  useEffect(() => {
    if (step === "config" && !portFetchedRef.current) {
      portFetchedRef.current = true;
      api
        .getAvailablePort()
        .then((r) => setData((d) => (d.port === 25565 ? { ...d, port: r.port } : d)))
        .catch(() => {});
    }
  }, [api, step]);

  const update = (partial: Partial<WizardData>) => {
    if ("name" in partial) {
      nameTouchedRef.current = true;
    }
    setData((d) => ({ ...d, ...partial }));
  };

  const handleCreate = async () => {
    setError("");
    setInstalledAddonTitles([]);
    setFailedAddonTitles([]);
    setAddonInstallStatus(null);
    try {
      const minMem = Math.max(512, Number(data.minMemoryMb) || 1024);
      const maxMem = Math.max(minMem, Number(data.maxMemoryMb) || 2048);
      const result = await createServer.mutateAsync({
        name: data.name,
        server_type: data.serverType,
        minecraft_version: data.minecraftVersion,
        port: Math.max(1, Math.min(65535, Number(data.port) || 25565)),
        max_players: Number(data.maxPlayers) || 20,
        min_memory_mb: minMem,
        max_memory_mb: maxMem,
        motd: data.motd,
        gamemode: data.gamemode,
        difficulty: data.difficulty,
        spawn_protection:
          data.spawnProtection === ""
            ? 16
            : Number.isFinite(Number(data.spawnProtection))
              ? Number(data.spawnProtection)
              : 16,
        pvp: data.pvp,
        enable_command_block: data.enableCommandBlock,
        online_mode: data.onlineMode,
        whitelist: data.whitelist,
        view_distance: Number(data.viewDistance) || 10,
        simulation_distance: Number(data.simulationDistance) || 10,
        provider: "docker",
        mode: data.mode,
      });
      const newServerId = result.server_id as string;
      setCreatedId(newServerId);
      const rawSnap = result.provisioning_progress as ProvisioningSnapshot | undefined;
      if (rawSnap && typeof rawSnap === "object") {
        setCreatedSnapshot(rawSnap);
        useProvisionProgressStore.getState().setSnapshot(newServerId, rawSnap);
      } else {
        setCreatedSnapshot(null);
        useProvisionProgressStore.getState().setProgress(newServerId, {
          stage: "success",
          percent: 100,
          message: "Server created and ready to start",
          timestamp: Date.now(),
        });
      }

      if (data.selectedAddons.length > 0 && api.installFromMarketplace) {
        setInstallingAddons(true);
        const installed: string[] = [];
        const failed: { title: string; error: string }[] = [];

        const useBranchWorkflow = data.mode === "advanced";
        const setupBranch = "setup-initial-addons";
        let branchReady = !useBranchWorkflow;

        if (useBranchWorkflow) {
          setAddonInstallStatus("Creating staging branch for add-ons...");
          try {
            await api.createServerBranch(newServerId, { name: setupBranch });
            branchReady = true;
          } catch (branchErr) {
            const msg =
              branchErr instanceof Error ? branchErr.message : "Failed to create staging branch";
            for (const addon of data.selectedAddons) {
              failed.push({ title: addon.title, error: msg });
            }
          }
        }

        if (branchReady) {
          for (let i = 0; i < data.selectedAddons.length; i += 1) {
            const addon = data.selectedAddons[i];
            setAddonInstallStatus(
              `Installing ${addon.project_type === "mod" ? "mods" : "plugins"} (${i + 1}/${data.selectedAddons.length}): ${addon.title}...`,
            );
            try {
              if (useBranchWorkflow) {
                await api.installFromMarketplace(
                  newServerId,
                  {
                    project_id: addon.project_id,
                    minecraft_version: data.minecraftVersion || undefined,
                  },
                  setupBranch,
                );
              } else {
                await api.installFromMarketplace(newServerId, {
                  project_id: addon.project_id,
                  minecraft_version: data.minecraftVersion || undefined,
                });
              }
              installed.push(addon.title);
            } catch (addonErr) {
              failed.push({
                title: addon.title,
                error: addonErr instanceof Error ? addonErr.message : "Install failed",
              });
            }
          }

          if (useBranchWorkflow && installed.length > 0) {
            setAddonInstallStatus("Committing add-ons and merging into main...");
            try {
              await api.createServerCommit(newServerId, {
                branch_name: setupBranch,
                message: `chore(addons): install initial add-ons (${installed.join(", ")})`,
              });
              await api.mergeServerCommits(newServerId, {
                target_branch_name: "main",
                source_branch_name: setupBranch,
                message: `chore(addons): merge initial add-ons into main (${installed.join(", ")})`,
                force: true,
                force_bypass_protection: true,
                force_reason: "Initial server creation add-on setup",
              });
              await api.deleteServerBranch(newServerId, setupBranch).catch(() => {});
            } catch (mergeErr) {
              const mergeMsg =
                mergeErr instanceof Error
                  ? mergeErr.message
                  : "Failed to merge staging add-ons branch into main";
              for (const title of installed) {
                failed.push({ title, error: mergeMsg });
              }
              installed.length = 0;
            }
          } else if (useBranchWorkflow && installed.length === 0) {
            await api.deleteServerBranch(newServerId, setupBranch).catch(() => {});
          }
        }

        setInstalledAddonTitles(installed);
        setFailedAddonTitles(failed);
        setInstallingAddons(false);
        setAddonInstallStatus(null);
      }

      setStep("done");
      if (creationMode === "modpack") {
        setIsModpackWizardOpen(true);
      }
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.code === "INFRASTRUCTURE_ERROR") {
          const timeoutSeconds =
            e.detail && typeof e.detail === "object" && "timeout_seconds" in e.detail
              ? (e.detail as { timeout_seconds?: number }).timeout_seconds
              : null;
          const msgLower = (e.message || "").toLowerCase();
          if (timeoutSeconds || msgLower.includes("timed out")) {
            setError(
              `Failed to download server software (${data.serverType} ` +
                `${data.minecraftVersion}): the download timed out. ` +
                "Please check your network connection or try again."
            );
          } else if (msgLower.includes("download failed")) {
            setError(
              `Failed to download server software (${data.serverType} ` +
                `${data.minecraftVersion}). The remote download server ` +
                "returned an error. Please try again later or select another version."
            );
          } else {
            setError(
              `Server creation failed due to an infrastructure error ` +
                `(${data.serverType} ${data.minecraftVersion}). Please check logs and try again.`
            );
          }
        } else {
          setError(e.message || "Failed to create server");
        }
      } else {
        setError(e instanceof Error ? e.message : "Failed to create server");
      }
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-text-primary">Create Server</h2>
        <button
          type="button"
          onClick={() => navigate("/servers")}
          className="text-sm text-text-muted hover:text-text-primary cursor-pointer transition-colors"
        >
          &larr; Back to Servers
        </button>
      </div>

      {step !== "done" && (
        <nav aria-label="Server creation steps" className="mb-8 rounded-xl border border-border-default bg-surface-card p-4 shadow-2xs">
          <ol className="flex items-start justify-between">
            {wizardSteps.map((s, i) => {
              const activeIdx = wizardSteps.findIndex((x) => x.key === step);
              const isActive = s.key === step;
              const isCompleted = activeIdx > i;
              const isLast = i === wizardSteps.length - 1;
              return (
                <li key={s.key} className={`flex items-start ${isLast ? "" : "flex-1"}`}>
                  <button
                    type="button"
                    disabled={!isCompleted}
                    aria-current={isActive ? "step" : undefined}
                    onClick={() => {
                      if (isCompleted) setStep(s.key);
                    }}
                    className={`flex flex-col items-center gap-1.5 text-center group shrink-0 ${
                      isCompleted ? "cursor-pointer" : "cursor-default"
                    }`}
                  >
                    <span
                      className={`flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold transition-all ${
                        isActive
                          ? "border-accent-primary bg-accent-primary text-accent-contrast-text ring-4 ring-accent-primary/20"
                          : isCompleted
                            ? "border-accent-primary bg-accent-primary/15 text-accent-primary group-hover:bg-accent-primary/25"
                            : "border-border-default bg-surface-page text-text-muted"
                      }`}
                    >
                      {isCompleted ? <Icon name="check" size={14} /> : i + 1}
                    </span>
                    <span
                      className={`text-[11px] font-medium whitespace-nowrap transition-colors ${
                        isActive
                          ? "text-text-primary font-semibold"
                          : isCompleted
                            ? "text-text-secondary group-hover:text-text-primary"
                            : "text-text-muted"
                      }`}
                    >
                      {s.label}
                    </span>
                  </button>
                  {!isLast && (
                    <div
                      aria-hidden="true"
                      className={`mt-3.5 h-0.5 flex-1 mx-2 rounded-full transition-colors ${
                        activeIdx > i ? "bg-accent-primary" : "bg-border-subtle"
                      }`}
                    />
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      )}

      {error && (
        <div role="alert" className="mb-4 p-3 rounded-xl bg-status-danger-bg border border-status-danger/30 text-sm text-status-danger">
          {error}
        </div>
      )}

      {step === "software" && (
        <div className="space-y-4">
          <div
            data-testid="creation-mode-selector"
            className="grid grid-cols-1 sm:grid-cols-2 gap-3"
          >
            <button
              type="button"
              data-testid="creation-mode-standard"
              aria-pressed={creationMode === "standard"}
              onClick={() => handleSelectCreationMode("standard")}
              className={`text-left rounded-xl border p-4 transition-colors cursor-pointer ${
                creationMode === "standard"
                  ? "border-accent-primary bg-accent-primary/10"
                  : "border-border-default bg-surface-card hover:bg-surface-hover"
              }`}
            >
              <div className="flex items-center gap-2 font-semibold text-sm text-text-primary">
                <Icon name="server" size={16} className="text-accent-primary" />
                <span>Standard Server</span>
              </div>
              <p className="mt-1 text-xs text-text-muted">
                Configure a new Minecraft server and pick any available server software manually.
              </p>
            </button>
            <button
              type="button"
              data-testid="creation-mode-modpack"
              aria-pressed={creationMode === "modpack"}
              onClick={() => handleSelectCreationMode("modpack")}
              className={`text-left rounded-xl border p-4 transition-colors cursor-pointer ${
                creationMode === "modpack"
                  ? "border-accent-primary bg-accent-primary/10"
                  : "border-border-default bg-surface-card hover:bg-surface-hover"
              }`}
            >
              <div className="flex items-center gap-2 font-semibold text-sm text-text-primary">
                <Icon name="modrinth" size={16} className="text-accent-primary" />
                <span>Install Modpack</span>
              </div>
              <p className="mt-1 text-xs text-text-muted">
                Provision a compatible modded server, then upload and install a .mrpack or zip archive automatically.
              </p>
            </button>
          </div>

          <SoftwareStep
            softwareList={visibleSoftwareList}
            selected={data.serverType}
            onSelect={(t) => {
              update({
                serverType: t,
                minecraftVersion: "",
                ...(data.serverType !== t ? { selectedAddons: [] } : {}),
              });
              setStep("version");
            }}
          />
        </div>
      )}

      {step === "version" && (
        <VersionStep
          serverType={data.serverType}
          versions={versionsState.versions}
          loading={versionsLoading}
          error={versionsState.error}
          selected={data.minecraftVersion}
          onSelect={(v) => {
            update({ minecraftVersion: v });
            setStep("config");
          }}
          onBack={() => setStep("software")}
        />
      )}

      {step === "config" && (
        <ConfigStep
          data={data}
          dockerAvailable={dockerAvailable}
          advancedEnabled={advancedEnabled}
          onChange={update}
          onNext={() => setStep("properties")}
          onBack={() => setStep("version")}
        />
      )}

      {step === "properties" && (
        <PropertiesStep
          data={data}
          onChange={update}
          onNext={() => setStep(hasAddonsStep ? "addons" : "review")}
          onBack={() => setStep("config")}
        />
      )}

      {step === "addons" && (
        <AddonsStep
          serverType={data.serverType}
          minecraftVersion={data.minecraftVersion}
          selectedAddons={data.selectedAddons}
          installModpack={creationMode === "modpack"}
          onToggleModpack={(enabled) => setCreationMode(enabled ? "modpack" : "standard")}
          onChangeAddons={(selectedAddons) => update({ selectedAddons })}
          onNext={() => setStep("review")}
          onSkip={() => {
            update({ selectedAddons: [] });
            setStep("review");
          }}
          onBack={() => setStep("properties")}
        />
      )}

      {step === "review" && (
        <ReviewStep
          data={data}
          creating={createServer.isPending || installingAddons}
          installModpack={creationMode === "modpack"}
          statusMessage={addonInstallStatus}
          onCreate={handleCreate}
          onBack={() => setStep(hasAddonsStep ? "addons" : "properties")}
        />
      )}

      {step === "done" && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border-default bg-surface-card px-5 py-4 shadow-xs">
            <div className="flex items-center gap-3">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-status-success-bg text-status-success">
                <Icon name="check" size={18} />
              </span>
              <div>
                <h3 className="text-base font-semibold text-text-primary">
                  {modpackInstalled ? "Server & Modpack Ready" : "Server Created"}
                </h3>
                <p className="text-xs text-text-muted">
                  {creationMode === "modpack"
                    ? modpackInstalled
                      ? `${data.name} is set up and your modpack has been installed.`
                      : `${data.name} has been provisioned. Install your .mrpack or CurseForge modpack below.`
                    : installedAddonTitles.length > 0
                      ? `${data.name} is ready with ${installedAddonTitles.length} installed (${installedAddonTitles.join(", ")}).`
                      : `${data.name} provisioning summary and live setup status.`}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {creationMode === "modpack" && (
                <button
                  type="button"
                  data-testid="open-modpack-installer-btn"
                  onClick={() => setIsModpackWizardOpen(true)}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-accent-primary/40 bg-accent-primary/10 hover:bg-accent-primary/20 text-accent-primary text-xs font-semibold transition-colors cursor-pointer"
                >
                  <Icon name="download" size={14} />
                  {modpackInstalled ? "Re-run Modpack Installer" : "Install Modpack"}
                </button>
              )}
              <button
                type="button"
                onClick={() => navigate("/servers")}
                className="px-4 py-2 rounded-lg border border-border-default text-text-secondary text-xs font-medium hover:bg-surface-hover transition-colors cursor-pointer"
              >
                Back to List
              </button>
            </div>
          </div>

          {failedAddonTitles.length > 0 && (
            <div
              role="alert"
              className="rounded-xl border border-status-warning/30 bg-status-warning-bg px-4 py-3 text-left text-xs text-status-warning"
            >
              <div className="font-semibold mb-1">
                Some optional add-ons could not be installed automatically:
              </div>
              <ul className="list-disc list-inside space-y-0.5">
                {failedAddonTitles.map((f) => (
                  <li key={f.title}>
                    {f.title}: {f.error}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {createdId && (
            <ProvisioningProgress
              serverId={createdId}
              serverName={data.name}
              serverType={data.serverType}
              minecraftVersion={data.minecraftVersion}
              mode={data.mode}
              port={Number(data.port) || 25565}
              initialSnapshot={createdSnapshot}
              enablePollingFallback
              onOpenConsole={() => navigate(`/servers/${createdId}/console`)}
            />
          )}

          {createdId && creationMode === "modpack" && (
            <ModpackInstallWizardModal
              serverId={createdId}
              isOpen={isModpackWizardOpen}
              onClose={() => setIsModpackWizardOpen(false)}
              onInstalled={() => setModpackInstalled(true)}
            />
          )}
        </div>
      )}
    </div>
  );
}
