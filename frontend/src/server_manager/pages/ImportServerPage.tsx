import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createAuthenticatedApi } from "@/services/api";
import type { ScanResult } from "@/server_manager/types";

export function ImportServerPage() {
  const navigate = useNavigate();
  const api = createAuthenticatedApi();

  const [path, setPath] = useState("");
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [createdId, setCreatedId] = useState("");
  const [step, setStep] = useState<"input" | "review" | "done">("input");

  const handleScan = async () => {
    if (!path.trim()) return;
    setError("");
    setScanning(true);
    try {
      const result = await api.scanDirectory(path.trim());
      setScanResult(result);
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to scan directory");
    } finally {
      setScanning(false);
    }
  };

  const handleImport = async () => {
    if (!scanResult) return;
    setError("");
    setImporting(true);
    try {
      const result = await api.importServer({
        source_path: scanResult.path,
        name: scanResult.name,
        server_type: scanResult.server_type,
        minecraft_version: scanResult.minecraft_version || "1.20.4",
        port: scanResult.properties.port,
        motd: scanResult.properties.motd,
        max_players: scanResult.properties.max_players,
        gamemode: scanResult.properties.gamemode,
        difficulty: scanResult.properties.difficulty,
        spawn_protection: scanResult.properties.spawn_protection,
        pvp: scanResult.properties.pvp,
        enable_command_block: scanResult.properties.enable_command_block,
        online_mode: scanResult.properties.online_mode,
        whitelist: scanResult.properties.whitelist,
        view_distance: scanResult.properties.view_distance,
        simulation_distance: scanResult.properties.simulation_distance,
      });
      setCreatedId(result.server_id as string);
      setStep("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to import server");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Import Server</h2>
        <button
          onClick={() => navigate("/servers")}
          className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
        >
          &larr; Back to Servers
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {step === "input" && (
        <div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">Server Directory</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
            Enter the absolute path to an existing Minecraft server directory.
            The application will scan it and detect the software, version, and configuration automatically.
          </p>
          <div className="flex gap-2">
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/opt/minecraft/survival"
              className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={handleScan}
              disabled={!path.trim() || scanning}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium disabled:opacity-50"
            >
              {scanning ? "Scanning..." : "Scan"}
            </button>
          </div>
        </div>
      )}

      {step === "review" && scanResult && (
        <div className="space-y-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Scan Results</h3>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Name</span>
              <span className="text-gray-900 dark:text-gray-100 font-medium">{scanResult.name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Software</span>
              <span className="text-gray-900 dark:text-gray-100 font-medium capitalize">{scanResult.server_type}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Version</span>
              <span className="text-gray-900 dark:text-gray-100 font-medium">{scanResult.minecraft_version || "Unknown"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Path</span>
              <span className="text-gray-900 dark:text-gray-100 font-mono text-xs">{scanResult.path}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">JAR</span>
              <span className="text-gray-900 dark:text-gray-100 font-medium">{scanResult.server_jar || "None"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">EULA</span>
              <span className={scanResult.eula_accepted ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
                {scanResult.eula_accepted ? "Accepted" : "Not Accepted"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">Port</span>
              <span className="text-gray-900 dark:text-gray-100 font-medium">{scanResult.properties.port}</span>
            </div>
          </div>

          {scanResult.plugins.length > 0 && (
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-gray-100 mb-2 text-sm">Plugins ({scanResult.plugins.length})</h4>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden text-sm">
                {scanResult.plugins.map((p) => (
                  <div key={p.filename} className="px-4 py-2 border-b border-gray-100 dark:border-gray-700/50 flex justify-between">
                    <span className="text-gray-900 dark:text-gray-100">{p.name}</span>
                    <span className="text-gray-500 dark:text-gray-400">{p.version || "—"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {scanResult.mods.length > 0 && (
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-gray-100 mb-2 text-sm">Mods ({scanResult.mods.length})</h4>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden text-sm">
                {scanResult.mods.map((m) => (
                  <div key={m.filename} className="px-4 py-2 border-b border-gray-100 dark:border-gray-700/50 flex justify-between">
                    <span className="text-gray-900 dark:text-gray-100">{m.name}</span>
                    <span className="text-gray-500 dark:text-gray-400">{m.version || "—"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {scanResult.worlds.length > 0 && (
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-gray-100 mb-2 text-sm">Worlds ({scanResult.worlds.length})</h4>
              <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden text-sm">
                {scanResult.worlds.map((w) => (
                  <div key={w.name} className="px-4 py-2 border-b border-gray-100 dark:border-gray-700/50 flex justify-between">
                    <span className="text-gray-900 dark:text-gray-100">{w.name}</span>
                    <span className="text-gray-500 dark:text-gray-400">{(w.size_bytes / 1048576).toFixed(1)} MB</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-between">
            <button onClick={() => setStep("input")} className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
              Back
            </button>
            <button
              onClick={handleImport}
              disabled={importing}
              className="px-6 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium disabled:opacity-50"
            >
              {importing ? "Importing..." : "Import Server"}
            </button>
          </div>
        </div>
      )}

      {step === "done" && (
        <div className="text-center py-12">
          <div className="text-4xl mb-4">&#10003;</div>
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-2">Server Imported</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
            {scanResult?.name} has been imported. The original files were not modified.
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