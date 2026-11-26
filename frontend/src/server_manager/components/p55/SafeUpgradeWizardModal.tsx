import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { LoaderBadge } from "@/components/ui/LoaderBadge";
import {
  HealthGateChecklist,
  OperationStepper,
} from "@/operations/components/OperationStepper";
import type { OperationHealthCheckItem } from "@/operations/types";
import { useOperationStore } from "@/operations/stores/operationStore";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import { useUIStore } from "@/stores/uiStore";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
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

const LOADERS: P55LoaderId[] = [
  "fabric",
  "quilt",
  "forge",
  "neoforge",
  "paper",
  "purpur",
];
const SUPPORTED_LOADER_SET = new Set<string>(LOADERS);
const TERMINAL_UPGRADE_STATUSES = new Set(["confirmed", "rolled_back", "failed"]);

function readSavedUpgradeStep(upgradeId: string): 1 | 2 | 3 | null {
  try {
    const raw = window.sessionStorage.getItem(`onx.upgradeStep.${upgradeId}`);
    if (raw === "2") return 2;
    if (raw === "3") return 3;
    return null;
  } catch {
    return null;
  }
}

function writeSavedUpgradeStep(upgradeId: string, step: 1 | 2 | 3): void {
  try {
    window.sessionStorage.setItem(`onx.upgradeStep.${upgradeId}`, String(step));
  } catch {
    // Ignore storage unavailability in test/privacy contexts
  }
}

const LOADER_DISPLAY_NAMES: Record<P55LoaderId, string> = {
  fabric: "Fabric",
  quilt: "Quilt",
  forge: "Forge",
  neoforge: "NeoForge",
  paper: "Paper",
  purpur: "Purpur",
};

function formatLoaderName(loader: string | null | undefined): string {
  const norm = (loader ?? "").trim().toLowerCase();
  if (norm in LOADER_DISPLAY_NAMES) {
    return LOADER_DISPLAY_NAMES[norm as P55LoaderId];
  }
  return norm ? norm.charAt(0).toUpperCase() + norm.slice(1) : "Unknown";
}

function resolveInitialLoader(serverType: string | null | undefined): {
  loader: P55LoaderId;
  isUnsupportedSource: boolean;
} {
  const norm = (serverType ?? "").trim().toLowerCase();
  if (SUPPORTED_LOADER_SET.has(norm)) {
    return { loader: norm as P55LoaderId, isUnsupportedSource: false };
  }
  if (norm === "spigot" || norm === "bukkit" || norm === "folia") {
    return { loader: "paper", isUnsupportedSource: false };
  }
  return { loader: "paper", isUnsupportedSource: Boolean(norm) };
}

function defaultLoaderVersionFor(loader: P55LoaderId): string {
  switch (loader) {
    case "fabric":
    case "quilt":
      return "0.16.10";
    case "paper":
    case "purpur":
      return "latest";
    case "forge":
    case "neoforge":
      return "latest";
  }
}

function loaderVersionPlaceholder(loader: P55LoaderId): string {
  switch (loader) {
    case "fabric":
    case "quilt":
      return "e.g. 0.16.10";
    case "paper":
    case "purpur":
      return "e.g. latest or build #";
    case "forge":
      return "e.g. 47.3.0 or latest";
    case "neoforge":
      return "e.g. 21.1.72 or latest";
  }
}

function isConcurrencyConflictError(
  message: string,
  code?: string | null,
): boolean {
  const lower = `${code ?? ""} ${message}`.toLowerCase();
  return (
    lower.includes("mutating operation") ||
    lower.includes("is already active") ||
    lower.includes("operation_concurrency_conflict")
  );
}

function extractOperationIdFromError(error: ApiError | null): string | null {
  if (!error?.detail || typeof error.detail !== "object" || Array.isArray(error.detail)) {
    return null;
  }
  const candidate = (error.detail as Record<string, unknown>).operation_id;
  return typeof candidate === "string" && candidate.trim().length > 0
    ? candidate.trim()
    : null;
}

function buildUpgradeRecoveryHint(
  message: string,
  code?: string | null,
): string {
  const lower = `${code ?? ""} ${message}`.toLowerCase();
  if (isConcurrencyConflictError(message, code)) {
    return "A version change operation is already running in the background for this server.";
  }
  if (
    lower.includes("previous tree retained") ||
    lower.includes("until confirmation") ||
    lower.includes("until_confirm") ||
    lower.includes(".prev")
  ) {
    return "A previous version change is still waiting for confirmation (retaining its rollback backup). Confirm the previous upgrade or roll it back from the banner above before starting a new version change.";
  }
  if (lower.includes("no changes to commit")) {
    return "The upgrade branch already matches the target lockfile. Retry Apply or click Start Fresh to re-plan.";
  }
  if (
    lower.includes("port") ||
    lower.includes("concurrent") ||
    lower.includes("docker") ||
    lower.includes("container")
  ) {
    return "Check running test containers or host port availability, or click Discard Test and retry.";
  }
  if (
    lower.includes("404") ||
    lower.includes("not found") ||
    lower.includes("download") ||
    lower.includes("allowlist")
  ) {
    return "Verify the target Minecraft version and loader build exist upstream, or choose another target version.";
  }
  if (lower.includes("conflict") || lower.includes("needs_resolution")) {
    return "Resolve the conflicting config files above or click Start Fresh to re-plan from the current server state.";
  }
  return "Review the error above, then retry or click Start Fresh / Discard Test to reset this plan.";
}

function parseNumericMcTuple(raw: string | null | undefined): number[] | null {
  const cleaned = (raw ?? "").trim().split("-")[0] ?? "";
  if (!cleaned) return null;
  const parts = cleaned.split(".");
  if (parts.length < 2 || parts.length > 3) return null;
  const nums: number[] = [];
  for (const part of parts) {
    if (!/^\d+$/.test(part)) return null;
    nums.push(Number.parseInt(part, 10));
  }
  while (nums.length < 3) nums.push(0);
  return nums;
}

function isMcDowngrade(
  currentMc: string | null | undefined,
  targetMc: string | null | undefined,
): boolean {
  const cur = parseNumericMcTuple(currentMc);
  const tgt = parseNumericMcTuple(targetMc);
  if (!cur || !tgt) return false;
  for (let i = 0; i < 3; i += 1) {
    if (tgt[i] < cur[i]) return true;
    if (tgt[i] > cur[i]) return false;
  }
  return false;
}

function resolveActionBadge(entry: MatrixEntryItem): {
  label: string;
  tone: string;
} {
  const labelKey = entry.action_label ?? "";

  if (
    entry.excluded_by_operator ||
    entry.status === "remove" ||
    labelKey === "excluded"
  ) {
    return {
      label: "Excluded",
      tone: "border-border-subtle bg-surface-muted text-text-muted",
    };
  }
  if (entry.kept_by_operator || labelKey === "kept_current") {
    return {
      label: "Kept Current",
      tone: "border-status-info-border bg-status-info-bg text-status-info",
    };
  }
  if (entry.status === "add") {
    return {
      label: "Add Dependency",
      tone: "border-status-success-border bg-status-success-bg text-status-success",
    };
  }
  if (entry.status === "carried" || labelKey === "will_upgrade") {
    return {
      label: "Will Upgrade",
      tone: "border-status-success-border bg-status-success-bg text-status-success",
    };
  }
  if (entry.status === "unchanged" || labelKey === "compatible") {
    return {
      label: "Compatible (No Change)",
      tone: "border-status-success-border bg-status-success-bg text-status-success",
    };
  }
  if (
    entry.status === "warning: unresolved_carried" ||
    labelKey === "unresolved_carried"
  ) {
    return {
      label: "Custom / Untracked (Carried)",
      tone: "border-status-warning-border bg-status-warning-bg text-status-warning",
    };
  }
  if (entry.status === "warning") {
    return {
      label: "Advisory",
      tone: "border-status-warning-border bg-status-warning-bg text-status-warning",
    };
  }
  if (
    entry.status === "blocker: manual_download_required" ||
    labelKey === "manual_upload"
  ) {
    return {
      label: "Manual Upload Required",
      tone: "border-status-danger-border bg-status-danger-bg text-status-danger",
    };
  }
  if (entry.status === "blocker: no_target_build") {
    return {
      label: "No Compatible Build",
      tone: "border-status-danger-border bg-status-danger-bg text-status-danger",
    };
  }
  if (
    entry.status === "blocker: missing_dependency" ||
    entry.status === "blocker: missing_transitive_dependency"
  ) {
    return {
      label: "Missing Dependency",
      tone: "border-status-danger-border bg-status-danger-bg text-status-danger",
    };
  }
  if (entry.status === "blocker: incompatible") {
    return {
      label: "Incompatible",
      tone: "border-status-danger-border bg-status-danger-bg text-status-danger",
    };
  }
  if (entry.status === "blocker: untrusted_host") {
    return {
      label: "Untrusted Download Host",
      tone: "border-status-danger-border bg-status-danger-bg text-status-danger",
    };
  }
  return {
    label: entry.is_blocker ? "Blocker" : entry.status,
    tone: entry.is_blocker
      ? "border-status-danger-border bg-status-danger-bg text-status-danger"
      : "border-border-default bg-surface-muted text-text-secondary",
  };
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
    (entry) =>
      entry.status === "warning" ||
      entry.status === "warning: unresolved_carried",
  ).length;
  return {
    ...matrix,
    entries,
    blockers_count: blockersCount,
    warnings_count: warningsCount,
    has_blockers: blockersCount > 0,
  };
}

