import { useState, useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { createAuthenticatedApi } from "@/services/api";
import { useCreateServer } from "@/server_manager/hooks/useServers";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/ui/Icon";
import { getPlatformInfo } from "@/server_manager/data/platforms";
import { FORGE_EDITION_LABELS, forgeEditionForVersion, isModernForgeVersion } from "@/server_manager/utils/forgeEdition";
import type { ForgeEdition } from "@/server_manager/utils/forgeEdition";
import type { SoftwareInfo } from "@/server_manager/types";

type Step = "software" | "version" | "config" | "properties" | "review" | "done";

const STEPS: { key: Step; label: string }[] = [
  { key: "software", label: "Software" },
  { key: "version", label: "Version" },
  { key: "config", label: "Configuration" },
  { key: "properties", label: "Properties" },
  { key: "review", label: "Review" },
];

interface WizardData {
  serverType: string;
  minecraftVersion: string;
  name: string;
  port: number | "";
  maxPlayers: number | "";
  minMemoryMb: number | "";
  maxMemoryMb: number | "";
  motd: string;
  gamemode: string;
  difficulty: string;
  spawnProtection: number | "";
  pvp: boolean;
  enableCommandBlock: boolean;
  onlineMode: boolean;
  whitelist: boolean;
  viewDistance: number | "";
  simulationDistance: number | "";
}

const INITIAL_DATA: WizardData = {
  serverType: "",
  minecraftVersion: "",
  name: "",
  port: 25565,
  maxPlayers: 20,
  minMemoryMb: 1024,
  maxMemoryMb: 2048,
  motd: "A Minecraft Server",
  gamemode: "survival",
  difficulty: "easy",
  spawnProtection: 16,
  pvp: true,
  enableCommandBlock: false,
  onlineMode: true,
  whitelist: false,
  viewDistance: 10,
  simulationDistance: 10,
};

export function CreateServerPage() {
  const navigate = useNavigate();
  const createServer = useCreateServer();
  const api = useMemo(() => createAuthenticatedApi(), []);

  const [step, setStep] = useState<Step>("software");
  const [softwareList, setSoftwareList] = useState<SoftwareInfo[]>([]);
  const [data, setData] = useState<WizardData>(INITIAL_DATA);
  const [versionsState, setVersionsState] = useState<{ serverType: string; versions: string[]; error: boolean }>({
    serverType: "",
    versions: [],
    error: false,
  });
  const versionsLoading = versionsState.serverType !== data.serverType;
  const [error, setError] = useState("");
  const [createdId, setCreatedId] = useState("");

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
      const minMem = Number(data.minMemoryMb) || 1024;
      const maxMem = Math.max(Number(data.maxMemoryMb) || 2048, minMem);
      const result = await createServer.mutateAsync({
        name: data.name,
        server_type: data.serverType,
        minecraft_version: data.minecraftVersion,
        port: Number(data.port) || 25565,
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
      });
      setCreatedId(result.server_id as string);
      setStep("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create server");
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Create Server</h2>
        <button
          onClick={() => navigate("/servers")}
          className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
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
                  className={`text-xs font-medium text-center py-1.5 rounded ${
                    isActive
                      ? "bg-blue-600 text-white"
                      : isDone
                        ? "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
                        : "bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500"
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
        <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {step === "software" && (
        <SoftwareStep softwareList={softwareList} selected={data.serverType} onSelect={(t) => { update({ serverType: t, minecraftVersion: "" }); setStep("version"); }} />
      )}

      {step === "version" && (
        <VersionStep serverType={data.serverType} versions={versionsState.versions} loading={versionsLoading} error={versionsState.error} selected={data.minecraftVersion} onSelect={(v) => { update({ minecraftVersion: v }); setStep("config"); }} onBack={() => setStep("software")} />
      )}

      {step === "config" && (
        <ConfigStep data={data} onChange={update} onNext={() => setStep("properties")} onBack={() => setStep("version")} />
      )}

      {step === "properties" && (
        <PropertiesStep data={data} onChange={update} onNext={() => setStep("review")} onBack={() => setStep("config")} />
      )}

      {step === "review" && (
        <ReviewStep data={data} creating={createServer.isPending} onCreate={handleCreate} onBack={() => setStep("properties")} />
      )}

      {step === "done" && (
        <div className="text-center py-12">
          <div className="text-4xl mb-4">&#10003;</div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-2">Server Created</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
            {data.name} is being set up. Server JAR has been downloaded and configured.
          </p>
          <div className="flex justify-center space-x-3">
            <button
              onClick={() => navigate(`/servers/${createdId}/console`)}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium"
            >
              Go to Server
            </button>
            <button
              onClick={() => navigate("/servers")}
              className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Back to List
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SoftwareStep({ softwareList, selected, onSelect }: { softwareList: SoftwareInfo[]; selected: string; onSelect: (type: string) => void }) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Choose Server Software</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {softwareList.map((sw) => {
          const platform = getPlatformInfo(sw.type);
          return (
            <button
              key={sw.type}
              onClick={() => onSelect(sw.type)}
              className={`text-left p-4 rounded-xl border-2 transition-all ${
                selected === sw.type
                  ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20 dark:border-blue-400"
                  : "border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 bg-white dark:bg-gray-800"
              }`}
            >
              <div className="flex items-start gap-3">
                <span
                  className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg"
                  style={{ backgroundColor: `${platform.color}22`, color: platform.color }}
                >
                  <Icon name={platform.icon} size={24} />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-gray-900 dark:text-gray-100">{sw.name}</span>
                    {platform.kind && (
                      <span
                        className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                        style={{ backgroundColor: `${platform.color}22`, color: platform.color }}
                      >
                        {platform.kind}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    {platform.description ?? sw.description}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function VersionStep({ serverType, versions, loading, error, selected, onSelect, onBack }: { serverType: string; versions: string[]; loading: boolean; error: boolean; selected: string; onSelect: (v: string) => void; onBack: () => void }) {
  const isForge = serverType === "forge";
  const [edition, setEdition] = useState<ForgeEdition>(() => {
    if (isForge && selected && !isModernForgeVersion(selected)) return "legacy";
    return "modern";
  });

  const visibleVersions = useMemo(() => {
    if (!isForge) return versions;
    return versions.filter((v) =>
      edition === "modern" ? isModernForgeVersion(v) : !isModernForgeVersion(v),
    );
  }, [isForge, versions, edition]);

  if (loading) {
    return (
      <div>
        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Choose Minecraft Version</h3>
        <p className="text-gray-500 dark:text-gray-400">Loading versions...</p>
        <button onClick={onBack} className="mt-4 text-sm text-blue-600 dark:text-blue-400 hover:underline">Back</button>
      </div>
    );
  }

  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Choose Minecraft Version</h3>
      {isForge && (
        <div className="mb-4">
          <div className="inline-flex rounded-lg border border-gray-300 dark:border-gray-600 p-1">
            {(["modern", "legacy"] as const).map((ed) => {
              const meta = FORGE_EDITION_LABELS[ed];
              return (
                <button
                  key={ed}
                  onClick={() => setEdition(ed)}
                  aria-pressed={edition === ed}
                  className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                    edition === ed
                      ? "bg-blue-600 text-white"
                      : "text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
                  }`}
                >
                  {meta.label}
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{FORGE_EDITION_LABELS[edition].description}</p>
        </div>
      )}
      {error ? (
        <ErrorState message="Failed to load versions — try again. If the problem persists, check your connection and refresh the page." />
      ) : visibleVersions.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400">
          {isForge ? `No ${edition} Forge versions available.` : "No versions available."}
        </p>
      ) : (
        <div className="max-h-64 overflow-y-auto grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
          {visibleVersions.map((v) => (
            <button
              key={v}
              onClick={() => onSelect(v)}
              className={`px-3 py-2 rounded-lg text-sm font-medium border transition-all ${
                selected === v
                  ? "border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-400"
                  : "border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:border-blue-300 dark:hover:border-blue-600 bg-white dark:bg-gray-800"
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      )}
      <button onClick={onBack} className="mt-4 text-sm text-blue-600 dark:text-blue-400 hover:underline">Back</button>
    </div>
  );
}

const RAM_PRESETS = [
  { label: "512 MB", min: 512, max: 512 },
  { label: "1 GB", min: 1024, max: 1024 },
  { label: "2 GB", min: 1024, max: 2048 },
  { label: "4 GB", min: 2048, max: 4096 },
  { label: "8 GB", min: 4096, max: 8192 },
  { label: "16 GB", min: 8192, max: 16384 },
  { label: "32 GB", min: 16384, max: 32768 },
  { label: "64 GB", min: 32768, max: 65536 },
  { label: "128 GB", min: 65536, max: 131072 },
];

function RamStepperField({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: number | "";
  placeholder: string;
  onChange: (val: number | "") => void;
}) {
  const gbDisplay =
    typeof value === "number" && value > 0
      ? value >= 1024
        ? `${(value / 1024).toFixed(value % 1024 === 0 ? 0 : 1)} GB`
        : `${value} MB`
      : "";

  const stepBy = (delta: number) => {
    const base = typeof value === "number" && value > 0 ? value : Number(placeholder) || 1024;
    const next = Math.max(512, base + delta);
    onChange(next);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider">
          {label}
        </label>
        {gbDisplay && (
          <span className="text-[11px] font-bold text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/30 px-2 py-0.5 rounded-full border border-blue-200 dark:border-blue-800">
            {gbDisplay}
          </span>
        )}
      </div>
      <div className="relative flex items-stretch rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500 shadow-sm overflow-hidden">
        <button
          type="button"
          onClick={() => stepBy(-512)}
          aria-label={`Decrease ${label} by 512 MB`}
          className="flex items-center justify-center px-3 text-xs font-bold text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 active:bg-gray-200 dark:active:bg-gray-600 border-r border-gray-200 dark:border-gray-700 transition-colors select-none"
        >
          <span className="text-gray-400 dark:text-gray-500 mr-0.5">▼</span> -512
        </button>
        <div className="relative flex-1 flex items-center">
          <input
            type="number"
            step={512}
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
            className="w-full h-10 px-3 text-sm text-center font-semibold text-gray-900 dark:text-gray-100 bg-transparent focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
          />
          <span className="absolute right-3 text-xs text-gray-400 dark:text-gray-500 pointer-events-none font-medium">
            MB
          </span>
        </div>
        <button
          type="button"
          onClick={() => stepBy(512)}
          aria-label={`Increase ${label} by 512 MB`}
          className="flex items-center justify-center px-3 text-xs font-bold text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 active:bg-gray-200 dark:active:bg-gray-600 border-l border-gray-200 dark:border-gray-700 transition-colors select-none"
        >
          +512 <span className="text-gray-400 dark:text-gray-500 ml-0.5">▲</span>
        </button>
      </div>
    </div>
  );
}

function ConfigStep({ data, onChange, onNext, onBack }: { data: WizardData; onChange: (d: Partial<WizardData>) => void; onNext: () => void; onBack: () => void }) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Server Configuration</h3>
      <div className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Server Name</label>
          <input
            value={data.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="My Awesome Server"
            required
            className="w-full px-3.5 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Port</label>
            <input
              type="number"
              value={data.port}
              placeholder="25565"
              onChange={(e) => onChange({ port: e.target.value === "" ? "" : Number(e.target.value) })}
              className="w-full px-3.5 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Max Players</label>
            <input
              type="number"
              value={data.maxPlayers}
              placeholder="20"
              onChange={(e) => onChange({ maxPlayers: e.target.value === "" ? "" : Number(e.target.value) })}
              className="w-full px-3.5 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm"
            />
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-800/40 p-4 space-y-3.5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <RamStepperField
              label="Min RAM"
              value={data.minMemoryMb}
              placeholder="1024"
              onChange={(v) => onChange({ minMemoryMb: v })}
            />
            <RamStepperField
              label="Max RAM"
              value={data.maxMemoryMb}
              placeholder="2048"
              onChange={(v) => onChange({ maxMemoryMb: v })}
            />
          </div>
          <div>
            <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-2 uppercase tracking-wider">
              Quick Memory Presets
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-9 gap-1.5">
              {RAM_PRESETS.map((preset) => {
                const isActive = data.minMemoryMb === preset.min && data.maxMemoryMb === preset.max;
                return (
                  <button
                    type="button"
                    key={preset.label}
                    onClick={() => onChange({ minMemoryMb: preset.min, maxMemoryMb: preset.max })}
                    className={`py-1.5 px-2 text-xs font-semibold rounded-lg border transition-all text-center ${
                      isActive
                        ? "bg-blue-600 text-white border-blue-600 shadow-sm ring-2 ring-blue-500/30"
                        : "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:border-blue-400 dark:hover:border-blue-500 hover:bg-blue-50/50 dark:hover:bg-blue-900/20"
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">MOTD</label>
          <input
            value={data.motd}
            onChange={(e) => onChange({ motd: e.target.value })}
            className="w-full px-3.5 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm"
          />
        </div>
      </div>
      <div className="flex justify-between mt-6">
        <button onClick={onBack} className="text-sm text-blue-600 dark:text-blue-400 hover:underline">Back</button>
        <button
          onClick={onNext}
          disabled={!data.name.trim()}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}

function PropertiesStep({ data, onChange, onNext, onBack }: { data: WizardData; onChange: (d: Partial<WizardData>) => void; onNext: () => void; onBack: () => void }) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Game Properties</h3>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Gamemode</label>
            <select
              value={data.gamemode}
              onChange={(e) => onChange({ gamemode: e.target.value })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="survival">Survival</option>
              <option value="creative">Creative</option>
              <option value="adventure">Adventure</option>
              <option value="spectator">Spectator</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Difficulty</label>
            <select
              value={data.difficulty}
              onChange={(e) => onChange({ difficulty: e.target.value })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="peaceful">Peaceful</option>
              <option value="easy">Easy</option>
              <option value="normal">Normal</option>
              <option value="hard">Hard</option>
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">View Distance</label>
            <input
              type="number"
              value={data.viewDistance}
              placeholder="10"
              onChange={(e) => onChange({ viewDistance: e.target.value === "" ? "" : Number(e.target.value) })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Simulation Distance</label>
            <input
              type="number"
              value={data.simulationDistance}
              placeholder="10"
              onChange={(e) => onChange({ simulationDistance: e.target.value === "" ? "" : Number(e.target.value) })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Spawn Protection</label>
            <input
              type="number"
              value={data.spawnProtection}
              placeholder="16"
              onChange={(e) => onChange({ spawnProtection: e.target.value === "" ? "" : Number(e.target.value) })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <div className="space-y-3">
          {([
            ["PVP", "pvp"],
            ["Enable Command Blocks", "enableCommandBlock"],
            ["Online Mode", "onlineMode"],
            ["Whitelist", "whitelist"],
          ] as const).map(([label, key]) => (
            <label key={key} className="flex items-center space-x-2">
              <input
                type="checkbox"
                checked={data[key]}
                onChange={(e) => onChange({ [key]: e.target.checked } as Partial<WizardData>)}
                className="rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-700 dark:text-gray-300">{label}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="flex justify-between mt-6">
        <button onClick={onBack} className="text-sm text-blue-600 dark:text-blue-400 hover:underline">Back</button>
        <button onClick={onNext} className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium">
          Next
        </button>
      </div>
    </div>
  );
}

function ReviewStep({ data, creating, onCreate, onBack }: { data: WizardData; creating: boolean; onCreate: () => void; onBack: () => void }) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Review &amp; Create</h3>
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-2 text-sm">
        {[
          ["Name", data.name],
          ["Software", data.serverType],
          ...(data.serverType === "forge"
            ? [["Forge Edition", FORGE_EDITION_LABELS[forgeEditionForVersion(data.minecraftVersion)].label] as [string, string]]
            : []),
          ["Version", data.minecraftVersion],
          ["Port", String(data.port || 25565)],
          ["Max Players", String(data.maxPlayers || 20)],
          ["RAM", `${data.minMemoryMb || 1024} - ${data.maxMemoryMb || 2048} MB`],
          ["MOTD", data.motd],
          ["Gamemode", data.gamemode],
          ["Difficulty", data.difficulty],
          ["PVP", data.pvp ? "Yes" : "No"],
          ["Online Mode", data.onlineMode ? "Yes" : "No"],
          ["Whitelist", data.whitelist ? "Yes" : "No"],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between">
            <span className="text-gray-500 dark:text-gray-400">{label}</span>
            <span className="text-gray-900 dark:text-gray-100 font-medium">{value}</span>
          </div>
        ))}
      </div>
      <div className="flex justify-between mt-6">
        <button onClick={onBack} className="text-sm text-blue-600 dark:text-blue-400 hover:underline">Back</button>
        <button
          onClick={onCreate}
          disabled={creating}
          className="px-6 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium disabled:opacity-50"
        >
          {creating ? "Creating..." : "Create Server"}
        </button>
      </div>
    </div>
  );
}
