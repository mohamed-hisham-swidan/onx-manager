import { useState, useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { useCreateServer } from "@/server_manager/hooks/useServers";
import { SoftwareStep } from "@/server_manager/components/wizard/SoftwareStep";
import { VersionStep } from "@/server_manager/components/wizard/VersionStep";
import { ConfigStep } from "@/server_manager/components/wizard/ConfigStep";
import { PropertiesStep } from "@/server_manager/components/wizard/PropertiesStep";
import { ReviewStep } from "@/server_manager/components/wizard/ReviewStep";
import {
  STEPS,
  INITIAL_DATA,
  type Step,
  type WizardData,
} from "@/server_manager/components/wizard/types";
import { SoftwareInfo } from "@/server_manager/types";
import { Icon } from "@/components/ui/Icon";

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
  const [dockerAvailable, setDockerAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    api
      .health?.()
      .then((h) => {
        const isDocker = h.docker ?? false;
        setDockerAvailable(isDocker);
        if (!isDocker) {
          setData((d) => (d.provider === "docker" ? { ...d, provider: "" } : d));
        }
      })
      .catch(() => {
        setDockerAvailable(false);
        setData((d) => (d.provider === "docker" ? { ...d, provider: "" } : d));
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

  const update = (partial: Partial<WizardData>) => setData((d) => ({ ...d, ...partial }));

  const handleCreate = async () => {
    setError("");
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
        spawn_protection: Number(data.spawnProtection) || 16,
        pvp: data.pvp,
        enable_command_block: data.enableCommandBlock,
        online_mode: data.onlineMode,
        whitelist: data.whitelist,
        view_distance: Number(data.viewDistance) || 10,
        simulation_distance: Number(data.simulationDistance) || 10,
        provider: data.provider || undefined,
        mode: data.mode,
      });
      setCreatedId(result.server_id as string);
      setStep("done");
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
        <div className="flex mb-8 space-x-1">
          {STEPS.map((s, i) => {
            const idx = STEPS.findIndex((x) => x.key === step);
            const isActive = s.key === step;
            const isDone = idx >= i;
            return (
              <div key={s.key} className="flex-1">
                <div
                  className={`text-xs font-medium text-center py-1.5 rounded transition-colors ${
                    isActive
                      ? "bg-accent-primary text-white shadow-xs"
                      : isDone
                        ? "bg-accent-primary/20 text-accent-primary"
                        : "bg-surface-hover text-text-muted"
                  }`}
                >
                  {s.label}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {error && (
        <div role="alert" className="mb-4 p-3 rounded-xl bg-status-danger-bg border border-status-danger/30 text-sm text-status-danger">
          {error}
        </div>
      )}

      {step === "software" && (
        <SoftwareStep
          softwareList={softwareList}
          selected={data.serverType}
          onSelect={(t) => {
            update({ serverType: t, minecraftVersion: "" });
            setStep("version");
          }}
        />
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
          onChange={update}
          onNext={() => setStep("properties")}
          onBack={() => setStep("version")}
        />
      )}

      {step === "properties" && (
        <PropertiesStep
          data={data}
          onChange={update}
          onNext={() => setStep("review")}
          onBack={() => setStep("config")}
        />
      )}

      {step === "review" && (
        <ReviewStep
          data={data}
          creating={createServer.isPending}
          onCreate={handleCreate}
          onBack={() => setStep("properties")}
        />
      )}

      {step === "done" && (
        <div className="text-center py-12 bg-surface-card rounded-xl border border-border-default p-8 shadow-xs">
          <Icon name="check" size={36} className="mx-auto mb-4 text-status-success" />
          <h3 className="text-lg font-semibold text-text-primary mb-2">Server Created</h3>
          <p className="text-sm text-text-muted mb-6">
            {data.name} is being set up. Server JAR has been downloaded and configured.
          </p>
          <div className="flex justify-center space-x-3">
            <button
              type="button"
              onClick={() => navigate(`/servers/${createdId}/console`)}
              className="px-5 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-white text-sm font-semibold transition-colors shadow-xs cursor-pointer"
            >
              Go to Server
            </button>
            <button
              type="button"
              onClick={() => navigate("/servers")}
              className="px-5 py-2 rounded-lg border border-border-default text-text-secondary text-sm font-medium hover:bg-surface-hover transition-colors cursor-pointer"
            >
              Back to List
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
