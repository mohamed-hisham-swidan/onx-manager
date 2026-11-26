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
  readOnly?: boolean;
}

const ADVANCED_OPERATIONS = [
  "Creates an automatic safety backup and encrypted live-data snapshot.",
  "Native Git repository initialized at root with initial main commit.",
  "Indexes server and plugin JARs into shared storage.",
  "Rollback guarantee: if any step fails, conversion is aborted with zero changes to server data.",
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
      return "Secret file detected in config folder. Move secrets to the Secret Vault or environment variables first.";
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

export function ServerModeConversionCard({
  serverId,
  server,
  readOnly = false,
}: ServerModeConversionCardProps) {
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
  const simpleConfirmTitle = `Create Simple Server from "${server.name}"?`;

  function handleConvertToAdvanced() {
    if (readOnly) return;
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
    if (readOnly) return;
    setError(null);
    if (!validateSimpleForm()) return;
    setSimpleConfirm(true);
  }

  async function handleConfirmConvertToSimple() {
    setError(null);
    if (!validateSimpleForm()) return;
    const port = simplePort.trim() ? Number(simplePort) : undefined;
    try {
      const res = await convertToSimple.mutateAsync({
        serverId,
        body: { name: simpleName, port },
      });
      toast(
        "success",
        "Simple Server Created",
        `New server '${res.name}' created successfully.`,
      );
      setCreatedSimpleServerId(res.new_server_id);
      setSimpleConfirm(false);
    } catch (err) {
      setError(translateConvertError(err, "simple"));
    }
  }

  return (
    <section
      data-testid="server-mode-conversion-card"
      className="rounded-xl border border-border-subtle bg-surface-card overflow-hidden"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-border-subtle bg-surface-muted/40">
        <div className="flex items-center gap-2.5">
          <Icon name="version-branch" size={16} className="text-text-muted" />
          <h3 className="text-sm font-semibold text-text-primary">Server Mode</h3>
          <span className="inline-flex items-center rounded-full border border-border-subtle bg-surface-card px-2.5 py-0.5 text-[11px] font-medium text-text-secondary">
            Mode: {serverModeLabel(server.mode)}
          </span>
        </div>
        {readOnly && (
          <span className="text-xs text-text-muted">Requires versioning permission</span>
        )}
      </div>

      <div className="p-5 space-y-4">
        {mode === "simple" ? (
          <>
            <div className="space-y-1">
              <h4 className="text-sm font-medium text-text-primary">
                Convert to Advanced Mode
              </h4>
              <p className="text-xs text-text-muted">
                Unlocks Git versioning, branches, and isolated test containers in place.
              </p>
            </div>

            {!isConvertible && (
              <div className="rounded-lg border border-status-warning-border bg-status-warning-bg px-3 py-2 text-xs text-status-warning flex items-center gap-2">
                <Icon name="alert" size={14} />
                <span>Server must be stopped before converting to Advanced mode.</span>
              </div>
            )}

            <div className="text-xs text-text-muted space-y-1">
              <span className="font-medium text-text-secondary">What happens:</span>
              <ul className="list-disc list-inside space-y-1">
                {ADVANCED_OPERATIONS.map((op, i) => (
                  <li key={i}>{op}</li>
                ))}
              </ul>
            </div>

            {conversionSummary && (
              <div className="rounded-lg border border-status-info-border bg-status-info-bg px-3 py-2 text-xs text-status-info">
                <span className="font-semibold">Conversion complete.</span>{" "}
                Commit <code className="font-mono">{conversionSummary.main_commit_sha}</code>,
                backup <code className="font-mono">{conversionSummary.backup_id}</code>, shared-storage
                objects indexed: {conversionSummary.cas_ingested}.
              </div>
            )}

            {error && (
              <div className="rounded-lg border border-status-danger-border bg-status-danger-bg px-3 py-2 text-xs text-status-danger">
                {error}
              </div>
            )}

            <div>
              <Button
                type="button"
                onClick={handleConvertToAdvanced}
                disabled={readOnly || !isConvertible || convertToAdvanced.isPending}
                icon="play"
                size="sm"
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
                " to Advanced mode in place: a safety backup and encrypted live-data snapshot are created, a Git repository is initialized, and server and plugin JARs are indexed into shared storage. If anything fails, changes are rolled back with zero changes to server data."
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
            <div className="space-y-1">
              <h4 className="text-sm font-medium text-text-primary">
                Convert to Simple Mode
              </h4>
              <p className="text-xs text-text-muted">
                Creates a brand-new Simple server from a clean export; &ldquo;{server.name}&rdquo; is NOT modified or deleted.
              </p>
              <p className="text-xs text-text-muted">
                Recommendation: Stop server before converting to ensure clean export of live files.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-1">
                <label
                  htmlFor="simple-conversion-name"
                  className="block text-xs font-medium text-text-secondary"
                >
                  Name
                </label>
                <input
                  id="simple-conversion-name"
                  type="text"
                  required
                  disabled={readOnly}
                  value={simpleName}
                  onChange={(e) => setSimpleName(e.target.value)}
                  className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
                />
              </div>
              <div className="space-y-1">
                <label
                  htmlFor="simple-conversion-port"
                  className="block text-xs font-medium text-text-secondary"
                >
                  Port
                </label>
                <input
                  id="simple-conversion-port"
                  type="number"
                  min="1024"
                  max="65535"
                  disabled={readOnly}
                  placeholder="Auto-allocate or specify port"
                  value={simplePort}
                  onChange={(e) => setSimplePort(e.target.value)}
                  className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
                />
              </div>
            </div>

            {simpleValidationError && (
              <div className="rounded-lg border border-status-danger-border bg-status-danger-bg px-3 py-2 text-xs text-status-danger">
                {simpleValidationError}
              </div>
            )}
            {error && (
              <div className="rounded-lg border border-status-danger-border bg-status-danger-bg px-3 py-2 text-xs text-status-danger">
                {error}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                onClick={handleConvertToSimple}
                disabled={readOnly || convertToSimple.isPending}
                icon="copy"
              >
                {convertToSimple.isPending ? "Creating..." : "Create Simple Server"}
              </Button>
              {createdSimpleServerId && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => navigate(`/servers/${createdSimpleServerId}/settings`)}
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
      </div>
    </section>
  );
}
