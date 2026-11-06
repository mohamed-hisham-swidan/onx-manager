import { useState, useRef, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { createAuthenticatedApi } from "@/services/api";
import type { ScanResult } from "@/server_manager/types";
import { Icon } from "@/components/ui/Icon";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

export function ImportServerPage() {
  const navigate = useNavigate();
  const api = createAuthenticatedApi();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<"upload" | "path">("upload");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const [path, setPath] = useState("");
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [createdId, setCreatedId] = useState("");
  const [step, setStep] = useState<"input" | "review" | "done">("input");

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (!file.name.toLowerCase().endsWith(".zip")) {
        setError("Please select a .zip archive");
        return;
      }
      setSelectedFile(file);
      setError("");
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      if (!file.name.toLowerCase().endsWith(".zip")) {
        setError("Please select a .zip archive");
        return;
      }
      setSelectedFile(file);
      setError("");
    }
  };

  const handleUploadAndScan = async () => {
    if (!selectedFile) return;
    setError("");
    setUploading(true);
    setUploadProgress(0);
    try {
      const result = await api.uploadImportZip(selectedFile, (percent) => {
        setUploadProgress(percent);
      });
      setScanResult(result);
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to upload and scan archive");
    } finally {
      setUploading(false);
    }
  };

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
        <h2 className="text-xl font-semibold text-text-primary">Import Server</h2>
        <button
          onClick={() => navigate("/servers")}
          className="text-sm text-text-muted hover:text-text-primary"
        >
          &larr; Back to Servers
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-status-danger-bg border border-status-danger-border text-sm text-status-danger">
          {error}
        </div>
      )}

      {step === "input" && (
        <div className="space-y-6">
          <div className="flex border-b border-border-subtle">
            <button
              type="button"
              onClick={() => setMode("upload")}
              className={`pb-3 px-4 text-sm font-medium border-b-2 transition-colors ${
                mode === "upload"
                  ? "border-accent-primary text-accent-primary"
                  : "border-transparent text-text-muted hover:text-text-primary"
              }`}
            >
              Upload Archive (.zip)
            </button>
            <button
              type="button"
              onClick={() => setMode("path")}
              className={`pb-3 px-4 text-sm font-medium border-b-2 transition-colors ${
                mode === "path"
                  ? "border-accent-primary text-accent-primary"
                  : "border-transparent text-text-muted hover:text-text-primary"
              }`}
            >
              Host Path (Advanced)
            </button>
          </div>

          {mode === "upload" && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-semibold text-text-primary mb-1">
                  Upload Server Archive
                </h3>
                <p className="text-sm text-text-muted">
                  Select or drag-and-drop a compressed .zip archive of your Minecraft server from your device.
                  The archive will be safely uploaded, unpacked, and scanned on the server.
                </p>
              </div>

              <input
                type="file"
                aria-label="Choose server zip archive file"
                ref={fileInputRef}
                accept=".zip"
                onChange={handleFileSelect}
                className="hidden"
                data-testid="zip-file-input"
              />

              {!selectedFile ? (
                <div
                  role="button"
                  tabIndex={0}
                  aria-label="Upload server zip archive"
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      fileInputRef.current?.click();
                    }
                  }}
                  className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-border-focus ${
                    isDragging
                      ? "border-accent-primary bg-status-info-bg"
                      : "border-border-default hover:border-border-strong bg-surface-muted/50"
                  }`}
                >
                  <div className="mx-auto w-12 h-12 mb-3 flex items-center justify-center rounded-full bg-surface-muted text-text-muted">
                    <svg className="w-6 h-6 text-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <p className="text-sm font-medium text-text-primary">
                    Drag and drop your server .zip archive here, or <span className="text-accent-primary underline">browse</span>
                  </p>
                  <p className="text-xs text-text-muted mt-1">
                    Supports world files, plugins, mods, and configuration. Large archives supported.
                  </p>
                </div>
              ) : (
                <div className="bg-surface-card rounded-xl border border-border-subtle p-5 space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-3 truncate">
                      <div className="w-10 h-10 rounded-lg bg-status-info-bg flex items-center justify-center shrink-0">
                        <svg className="w-5 h-5 text-status-info" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                      </div>
                      <div className="truncate">
                        <p className="text-sm font-medium text-text-primary truncate">
                          {selectedFile.name}
                        </p>
                        <p className="text-xs text-text-muted">
                          {formatBytes(selectedFile.size)}
                        </p>
                      </div>
                    </div>
                    {!uploading && (
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedFile(null);
                          setUploadProgress(0);
                        }}
                        className="text-xs text-status-danger hover:underline shrink-0 ml-3"
                      >
                        Remove
                      </button>
                    )}
                  </div>

                  {uploading && (
                    <div className="space-y-2">
                      <div className="flex justify-between text-xs text-text-secondary">
                        <span>{uploadProgress < 100 ? `Uploading archive (${uploadProgress}%)...` : "Extracting archive & scanning on host..."}</span>
                        <span>{uploadProgress}%</span>
                      </div>
                      <div className="w-full bg-surface-muted rounded-full h-2 overflow-hidden">
                        <div
                          className="bg-accent-primary h-2 rounded-full transition-all duration-200"
                          style={{ width: `${uploadProgress}%` }}
                        />
                      </div>
                    </div>
                  )}

                  <div className="flex justify-end pt-2">
                    <button
                      type="button"
                      onClick={handleUploadAndScan}
                      disabled={uploading}
                      className="px-5 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium disabled:opacity-50 flex items-center gap-2"
                    >
                      {uploading ? (
                        <>
                          <svg className="animate-spin h-4 w-4 text-accent-contrast-text" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                          </svg>
                          <span>{uploadProgress < 100 ? "Uploading..." : "Scanning..."}</span>
                        </>
                      ) : (
                        "Upload & Scan Server"
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {mode === "path" && (
            <div>
              <h3 className="text-lg font-semibold text-text-primary mb-2">Server Directory</h3>
              <p className="text-sm text-text-muted mb-4">
                Enter the absolute path to an existing Minecraft server directory on the host machine.
                The application will scan it and detect the software, version, and configuration automatically.
              </p>
              <div className="flex gap-2">
                <input
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  placeholder="/opt/minecraft/survival"
                  className="flex-1 px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-border-focus"
                />
                <button
                  onClick={handleScan}
                  disabled={!path.trim() || scanning}
                  className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium disabled:opacity-50"
                >
                  {scanning ? "Scanning..." : "Scan"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {step === "review" && scanResult && (
        <div className="space-y-6">
          <h3 className="text-lg font-semibold text-text-primary">Scan Results</h3>

          <div className="bg-surface-card rounded-xl border border-border-subtle p-4 space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-text-muted">Name</span>
              <span className="text-text-primary font-medium">{scanResult.name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Software</span>
              <span className="text-text-primary font-medium capitalize">{scanResult.server_type}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Version</span>
              <span className="text-text-primary font-medium">{scanResult.minecraft_version || "Unknown"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Path</span>
              <span className="text-text-primary font-mono text-xs">{scanResult.path}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">JAR</span>
              <span className="text-text-primary font-medium">{scanResult.server_jar || "None"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">EULA</span>
              <span className={scanResult.eula_accepted ? "text-status-success font-medium" : "text-status-danger font-medium"}>
                {scanResult.eula_accepted ? "Accepted" : "Not Accepted"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Port</span>
              <span className="text-text-primary font-medium">{scanResult.properties.port}</span>
            </div>
          </div>

          {scanResult.plugins.length > 0 && (
            <div>
              <h4 className="font-semibold text-text-primary mb-2 text-sm">Plugins ({scanResult.plugins.length})</h4>
              <div className="bg-surface-card rounded-xl border border-border-subtle overflow-hidden text-sm">
                {scanResult.plugins.map((p) => (
                  <div key={p.filename} className="px-4 py-2 border-b border-border-subtle last:border-b-0 flex justify-between">
                    <span className="text-text-primary">{p.name}</span>
                    <span className="text-text-muted">{p.version || "—"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {scanResult.mods.length > 0 && (
            <div>
              <h4 className="font-semibold text-text-primary mb-2 text-sm">Mods ({scanResult.mods.length})</h4>
              <div className="bg-surface-card rounded-xl border border-border-subtle overflow-hidden text-sm">
                {scanResult.mods.map((m) => (
                  <div key={m.filename} className="px-4 py-2 border-b border-border-subtle last:border-b-0 flex justify-between">
                    <span className="text-text-primary">{m.name}</span>
                    <span className="text-text-muted">{m.version || "—"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {scanResult.worlds.length > 0 && (
            <div>
              <h4 className="font-semibold text-text-primary mb-2 text-sm">Worlds ({scanResult.worlds.length})</h4>
              <div className="bg-surface-card rounded-xl border border-border-subtle overflow-hidden text-sm">
                {scanResult.worlds.map((w) => (
                  <div key={w.name} className="px-4 py-2 border-b border-border-subtle last:border-b-0 flex justify-between">
                    <span className="text-text-primary">{w.name}</span>
                    <span className="text-text-muted">{(w.size_bytes / 1048576).toFixed(1)} MB</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-between">
            <button onClick={() => setStep("input")} className="text-sm text-accent-primary hover:underline">
              Back
            </button>
            <button
              onClick={handleImport}
              disabled={importing}
              className="px-6 py-2 rounded-lg bg-status-success hover:opacity-90 text-accent-contrast-text text-sm font-medium disabled:opacity-50"
            >
              {importing ? "Importing..." : "Import Server"}
            </button>
          </div>
        </div>
      )}

      {step === "done" && (
        <div className="text-center py-12">
          <Icon name="check" size={36} className="mx-auto mb-4 text-status-success" />
          <h3 className="text-lg font-semibold text-text-primary mb-2">Server Imported</h3>
          <p className="text-sm text-text-muted mb-6">
            {scanResult?.name} has been imported. The original files were not modified.
          </p>
          <div className="flex justify-center space-x-3">
            <button
              onClick={() => navigate(`/servers/${createdId}/console`)}
              className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium"
            >
              Go to Server
            </button>
            <button
              onClick={() => navigate("/servers")}
              className="px-4 py-2 rounded-lg border border-border-default text-text-secondary text-sm font-medium hover:bg-surface-hover"
            >
              Back to List
            </button>
          </div>
        </div>
      )}
    </div>
  );
}