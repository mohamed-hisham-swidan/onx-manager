import { useMemo, useState } from "react";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import { Modal } from "@/components/ui/Modal";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import type {
  CompatibilityMatrixPayload,
  ManualDownloadBlockerItem,
  MatrixEntryItem,
  P55LoaderId,
  PrepareUpgradeTestResponse,
  ServerMode,
  ServerUpgradeResponse,
} from "@/server_manager/types";

export interface SafeUpgradeWizardModalProps {
  serverId: string;
  isOpen: boolean;
  onClose: () => void;
  serverMode?: ServerMode;
  serverType?: string | null;
  currentMc?: string | null;
  stagedPackId?: string | null;
  onApplied?: (upgrade: ServerUpgradeResponse) => void;
}

const LOADERS: P55LoaderId[] = ["fabric", "quilt", "forge", "neoforge", "paper"];

const SUPPORTED_LOADER_SET = new Set<string>(LOADERS);

function normalizeLoader(serverType: string | null | undefined): P55LoaderId {
  const norm = (serverType ?? "").trim().toLowerCase();
  if (SUPPORTED_LOADER_SET.has(norm)) return norm as P55LoaderId;
  if (norm === "purpur" || norm === "spigot" || norm === "bukkit") return "paper";
  return "fabric";
}

function statusTone(status: MatrixEntryItem["status"], isBlocker: boolean) {
  if (isBlocker) {
    return "border-status-danger-border bg-status-danger-bg text-status-danger";
  }
  if (status === "warning: unresolved_carried" || status === "warning") {
    return "border-status-warning-border bg-status-warning-bg text-status-warning";
  }
  if (status === "add") {
    return "border-status-success-border bg-status-success-bg text-status-success";
  }
  return "border-border-default bg-surface-elevated text-text-secondary";
}

function statusLabel(status: MatrixEntryItem["status"], isBlocker: boolean): string {
  if (status === "warning: unresolved_carried") {
    return "Unresolved (Carried Forward — Does Not Block Test/Upgrade)";
  }
  if (isBlocker) return status;
  if (status === "warning") return "warning";
  return status;
}

function blockerKey(blocker: ManualDownloadBlockerItem): string {
  return `${blocker.path}|${blocker.file_id ?? "none"}`;
}

function recomputeMatrix(
  matrix: CompatibilityMatrixPayload,
  entries: MatrixEntryItem[],
): CompatibilityMatrixPayload {
  const blockersCount = entries.filter((entry) => entry.is_blocker).length;
  const warningsCount = entries.filter(
    (entry) => entry.status === "warning" || entry.status === "warning: unresolved_carried",
  ).length;
  return {
    ...matrix,
    entries,
    blockers_count: blockersCount,
    warnings_count: warningsCount,
    has_blockers: blockersCount > 0,
  };
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="space-y-0.5">
      <h3 className="text-sm font-bold text-text-primary">{title}</h3>
      {subtitle && <p className="text-xs text-text-muted">{subtitle}</p>}
    </div>
  );
}

function AutoRollbackAlert({
  errorCode,
  errorMessage,
}: {
  errorCode: string | null;
  errorMessage: string | null;
}) {
  return (
    <div
      data-testid="upgrade-auto-rollback-alert"
      className="rounded-xl border border-status-danger-border bg-status-danger-bg p-4 space-y-1"
    >
      <div className="flex items-center gap-2 text-status-danger">
        <Icon name="alert" size={18} />
        <h4 className="text-sm font-bold">
          Health Gate Failed — Automatic Triad Rollback Restored Pre-Upgrade Server
        </h4>
      </div>
      <p className="text-xs text-text-secondary">
        Class A/B live files, the Class-C vault snapshot, and the pinned pre-upgrade
        world backup were restored atomically.
      </p>
      <p className="font-mono text-[11px] text-status-danger break-all">
        {errorCode ?? "HEALTH_GATE_FAILED"}
        {errorMessage ? ` — ${errorMessage}` : ""}
      </p>
    </div>
  );
}

