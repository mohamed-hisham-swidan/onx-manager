import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useConvertToAdvanced, useConvertToSimple } from "@/server_manager/hooks/useConversion";
import { resolveServerMode, serverModeLabel } from "@/server_manager/utils/serverMode";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { toast } from "@/stores/toastStore";
import { ApiError } from "@/services/api";
import type { ServerDetailResponse } from "@/server_manager/types";

export interface ServerModeConversionCardProps {
  serverId: string;
  server: ServerDetailResponse;
}

const ADVANCED_OPERATIONS = [
  "Automatic pinned Tier-1 backup + pinned encrypted Class-C snapshot created.",
  "Native Git repository initialized at root with initial main commit.",
  "Content-addressable storage (CAS) ingest for Class-A jars.",
  "Rollback guarantee: if any step fails (e.g. secret detected), conversion is aborted with zero changes to server data.",
];

function convertStatus(server: ServerDetailResponse): "stopped-or-created" | "other" {
  if (!server.status) return "other";
  return ["stopped", "created"].includes(server.status.toLowerCase()) ? "stopped-or-created" : "other";
}

function translateConvertError(err: unknown, operation: "advanced" | "simple"): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403 || err.code === "PERMISSION_DENIED") {
      return "Permission denied: Requires 'server.versioning.manage' permission.";
    }
    if (err.status === 409 && err.code === "CONFLICT") {
      return operation === "advanced"
        ? "Server must be stopped before converting to Advanced mode."
        : "Target name/port already exists";
    }
    if (err.status === 422 && err.code === "SECRET_FILE_IN_GIT_FORBIDDEN") {
      return "Class-B secret file detected. Secrets cannot be committed to Git. Move secrets to Class-C or environment variables before converting.";
    }
    if (err.status === 501 && err.code === "CAS_UNSUPPORTED_PLATFORM") {
      return "Advanced mode requires a POSIX operating system (Linux/macOS).";
    }
    if (err.status === 404 && err.code === "NOT_FOUND") {
      return "Server not found.";
    }
  }
  return err instanceof Error ? err.message : "Action failed";
}

