import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { createAuthenticatedApi } from "@/services/api";
import { useCreateServer } from "@/server_manager/hooks/useServers";
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
  port: number;
  maxPlayers: number;
  minMemoryMb: number;
  maxMemoryMb: number;
  motd: string;
  gamemode: string;
  difficulty: string;
  spawnProtection: number;
  pvp: boolean;
  enableCommandBlock: boolean;
  onlineMode: boolean;
  whitelist: boolean;
  viewDistance: number;
  simulationDistance: number;
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
  const api = createAuthenticatedApi();

  const [step, setStep] = useState<Step>("software");
  const [softwareList, setSoftwareList] = useState<SoftwareInfo[]>([]);
  const [versions, setVersions] = useState<string[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(true);
  const [versionsError, setVersionsError] = useState(false);
  const [error, setError] = useState("");
  const [createdId, setCreatedId] = useState("");
  const [data, setData] = useState<WizardData>(INITIAL_DATA);

  useEffect(() => {
    api.listSoftware().then(setSoftwareList).catch(() => {});
  }, []);

  useEffect(() => {
    if (!data.serverType) return;
    setVersionsLoading(true);
    setVersionsError(false);
    api
      .listSoftwareVersions(data.serverType)
      .then((v) => {
        setVersions(v);
        setVersionsLoading(false);
        if (v.length > 0 && !data.minecraftVersion) {
          setData((d) => ({ ...d, minecraftVersion: v[0] }));
        }
      })
      .catch(() => {
        setVersions([]);
        setVersionsError(true);
        setVersionsLoading(false);
      });
  }, [data.serverType]);

  useEffect(() => {
    if (step === "config" && !data.port) {
      api.getAvailablePort().then((r) => setData((d) => ({ ...d, port: r.port }))).catch(() => {});
    }
  }, [step]);

  const update = (partial: Partial<WizardData>) => setData((d) => ({ ...d, ...partial }));

  const handleCreate = async () => {
    setError("");
    try {
      const result = await createServer.mutateAsync({
        name: data.name,
        server_type: data.serverType,
        minecraft_version: data.minecraftVersion,
        port: data.port,
        max_players: data.maxPlayers,
        min_memory_mb: data.minMemoryMb,
        max_memory_mb: data.maxMemoryMb,
        motd: data.motd,
        gamemode: data.gamemode,
        difficulty: data.difficulty,
        spawn_protection: data.spawnProtection,
        pvp: data.pvp,
        enable_command_block: data.enableCommandBlock,
        online_mode: data.onlineMode,
        whitelist: data.whitelist,
        view_distance: data.viewDistance,
        simulation_distance: data.simulationDistance,
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
        <SoftwareStep softwareList={softwareList} selected={data.serverType} onSelect={(t) => { update({ serverType: t }); setStep("version"); }} />
      )}

      {step === "version" && (
        <VersionStep versions={versions} loading={versionsLoading} error={versionsError} selected={data.minecraftVersion} onSelect={(v) => { update({ minecraftVersion: v }); setStep("config"); }} onBack={() => setStep("software")} />
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
              onClick={() => navigate(`/servers/${createdId}`)}
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
        {softwareList.map((sw) => (
          <button
            key={sw.type}
            onClick={() => onSelect(sw.type)}
            className={`text-left p-4 rounded-xl border-2 transition-all ${
              selected === sw.type
                ? "border-blue-500 bg-blue-50 dark:bg-blue-900/20 dark:border-blue-400"
                : "border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 bg-white dark:bg-gray-800"
            }`}
          >
            <div className="font-semibold text-gray-900 dark:text-gray-100">{sw.name}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{sw.description}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

function VersionStep({ versions, loading, error, selected, onSelect, onBack }: { versions: string[]; loading: boolean; error: boolean; selected: string; onSelect: (v: string) => void; onBack: () => void }) {
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
      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-400">
          Failed to load versions — try again. If the problem persists, check your connection and refresh the page.
        </div>
      ) : versions.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400">No versions available.</p>
      ) : (
        <div className="max-h-64 overflow-y-auto grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
          {versions.map((v) => (
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

function ConfigStep({ data, onChange, onNext, onBack }: { data: WizardData; onChange: (d: Partial<WizardData>) => void; onNext: () => void; onBack: () => void }) {
  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Server Configuration</h3>
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Server Name</label>
          <input
            value={data.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="My Awesome Server"
            required
            className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Port</label>
            <input
              type="number"
              value={data.port}
              onChange={(e) => onChange({ port: Number(e.target.value) || 25565 })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Max Players</label>
            <input
              type="number"
              value={data.maxPlayers}
              onChange={(e) => onChange({ maxPlayers: Number(e.target.value) || 20 })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Min RAM (MB)</label>
            <input
              type="number"
              value={data.minMemoryMb}
              onChange={(e) => onChange({ minMemoryMb: Number(e.target.value) || 1024 })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Max RAM (MB)</label>
            <input
              type="number"
              value={data.maxMemoryMb}
              onChange={(e) => onChange({ maxMemoryMb: Number(e.target.value) || 2048 })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">MOTD</label>
          <input
            value={data.motd}
            onChange={(e) => onChange({ motd: e.target.value })}
            className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
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
              onChange={(e) => onChange({ viewDistance: Number(e.target.value) || 10 })}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Simulation Distance</label>
            <input
              type="number"
              value={data.simulationDistance}
              onChange={(e) => onChange({ simulationDistance: Number(e.target.value) || 10 })}
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
              onChange={(e) => onChange({ spawnProtection: Number(e.target.value) || 16 })}
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
                checked={(data as any)[key] as boolean}
                onChange={(e) => onChange({ [key]: e.target.checked } as any)}
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
          ["Version", data.minecraftVersion],
          ["Port", String(data.port)],
          ["Max Players", String(data.maxPlayers)],
          ["RAM", `${data.minMemoryMb} - ${data.maxMemoryMb} MB`],
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