function SafeUpgradeWizardModalInner({
  serverId,
  onClose,
  serverMode = "simple",
  serverType,
  currentMc,
  stagedPackId,
  onApplied,
}: SafeUpgradeWizardModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [targetMc, setTargetMc] = useState(currentMc ?? "");
  const [targetLoaderId, setTargetLoaderId] = useState<P55LoaderId>(
    normalizeLoader(serverType),
  );
  const [targetLoaderVersion, setTargetLoaderVersion] = useState("0.16.10");
  const [versionTypes, setVersionTypes] = useState<Record<string, boolean>>({
    release: true,
    beta: false,
    alpha: false,
  });

  const [isPlanning, setIsPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [upgrade, setUpgrade] = useState<ServerUpgradeResponse | null>(null);
  const [excludedPaths, setExcludedPaths] = useState<string[]>([]);

  const [manualUploadKey, setManualUploadKey] = useState<string | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);

  const [resolvedConflicts, setResolvedConflicts] = useState<Record<string, string>>({});
  const [conflictPath, setConflictPath] = useState("");
  const [conflictBody, setConflictBody] = useState("");

  const [isPreparing, setIsPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<PrepareUpgradeTestResponse["runtime"]>(null);

  const [isApplying, setIsApplying] = useState(false);
  const [applyAsyncMode, setApplyAsyncMode] = useState(false);
  const [applyError, setApplyError] = useState<ApiError | null>(null);
  const [applyResult, setApplyResult] = useState<ServerUpgradeResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const matrix = upgrade?.matrix ?? null;
  const entries = matrix?.entries ?? [];
  const selectedVersionTypes = (["release", "beta", "alpha"] as const).filter(
    (type) => versionTypes[type],
  );

  const gatedByStatus =
    upgrade?.status === "blocked" || upgrade?.status === "awaiting_manual_uploads";
  const hasBlockers = matrix?.has_blockers === true || gatedByStatus;
  const needsResolution = upgrade?.status === "needs_resolution";

  async function handlePlan() {
    if (typeof api.planServerUpgrade !== "function") return;
    if (!targetMc.trim() || !targetLoaderVersion.trim()) {
      setPlanError("Target Minecraft version and loader version are required.");
      return;
    }
    if (selectedVersionTypes.length === 0) {
      setPlanError("Select at least one release channel (release, beta, or alpha).");
      return;
    }
    setIsPlanning(true);
    setPlanError(null);
    setApplyError(null);
    setApplyResult(null);
    try {
      const response = await api.planServerUpgrade(serverId, {
        target_mc: targetMc.trim(),
        target_loader_id: targetLoaderId,
        target_loader_version: targetLoaderVersion.trim(),
        staged_pack_id: stagedPackId ?? null,
        excluded_paths: excludedPaths,
        version_types: selectedVersionTypes,
      });
      setUpgrade(response);
      setExcludedPaths(response.matrix?.excluded_paths ?? excludedPaths);
      setStep(2);
    } catch (error) {
      setPlanError(error instanceof ApiError ? error.message : "Compatibility planning failed");
    } finally {
      setIsPlanning(false);
    }
  }

  function toggleExcluded(path: string, excluded: boolean) {
    setExcludedPaths((previous) =>
      excluded ? [...new Set([...previous, path])] : previous.filter((item) => item !== path),
    );
  }

  async function handleReevaluate() {
    if (typeof api.planServerUpgrade !== "function") return;
    setIsPlanning(true);
    setPlanError(null);
    try {
      const response = await api.planServerUpgrade(serverId, {
        target_mc: targetMc.trim(),
        target_loader_id: targetLoaderId,
        target_loader_version: targetLoaderVersion.trim(),
        staged_pack_id: stagedPackId ?? null,
        excluded_paths: excludedPaths,
        version_types: selectedVersionTypes,
      });
      setUpgrade(response);
      setExcludedPaths(response.matrix?.excluded_paths ?? excludedPaths);
    } catch (error) {
      setPlanError(error instanceof ApiError ? error.message : "Matrix re-evaluation failed");
    } finally {
      setIsPlanning(false);
    }
  }

  async function handleManualUpload(
    blocker: ManualDownloadBlockerItem,
    uploadedFile: File | undefined,
    entryPath: string,
  ) {
    if (!uploadedFile || !upgrade || typeof api.resolveUpgradeManualUpload !== "function") return;
    const key = blockerKey(blocker);
    setManualUploadKey(key);
    setManualError(null);
    try {
      const response = await api.resolveUpgradeManualUpload(
        serverId,
        upgrade.id,
        uploadedFile,
        { file_id: blocker.file_id, path: blocker.path },
      );
      if (response.matrix) {
        setUpgrade(response);
      } else {
        const resolved: ManualDownloadBlockerItem = { ...blocker, resolved: true };
        const patchedEntries = entries.map((entry) =>
          entry.path === entryPath || entry.path === blocker.path
            ? {
                ...entry,
                status: "add" as const,
                is_blocker: false,
                manual_blocker: resolved,
              }
            : entry,
        );
        setUpgrade({
          ...upgrade,
          ...response,
          matrix: matrix ? recomputeMatrix(matrix, patchedEntries) : response.matrix,
        });
      }
    } catch (error) {
      setManualError(
        error instanceof ApiError ? error.message : "Manual upload verification failed",
      );
    } finally {
      setManualUploadKey(null);
    }
  }

  async function handlePrepareTest() {
    if (!upgrade || typeof api.prepareServerUpgradeTest !== "function") return;
    setIsPreparing(true);
    setPrepareError(null);
    setNotice(null);
    try {
      const response = await api.prepareServerUpgradeTest(serverId, upgrade.id, {
        resolved_conflicts: resolvedConflicts,
        start_test: true,
      });
      setUpgrade(response.upgrade);
      setRuntime(response.runtime);
      if (response.upgrade.status === "needs_resolution") {
        setNotice("Three-way merge conflicts must be resolved before the test can start.");
      } else {
        setNotice("Isolated test container prepared from the upgrade branch.");
      }
    } catch (error) {
      setPrepareError(
        error instanceof ApiError ? error.message : "Preparing the isolated test failed",
      );
    } finally {
      setIsPreparing(false);
    }
  }

  async function handleApply() {
    if (!upgrade || typeof api.applyServerUpgrade !== "function") return;
    setIsApplying(true);
    setApplyError(null);
    setApplyResult(null);
    setNotice(null);
    try {
      const response = await api.applyServerUpgrade(serverId, upgrade.id, {
        resolved_conflicts: resolvedConflicts,
        async_mode: applyAsyncMode,
      });
      setUpgrade(response);
      setApplyResult(response);
      onApplied?.(response);
    } catch (error) {
      if (error instanceof ApiError) {
        setApplyError(error);
      } else {
        setApplyError(
          new ApiError(0, "UNKNOWN", error instanceof Error ? error.message : "Upgrade failed"),
        );
      }
    } finally {
      setIsApplying(false);
    }
  }

  async function handleConfirm() {
    if (!applyResult || typeof api.confirmServerUpgrade !== "function") return;
    try {
      const response = await api.confirmServerUpgrade(serverId, applyResult.id);
      setApplyResult(response);
      setUpgrade(response);
      setNotice("Upgrade confirmed. The rollback backup pin was released.");
    } catch (error) {
      setApplyError(
        error instanceof ApiError
          ? error
          : new ApiError(0, "UNKNOWN", "Confirm failed"),
      );
    }
  }

  function addConflictEntry() {
    const path = conflictPath.trim();
    if (!path) return;
    setResolvedConflicts((previous) => ({
      ...previous,
      [path]: conflictBody,
    }));
    setConflictPath("");
    setConflictBody("");
  }

  function removeConflictEntry(path: string) {
    setResolvedConflicts((previous) => {
      const next = { ...previous };
      delete next[path];
      return next;
    });
  }

  const rolledBack =
    applyResult?.status === "rolled_back" ||
    applyError?.code === "HEALTH_GATE_FAILED" ||
    applyResult?.error_code === "HEALTH_GATE_FAILED";

  return (
    <Modal
      open
      onClose={onClose}
      size="2xl"
      title="1-Click Safe Upgrade"
      description="Plan the target version, review the hash-only compatibility matrix, then apply behind the 4-step Health Gate."
      closeOnBackdrop={!isApplying && !isPreparing}
      closeOnEscape={!isApplying && !isPreparing}
    >
      <div className="space-y-5 max-h-[74vh] overflow-y-auto pr-1">
        {applyResult?.status === "active_pinned" && !rolledBack ? (
          <div className="space-y-4">
            <Banner
              variant="success"
              title="Health Gate Passed — Upgrade Active & Rollback Snapshot Pinned"
              description={`Live server is now running MC ${applyResult.target_mc} (${applyResult.target_loader_id} ${applyResult.target_loader_version}). Pre-upgrade backup ${applyResult.pre_upgrade_backup_id ?? "pinned"} remains available until confirmation.`}
            />
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                data-testid="confirm-upgrade-unpin-btn"
                variant="primary"
                icon="check"
                onClick={handleConfirm}
              >
                Confirm Upgrade & Unpin Rollback Backup
              </Button>
              <Button type="button" variant="secondary" onClick={onClose}>
                Close (Keep Pinned)
              </Button>
            </div>
            {notice && <Banner variant="info" title={notice} />}
          </div>
        ) : (
          <>
            {rolledBack && (
              <AutoRollbackAlert
                errorCode={applyError?.code ?? applyResult?.error_code ?? null}
                errorMessage={applyError?.message ?? applyResult?.error_message ?? null}
              />
            )}

            <div className="flex items-center gap-2">
              {[1, 2, 3].map((item) => (
                <span
                  key={item}
                  className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold ${
                    step === item
                      ? "bg-accent-primary text-white"
                      : step > item
                        ? "bg-status-success-bg text-status-success border border-status-success-border"
                        : "bg-surface-elevated text-text-muted border border-border-default"
                  }`}
                >
                  {item}
                </span>
              ))}
              <span className="text-xs font-semibold text-text-secondary">
                {step === 1
                  ? "Select target"
                  : step === 2
                    ? "Compatibility matrix"
                    : serverMode === "advanced"
                      ? "Branch test & live apply"
                      : "1-Click backup, staging swap & Health Gate"}
              </span>
            </div>

            {step === 1 && (
              <div className="space-y-4">
                <SectionHeader
                  title="Select Target Version (or Staged Modpack)"
                  subtitle="The matrix is hash-only and never writes to the live server."
                />
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <label htmlFor="upgrade-target-mc" className="mb-1 block text-[11px] font-medium text-text-muted">
                      Target Minecraft
                    </label>
                    <input
                      id="upgrade-target-mc"
                      value={targetMc}
                      onChange={(event) => setTargetMc(event.target.value)}
                      placeholder="1.21.4"
                      className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
                    />
                  </div>
                  <div>
                    <label htmlFor="upgrade-target-loader" className="mb-1 block text-[11px] font-medium text-text-muted">
                      Target Loader
                    </label>
                    <select
                      id="upgrade-target-loader"
                      value={targetLoaderId}
                      onChange={(event) =>
                        setTargetLoaderId(event.target.value as P55LoaderId)
                      }
                      className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-sm text-text-primary focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
                    >
                      {LOADERS.map((loader) => (
                        <option key={loader} value={loader}>
                          {loader}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="upgrade-target-loader-version" className="mb-1 block text-[11px] font-medium text-text-muted">
                      Target Loader Version
                    </label>
                    <input
                      id="upgrade-target-loader-version"
                      value={targetLoaderVersion}
                      onChange={(event) => setTargetLoaderVersion(event.target.value)}
                      placeholder="0.16.10"
                      className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <p className="text-[11px] font-medium text-text-muted">Release Channels</p>
                  <div className="flex flex-wrap gap-3">
                    {(["release", "beta", "alpha"] as const).map((type) => (
                      <label key={type} className="inline-flex items-center gap-2 text-xs text-text-secondary">
                        <input
                          type="checkbox"
                          checked={versionTypes[type]}
                          onChange={(event) =>
                            setVersionTypes((previous) => ({
                              ...previous,
                              [type]: event.target.checked,
                            }))
                          }
                          className="h-4 w-4 rounded border-border-default"
                        />
                        {type}
                      </label>
                    ))}
                  </div>
                </div>

                {stagedPackId && (
                  <p className="text-xs text-text-muted">
                    Planning from staged modpack{" "}
                    <span className="font-mono text-text-secondary">{stagedPackId}</span>.
                  </p>
                )}

                {planError && <Banner variant="danger" title={planError} />}

                <div className="flex justify-end">
                  <Button
                    type="button"
                    data-testid="plan-upgrade-btn"
                    variant="primary"
                    icon="activity"
                    loading={isPlanning}
                    onClick={handlePlan}
                  >
                    Run Compatibility Matrix
                  </Button>
                </div>
              </div>
            )}

            {step === 2 && upgrade && (
              <div className="space-y-4" data-testid="upgrade-compatibility-matrix">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <SectionHeader
                    title={`Compatibility Matrix — MC ${matrix?.target_mc ?? targetMc} · ${matrix?.target_loader.id ?? targetLoaderId} ${matrix?.target_loader.version ?? targetLoaderVersion}`}
                    subtitle={`Source MC ${matrix?.source_mc ?? upgrade.source_mc ?? "unknown"} → target ${matrix?.target_mc ?? targetMc}`}
                  />
                  <LoaderBadge loader={upgrade.target_loader_id} />
                </div>

                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {[
                    ["Total Entries", entries.length],
                    ["Blockers", matrix?.blockers_count ?? 0],
                    ["Warnings", matrix?.warnings_count ?? 0],
                    ["BFS Depth", matrix?.bfs_depth_reached ?? 0],
                    ["Projects Resolved", matrix?.bfs_projects_resolved ?? 0],
                  ].map(([label, value]) => (
                    <div
                      key={String(label)}
                      className="rounded-lg border border-border-subtle bg-surface-page p-2.5"
                    >
                      <p className="text-[10px] uppercase tracking-wider text-text-muted">
                        {label}
                      </p>
                      <p className="mt-0.5 font-mono text-sm font-bold text-text-primary">
                        {value}
                      </p>
                    </div>
                  ))}
                </div>

                {matrix?.has_blockers && (
                  <Banner
                    variant="danger"
                    title="Upgrade blocked by compatibility matrix"
                    description="Exclude blocking entries or upload the required manual downloads. Live apply stays disabled until every blocker is resolved."
                  />
                )}

                {needsResolution && (
                  <Banner
                    variant="warning"
                    title="3-way merge conflicts need resolution"
                    description="Provide clean resolved content for every conflicting file before preparing the test or applying."
                  />
                )}

                <div className="overflow-hidden rounded-xl border border-border-default">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border-subtle bg-surface-page/60 text-left text-[11px] text-text-muted">
                        <th className="px-3 py-2 font-medium">Path</th>
                        <th className="px-3 py-2 font-medium">Status</th>
                        <th className="px-3 py-2 font-medium">Detail</th>
                        <th className="px-3 py-2 font-medium">Exclude</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entries.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="px-3 py-4 text-xs text-text-muted">
                            No matrix entries returned.
                          </td>
                        </tr>
                      ) : (
                        entries.map((entry) => (
                          <tr
                            key={entry.path}
                            className="border-b border-border-subtle last:border-b-0 align-top"
                          >
                            <td className="px-3 py-2">
                              <span className="font-mono text-[11px] text-text-primary break-all">
                                {entry.path}
                              </span>
                              {entry.required_by.length > 0 && (
                                <p className="mt-0.5 text-[10px] text-text-muted">
                                  required by {entry.required_by.join(", ")}
                                </p>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              <span
                                className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${statusTone(entry.status, entry.is_blocker)}`}
                              >
                                {statusLabel(entry.status, entry.is_blocker)}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-[11px] text-text-muted max-w-xs">
                              {entry.detail || "—"}
                              {entry.status === "blocker: manual_download_required" &&
                                entry.manual_blocker && (
                                  <div className="mt-1.5 space-y-1">
                                    <p className="font-mono text-[10px] break-all">
                                      {entry.manual_blocker.filename || entry.path}
                                    </p>
                                    {entry.manual_blocker.webpage_url && (
                                      <a
                                        href={entry.manual_blocker.webpage_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-accent-primary hover:underline"
                                      >
                                        Open download page
                                      </a>
                                    )}
                                    <input
                                      data-testid={`upgrade-manual-upload-${entry.manual_blocker.file_id ?? entry.manual_blocker.path}`}
                                      type="file"
                                      onChange={(event) => {
                                        void handleManualUpload(
                                          entry.manual_blocker as ManualDownloadBlockerItem,
                                          event.target.files?.[0],
                                          entry.path,
                                        );
                                        event.target.value = "";
                                      }}
                                      className="block w-full text-[10px] text-text-secondary file:mr-2 file:rounded-md file:border-0 file:bg-surface-elevated file:px-2 file:py-0.5 file:text-[10px] file:font-medium file:text-text-primary"
                                    />
                                    {manualUploadKey ===
                                      blockerKey(entry.manual_blocker) && (
                                      <span className="text-[10px] text-text-muted">
                                        Verifying…
                                      </span>
                                    )}
                                  </div>
                                )}
                            </td>
                            <td className="px-3 py-2">
                              {entry.path.startsWith("mods/") ||
                              entry.path.startsWith("plugins/") ? (
                                <input
                                  data-testid={`exclude-entry-${entry.path}`}
                                  type="checkbox"
                                  aria-label={`Exclude ${entry.path} from upgrade`}
                                  checked={excludedPaths.includes(entry.path)}
                                  onChange={(event) =>
                                    toggleExcluded(entry.path, event.target.checked)
                                  }
                                  className="h-4 w-4 rounded border-border-default"
                                />
                              ) : (
                                <span className="text-[10px] text-text-muted">—</span>
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                {manualError && <Banner variant="danger" title={manualError} />}

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    icon="restart"
                    loading={isPlanning}
                    onClick={handleReevaluate}
                  >
                    Re-evaluate Matrix
                  </Button>
                  <div className="flex items-center gap-2">
                    <Button type="button" variant="ghost" onClick={() => setStep(1)}>
                      Back
                    </Button>
                    <Button
                      type="button"
                      data-testid="continue-upgrade-btn"
                      variant="primary"
                      icon="chevron-right"
                      iconPosition="right"
                      disabled={hasBlockers}
                      onClick={() => setStep(3)}
                    >
                      Continue to Apply
                    </Button>
                  </div>
                </div>
                {hasBlockers && (
                  <p className="text-right text-xs text-text-muted">
                    Resolve all blockers and re-evaluate the matrix to continue.
                  </p>
                )}
              </div>
            )}

            {step === 3 && upgrade && (
              <div className="space-y-4">
                {needsResolution && (
                  <div className="rounded-xl border border-status-warning-border bg-status-warning-bg/40 p-4 space-y-3">
                    <SectionHeader
                      title="3-Way Merge Conflict Resolver"
                      subtitle="Provide clean, conflict-free content for each file before retrying."
                    />
                    <div className="space-y-2">
                      {Object.entries(resolvedConflicts).map(([path, body]) => (
                        <div
                          key={path}
                          className="rounded-lg border border-border-subtle bg-surface-card p-3 space-y-1"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-mono text-[11px] text-text-primary break-all">
                              {path}
                            </span>
                            <button
                              type="button"
                              aria-label={`Remove resolution for ${path}`}
                              onClick={() => removeConflictEntry(path)}
                              className="rounded p-0.5 text-text-muted hover:bg-surface-hover hover:text-text-primary"
                            >
                              <Icon name="x" size={12} />
                            </button>
                          </div>
                          <p className="text-[10px] text-text-muted">
                            {body.length} characters of resolved content staged.
                          </p>
                        </div>
                      ))}
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
                      <div>
                        <label htmlFor="conflict-path" className="mb-1 block text-[10px] font-medium text-text-muted">
                          Conflict File Path
                        </label>
                        <input
                          id="conflict-path"
                          value={conflictPath}
                          onChange={(event) => setConflictPath(event.target.value)}
                          placeholder="config/example.toml"
                          className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none"
                        />
                      </div>
                      <div>
                        <label htmlFor="conflict-body" className="mb-1 block text-[10px] font-medium text-text-muted">
                          Resolved Content
                        </label>
                        <textarea
                          id="conflict-body"
                          value={conflictBody}
                          onChange={(event) => setConflictBody(event.target.value)}
                          rows={2}
                          className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1 font-mono text-xs text-text-primary focus:border-accent-primary focus:outline-none"
                        />
                      </div>
                      <Button type="button" size="sm" variant="secondary" onClick={addConflictEntry}>
                        Add Resolution
                      </Button>
                    </div>
                  </div>
                )}

                {serverMode === "advanced" ? (
                  <div className="space-y-4">
                    <div className="rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3">
                      <SectionHeader
                        title="Step 3A: Isolated Branch & Disposable World Test"
                        subtitle="Prepare a disposable upgrade branch and test container on a separate host port set before touching main."
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          data-testid="prepare-upgrade-test-btn"
                          variant="secondary"
                          icon="server"
                          loading={isPreparing}
                          disabled={hasBlockers}
                          onClick={handlePrepareTest}
                        >
                          Prepare upgrade/{upgrade.target_mc} Branch &amp; Start Isolated Test
                        </Button>
                        {upgrade.upgrade_branch && (
                          <span className="font-mono text-[11px] text-text-secondary">
                            Branch: {upgrade.upgrade_branch}
                          </span>
                        )}
                      </div>
                      {prepareError && <Banner variant="danger" title={prepareError} />}
                      {notice && <Banner variant="info" title={notice} />}
                      {(runtime || upgrade.data_template_id) && (
                        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3 text-xs">
                          <div className="rounded-lg border border-border-subtle bg-surface-page p-2.5">
                            <dt className="text-[10px] uppercase tracking-wider text-text-muted">
                              Data Template Clone
                            </dt>
                            <dd className="mt-0.5 font-mono text-[11px] break-all">
                              {runtime?.data_template_id ?? upgrade.data_template_id ?? "—"}
                            </dd>
                          </div>
                          <div className="rounded-lg border border-border-subtle bg-surface-page p-2.5">
                            <dt className="text-[10px] uppercase tracking-wider text-text-muted">
                              Isolated Container
                            </dt>
                            <dd className="mt-0.5 font-mono text-[11px] break-all">
                              {runtime?.container_name ?? "Not started"}
                            </dd>
                          </div>
                          <div className="rounded-lg border border-border-subtle bg-surface-page p-2.5">
                            <dt className="text-[10px] uppercase tracking-wider text-text-muted">
                              Host Port Set
                            </dt>
                            <dd className="mt-0.5 font-mono text-[11px]">
                              {runtime
                                ? `game ${runtime.port_set.game_port} · rcon ${runtime.port_set.rcon_port} · query ${runtime.port_set.query_port ?? "—"}`
                                : "—"}
                            </dd>
                          </div>
                        </dl>
                      )}
                    </div>

                    <div className="rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3">
                      <SectionHeader
                        title="Step 3B: Merge Upgrade to main & Refresh Live"
                        subtitle="Quiesce, pin the pre-upgrade backup and Class-C snapshot, merge the upgrade branch into main, then run the 5-step Clean Export and 4-step race-free Health Gate."
                      />
                      <Button
                        type="button"
                        data-testid="apply-upgrade-live-btn"
                        variant="primary"
                        icon="download"
                        loading={isApplying}
                        disabled={hasBlockers}
                        onClick={handleApply}
                      >
                        Merge Upgrade to main &amp; Refresh Live
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3">
                    <SectionHeader
                      title="Step 3: 1-Click Backup, Staging Swap & Health Gate"
                      subtitle="Pinned pre-upgrade backup + Class-C snapshot, Git-free 5-step <server_root>.staging/ swap around live world*, then the 4-step Health Gate."
                    />
                    <p className="text-xs text-text-secondary leading-relaxed">
                      Simple Mode performs a 1-Click Safe Upgrade without Git branches:
                      quiesce and pin backups, build the staging tree, swap worlds,
                      start the server behind the race-free Health Gate, and
                      automatically restore the triad (Class A/B, Class-C, Class-E) if
                      the gate fails.
                    </p>
                    <Button
                      type="button"
                      data-testid="apply-upgrade-live-btn"
                      variant="primary"
                      icon="download"
                      loading={isApplying}
                      disabled={hasBlockers}
                      onClick={handleApply}
                    >
                      Apply 1-Click Safe Upgrade
                    </Button>
                  </div>
                )}

                {applyError && !rolledBack && (
                  <Banner variant="danger" title={applyError.message} />
                )}

                <label className="flex items-center gap-2 text-xs text-text-secondary">
                  <input
                    type="checkbox"
                    checked={applyAsyncMode}
                    onChange={(event) => setApplyAsyncMode(event.target.checked)}
                    className="h-4 w-4 rounded border-border-default"
                  />
                  Run apply in the background operation drawer
                </label>

                <div className="flex justify-between">
                  <Button type="button" variant="ghost" onClick={() => setStep(2)}>
                    Back to Matrix
                  </Button>
                  <Button type="button" variant="secondary" onClick={onClose}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

export function SafeUpgradeWizardModal(props: SafeUpgradeWizardModalProps) {
  if (!props.isOpen) return null;
  return <SafeUpgradeWizardModalInner {...props} />;
}