export function ServerModeConversionCard({ serverId, server }: ServerModeConversionCardProps) {
  const navigate = useNavigate();
  const mode = resolveServerMode(server.mode);
  const convertToAdvanced = useConvertToAdvanced();
  const convertToSimple = useConvertToSimple();
  const [advancedConfirm, setAdvancedConfirm] = useState(false);
  const [simpleConfirm, setSimpleConfirm] = useState(false);
  const [conversionSummary, setConversionSummary] = useState<{
    main_commit_sha: string;
    backup_id: string;
    cas_ingested: number;
  } | null>(null);
  const [simpleName, setSimpleName] = useState(server.name + " (Simple)");
  const [simplePort, setSimplePort] = useState("");
  const [simpleValidationError, setSimpleValidationError] = useState<string | null>(null);
  const [createdSimpleServerId, setCreatedSimpleServerId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isConvertible = convertStatus(server) === "stopped-or-created";
  const simpleConfirmTitle = "Create Simple Server from \"" + server.name + "\"?";
  const modeBadgeClasses =
    "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border " +
    (mode === "advanced"
      ? "bg-surface-elevated text-text-primary border border-border-default"
      : "bg-surface-muted text-text-secondary border border-border-subtle");

  function handleViewServerBackups() {
    navigate("/backups?server_id=" + serverId);
  }

  function handleConvertToAdvanced() {
    setError(null);
    setAdvancedConfirm(true);
  }

  async function handleConfirmConvertToAdvanced() {
    setError(null);
    try {
      const data = await convertToAdvanced.mutateAsync(serverId);
      setConversionSummary(data);
      toast("success", "Conversion Complete", "Server successfully converted to Advanced mode.");
      setAdvancedConfirm(false);
    } catch (err) {
      setError(translateConvertError(err, "advanced"));
    }
  }

  function validateSimpleForm(): boolean {
    setSimpleValidationError(null);
    if (!simpleName.trim()) {
      setSimpleValidationError("Server name is required.");
      return false;
    }
    if (simplePort.trim()) {
      const port = Number(simplePort);
      if (!Number.isInteger(port) || port < 1024 || port > 65535) {
        setSimpleValidationError("Port must be between 1024 and 65535.");
        return false;
      }
    }
    return true;
  }

  function handleConvertToSimple() {
    setError(null);
    if (!validateSimpleForm()) return;
    setSimpleConfirm(true);
  }

  async function handleConfirmConvertToSimple() {
    setError(null);
    if (!validateSimpleForm()) return;
    const port = simplePort.trim() ? Number(simplePort) : undefined;
    try {
      const res = await convertToSimple.mutateAsync({ serverId, body: { name: simpleName, port } });
      toast("success", "Simple Server Created", "New server '" + res.name + "' created successfully.");
      setCreatedSimpleServerId(res.new_server_id);
      setSimpleConfirm(false);
    } catch (err) {
      setError(translateConvertError(err, "simple"));
    }
  }

  return (
    <section
      data-testid="server-mode-conversion-card"
      className="rounded-2xl border border-border-default bg-surface-card p-6 shadow-xs space-y-4"
    >
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3">
        <div className="flex items-center gap-2">
          <Icon name="version-branch" size={16} className="text-text-muted" />
          <h3 className="text-base font-bold text-text-primary">Mode Conversion</h3>
        </div>
        <span className={modeBadgeClasses}>
          Mode: {serverModeLabel(server.mode)}
        </span>
        <Button
          onClick={handleViewServerBackups}
          icon="external"
          size="sm"
        >
          View Server Backups
        </Button>
      </div>

      {mode === "simple" ? (
        <>
          <div className="space-y-2">
            <h4 className="text-sm font-semibold text-text-primary">Convert to Advanced Mode</h4>
            <p className="text-xs text-text-muted">
              Conversion runs in place. Advanced mode unlocks versioning, branches, and isolated testing for this server.
            </p>
          </div>

          {!isConvertible && (
            <div className="rounded-lg border border-status-warning-bg bg-status-warning-bg/50 p-3 text-sm text-status-warning">
              <Icon name="alert" size={14} className="mr-2" />
              Server must be stopped before converting to Advanced mode.
            </div>
          )}

          <div className="text-xs text-text-muted space-y-1">
            <span className="font-semibold text-text-secondary">What happens:</span>
            <ul className="list-disc list-inside space-y-1 text-text-muted">
              {ADVANCED_OPERATIONS.map((op, i) => (
                <li key={i}>{op}</li>
              ))}
            </ul>
          </div>

          {conversionSummary && (
            <div className="rounded-lg border border-status-info-bg bg-status-info-bg/50 p-3 text-sm text-status-info">
              <span className="font-semibold">Conversion complete.</span>{" "}
              Commit <code className="font-mono">{conversionSummary.main_commit_sha}</code>, backup{" "}
              <code className="font-mono">{conversionSummary.backup_id}</code>, CAS objects ingested: {conversionSummary.cas_ingested}.
            </div>
          )}
          {error && (
            <div className="rounded-lg border border-status-danger-bg bg-status-danger-bg/50 p-3 text-sm text-status-danger">
              {error}
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button
              onClick={handleConvertToAdvanced}
              disabled={!isConvertible || convertToAdvanced.isPending}
              icon="play"
            >
              {convertToAdvanced.isPending ? "Converting..." : "Convert to Advanced"}
            </Button>
          </div>

          <ConfirmDialog
            open={advancedConfirm}
            title="Convert Server to Advanced Mode?"
            description={
              "This converts " +
              server.name +
              " to Advanced mode in place: an automatic pinned Tier-1 backup and pinned encrypted Class-C snapshot are created, a Git repository is initialized, and Class-A jars are ingested into CAS. If anything fails, changes are rolled back with zero changes to server data."
            }
            confirmLabel="Convert"
            cancelLabel="Cancel"
            variant="warning"
            isPending={convertToAdvanced.isPending}
            onConfirm={handleConfirmConvertToAdvanced}
            onCancel={() => setAdvancedConfirm(false)}
          />
        </>
      ) : (
        <>
          <div className="space-y-2">
            <h4 className="text-sm font-semibold text-text-primary">Convert to Simple Mode</h4>
            <p className="text-xs text-text-muted">
              Converting creates a brand-new Simple server with a Clean Export of files. The existing Advanced server ("{server.name}") is NOT modified or deleted.
            </p>
            <p className="text-xs text-text-muted">
              Recommendation: Stop server before converting to ensure clean export of live files.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label htmlFor="simple-conversion-name" className="block text-xs font-semibold text-text-secondary">
                Name
              </label>
              <input
                id="simple-conversion-name"
                type="text"
                required
                value={simpleName}
                onChange={(e) => setSimpleName(e.target.value)}
                className="px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="simple-conversion-port" className="block text-xs font-semibold text-text-secondary">
                Port
              </label>
              <input
                id="simple-conversion-port"
                type="number"
                min="1024"
                max="65535"
                placeholder="Auto-allocate or specify port"
                value={simplePort}
                onChange={(e) => setSimplePort(e.target.value)}
                className="px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
              />
            </div>
          </div>

          {simpleValidationError && (
            <div className="rounded-lg border border-status-danger-bg bg-status-danger-bg/50 p-3 text-sm text-status-danger">
              {simpleValidationError}
            </div>
          )}
          {error && (
            <div className="rounded-lg border border-status-danger-bg bg-status-danger-bg/50 p-3 text-sm text-status-danger">
              {error}
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button
              onClick={handleConvertToSimple}
              disabled={convertToSimple.isPending}
              icon="copy"
            >
              {convertToSimple.isPending ? "Creating..." : "Create Simple Server"}
            </Button>
            {createdSimpleServerId && (
              <Button
                variant="outline"
                onClick={() => navigate("/servers/" + createdSimpleServerId + "/settings")}
              >
                Go to New Server Settings
              </Button>
            )}
          </div>

          <ConfirmDialog
            open={simpleConfirm}
            title={simpleConfirmTitle}
            description={
              "A brand-new Simple server will be created from a clean export of " +
              server.name +
              "'s files. The existing Advanced server is left untouched."
            }
            confirmLabel="Create Simple Server"
            cancelLabel="Cancel"
            variant="info"
            isPending={convertToSimple.isPending}
            onConfirm={handleConfirmConvertToSimple}
            onCancel={() => setSimpleConfirm(false)}
          />
        </>
      )}
    </section>
  );
}