function sameSortedList(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sa = [...a].sort();
  const sb = [...b].sort();
  return sa.every((v, i) => v === sb[i]);
}

function SectionHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="space-y-0.5">
      <h3 className="text-sm font-bold text-text-primary">{title}</h3>
      {subtitle && <p className="text-xs text-text-muted">{subtitle}</p>}
    </div>
  );
}

function readDismissedOutcomeId(serverId: string): string | null {
  try {
    return window.sessionStorage.getItem(`onx.dismissedUpgradeOutcome.${serverId}`);
  } catch {
    return null;
  }
}

function writeDismissedOutcomeId(serverId: string, upgradeId: string): void {
  try {
    window.sessionStorage.setItem(`onx.dismissedUpgradeOutcome.${serverId}`, upgradeId);
  } catch {
    // ignore storage errors
  }
}

const STEP_LABELS: Record<string, string> = {
  PREPARE_AND_DOWNLOAD: "Preparing backup & downloading target artifacts",
  STAGE_FILES: "Staging new server core, plugins & configs",
  SWAP_LIVE_TREE: "Swapping live tree safely",
  HEALTH_GATE: "Booting server & running 5-check Health Gate",
  FINALIZE: "Finalizing version change",
};

function AutoRollbackAlert({
  errorCode,
  errorMessage,
  sourceLabel,
  isFailedOnly = false,
  onDismiss,
  onTryAgain,
}: {
  errorCode: string | null;
  errorMessage: string | null;
  sourceLabel?: string;
  isFailedOnly?: boolean;
  onDismiss?: () => void;
  onTryAgain?: () => void;
}) {
  return (
    <div
      data-testid="upgrade-auto-rollback-alert"
      className="rounded-xl border border-status-danger-border bg-status-danger-bg p-4 space-y-2.5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-status-danger">
          <Icon name="alert" size={18} />
          <h4 className="text-sm font-bold">
            {isFailedOnly
              ? "Version Change Failed"
              : "Health Gate Failed — Automatic Triad Rollback Restored Pre-Upgrade Server"}
          </h4>
        </div>
        <span
          data-testid="upgrade-outcome-badge"
          className="inline-flex items-center rounded-full border border-status-danger-border bg-surface-card px-2 py-0.5 text-[10px] font-semibold text-status-danger"
        >
          {isFailedOnly ? "Version Change Failed" : "Rolled Back Automatically"}
        </span>
      </div>
      <p className="text-xs text-text-secondary">
        {isFailedOnly
          ? "No unverified upgrade changes remain active."
          : sourceLabel
            ? `Your server was restored to ${sourceLabel} safely (server files, configs, and world backup intact).`
            : "Your server was restored to its pre-upgrade state safely."}
      </p>
      <p className="font-mono text-[11px] text-status-danger break-words">
        {errorCode ?? "HEALTH_GATE_FAILED"}
        {errorMessage ? ` — ${errorMessage}` : ""}
      </p>
      {(onDismiss || onTryAgain) && (
        <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
          {onDismiss && (
            <Button
              type="button"
              data-testid="outcome-dismiss-btn"
              size="sm"
              variant="ghost"
              onClick={onDismiss}
            >
              Dismiss
            </Button>
          )}
          {onTryAgain && (
            <Button
              type="button"
              data-testid="outcome-try-again-btn"
              size="sm"
              variant="primary"
              icon="restart"
              onClick={onTryAgain}
            >
              Try Again
            </Button>
          )}
        </div>
      )}
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
  const queryClient = useQueryClient();
  const branchCtx = useServerBranchContext();
  const setChangeVersionOpen = useUIStore((s) => s.setChangeVersionOpen);

  useEffect(() => {
    setChangeVersionOpen(true);
    return () => {
      setChangeVersionOpen(false);
    };
  }, [setChangeVersionOpen]);

  const initialLoader = useMemo(
    () => resolveInitialLoader(serverType),
    [serverType],
  );

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [targetMc, setTargetMc] = useState(currentMc ?? "");
  const [targetLoaderId, setTargetLoaderId] = useState<P55LoaderId>(
    initialLoader.loader,
  );
  const [targetLoaderVersion, setTargetLoaderVersion] = useState(
    defaultLoaderVersionFor(initialLoader.loader),
  );
  const [versionTypes, setVersionTypes] = useState<Record<string, boolean>>({
    release: true,
    beta: false,
    alpha: false,
  });

  const upgradesQuery = useQuery({
    queryKey: queryKeys.p55.upgrades(serverId),
    queryFn: async () => api.listServerUpgrades?.(serverId) ?? null,
    enabled: typeof api.listServerUpgrades === "function" && Boolean(serverId),
    staleTime: 2_000,
    refetchInterval: (query) => {
      const current = query.state.data?.active_upgrade;
      return current?.status === "applying" ? 1_500 : false;
    },
    retry: false,
  });

  const availableVersionsQuery = useQuery({
    queryKey: queryKeys.software.versions(targetLoaderId),
    queryFn: () => api.listSoftwareVersions(targetLoaderId),
    enabled: typeof api.listSoftwareVersions === "function",
    staleTime: 60_000,
    retry: false,
  });
  const availableMcVersions = availableVersionsQuery.data ?? [];

  const exposureQuery = useQuery({
    queryKey: ["p55", "server-exposure", serverId],
    queryFn: async () => api.getServerExposure?.(serverId, "main") ?? null,
    enabled: typeof api.getServerExposure === "function" && Boolean(serverId),
    staleTime: 30_000,
    retry: false,
  });
  const exposureData = exposureQuery.data ?? null;
  const javaExposureTarget =
    exposureData?.targets?.find(
      (t) => t.service_type === "java" && Boolean(t.public_address),
    ) ??
    exposureData?.targets?.find((t) => Boolean(t.public_address)) ??
    null;
  const hasActiveExposure = Boolean(
    exposureData &&
      exposureData.desired_state === "ENABLED" &&
      javaExposureTarget?.public_address,
  );
  const exposureMethodLabel = exposureData?.method ?? "tunnel";
  const exposurePublicAddress = javaExposureTarget?.public_address ?? null;
  const [verifyPublicNetworkOverride, setVerifyPublicNetworkOverride] = useState<
    boolean | null
  >(null);
  const effectiveVerifyPublicNetwork =
    verifyPublicNetworkOverride ?? hasActiveExposure;

  const [startedFresh, setStartedFresh] = useState(false);
  const [hydratedRunId, setHydratedRunId] = useState<string | null>(null);
  const [upgrade, setUpgrade] = useState<ServerUpgradeResponse | null>(null);
  const [excludedPaths, setExcludedPaths] = useState<string[]>([]);
  const [keepPaths, setKeepPaths] = useState<string[]>([]);
  const [planError, setPlanError] = useState<string | null>(null);
  const [isPlanning, setIsPlanning] = useState(false);

  const [manualUploadKey, setManualUploadKey] = useState<string | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);

  const [resolvedConflicts, setResolvedConflicts] = useState<
    Record<string, string>
  >({});
  const [conflictPath, setConflictPath] = useState("");
  const [conflictBody, setConflictBody] = useState("");

  const [runtime, setRuntime] =
    useState<PrepareUpgradeTestResponse["runtime"]>(null);
  const [isPreparing, setIsPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState<string | null>(null);
  const [isDiscarding, setIsDiscarding] = useState(false);

  const [applyAsyncMode, setApplyAsyncMode] = useState(true);
  const [isApplying, setIsApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<ServerUpgradeResponse | null>(
    null,
  );
  const [applyError, setApplyError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dismissedOutcomeId, setDismissedOutcomeId] = useState<string | null>(() =>
    readDismissedOutcomeId(serverId),
  );

  // Hydrate an active non-terminal run from backend state when reopening the panel
  const activeRun = upgradesQuery.data?.active_upgrade ?? null;
  if (
    !startedFresh &&
    !upgrade &&
    activeRun &&
    !TERMINAL_UPGRADE_STATUSES.has(activeRun.status) &&
    hydratedRunId !== activeRun.id
  ) {
    setHydratedRunId(activeRun.id);
    setUpgrade(activeRun);
    setTargetMc(activeRun.target_mc);
    if (SUPPORTED_LOADER_SET.has(activeRun.target_loader_id)) {
      setTargetLoaderId(activeRun.target_loader_id as P55LoaderId);
    }
    setTargetLoaderVersion(activeRun.target_loader_version);
    setExcludedPaths(activeRun.matrix?.excluded_paths ?? []);
    setKeepPaths(activeRun.matrix?.kept_paths ?? []);
    const savedStep = readSavedUpgradeStep(activeRun.id);
    if (activeRun.status === "active_pinned") {
      setApplyResult(activeRun);
      setStep(3);
    } else if (
      activeRun.status === "staging" ||
      activeRun.status === "testing" ||
      activeRun.status === "needs_resolution" ||
      activeRun.status === "ready" ||
      activeRun.status === "applying" ||
      Boolean(activeRun.error_message) ||
      (savedStep === 3 && !activeRun.matrix?.has_blockers)
    ) {
      setStep(3);
    } else {
      setStep(2);
    }
  }

  // Keep local state in sync when a background apply finishes (active_pinned, rolled_back, or failed)
  const matchedServerRun = upgrade
    ? (upgradesQuery.data?.items?.find((item) => item.id === upgrade.id) ?? activeRun)
    : null;
  if (
    upgrade &&
    matchedServerRun &&
    matchedServerRun.id === upgrade.id &&
    upgrade.status === "applying" &&
    (matchedServerRun.status === "active_pinned" ||
      matchedServerRun.status === "rolled_back" ||
      matchedServerRun.status === "failed" ||
      matchedServerRun.status === "confirmed")
  ) {
    setUpgrade(matchedServerRun);
    setApplyResult(matchedServerRun);
  }

  const trackedOpId =
    (upgrade?.status === "applying" ? upgrade.operation_id : null) ??
    (activeRun?.status === "applying" ? activeRun.operation_id : null) ??
    null;

  const liveOpQuery = useQuery({
    queryKey: ["p55", "upgrade-operation", trackedOpId],
    queryFn: async () => api.getOperation(trackedOpId!),
    enabled: Boolean(trackedOpId) && typeof api.getOperation === "function",
    refetchInterval: (query) => {
      const st = query.state.data?.status;
      if (st && ["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(st)) {
        return false;
      }
      return 1_500;
    },
    retry: false,
  });

  useEffect(() => {
    const op = liveOpQuery.data;
    if (!op) return;
    useOperationStore.getState().setOperation(op);
    if (["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(op.status)) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.p55.upgrades(serverId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.servers.detail(serverId),
      });
    }
  }, [liveOpQuery.data, queryClient, serverId]);

  const selectedVersionTypes = (["release", "beta", "alpha"] as const).filter(
    (item) => versionTypes[item],
  );
  const effectiveVersionTypes: Array<"release" | "beta" | "alpha"> =
    selectedVersionTypes.length > 0 ? selectedVersionTypes : ["release"];

  const matrix = upgrade?.matrix ?? null;
  const entries = matrix?.entries ?? [];
  const hasBlockers = Boolean(matrix?.has_blockers);
  const needsResolution = upgrade?.status === "needs_resolution";
  const showDowngradeAdvisory = isMcDowngrade(currentMc, targetMc);

  const matrixSelectionDirty = Boolean(
    matrix &&
      (!sameSortedList(excludedPaths, matrix.excluded_paths ?? []) ||
        !sameSortedList(keepPaths, matrix.kept_paths ?? [])),
  );

  function invalidateUpgradeQueries() {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.p55.upgrades(serverId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.versioning.branches(serverId),
    });
  }

  function handleStartFresh(skipAbandon = false) {
    const previous = upgrade;
    if (previous) {
      try {
        window.sessionStorage.removeItem(`onx.upgradeStep.${previous.id}`);
      } catch {
        // ignore storage errors
      }
    }
    if (
      !skipAbandon &&
      previous &&
      !TERMINAL_UPGRADE_STATUSES.has(previous.status) &&
      previous.status !== "active_pinned" &&
      typeof api.rollbackServerUpgrade === "function"
    ) {
      void Promise.resolve(
        api.rollbackServerUpgrade(serverId, previous.id, {
          reason: "operator started fresh plan",
        }),
      )
        .catch(() => null)
        .finally(() => {
          invalidateUpgradeQueries();
        });
    }
    setStartedFresh(true);
    setUpgrade(null);
    setRuntime(null);
    setApplyResult(null);
    setExcludedPaths([]);
    setKeepPaths([]);
    setResolvedConflicts({});
    setPlanError(null);
    setPrepareError(null);
    setApplyError(null);
    setNotice(null);
    setStep(1);
  }

  function setEntryMode(path: string, mode: "auto" | "keep" | "exclude") {
    if (mode === "keep") {
      setKeepPaths((prev) => [...new Set([...prev, path])]);
      setExcludedPaths((prev) => prev.filter((item) => item !== path));
    } else if (mode === "exclude") {
      setExcludedPaths((prev) => [...new Set([...prev, path])]);
      setKeepPaths((prev) => prev.filter((item) => item !== path));
    } else {
      setExcludedPaths((prev) => prev.filter((item) => item !== path));
      setKeepPaths((prev) => prev.filter((item) => item !== path));
    }
  }

  async function handlePlan() {
    if (typeof api.planServerUpgrade !== "function") return;
    setPlanError(null);
    if (!targetMc.trim() || !targetLoaderVersion.trim()) {
      setPlanError("Target MC version and loader version are required.");
      return;
    }
    setIsPlanning(true);
    try {
      const response = await api.planServerUpgrade(serverId, {
        target_mc: targetMc.trim(),
        target_loader_id: targetLoaderId,
        target_loader_version: targetLoaderVersion.trim(),
        staged_pack_id: stagedPackId ?? null,
        excluded_paths: excludedPaths,
        keep_paths: keepPaths,
        version_types: effectiveVersionTypes,
      });
      setStartedFresh(false);
      setHydratedRunId(response.id);
      setUpgrade(response);
      setExcludedPaths(response.matrix?.excluded_paths ?? excludedPaths);
      setKeepPaths(response.matrix?.kept_paths ?? keepPaths);
      setStep(2);
      invalidateUpgradeQueries();
    } catch (error) {
      setPlanError(
        error instanceof ApiError
          ? error.message
          : "Compatibility planning failed",
      );
    } finally {
      setIsPlanning(false);
    }
  }

  async function handleReevaluate(): Promise<ServerUpgradeResponse | null> {
    if (typeof api.planServerUpgrade !== "function") return null;
    setIsPlanning(true);
    setPlanError(null);
    try {
      const response = await api.planServerUpgrade(serverId, {
        target_mc: targetMc.trim(),
        target_loader_id: targetLoaderId,
        target_loader_version: targetLoaderVersion.trim(),
        staged_pack_id: stagedPackId ?? null,
        excluded_paths: excludedPaths,
        keep_paths: keepPaths,
        version_types: effectiveVersionTypes,
      });
      setUpgrade(response);
      setExcludedPaths(response.matrix?.excluded_paths ?? excludedPaths);
      setKeepPaths(response.matrix?.kept_paths ?? keepPaths);
      invalidateUpgradeQueries();
      return response;
    } catch (error) {
      setPlanError(
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Matrix re-evaluation failed",
      );
      return null;
    } finally {
      setIsPlanning(false);
    }
  }

  async function handleContinueToApply() {
    setPlanError(null);
    if (matrixSelectionDirty) {
      const refreshed = await handleReevaluate();
      if (!refreshed) return;
      if (refreshed.matrix?.has_blockers) {
        setPlanError(
          "Compatibility blockers remain after re-evaluation. Resolve them before continuing to Apply.",
        );
        return;
      }
      writeSavedUpgradeStep(refreshed.id, 3);
    } else if (hasBlockers) {
      setPlanError(
        "Resolve all compatibility blockers before continuing to Apply.",
      );
      return;
    } else if (upgrade) {
      writeSavedUpgradeStep(upgrade.id, 3);
    }
    setStep(3);
  }

  async function handleManualUpload(
    blocker: ManualDownloadBlockerItem,
    uploadedFile: File | undefined,
    entryPath: string,
  ) {
    if (
      !uploadedFile ||
      !upgrade ||
      typeof api.resolveUpgradeManualUpload !== "function"
    ) {
      return;
    }
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
        setExcludedPaths(response.matrix.excluded_paths ?? excludedPaths);
        setKeepPaths(response.matrix.kept_paths ?? keepPaths);
      } else {
        const resolved: ManualDownloadBlockerItem = {
          ...blocker,
          resolved: true,
        };
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
          matrix: matrix
            ? recomputeMatrix(matrix, patchedEntries)
            : response.matrix,
        });
      }
      invalidateUpgradeQueries();
    } catch (error) {
      setManualError(
        error instanceof ApiError
          ? error.message
          : "Manual upload verification failed",
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
      const response = await api.prepareServerUpgradeTest(
        serverId,
        upgrade.id,
        {
          resolved_conflicts: resolvedConflicts,
          start_test: true,
        },
      );
      setUpgrade(response.upgrade);
      setRuntime(response.runtime);
      invalidateUpgradeQueries();
      if (response.upgrade.upgrade_branch) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.versioning.branchRuntime(
            serverId,
            response.upgrade.upgrade_branch,
          ),
        });
      }
      if (response.upgrade.status === "needs_resolution") {
        setNotice(
          "Three-way merge conflicts must be resolved before the test can start.",
        );
      } else {
        setNotice(
          response.upgrade.upgrade_branch
            ? `Isolated test branch "${response.upgrade.upgrade_branch}" is ready in the branch switcher.`
            : "Isolated test container prepared from the upgrade branch.",
        );
      }
    } catch (error) {
      setPrepareError(
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Preparing the isolated test failed",
      );
      invalidateUpgradeQueries();
    } finally {
      setIsPreparing(false);
    }
  }

  async function handleDiscardTest() {
    if (!upgrade) return;
    setIsDiscarding(true);
    setPrepareError(null);
    try {
      const targetBranch = upgrade.upgrade_branch;
      if (targetBranch) {
        if (branchCtx?.branch === targetBranch) {
          branchCtx.setBranch("main");
        }
        if (typeof api.stopBranchRun === "function") {
          try {
            await api.stopBranchRun(serverId, targetBranch, {});
          } catch {
            // best-effort cleanup
          }
        }
        if (typeof api.destroyBranchRun === "function") {
          try {
            await api.destroyBranchRun(serverId, targetBranch, {});
          } catch {
            // best-effort cleanup
          }
        }
        if (typeof api.deleteServerBranch === "function") {
          try {
            await api.deleteServerBranch(serverId, targetBranch);
          } catch {
            // best-effort cleanup
          }
        }
      }
      if (
        !TERMINAL_UPGRADE_STATUSES.has(upgrade.status) &&
        upgrade.status !== "active_pinned" &&
        typeof api.rollbackServerUpgrade === "function"
      ) {
        try {
          await api.rollbackServerUpgrade(serverId, upgrade.id, {
            reason: "operator discarded test branch",
          });
        } catch {
          // best-effort cleanup
        }
      }
      invalidateUpgradeQueries();
      handleStartFresh(true);
    } catch (error) {
      setPrepareError(
        error instanceof ApiError
          ? error.message
          : "Failed to discard isolated test branch",
      );
    } finally {
      setIsDiscarding(false);
    }
  }

  async function handleApply() {
    if (!upgrade || isApplying || upgrade.status === "applying" || typeof api.applyServerUpgrade !== "function") {
      return;
    }
    setIsApplying(true);
    setApplyError(null);
    setApplyResult(null);
    setNotice(null);
    try {
      const response = await api.applyServerUpgrade(serverId, upgrade.id, {
        resolved_conflicts: resolvedConflicts,
        async_mode: applyAsyncMode,
        verify_public_network: effectiveVerifyPublicNetwork,
      });
      setUpgrade(response);
      setApplyResult(response);
      setStep(3);
      invalidateUpgradeQueries();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.servers.detail(serverId),
      });
      if (response.status === "applying") {
        setNotice(
          "Version change is running — follow live stages below or open the Operation Log drawer.",
        );
      }
      onApplied?.(response);
    } catch (error) {
      if (error instanceof ApiError) {
        setApplyError(error);
      } else {
        setApplyError(
          new ApiError(
            0,
            "UNKNOWN",
            error instanceof Error ? error.message : "Upgrade failed",
          ),
        );
      }
    } finally {
      setIsApplying(false);
    }
  }

  async function handleViewLiveOperation(preferredId?: string | null) {
    let opId =
      preferredId ||
      extractOperationIdFromError(applyError) ||
      upgrade?.operation_id ||
      null;
    if (!opId && typeof api.listOperations === "function") {
      try {
        const ops = await api.listOperations({
          target_type: "server",
          target_id: serverId,
          limit: 10,
        });
        const activeOp = ops.find((item) =>
          ["QUEUED", "PREPARING", "RUNNING", "CANCEL_REQUESTED"].includes(item.status),
        );
        opId = activeOp?.id ?? ops[0]?.id ?? null;
      } catch {
        // Ignore lookup error
      }
    }
    if (opId) {
      useOperationStore.getState().openDrawer(opId);
      onClose();
    } else {
      setNotice("Open the Operations panel from the top bar to inspect live progress.");
    }
  }

  async function handleConfirm() {
    if (!applyResult || typeof api.confirmServerUpgrade !== "function") return;
    try {
      const response = await api.confirmServerUpgrade(
        serverId,
        applyResult.id,
      );
      setApplyResult(response);
      setUpgrade(response);
      invalidateUpgradeQueries();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.servers.detail(serverId),
      });
      setNotice("Version change confirmed. The rollback backup pin was released.");
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

  const activePinnedUpgrade =
    upgradesQuery.data?.items?.find((item) => item.status === "active_pinned") ??
    (upgradesQuery.data?.active_upgrade?.status === "active_pinned"
      ? upgradesQuery.data.active_upgrade
      : null);

  async function handleUnblockConfirmPinned() {
    if (!activePinnedUpgrade || typeof api.confirmServerUpgrade !== "function") {
      return;
    }
    try {
      await api.confirmServerUpgrade(serverId, activePinnedUpgrade.id);
      setApplyError(null);
      setPrepareError(null);
      setNotice("Previous upgrade confirmed and rollback pin released. You may retry now.");
      invalidateUpgradeQueries();
    } catch (error) {
      setApplyError(
        error instanceof ApiError
          ? error
          : new ApiError(0, "UNKNOWN", "Confirming previous upgrade failed"),
      );
    }
  }

  async function handleUnblockRollbackPinned() {
    if (!activePinnedUpgrade || typeof api.rollbackServerUpgrade !== "function") {
      return;
    }
    try {
      await api.rollbackServerUpgrade(serverId, activePinnedUpgrade.id, {
        reason: "operator rolled back previous pinned upgrade",
      });
      setApplyError(null);
      setPrepareError(null);
      setNotice("Previous upgrade rolled back. You may retry now.");
      invalidateUpgradeQueries();
    } catch (error) {
      setApplyError(
        error instanceof ApiError
          ? error
          : new ApiError(0, "UNKNOWN", "Rolling back previous upgrade failed"),
      );
    }
  }

  const latestItem = upgradesQuery.data?.items?.[0] ?? null;
  const recentTerminalOutcome =
    !upgrade &&
    !applyResult &&
    !startedFresh &&
    latestItem &&
    (latestItem.status === "rolled_back" || latestItem.status === "failed") &&
    dismissedOutcomeId !== latestItem.id
      ? latestItem
      : null;

  const outcomeRecord =
    applyResult?.status === "rolled_back" || applyResult?.status === "failed"
      ? applyResult
      : upgrade?.status === "rolled_back" || upgrade?.status === "failed"
        ? upgrade
        : recentTerminalOutcome;

  const rolledBack =
    outcomeRecord?.status === "rolled_back" ||
    applyError?.code === "HEALTH_GATE_FAILED" ||
    applyResult?.error_code === "HEALTH_GATE_FAILED";

  const failedOnly =
    !rolledBack && outcomeRecord?.status === "failed";

  const isOperationInFlight =
    isApplying ||
    upgrade?.status === "applying" ||
    activeRun?.status === "applying" ||
    Boolean(
      liveOpQuery.data &&
        ["QUEUED", "PREPARING", "RUNNING", "CANCEL_REQUESTED"].includes(
          liveOpQuery.data.status,
        ),
    );

  const canHideWithEscape = !isApplying && !isPreparing && !isDiscarding;

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && canHideWithEscape) {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canHideWithEscape, onClose]);

  return (
    <>
      <div
        aria-hidden="true"
        onClick={() => {
          if (canHideWithEscape) onClose();
        }}
        className="fixed inset-x-0 top-14 bottom-0 z-30 bg-black/50 backdrop-blur-xs lg:hidden"
      />
      <aside
        role="complementary"
        aria-label="Change Version"
        data-testid="change-version-side-panel"
        className="fixed inset-x-3 top-16 z-40 mx-auto flex max-h-[calc(100dvh-5rem)] max-w-xl flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-card shadow-2xl lg:inset-x-auto lg:left-auto lg:top-16 lg:right-4 lg:bottom-auto lg:mx-0 lg:h-fit lg:max-h-[calc(100dvh-5.5rem)] lg:w-[460px] xl:w-[500px] lg:shadow-xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border-subtle px-4 py-3 shrink-0">
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-text-primary">
              Change Version
            </h2>
            <p className="text-[11px] text-text-muted leading-snug">
              Plan version, review addons, test or apply in the background without blocking the workspace.
            </p>
          </div>
          <Button
            type="button"
            data-testid="hide-upgrade-panel-btn"
            aria-label="Hide Change Version panel"
            title="Hide panel (keeps active plan & background tasks running)"
            size="sm"
            variant="ghost"
            icon="panel-right-close"
            onClick={onClose}
          >
            Hide
          </Button>
        </div>
      <div className="flex-1 min-h-0 overflow-y-auto space-y-4 p-4">
        {upgrade && !TERMINAL_UPGRADE_STATUSES.has(upgrade.status) && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border-subtle bg-surface-muted px-3.5 py-2.5 text-xs">
            <div className="flex flex-wrap items-center gap-2 min-w-0">
              <span className="font-semibold text-text-primary">
                Active Plan: MC {upgrade.target_mc} ({upgrade.target_loader_id})
              </span>
              <span className="inline-flex items-center rounded-full border border-border-default bg-surface-card px-2 py-0.5 font-mono text-[10px] font-medium text-text-secondary">
                {upgrade.status}
              </span>
            </div>
            <Button
              type="button"
              data-testid="start-fresh-upgrade-btn"
              size="sm"
              variant="ghost"
              icon="restart"
              onClick={() => handleStartFresh()}
            >
              Start Fresh
            </Button>
          </div>
        )}

        {applyResult?.status === "active_pinned" && !rolledBack ? (
          (() => {
            const pinnedChecks: OperationHealthCheckItem[] =
              applyResult.matrix?.health_gate_checks ??
              ((liveOpQuery.data?.steps?.find((s) => s.step_id === "HEALTH_GATE")
                ?.context?.checks as OperationHealthCheckItem[] | undefined) ??
                []);
            const pinnedWarnings =
              applyResult.matrix?.health_gate_warnings ??
              pinnedChecks
                .filter((c) => c.status === "warned" && c.detail)
                .map((c) => String(c.detail));
            const hasWarning = pinnedWarnings.length > 0;
            return (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="inline-flex items-center rounded-full border border-status-success-border bg-status-success-bg px-2.5 py-0.5 text-[11px] font-semibold text-status-success">
                    Waiting for Confirmation
                  </span>
                  {hasWarning && (
                    <span
                      data-testid="wizard-network-warning-badge"
                      className="inline-flex items-center rounded-full border border-status-warning-border bg-status-warning-bg px-2.5 py-0.5 text-[11px] font-semibold text-status-warning"
                    >
                      Public Network Warning
                    </span>
                  )}
                </div>
                <Banner
                  variant="success"
                  title="Health Gate Passed — Upgrade Active & Rollback Snapshot Pinned"
                  description={`Live server is now running MC ${applyResult.target_mc} (${applyResult.target_loader_id} ${applyResult.target_loader_version}). Pre-upgrade backup ${applyResult.pre_upgrade_backup_id ?? "pinned"} remains available until confirmation.`}
                />
                {hasWarning && (
                  <div data-testid="wizard-health-warning-banner">
                    <Banner
                      variant="warning"
                      title="Public Network / Tunnel Unreachable"
                      description={pinnedWarnings.join(" ")}
                    />
                  </div>
                )}
                {pinnedChecks.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                      Health Gate Verification Summary
                    </p>
                    <HealthGateChecklist checks={pinnedChecks} parentTerminal />
                  </div>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    type="button"
                    data-testid="confirm-upgrade-unpin-btn"
                    variant="primary"
                    icon="check"
                    onClick={handleConfirm}
                  >
                    Confirm &amp; Keep MC {applyResult.target_mc}
                  </Button>
                  {typeof api.rollbackServerUpgrade === "function" && (
                    <Button
                      type="button"
                      data-testid="wizard-rollback-pinned-btn"
                      variant="danger"
                      icon="restart"
                      onClick={() => void handleUnblockRollbackPinned()}
                    >
                      Rollback to {applyResult.source_mc || currentMc || "Previous"}
                    </Button>
                  )}
                  <Button type="button" variant="secondary" onClick={onClose}>
                    Hide
                  </Button>
                </div>
                {notice && <Banner variant="info" title={notice} />}
              </div>
            );
          })()
        ) : (
          <>
            {(rolledBack || failedOnly) && (
              <AutoRollbackAlert
                errorCode={
                  applyError?.code ??
                  outcomeRecord?.error_code ??
                  applyResult?.error_code ??
                  liveOpQuery.data?.failure_code ??
                  null
                }
                errorMessage={
                  applyError?.message ??
                  outcomeRecord?.error_message ??
                  applyResult?.error_message ??
                  liveOpQuery.data?.error_message ??
                  null
                }
                sourceLabel={
                  outcomeRecord?.source_mc
                    ? `${outcomeRecord.source_loader_id ?? serverType ?? ""} ${outcomeRecord.source_mc}`.trim()
                    : currentMc
                      ? `${serverType ?? ""} ${currentMc}`.trim()
                      : undefined
                }
                isFailedOnly={failedOnly}
                onDismiss={() => {
                  const targetDismissId = outcomeRecord?.id ?? upgrade?.id;
                  if (targetDismissId) {
                    writeDismissedOutcomeId(serverId, targetDismissId);
                    setDismissedOutcomeId(targetDismissId);
                  }
                  setApplyResult(null);
                  setApplyError(null);
                  handleStartFresh(true);
                }}
                onTryAgain={() => {
                  const targetDismissId = outcomeRecord?.id ?? upgrade?.id;
                  if (targetDismissId) {
                    writeDismissedOutcomeId(serverId, targetDismissId);
                    setDismissedOutcomeId(targetDismissId);
                  }
                  setApplyResult(null);
                  setApplyError(null);
                  handleStartFresh(true);
                }}
              />
            )}

            <div className="flex items-center gap-2">
              {[1, 2, 3].map((item) => (
                <span
                  key={item}
                  className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold ${
                    step === item
                      ? "bg-accent-primary text-accent-contrast-text"
                      : step > item
                        ? "bg-status-success-bg text-status-success border border-status-success-border"
                        : "bg-surface-muted text-text-muted border border-border-subtle"
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
                      ? "Test branch & live merge"
                      : "Backup, upgrade & Health Gate"}
              </span>
            </div>

            {step === 1 && (
              <div className="space-y-4">
                {initialLoader.isUnsupportedSource && (
                  <Banner
                    variant="warning"
                    title={`Source server type "${serverType}" does not auto-map to a managed mod/plugin loader`}
                    description="Change Version plans compatibility matrices for Fabric, Quilt, Forge, NeoForge, Paper, and Purpur. Select a target loader below to plan a migration."
                  />
                )}
                {showDowngradeAdvisory && (
                  <div data-testid="downgrade-advisory-banner">
                    <Banner
                      variant="warning"
                      title="Minecraft world downgrade advisory"
                      description={`Changing from MC ${currentMc} down to MC ${targetMc} is an older target version. Minecraft worlds do not support lossless downgrading of chunk or player NBT data — test in an isolated branch and verify backups before touching live worlds.`}
                    />
                  </div>
                )}
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <label
                      htmlFor="upgrade-target-mc"
                      className="mb-1 block text-[11px] font-medium text-text-muted"
                    >
                      Target Minecraft
                    </label>
                    <input
                      id="upgrade-target-mc"
                      list="upgrade-mc-versions-list"
                      value={targetMc}
                      onChange={(event) => setTargetMc(event.target.value)}
                      placeholder={availableMcVersions[0] ?? "1.21.4"}
                      className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
                    />
                    {availableMcVersions.length > 0 && (
                      <datalist id="upgrade-mc-versions-list">
                        {availableMcVersions.slice(0, 30).map((ver) => (
                          <option key={ver} value={ver} />
                        ))}
                      </datalist>
                    )}
                  </div>
                  <div>
                    <label
                      htmlFor="upgrade-target-loader"
                      className="mb-1 block text-[11px] font-medium text-text-muted"
                    >
                      Target Loader
                    </label>
                    <select
                      id="upgrade-target-loader"
                      value={targetLoaderId}
                      onChange={(event) => {
                        const nextLoader = event.target.value as P55LoaderId;
                        setTargetLoaderId(nextLoader);
                        setTargetLoaderVersion(
                          defaultLoaderVersionFor(nextLoader),
                        );
                      }}
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
                    <label
                      htmlFor="upgrade-target-loader-version"
                      className="mb-1 block text-[11px] font-medium text-text-muted"
                    >
                      Target Loader Version
                    </label>
                    <input
                      id="upgrade-target-loader-version"
                      value={targetLoaderVersion}
                      onChange={(event) =>
                        setTargetLoaderVersion(event.target.value)
                      }
                      placeholder={loaderVersionPlaceholder(targetLoaderId)}
                      className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none focus:ring-1 focus:ring-accent-primary"
                    />
                  </div>
                </div>

                {!initialLoader.isUnsupportedSource &&
                  targetLoaderId !== initialLoader.loader && (
                    <p
                      data-testid="loader-switch-note"
                      className="text-xs font-medium text-status-info"
                    >
                      Switching loader:{" "}
                      {formatLoaderName(serverType || initialLoader.loader)} →{" "}
                      {formatLoaderName(targetLoaderId)}
                    </p>
                  )}

                <div className="space-y-1.5">
                  <p className="text-[11px] font-medium text-text-muted">
                    Release Channels
                  </p>
                  <div className="flex flex-wrap gap-3">
                    {(["release", "beta", "alpha"] as const).map((type) => (
                      <label
                        key={type}
                        className="inline-flex items-center gap-2 text-xs text-text-secondary"
                      >
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
                    <span className="font-mono text-text-secondary">
                      {stagedPackId}
                    </span>
                    .
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
              <div
                className="space-y-4"
                data-testid="upgrade-compatibility-matrix"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <SectionHeader
                    title={`Compatibility Matrix — MC ${matrix?.target_mc ?? targetMc} · ${matrix?.target_loader.id ?? targetLoaderId} ${matrix?.target_loader.version ?? targetLoaderVersion}`}
                    subtitle={`Source MC ${matrix?.source_mc ?? upgrade.source_mc ?? "unknown"} → target ${matrix?.target_mc ?? targetMc}`}
                  />
                  <LoaderBadge loader={upgrade.target_loader_id} />
                </div>

                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {[
                    ["Total Entries", entries.length],
                    ["Blockers", matrix?.blockers_count ?? 0],
                    ["Warnings", matrix?.warnings_count ?? 0],
                    ["BFS Depth", matrix?.bfs_depth_reached ?? 0],
                    ["Projects Resolved", matrix?.bfs_projects_resolved ?? 0],
                  ].map(([label, value]) => (
                    <div
                      key={String(label)}
                      className="rounded-lg border border-border-subtle bg-surface-muted p-2.5"
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
                    title="Version change blocked by compatibility matrix"
                    description="Choose Keep Current (carry existing JAR into test), Exclude, or upload the required file before continuing."
                  />
                )}

                {needsResolution && (
                  <Banner
                    variant="warning"
                    title="3-way merge conflicts need resolution"
                    description="Provide clean resolved content for every conflicting file before preparing the test or applying."
                  />
                )}

                <div className="overflow-x-auto rounded-xl border border-border-default">
                  <table className="w-full table-fixed text-xs">
                    <thead>
                      <tr className="border-b border-border-subtle bg-surface-muted text-left text-[11px] text-text-muted">
                        <th className="w-[31%] px-2.5 py-2 font-medium">Path</th>
                        <th className="w-[21%] px-2 py-2 font-medium">Status</th>
                        <th className="w-[24%] px-2 py-2 font-medium">Detail</th>
                        <th className="w-[24%] px-2 py-2 font-medium">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entries.length === 0 ? (
                        <tr>
                          <td
                            colSpan={4}
                            className="px-3 py-4 text-xs text-text-muted"
                          >
                            No matrix entries returned.
                          </td>
                        </tr>
                      ) : (
                        entries.map((entry) => {
                          const badge = resolveActionBadge(entry);
                          const isAddon =
                            entry.path.startsWith("mods/") ||
                            entry.path.startsWith("plugins/");
                          const isKept = keepPaths.includes(entry.path);
                          const isExcluded = excludedPaths.includes(entry.path);
                          const currentAction: "auto" | "keep" | "exclude" =
                            isExcluded
                              ? "exclude"
                              : isKept
                                ? "keep"
                                : "auto";
                          return (
                            <tr
                              key={entry.path}
                              className="border-b border-border-subtle last:border-b-0 align-top"
                            >
                              <td className="px-2.5 py-2 min-w-0">
                                <span
                                  title={entry.path}
                                  className="block truncate font-mono text-[11px] text-text-primary"
                                >
                                  {entry.path}
                                </span>
                                {entry.required_by.length > 0 && (
                                  <p
                                    title={entry.required_by.join(", ")}
                                    className="mt-0.5 truncate text-[10px] text-text-muted"
                                  >
                                    required by {entry.required_by.join(", ")}
                                  </p>
                                )}
                              </td>
                              <td className="px-2 py-2 whitespace-nowrap">
                                <span
                                  className={`inline-flex max-w-full truncate rounded-full border px-2 py-0.5 text-[10px] font-semibold ${badge.tone}`}
                                >
                                  {badge.label}
                                </span>
                              </td>
                              <td className="px-2 py-2 text-[11px] text-text-muted min-w-0">
                                <p
                                  title={entry.detail || undefined}
                                  className="line-clamp-2 break-words"
                                >
                                  {entry.detail || "—"}
                                </p>
                                {entry.status ===
                                  "blocker: manual_download_required" &&
                                  entry.manual_blocker && (
                                    <div className="mt-1.5 space-y-1">
                                      <p
                                        title={entry.manual_blocker.filename || entry.path}
                                        className="truncate font-mono text-[10px]"
                                      >
                                        {entry.manual_blocker.filename ||
                                          entry.path}
                                      </p>
                                      {entry.manual_blocker.webpage_url && (
                                        <a
                                          href={
                                            entry.manual_blocker.webpage_url
                                          }
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
                              <td className="px-2 py-2">
                                {isAddon ? (
                                  <div
                                    role="group"
                                    aria-label={`Action for ${entry.path}`}
                                    className="inline-flex flex-wrap gap-0.5 rounded-lg border border-border-subtle bg-surface-muted p-0.5 text-[10px] font-medium"
                                  >
                                    <button
                                      type="button"
                                      data-testid={`auto-entry-${entry.path}`}
                                      onClick={() =>
                                        setEntryMode(entry.path, "auto")
                                      }
                                      className={`rounded-md px-1.5 py-0.5 transition-colors cursor-pointer ${
                                        currentAction === "auto"
                                          ? "bg-surface-card text-text-primary shadow-2xs"
                                          : "text-text-muted hover:text-text-primary"
                                      }`}
                                    >
                                      Auto
                                    </button>
                                    <button
                                      type="button"
                                      data-testid={`keep-entry-${entry.path}`}
                                      onClick={() =>
                                        setEntryMode(entry.path, "keep")
                                      }
                                      className={`rounded-md px-1.5 py-0.5 transition-colors cursor-pointer whitespace-nowrap ${
                                        currentAction === "keep"
                                          ? "bg-accent-primary text-accent-contrast-text shadow-2xs"
                                          : "text-text-muted hover:text-text-primary"
                                      }`}
                                    >
                                      Keep Current
                                    </button>
                                    <button
                                      type="button"
                                      data-testid={`exclude-entry-${entry.path}`}
                                      onClick={() =>
                                        setEntryMode(entry.path, "exclude")
                                      }
                                      className={`rounded-md px-1.5 py-0.5 transition-colors cursor-pointer ${
                                        currentAction === "exclude"
                                          ? "bg-status-danger-bg text-status-danger border border-status-danger-border"
                                          : "text-text-muted hover:text-text-primary"
                                      }`}
                                    >
                                      Exclude
                                    </button>
                                  </div>
                                ) : (
                                  <span className="text-[10px] text-text-muted">
                                    —
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>

                {manualError && (
                  <div data-testid="upgrade-error-banner">
                    <Banner
                      variant="danger"
                      title={manualError}
                      description={buildUpgradeRecoveryHint(manualError)}
                    />
                  </div>
                )}
                {planError && (
                  <div data-testid="upgrade-error-banner">
                    <Banner
                      variant="danger"
                      title={planError}
                      description={buildUpgradeRecoveryHint(planError)}
                    />
                  </div>
                )}

                {matrixSelectionDirty && (
                  <p className="text-xs text-status-warning font-medium">
                    Per-addon selections changed — click Re-evaluate Matrix or
                    Continue to Apply to refresh compatibility status.
                  </p>
                )}

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    icon="restart"
                    loading={isPlanning}
                    onClick={() => void handleReevaluate()}
                  >
                    Re-evaluate Matrix
                  </Button>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setStep(1)}
                    >
                      Back
                    </Button>
                    <Button
                      type="button"
                      data-testid="continue-upgrade-btn"
                      variant="primary"
                      icon="chevron-right"
                      iconPosition="right"
                      loading={isPlanning}
                      disabled={hasBlockers && !matrixSelectionDirty}
                      onClick={() => void handleContinueToApply()}
                    >
                      Continue to Apply
                    </Button>
                  </div>
                </div>
                {hasBlockers && (
                  <p className="text-right text-xs text-text-muted">
                    Choose Keep Current / Exclude or upload manual files, then
                    Re-evaluate Matrix to continue.
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
                        <label
                          htmlFor="conflict-path"
                          className="mb-1 block text-[10px] font-medium text-text-muted"
                        >
                          Conflict File Path
                        </label>
                        <input
                          id="conflict-path"
                          value={conflictPath}
                          onChange={(event) =>
                            setConflictPath(event.target.value)
                          }
                          placeholder="config/example.toml"
                          className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-primary focus:outline-none"
                        />
                      </div>
                      <div>
                        <label
                          htmlFor="conflict-body"
                          className="mb-1 block text-[10px] font-medium text-text-muted"
                        >
                          Resolved Content
                        </label>
                        <textarea
                          id="conflict-body"
                          value={conflictBody}
                          onChange={(event) =>
                            setConflictBody(event.target.value)
                          }
                          rows={2}
                          className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1 font-mono text-xs text-text-primary focus:border-accent-primary focus:outline-none"
                        />
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={addConflictEntry}
                      >
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
                        subtitle="Prepare a selectable upgrade branch and test container on a separate host port set before touching main."
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
                          Prepare upgrade-{upgrade.target_mc} Branch &amp; Start
                          Test
                        </Button>
                        {upgrade.upgrade_branch && (
                          <span className="font-mono text-[11px] text-text-secondary">
                            Branch: {upgrade.upgrade_branch}
                          </span>
                        )}
                      </div>

                      {upgrade.upgrade_branch && (
                        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-subtle bg-surface-muted p-3">
                          {branchCtx && (
                            <Button
                              type="button"
                              data-testid="switch-to-upgrade-branch-btn"
                              size="sm"
                              variant="primary"
                              icon="terminal"
                              onClick={() => {
                                branchCtx.setBranch(upgrade.upgrade_branch!);
                                onClose();
                              }}
                            >
                              Switch to Branch &amp; Inspect
                            </Button>
                          )}
                          <Button
                            type="button"
                            data-testid="discard-upgrade-test-btn"
                            size="sm"
                            variant="danger"
                            icon="x"
                            loading={isDiscarding}
                            onClick={handleDiscardTest}
                          >
                            Discard Test
                          </Button>
                        </div>
                      )}

                      {prepareError && (
                        <div data-testid="upgrade-error-banner">
                          <Banner
                            variant="danger"
                            title={prepareError}
                            description={buildUpgradeRecoveryHint(prepareError)}
                          />
                        </div>
                      )}
                      {!prepareError &&
                        !applyError &&
                        upgrade.error_message &&
                        !rolledBack && (
                          <div data-testid="upgrade-error-banner">
                            <Banner
                              variant="danger"
                              title={upgrade.error_message}
                              description={buildUpgradeRecoveryHint(
                                upgrade.error_message,
                                upgrade.error_code,
                              )}
                            />
                          </div>
                        )}
                      {notice && <Banner variant="info" title={notice} />}
                      {(runtime || upgrade.data_template_id) && (
                        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3 text-xs">
                          <div className="rounded-lg border border-border-subtle bg-surface-muted p-2.5">
                            <dt className="text-[10px] uppercase tracking-wider text-text-muted">
                              Data Template Clone
                            </dt>
                            <dd className="mt-0.5 font-mono text-[11px] break-all">
                              {runtime?.data_template_id ??
                                upgrade.data_template_id ??
                                "—"}
                            </dd>
                          </div>
                          <div className="rounded-lg border border-border-subtle bg-surface-muted p-2.5">
                            <dt className="text-[10px] uppercase tracking-wider text-text-muted">
                              Isolated Container
                            </dt>
                            <dd className="mt-0.5 font-mono text-[11px] break-all">
                              {runtime?.container_name ?? "Not started"}
                            </dd>
                          </div>
                          <div className="rounded-lg border border-border-subtle bg-surface-muted p-2.5">
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
                        title="Step 3B: Apply to Live (main)"
                        subtitle="Stop the live server, create a rollback backup, merge into main, then run the 5-check Health Gate."
                      />
                      <div
                        data-testid="external-network-verification-card"
                        className="rounded-lg border border-border-subtle bg-surface-muted p-3 space-y-1.5"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <label className="inline-flex items-center gap-2 text-xs font-semibold text-text-primary cursor-pointer">
                            <input
                              type="checkbox"
                              data-testid="verify-public-network-toggle"
                              checked={effectiveVerifyPublicNetwork}
                              disabled={isOperationInFlight || !hasActiveExposure}
                              onChange={(event) =>
                                setVerifyPublicNetworkOverride(event.target.checked)
                              }
                              className="h-4 w-4 rounded border-border-default"
                            />
                            External Network Verification
                          </label>
                          {hasActiveExposure && (
                            <span
                              data-testid="external-network-active-pill"
                              className="inline-flex items-center rounded-full border border-status-info-border bg-status-info-bg px-2 py-0.5 text-[10px] font-semibold text-status-info"
                            >
                              Active: {exposureMethodLabel}
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-text-muted">
                          {hasActiveExposure
                            ? `Verifies players can reach the upgraded server through your public tunnel/IP${exposurePublicAddress ? ` (${exposurePublicAddress})` : ""}.`
                            : "No active public tunnel or exposure on this server."}
                        </p>
                      </div>
                      <Button
                        type="button"
                        data-testid="apply-upgrade-live-btn"
                        variant="primary"
                        icon="download"
                        loading={isOperationInFlight}
                        disabled={hasBlockers || isOperationInFlight}
                        onClick={handleApply}
                      >
                        {isApplying
                          ? "Starting version change..."
                          : isOperationInFlight
                            ? "Applying version change..."
                            : "Apply to Live (main)"}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-xl border border-border-subtle bg-surface-card p-4 space-y-3">
                    <SectionHeader
                      title="Step 3: Backup, Upgrade & Health Gate"
                      subtitle="Rollback backup, upgrade server files around the live world, then the 5-check Health Gate."
                    />
                    <p className="text-xs text-text-secondary leading-relaxed">
                      Simple Mode stops the server, creates a rollback backup, upgrades files around your worlds, boots with startup checks, and restores automatically if the Health Gate fails.
                    </p>
                    <div
                      data-testid="external-network-verification-card"
                      className="rounded-lg border border-border-subtle bg-surface-muted p-3 space-y-1.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <label className="inline-flex items-center gap-2 text-xs font-semibold text-text-primary cursor-pointer">
                          <input
                            type="checkbox"
                            data-testid="verify-public-network-toggle"
                            checked={effectiveVerifyPublicNetwork}
                            disabled={isOperationInFlight || !hasActiveExposure}
                            onChange={(event) =>
                              setVerifyPublicNetworkOverride(event.target.checked)
                            }
                            className="h-4 w-4 rounded border-border-default"
                          />
                          External Network Verification
                        </label>
                        {hasActiveExposure && (
                          <span
                            data-testid="external-network-active-pill"
                            className="inline-flex items-center rounded-full border border-status-info-border bg-status-info-bg px-2 py-0.5 text-[10px] font-semibold text-status-info"
                          >
                            Active: {exposureMethodLabel}
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-text-muted">
                        {hasActiveExposure
                          ? `Verifies players can reach the upgraded server through your public tunnel/IP${exposurePublicAddress ? ` (${exposurePublicAddress})` : ""}.`
                          : "No active public tunnel or exposure on this server."}
                      </p>
                    </div>
                    <Button
                      type="button"
                      data-testid="apply-upgrade-live-btn"
                      variant="primary"
                      icon="download"
                      loading={isOperationInFlight}
                      disabled={hasBlockers || isOperationInFlight}
                      onClick={handleApply}
                    >
                      {isApplying
                        ? "Starting version change..."
                        : isOperationInFlight
                          ? "Applying version change..."
                          : "Apply Change Version"}
                    </Button>
                  </div>
                )}

                {(isOperationInFlight || liveOpQuery.data) && (
                  <div
                    data-testid="upgrade-live-progress-card"
                    className="rounded-xl border border-status-info-border bg-surface-muted p-4 space-y-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-text-primary">
                          Live Execution Progress
                        </h4>
                        <p className="text-xs text-text-secondary mt-0.5">
                          {liveOpQuery.data?.current_step_id
                            ? STEP_LABELS[liveOpQuery.data.current_step_id] ??
                              liveOpQuery.data.current_step_id
                            : "Preparing version change operation…"}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {liveOpQuery.data?.elapsed_ms != null && (
                          <span className="font-mono text-[11px] text-text-muted">
                            {(liveOpQuery.data.elapsed_ms / 1000).toFixed(1)}s
                          </span>
                        )}
                        {(trackedOpId || upgrade.operation_id) && (
                          <Button
                            type="button"
                            data-testid="open-operation-drawer-btn"
                            size="sm"
                            variant="secondary"
                            icon="activity"
                            onClick={() => {
                              const targetOpId = trackedOpId || upgrade.operation_id;
                              if (targetOpId) {
                                useOperationStore.getState().openDrawer(targetOpId);
                                onClose();
                              }
                            }}
                          >
                            View Live Logs →
                          </Button>
                        )}
                      </div>
                    </div>
                    {liveOpQuery.data?.steps && liveOpQuery.data.steps.length > 0 ? (
                      <OperationStepper
                        steps={liveOpQuery.data.steps}
                        currentStepId={liveOpQuery.data.current_step_id}
                        operationStatus={liveOpQuery.data.status}
                      />
                    ) : (
                      <p className="text-xs text-text-muted">
                        Initializing live upgrade steps…
                      </p>
                    )}
                    {(() => {
                      const rawLogs = liveOpQuery.data?.metadata?.logs;
                      if (!Array.isArray(rawLogs) || rawLogs.length === 0) {
                        return null;
                      }
                      const recentLines = rawLogs.slice(-4);
                      return (
                        <div
                          data-testid="upgrade-inline-log-tail"
                          className="rounded-lg border border-border-subtle bg-surface-card p-2.5 font-mono text-[11px] text-text-secondary space-y-0.5"
                        >
                          {recentLines.map((entry, idx) => {
                            const lineText =
                              typeof entry === "string"
                                ? entry
                                : typeof entry === "object" &&
                                    entry !== null &&
                                    "line" in entry
                                  ? String((entry as { line: unknown }).line)
                                  : String(entry);
                            return (
                              <p key={idx} className="truncate" title={lineText}>
                                {lineText}
                              </p>
                            );
                          })}
                        </div>
                      );
                    })()}
                  </div>
                )}

                {applyError && !rolledBack && (
                  <div data-testid="upgrade-error-banner" className="space-y-2">
                    <Banner
                      variant="danger"
                      title={applyError.message}
                      description={buildUpgradeRecoveryHint(
                        applyError.message,
                        applyError.code,
                      )}
                    />
                    {isConcurrencyConflictError(
                      applyError.message,
                      applyError.code,
                    ) && (
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          data-testid="view-conflict-operation-btn"
                          size="sm"
                          variant="secondary"
                          icon="activity"
                          onClick={() =>
                            void handleViewLiveOperation(
                              extractOperationIdFromError(applyError),
                            )
                          }
                        >
                          View Live Progress →
                        </Button>
                      </div>
                    )}
                    {activePinnedUpgrade &&
                      (applyError.message.toLowerCase().includes("previous tree retained") ||
                        applyError.message.toLowerCase().includes("until confirmation")) && (
                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            type="button"
                            data-testid="inline-confirm-prev-upgrade-btn"
                            size="sm"
                            variant="primary"
                            icon="check"
                            onClick={() => void handleUnblockConfirmPinned()}
                          >
                            Confirm Previous Upgrade
                          </Button>
                          <Button
                            type="button"
                            data-testid="inline-rollback-prev-upgrade-btn"
                            size="sm"
                            variant="danger"
                            icon="restart"
                            onClick={() => void handleUnblockRollbackPinned()}
                          >
                            Rollback Previous Upgrade
                          </Button>
                        </div>
                      )}
                  </div>
                )}

                <label className="flex items-center gap-2 text-xs text-text-secondary">
                  <input
                    type="checkbox"
                    data-testid="upgrade-async-checkbox"
                    checked={applyAsyncMode}
                    disabled={isOperationInFlight}
                    onChange={(event) =>
                      setApplyAsyncMode(event.target.checked)
                    }
                    className="h-4 w-4 rounded border-border-default"
                  />
                  Run apply in background operation
                </label>

                <div className="flex justify-between">
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={isOperationInFlight}
                    onClick={() => {
                      if (upgrade) writeSavedUpgradeStep(upgrade.id, 2);
                      setStep(2);
                    }}
                  >
                    Back to Matrix
                  </Button>
                  <Button type="button" variant="secondary" onClick={onClose}>
                    Hide
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
      </aside>
    </>
  );
}

export function SafeUpgradeWizardModal(props: SafeUpgradeWizardModalProps) {
  if (!props.isOpen) return null;
  return <SafeUpgradeWizardModalInner {...props} />;
}
