import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { QueryClientContext } from "@tanstack/react-query";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { Modal } from "@/components/ui/Modal";
import { useOperationStore } from "@/operations/stores/operationStore";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import type {
  ManualDownloadBlockerItem,
  ModpackInspectResponse,
  ModpackInstallResponse,
} from "@/server_manager/types";

export interface ModpackInstallWizardModalProps {
  serverId: string;
  isOpen: boolean;
  onClose: () => void;
  onInstalled?: (result: ModpackInstallResponse) => void;
  initialStagedPackId?: string | null;
  initialFormat?: "auto" | "mrpack" | "curseforge";
}

type ModpackFormat = "auto" | "mrpack" | "curseforge";

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unit]}`;
}

function blockerKey(blocker: ManualDownloadBlockerItem): string {
  return `${blocker.path}|${blocker.file_id ?? "none"}`;
}

function detailText(detail: ApiError["detail"]): string | null {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.join("; ");
  return JSON.stringify(detail);
}

function formatLabel(source: string): string {
  if (source === "modrinth") return "Modrinth (.mrpack)";
  if (source === "curseforge") return "CurseForge (.zip)";
  return source;
}

function StepHeader({ step, title }: { step: number; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent-primary text-[11px] font-bold text-accent-contrast-text">
        {step}
      </span>
      <h3 className="text-sm font-bold text-text-primary">{title}</h3>
    </div>
  );
}

function InspectErrorCallout({
  error,
  onDismiss,
}: {
  error: ApiError;
  onDismiss: () => void;
}) {
  const detail = detailText(error.detail);

  if (error.status === 409 && error.code === "CURSEFORGE_API_KEY_MISSING") {
    return (
      <div data-testid="curseforge-key-missing-alert">
        <Banner
          variant="warning"
          title="CurseForge API key required"
          description="CurseForge modpack inspection needs a panel CurseForge Eternal API key. Add one in Panel Settings, then retry the upload."
          action={
            <Link
              to="/settings?tab=integrations"
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover"
            >
              <Icon name="lock" size={13} />
              Configure CurseForge API Key in Panel Settings
            </Link>
          }
          onDismiss={onDismiss}
        />
      </div>
    );
  }

  if (error.code === "UNSUPPORTED_FORGE_VERSION") {
    return (
      <Banner
        variant="danger"
        title="Legacy Forge version is not supported"
        description="Forge is restricted to Minecraft 1.17.1 through 1.20.1. For Minecraft 1.20.2+ use NeoForge for modpacks."
        onDismiss={onDismiss}
      />
    );
  }

  if (
    error.code === "HOSTILE_EXECUTABLE_REJECTED" ||
    error.code === "UNTRUSTED_DOWNLOAD_HOST" ||
    error.code === "MODPACK_FORMAT_INVALID"
  ) {
    return (
      <Banner
        variant="danger"
        title={error.message}
        description={
          detail ? (
            <span className="font-mono text-[11px] break-all">{detail}</span>
          ) : undefined
        }
        onDismiss={onDismiss}
      />
    );
  }

  return (
    <Banner
      variant="danger"
      title={error.message || "Modpack inspection failed"}
      description={detail ?? undefined}
      onDismiss={onDismiss}
    />
  );
}

function ModpackInstallWizardModalInner({
  serverId,
  onClose,
  onInstalled,
  initialFormat = "auto",
}: ModpackInstallWizardModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const queryClient = useContext(QueryClientContext);

  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState<ModpackFormat>(initialFormat);
  const [includeOptional, setIncludeOptional] = useState(true);
  const [isInspecting, setIsInspecting] = useState(false);
  const [inspectError, setInspectError] = useState<ApiError | null>(null);
  const [inspection, setInspection] = useState<ModpackInspectResponse | null>(null);
  const [resolvedBlockers, setResolvedBlockers] = useState<Record<string, boolean>>({});
  const [manualError, setManualError] = useState<string | null>(null);
  const [uploadingBlockerKey, setUploadingBlockerKey] = useState<string | null>(null);

  const [buildLec, setBuildLec] = useState(false);
  const [asyncMode, setAsyncMode] = useState(false);
  const [isInstalling, setIsInstalling] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const [installResult, setInstallResult] = useState<ModpackInstallResponse | null>(null);
  const [activeOperationId, setActiveOperationId] = useState<string | null>(null);
  const pendingAsyncBaseRef = useRef<ModpackInstallResponse | null>(null);

  const openOperationDrawer = useOperationStore((s) => s.openDrawer);
  const setOperation = useOperationStore((s) => s.setOperation);
  const activeOperation = useOperationStore((s) =>
    activeOperationId ? s.operations[activeOperationId] : undefined,
  );
  const activeOperationLogs = useOperationStore((s) =>
    activeOperationId ? s.logs[activeOperationId] : undefined,
  );

  const plan = inspection?.plan ?? null;
  const blockers = plan?.manual_blockers ?? [];

  useEffect(() => {
    if (!activeOperationId || typeof api.getOperation !== "function") return;
    let cancelled = false;

    async function pollOperation() {
      if (cancelled || !activeOperationId || typeof api.getOperation !== "function") {
        return;
      }
      try {
        const detail = await api.getOperation(activeOperationId);
        if (cancelled) return;
        setOperation(detail);

        if (detail.status === "COMPLETED") {
          const base = pendingAsyncBaseRef.current;
          const stepTotal = detail.steps?.[0]?.context?.total;
          const completedResult: ModpackInstallResponse = {
            server_id: base?.server_id ?? serverId,
            upgrade_id: base?.upgrade_id ?? inspection?.staged_pack_id ?? "",
            status: "confirmed",
            mc_version: base?.mc_version ?? inspection?.mc_version ?? "",
            loader_id: base?.loader_id ?? inspection?.loader_id ?? "",
            loader_version: base?.loader_version ?? inspection?.loader_version ?? "",
            lec_key: base?.lec_key ?? null,
            files_installed:
              typeof stepTotal === "number" ? stepTotal : (plan?.files.length ?? 0),
            base_overrides_count: plan?.overrides.length ?? 0,
            commit_sha: base?.commit_sha ?? null,
            operation_id: activeOperationId,
          };
          pendingAsyncBaseRef.current = null;
          setActiveOperationId(null);
          setIsInstalling(false);
          setInstallResult(completedResult);
          if (queryClient) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId) });
            void queryClient.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
          }
          onInstalled?.(completedResult);
        } else if (
          detail.status === "FAILED" ||
          detail.status === "CANCELLED" ||
          detail.status === "TIMED_OUT"
        ) {
          pendingAsyncBaseRef.current = null;
          setActiveOperationId(null);
          setIsInstalling(false);
          setInstallError(
            detail.error_message ||
              `Modpack installation ${detail.status.toLowerCase()}`,
          );
        }
      } catch {
        // Keep polling while WebSocket or subsequent poll recovers.
      }
    }

    void pollOperation();
    const timer = setInterval(() => {
      void pollOperation();
    }, 1500);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activeOperationId, api, serverId, inspection, plan, setOperation, onInstalled, queryClient]);

  function blockerResolved(blocker: ManualDownloadBlockerItem): boolean {
    return blocker.resolved || Boolean(resolvedBlockers[blockerKey(blocker)]);
  }

  const unresolvedBlockers = blockers.filter((blocker) => !blockerResolved(blocker));
  const hasUnresolvedBlockers =
    inspection?.has_unresolved_blockers === true && unresolvedBlockers.length > 0;

  async function handleInspect() {
    if (!file || typeof api.inspectModpack !== "function") return;
    setIsInspecting(true);
    setInspectError(null);
    try {
      const response = await api.inspectModpack(serverId, file, {
        format,
        install_optional_server_files: includeOptional,
      });
      setInspection(response);
      setResolvedBlockers({});
      setInstallResult(null);
      setInstallError(null);
      pendingAsyncBaseRef.current = null;
      setActiveOperationId(null);
    } catch (error) {
      if (error instanceof ApiError) {
        setInspectError(error);
      } else {
        setInspectError(
          new ApiError(0, "UNKNOWN", error instanceof Error ? error.message : "Inspection failed"),
        );
      }
    } finally {
      setIsInspecting(false);
    }
  }

  async function handleManualUpload(
    blocker: ManualDownloadBlockerItem,
    uploadedFile: File | undefined,
  ) {
    if (!uploadedFile || !inspection || typeof api.resolveUpgradeManualUpload !== "function") {
      return;
    }
    const key = blockerKey(blocker);
    setUploadingBlockerKey(key);
    setManualError(null);
    try {
      const upgraded = await api.resolveUpgradeManualUpload(
        serverId,
        inspection.staged_pack_id,
        uploadedFile,
        { file_id: blocker.file_id, path: blocker.path },
      );
      setResolvedBlockers((previous) => ({ ...previous, [key]: true }));
      if (upgraded.manual_blockers && inspection) {
        setInspection({
          ...inspection,
          plan: { ...inspection.plan, manual_blockers: upgraded.manual_blockers },
          has_unresolved_blockers: upgraded.manual_blockers.some(
            (item) => !item.resolved && !resolvedBlockers[blockerKey(item)],
          ),
        });
      }
    } catch (error) {
      setManualError(error instanceof ApiError ? error.message : "Manual upload failed");
    } finally {
      setUploadingBlockerKey(null);
    }
  }

  async function handleInstall() {
    if (!inspection || typeof api.installModpack !== "function") return;
    setIsInstalling(true);
    setInstallError(null);
    setManualError(null);
    let keepInstalling = false;
    try {
      const result = await api.installModpack(serverId, {
        staged_pack_id: inspection.staged_pack_id,
        build_lec: buildLec,
        async_mode: asyncMode,
      });
      const isBackgroundStarted =
        Boolean(result.operation_id) &&
        (result.status === "installing" ||
          result.status === "queued" ||
          result.status === "running");

      if (isBackgroundStarted && result.operation_id) {
        keepInstalling = true;
        pendingAsyncBaseRef.current = result;
        setActiveOperationId(result.operation_id);
        openOperationDrawer(result.operation_id);
        return;
      }

      setInstallResult(result);
      if (queryClient) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.plugins.list(serverId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.servers.detail(serverId) });
      }
      onInstalled?.(result);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.code === "MANUAL_DOWNLOAD_REQUIRED" &&
        typeof api.getServerUpgrade === "function"
      ) {
        try {
          const refreshed = await api.getServerUpgrade(serverId, inspection.staged_pack_id);
          if (refreshed.manual_blockers) {
            setInspection({
              ...inspection,
              plan: { ...inspection.plan, manual_blockers: refreshed.manual_blockers },
              has_unresolved_blockers: refreshed.manual_blockers.some(
                (item) => !item.resolved && !resolvedBlockers[blockerKey(item)],
              ),
            });
          }
          setInstallError(
            "CurseForge requires a manual download. Upload the newly blocked file below to continue.",
          );
        } catch {
          // The refresh is best-effort; the original install error still explains the block.
          setInstallError(error.message);
        }
      } else {
        setInstallError(error instanceof ApiError ? error.message : "Modpack installation failed");
      }
    } finally {
      if (!keepInstalling) {
        setIsInstalling(false);
      }
    }
  }

  const blockModalDismiss = isInspecting || (isInstalling && !activeOperationId);

  return (
    <Modal
      open
      onClose={onClose}
      size="2xl"
      title="Install Modpack (.mrpack / CurseForge)"
      description="Inspect the archive and resolve manual downloads before anything is written to this server."
      closeOnBackdrop={!blockModalDismiss}
      closeOnEscape={!blockModalDismiss}
    >
      <div className="flex flex-col max-h-[76vh] min-w-0 overflow-x-hidden">
        {installResult ? (
          <div className="flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden pr-1 space-y-4">
            <Banner
              variant="success"
              title={
                installResult.status === "applied" || installResult.status === "active_pinned"
                  ? "Modpack installed successfully"
                  : `Modpack installation ${installResult.status}`
              }
              description={`${installResult.files_installed} server files installed, ${installResult.base_overrides_count} base overrides committed.`}
            />
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <dt className="text-[11px] uppercase tracking-wider text-text-muted">Target</dt>
                <dd className="mt-1 font-medium text-text-primary">
                  MC {installResult.mc_version} · {installResult.loader_id}{" "}
                  {installResult.loader_version}
                </dd>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <dt className="text-[11px] uppercase tracking-wider text-text-muted">
                  Upgrade ID
                </dt>
                <dd className="mt-1 font-mono text-xs text-text-primary break-all">
                  {installResult.upgrade_id}
                </dd>
              </div>
              {installResult.lec_key && (
                <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                  <dt className="text-[11px] uppercase tracking-wider text-text-muted">
                    Loader Cache
                  </dt>
                  <dd className="mt-1 font-mono text-xs text-text-primary break-all">
                    {installResult.lec_key}
                  </dd>
                </div>
              )}
              {installResult.commit_sha && (
                <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                  <dt className="text-[11px] uppercase tracking-wider text-text-muted">
                    Commit SHA
                  </dt>
                  <dd className="mt-1 font-mono text-xs text-text-primary break-all">
                    {installResult.commit_sha}
                  </dd>
                </div>
              )}
              {installResult.operation_id && (
                <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                  <dt className="text-[11px] uppercase tracking-wider text-text-muted">
                    Operation
                  </dt>
                  <dd className="mt-1 font-mono text-xs text-text-primary break-all">
                    {installResult.operation_id}
                  </dd>
                </div>
              )}
            </dl>
            <div className="flex justify-end">
              <Button type="button" variant="primary" onClick={onClose}>
                Close
              </Button>
            </div>
          </div>
        ) : !inspection ? (
          <div className="flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden pr-1 space-y-5">
            <StepHeader step={1} title="Upload & Inspect Archive" />

            <div className="rounded-xl border border-dashed border-border-default bg-surface-page/60 p-5 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <label
                  htmlFor="modpack-file-input"
                  className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border-default bg-surface-card px-3.5 py-2 text-sm font-medium text-text-primary hover:bg-surface-hover"
                >
                  <Icon name="upload" size={16} />
                  Choose .mrpack / .zip
                </label>
                <input
                  id="modpack-file-input"
                  data-testid="modpack-file-input"
                  type="file"
                  accept=".mrpack,.zip"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  className="sr-only"
                />
                <span className="text-xs text-text-muted break-all">
                  {file ? `${file.name} (${formatBytes(file.size)})` : "No archive selected yet."}
                </span>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label
                    htmlFor="modpack-format"
                    className="mb-1 block text-[11px] font-medium text-text-muted"
                  >
                    Archive Format
                  </label>
                  <select
                    id="modpack-format"
                    value={format}
                    onChange={(event) => setFormat(event.target.value as ModpackFormat)}
                    className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-sm text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
                  >
                    <option value="auto">Auto-detect</option>
                    <option value="mrpack">Modrinth (.mrpack)</option>
                    <option value="curseforge">CurseForge (.zip)</option>
                  </select>
                </div>
                <label className="flex items-end gap-2 pb-1.5 text-xs text-text-secondary">
                  <input
                    type="checkbox"
                    checked={includeOptional}
                    onChange={(event) => setIncludeOptional(event.target.checked)}
                    className="h-4 w-4 rounded border-border-default"
                  />
                  Include Optional Server Mods (env.server = optional)
                </label>
              </div>
            </div>

            {inspectError && (
              <InspectErrorCallout error={inspectError} onDismiss={() => setInspectError(null)} />
            )}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-text-muted">
                Inspection stages the archive and computes a hash-only plan; the live
                server is untouched.
              </p>
              <Button
                type="button"
                data-testid="inspect-modpack-btn"
                variant="primary"
                icon="search"
                loading={isInspecting}
                disabled={!file}
                onClick={handleInspect}
              >
                Inspect Modpack
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden pr-1 space-y-4">
            <StepHeader step={2} title="Inspect Plan Preview & Manual Download Unblock" />

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <p className="text-[10px] uppercase tracking-wider text-text-muted">Source</p>
                <p className="mt-1 text-sm font-semibold text-text-primary">
                  {formatLabel(inspection.source)}
                </p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <p className="text-[10px] uppercase tracking-wider text-text-muted">Pack Version</p>
                <p className="mt-1 text-sm font-semibold text-text-primary">
                  {plan?.version_label ?? inspection.mc_version}
                </p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <p className="text-[10px] uppercase tracking-wider text-text-muted">Target MC</p>
                <p className="mt-1 text-sm font-semibold text-text-primary">
                  {inspection.mc_version}
                </p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <p className="text-[10px] uppercase tracking-wider text-text-muted">Target Loader</p>
                <p className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-text-primary">
                  <LoaderBadge loader={inspection.loader_id} />
                  <span className="font-mono text-xs">{inspection.loader_version}</span>
                </p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <p className="text-[10px] uppercase tracking-wider text-text-muted">Server Files</p>
                <p className="mt-1 text-sm font-semibold text-text-primary">
                  {plan?.files.length ?? 0}
                </p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <p className="text-[10px] uppercase tracking-wider text-text-muted">Overrides</p>
                <p className="mt-1 text-sm font-semibold text-text-primary">
                  {plan?.overrides.length ?? 0}
                </p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <p className="text-[10px] uppercase tracking-wider text-text-muted">
                  Skipped Client-Only
                </p>
                <p className="mt-1 text-sm font-semibold text-text-primary">
                  {(plan?.skipped_client_files.length ?? 0) +
                    (plan?.skipped_client_override_jars.length ?? 0)}
                </p>
              </div>
              <div className="rounded-lg border border-border-subtle bg-surface-page p-3">
                <p className="text-[10px] uppercase tracking-wider text-text-muted">
                  Skipped Optional
                </p>
                <p className="mt-1 text-sm font-semibold text-text-primary">
                  {plan?.skipped_optional_files.length ?? 0}
                </p>
              </div>
            </div>

            {plan && plan.warnings.length > 0 && (
              <details
                data-testid="modpack-skipped-paths-details"
                className="rounded-xl border border-border-subtle bg-surface-card"
              >
                <summary className="cursor-pointer px-4 py-2.5 text-xs font-medium text-text-secondary flex items-center justify-between gap-2 select-none">
                  <span>Skipped non-server paths &amp; notes ({plan.warnings.length})</span>
                  <span className="text-[11px] text-text-muted">Click to inspect</span>
                </summary>
                <ul className="max-h-36 overflow-y-auto overflow-x-hidden border-t border-border-subtle divide-y divide-border-subtle/60 text-left">
                  {plan.warnings.map((warning, idx) => (
                    <li
                      key={`${idx}-${warning}`}
                      className="px-4 py-1.5 font-mono text-[11px] text-text-muted break-all"
                    >
                      {warning}
                    </li>
                  ))}
                </ul>
              </details>
            )}

            <details className="rounded-xl border border-border-subtle bg-surface-card">
              <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-text-secondary">
                Server files ({plan?.files.length ?? 0})
              </summary>
              <ul className="max-h-44 overflow-y-auto border-t border-border-subtle divide-y divide-border-subtle/60">
                {plan?.files.map((item) => (
                  <li key={item.path} className="px-4 py-2 text-xs flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-text-primary break-all">
                      {item.path}
                    </span>
                    <span className="text-text-muted">{formatBytes(item.size)}</span>
                    {item.optional && (
                      <span className="rounded bg-status-warning-bg px-1.5 py-0.5 text-[10px] font-semibold text-status-warning">
                        optional
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </details>

            <details className="rounded-xl border border-border-subtle bg-surface-card">
              <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-text-secondary">
                Classified overrides ({plan?.overrides.length ?? 0})
              </summary>
              <ul className="max-h-44 overflow-y-auto border-t border-border-subtle divide-y divide-border-subtle/60">
                {plan?.overrides.map((item) => (
                  <li key={item.path} className="px-4 py-2 text-xs flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-text-primary break-all">
                      {item.path}
                    </span>
                    <span className="rounded bg-surface-elevated px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary">
                      {item.classification === "routed_cas" ? "Cached Binary" : "B"}
                    </span>
                    <span className="text-text-muted">{formatBytes(item.size)}</span>
                  </li>
                ))}
              </ul>
            </details>

            <details className="rounded-xl border border-border-subtle bg-surface-card">
              <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-text-secondary">
                Filtered client-only files ({plan?.skipped_client_files.length ?? 0})
              </summary>
              <ul className="max-h-32 overflow-y-auto border-t border-border-subtle divide-y divide-border-subtle/60">
                {plan?.skipped_client_files.map((path) => (
                  <li key={path} className="px-4 py-1.5 font-mono text-[11px] text-text-muted break-all">
                    {path}
                  </li>
                ))}
              </ul>
            </details>

            {blockers.length > 0 && (
              <div
                data-testid="modpack-manual-blockers"
                className="rounded-xl border border-status-warning-border bg-status-warning-bg/40 p-4 space-y-3"
              >
                <div className="flex items-center gap-2">
                  <Icon name="alert" size={16} className="text-status-warning" />
                  <h4 className="text-sm font-bold text-text-primary">
                    CurseForge Manual Downloads Required
                  </h4>
                </div>
                <p className="text-xs text-text-secondary">
                  These files cannot be fetched automatically. Download them from the
                  project page and drop them here; each upload is verified against the
                  expected hash before installation is enabled.
                </p>
                {manualError && (
                  <p className="text-xs font-medium text-status-danger">{manualError}</p>
                )}
                <div className="space-y-2">
                  {blockers.map((blocker, index) => {
                    const key = blockerKey(blocker);
                    const isResolved = blockerResolved(blocker);
                    return (
                      <div
                        key={key}
                        className="rounded-lg border border-border-subtle bg-surface-card p-3 space-y-2"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-xs font-semibold text-text-primary break-all">
                              {blocker.filename}
                            </p>
                            <p className="font-mono text-[10px] text-text-muted break-all">
                              {blocker.path}
                            </p>
                          </div>
                          {isResolved ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-status-success-border bg-status-success-bg px-2 py-0.5 text-[10px] font-semibold text-status-success">
                              <Icon name="check" size={10} />
                              Verified
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[10px] font-semibold text-status-warning">
                              Download required
                            </span>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-3 text-[10px] text-text-muted">
                          <span>Reason: {blocker.reason}</span>
                          <span>Size: {formatBytes(blocker.expected_size)}</span>
                          {blocker.expected_sha1 && (
                            <span className="font-mono break-all">sha1 {blocker.expected_sha1}</span>
                          )}
                          {blocker.webpage_url && (
                            <a
                              href={blocker.webpage_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-accent-primary hover:underline"
                            >
                              Open download page
                            </a>
                          )}
                        </div>
                        {!isResolved && (
                          <div className="flex items-center gap-2">
                            <input
                              data-testid={`manual-upload-input-${blocker.file_id ?? index}`}
                              type="file"
                              onChange={(event) => {
                                void handleManualUpload(blocker, event.target.files?.[0]);
                                event.target.value = "";
                              }}
                              className="block w-full text-[11px] text-text-secondary file:mr-2 file:rounded-md file:border-0 file:bg-surface-elevated file:px-2.5 file:py-1 file:text-[11px] file:font-medium file:text-text-primary"
                            />
                            {uploadingBlockerKey === key && (
                              <span className="text-[10px] text-text-muted">Verifying…</span>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary">
                Install Options
              </h4>
              <label className="flex items-start gap-2 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={buildLec}
                  disabled={isInstalling}
                  onChange={(event) => setBuildLec(event.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-border-default"
                />
                Pre-build loader files during install
              </label>
              <label className="flex items-start gap-2 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  data-testid="modpack-async-checkbox"
                  checked={asyncMode}
                  disabled={isInstalling}
                  onChange={(event) => setAsyncMode(event.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-border-default"
                />
                Run installation in background operation drawer
              </label>
            </div>

            {activeOperationId ? (
              <div
                data-testid="modpack-live-progress"
                className="rounded-xl border border-accent-primary/40 bg-surface-page p-4 space-y-3 min-w-0"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-accent-primary animate-pulse" />
                    <span className="text-xs font-bold text-text-primary truncate">
                      {activeOperation?.steps?.[0]?.message_key ||
                        "Installing modpack in background…"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="rounded-full bg-surface-elevated px-2 py-0.5 font-mono text-[10px] font-semibold text-text-secondary">
                      {activeOperation?.status ?? "QUEUED"}
                      {typeof activeOperation?.steps?.[0]?.progress === "number"
                        ? ` · ${Math.min(100, Math.max(0, Math.round(activeOperation.steps[0].progress)))}%`
                        : ""}
                    </span>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      data-testid="open-modpack-op-drawer-btn"
                      onClick={() => openOperationDrawer(activeOperationId)}
                    >
                      Open Progress Drawer
                    </Button>
                  </div>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-elevated">
                  <div
                    className="h-full rounded-full bg-accent-primary transition-all duration-300"
                    style={{
                      width: `${
                        typeof activeOperation?.steps?.[0]?.progress === "number"
                          ? Math.min(100, Math.max(4, Math.round(activeOperation.steps[0].progress)))
                          : 15
                      }%`,
                    }}
                  />
                </div>
                {typeof activeOperation?.steps?.[0]?.context?.current_file === "string" && (
                  <p className="font-mono text-[11px] text-text-muted break-all">
                    Downloading: {activeOperation.steps[0].context.current_file}
                  </p>
                )}
                {activeOperationLogs && activeOperationLogs.length > 0 && (
                  <div
                    data-testid="modpack-live-logs"
                    className="max-h-32 overflow-y-auto overflow-x-hidden rounded-lg border border-border-subtle bg-black/50 p-2.5 font-mono text-[11px] text-text-secondary space-y-1"
                  >
                    {activeOperationLogs.slice(-6).map((entry, idx) => (
                      <div key={`${entry.timestamp}-${idx}`} className="break-all">
                        {entry.line}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : isInstalling ? (
              <div
                data-testid="modpack-foreground-progress"
                className="rounded-xl border border-border-subtle bg-surface-page p-3 text-xs text-text-secondary flex items-center gap-2.5"
              >
                <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-accent-primary animate-pulse" />
                <span>
                  Downloading and verifying server mods &amp; overrides from CDN… This may take a
                  moment for large packs.
                </span>
              </div>
            ) : null}

            {installError && <Banner variant="danger" title={installError} />}
            </div>

            <div className="shrink-0 mt-4 pt-3 border-t border-border-subtle flex flex-wrap items-center justify-between gap-3">
              <Button
                type="button"
                variant="ghost"
                disabled={isInstalling && !activeOperationId}
                onClick={() => {
                  pendingAsyncBaseRef.current = null;
                  setActiveOperationId(null);
                  setIsInstalling(false);
                  setInspection(null);
                  setInspectError(null);
                  setManualError(null);
                  setInstallError(null);
                }}
              >
                Back to Upload
              </Button>
              <div className="flex flex-wrap items-center gap-2">
                {hasUnresolvedBlockers && (
                  <span className="text-xs text-text-muted">
                    Resolve all manual download blockers above to enable installation
                  </span>
                )}
                {activeOperationId && (
                  <Button
                    type="button"
                    variant="secondary"
                    data-testid="close-while-installing-btn"
                    onClick={onClose}
                  >
                    Continue in Background
                  </Button>
                )}
                <Button
                  type="button"
                  data-testid="confirm-install-modpack-btn"
                  variant="primary"
                  icon="download"
                  loading={isInstalling}
                  disabled={hasUnresolvedBlockers || isInstalling}
                  onClick={handleInstall}
                >
                  {activeOperationId ? "Installing…" : "Install Modpack"}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}

export function ModpackInstallWizardModal(props: ModpackInstallWizardModalProps) {
  if (!props.isOpen) return null;
  return <ModpackInstallWizardModalInner {...props} />;
}
