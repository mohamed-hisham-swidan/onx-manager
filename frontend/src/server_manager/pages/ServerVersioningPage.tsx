import { useState, useEffect, useMemo, useContext } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  QueryClient,
  QueryClientContext,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Icon } from "@/components/ui/Icon";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { createAuthenticatedApi } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { useAuthPermissions } from "@/hooks/useAuthPermissions";
import { useServerBranchContext } from "@/server_manager/context/ServerBranchContext";
import {
  invalidateVersioningScope,
  useBranchRuntimeQuery,
  useGitHubStatusQuery,
  useVersioningBranches,
  useVersioningCommits,
  useVersioningDataTemplates,
  useVersioningLiveChanges,
  useVersioningMutations,
  useVersioningRefreshState,
  useVersioningSettings,
  useVersioningTags,
} from "@/server_manager/hooks/useVersioning";
import { BranchCockpitTab } from "@/server_manager/components/versioning/BranchCockpitTab";
import { CommitTimeline } from "@/server_manager/components/versioning/CommitTimeline";
import { SyncAndVaultTab } from "@/server_manager/components/versioning/SyncAndVaultTab";
import { type GitHubSyncAlertState } from "@/server_manager/components/versioning/GitHubSyncPanel";
import { BranchProtectionModal } from "@/server_manager/components/BranchProtectionModal";
import { ManageBranchesModal } from "@/server_manager/components/ManageBranchesModal";
import { CreateTagModal } from "@/server_manager/components/CreateTagModal";
import { CommitDiffModal } from "@/server_manager/components/CommitDiffModal";
import {
  ConnectGitHubModal,
  DisconnectGitHubModal,
  GitHubWebhookDeliveriesModal,
  RotateGitHubCredentialsModal,
} from "@/server_manager/components/versioning/GitHubModals";
import {
  BranchConsoleActivityModal,
  BranchPortSetModal,
  DataTemplatesModal,
  StartBranchRunModal,
  StopBranchRunModal,
} from "@/server_manager/components/versioning/BranchRunModals";
import {
  ClassCVaultModal,
  CreateBranchModal,
  CreateCommitModal,
  DeployLiveModal,
  MergeBranchModal,
} from "@/server_manager/components/versioning/VersioningModals";
import type {
  PortSet,
  ServerBranch,
  ServerCommit,
} from "@/server_manager/types";

type VersioningTab = "branches" | "snapshots" | "sync";

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function classifyGitHubSyncError(
  err: unknown,
  fallback: string,
): GitHubSyncAlertState {
  const rec = isPlainObject(err) ? err : null;
  const detail = isPlainObject(rec?.detail) ? rec.detail : null;
  const code =
    typeof rec?.code === "string"
      ? rec.code
      : typeof detail?.code === "string"
        ? detail.code
        : null;
  const detailMessage =
    detail && typeof detail.message === "string" ? detail.message : null;
  const message =
    err instanceof Error && err.message
      ? err.message
      : detailMessage ?? fallback;

  if (code === "GITHUB_AUTH_FAILED" || detail?.needs_reauth === true) {
    return { kind: "auth_failed", code, message };
  }
  if (code === "GITHUB_NON_FAST_FORWARD_MAIN") {
    return {
      kind: "non_fast_forward_main",
      code,
      message,
      localSha: typeof detail?.local_sha === "string" ? detail.local_sha : null,
      remoteSha:
        typeof detail?.remote_sha === "string" ? detail.remote_sha : null,
    };
  }
  if (code === "GITHUB_PUSH_REJECTED") {
    const forbiddenPaths = Array.isArray(detail?.forbidden_paths)
      ? detail.forbidden_paths.filter((p): p is string => typeof p === "string")
      : [];
    return {
      kind: "push_rejected",
      code,
      message,
      branch: typeof detail?.branch === "string" ? detail.branch : null,
      reason: typeof detail?.reason === "string" ? detail.reason : null,
      forbiddenPaths,
    };
  }
  return { kind: "generic", code, message };
}

function normalizeTab(raw: string | null): VersioningTab {
  if (raw === "snapshots" || raw === "sync" || raw === "branches") {
    return raw;
  }
  return "branches";
}

function ServerVersioningPageInner() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { serverId = "" } = useParams<{ serverId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const branchCtx = useServerBranchContext();
  const { canVersioning } = useAuthPermissions();
  const canEdit = canVersioning(serverId);

  const activeTab = normalizeTab(searchParams.get("tab"));
  const setActiveTab = (tab: VersioningTab) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("tab", tab);
        return next;
      },
      { replace: true },
    );
  };

  // Selected branch synced with ServerBranchContext
  const [localBranch, setLocalBranch] = useState<string>(
    branchCtx?.branch || "main",
  );
  const candidateBranch = branchCtx?.branch || localBranch;
  const selectBranch = (name: string) => {
    setLocalBranch(name);
    branchCtx?.setBranch(name);
  };

  // Server detail query (shared cache key with ServerShell)
  const serverQuery = useQuery({
    queryKey: queryKeys.servers.detail(serverId),
    queryFn: () =>
      typeof api.getServer === "function"
        ? api.getServer(serverId)
        : Promise.resolve(null),
    enabled: Boolean(serverId),
  });
  const serverDetail = serverQuery.data ?? null;
  const resolvedMode = branchCtx?.serverMode ?? serverDetail?.mode;
  const isSimpleMode = resolvedMode === "simple";
  const queriesEnabled = Boolean(serverId) && !isSimpleMode;

  // React Query data hooks
  const branchesQuery = useVersioningBranches(serverId, queriesEnabled);
  const branches = useMemo(
    () => (Array.isArray(branchesQuery.data) ? branchesQuery.data : []),
    [branchesQuery.data],
  );
  const selectedBranch =
    branches.length > 0 && !branches.some((b) => b.name === candidateBranch)
      ? branches[0].name
      : candidateBranch;

  const commitsQuery = useVersioningCommits(
    serverId,
    selectedBranch,
    queriesEnabled,
  );
  const tagsQuery = useVersioningTags(serverId, queriesEnabled);
  const refreshStateQuery = useVersioningRefreshState(serverId, queriesEnabled);
  const settingsQuery = useVersioningSettings(serverId, queriesEnabled);
  const liveChangesQuery = useVersioningLiveChanges(
    serverId,
    selectedBranch,
    queriesEnabled,
  );
  const dataTemplatesQuery = useVersioningDataTemplates(
    serverId,
    queriesEnabled,
  );
  const branchRuntimeQuery = useBranchRuntimeQuery(
    serverId,
    selectedBranch,
    queriesEnabled && selectedBranch !== "main",
  );
  const githubStatusQuery = useGitHubStatusQuery(serverId, queriesEnabled);

  const commits = useMemo(
    () => (Array.isArray(commitsQuery.data) ? commitsQuery.data : []),
    [commitsQuery.data],
  );
  const tags = useMemo(
    () => (Array.isArray(tagsQuery.data) ? tagsQuery.data : []),
    [tagsQuery.data],
  );
  const refreshState = refreshStateQuery.data ?? null;
  const settings = settingsQuery.data ?? null;
  const liveChanges = liveChangesQuery.data ?? null;
  const dataTemplates = useMemo(
    () =>
      Array.isArray(dataTemplatesQuery.data) ? dataTemplatesQuery.data : [],
    [dataTemplatesQuery.data],
  );
  const branchRuntime = branchRuntimeQuery.data ?? null;
  const githubStatus = githubStatusQuery.data ?? null;

  const mutations = useVersioningMutations(serverId);

  // Page feedback banners
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Deep-link support for ?openVault=true
  const openVaultParam = searchParams.get("openVault");
  const [isVaultModalOpen, setIsVaultModalOpen] = useState(
    () => openVaultParam === "true",
  );
  const [prevOpenVaultParam, setPrevOpenVaultParam] = useState(openVaultParam);
  if (openVaultParam !== prevOpenVaultParam) {
    setPrevOpenVaultParam(openVaultParam);
    if (openVaultParam === "true") {
      setIsVaultModalOpen(true);
    }
  }
  useEffect(() => {
    if (openVaultParam !== "true") return;
    setSearchParams(
      (prev) => {
        if (!prev.has("openVault")) return prev;
        const next = new URLSearchParams(prev);
        next.delete("openVault");
        return next;
      },
      { replace: true },
    );
  }, [openVaultParam, setSearchParams]);

  // Modal & action state
  const [isNewBranchOpen, setIsNewBranchOpen] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");

  const [snapshotBranch, setSnapshotBranch] = useState<string | null>(null);
  const [newCommitMessage, setNewCommitMessage] = useState("");
  const [commitForceBypass, setCommitForceBypass] = useState(false);
  const [commitForceReason, setCommitForceReason] = useState("");

  const [deployModalTarget, setDeployModalTarget] = useState<{
    open: boolean;
    commit: ServerCommit | null;
  }>({ open: false, commit: null });

  const [showRollbackConfirm, setShowRollbackConfirm] = useState(false);

  const [mergeSourceBranch, setMergeSourceBranch] = useState<string | null>(
    null,
  );
  const [isMergeBranchOpen, setIsMergeBranchOpen] = useState(false);

  const [protectionModalBranch, setProtectionModalBranch] =
    useState<ServerBranch | null>(null);
  const [isManageBranchesOpen, setIsManageBranchesOpen] = useState(false);
  const [archiveConfirmBranch, setArchiveConfirmBranch] =
    useState<ServerBranch | null>(null);
  const [deleteConfirmBranch, setDeleteConfirmBranch] =
    useState<ServerBranch | null>(null);

  const [tagModalCommitId, setTagModalCommitId] = useState<string | null>(null);
  const [diffParams, setDiffParams] = useState<{
    from: string;
    to: string;
    parentIds?: string[];
  } | null>(null);

  // Branch Sandbox modal state
  const [sandboxTargetBranch, setSandboxTargetBranch] = useState<string | null>(
    null,
  );
  const [startSandboxModal, setStartSandboxModal] = useState<{
    open: boolean;
    branchName: string;
    commitSha?: string | null;
  }>({ open: false, branchName: "", commitSha: null });
  const [stopSandboxModal, setStopSandboxModal] = useState<{
    open: boolean;
    branchName: string;
    runtimeId?: string | null;
  }>({ open: false, branchName: "", runtimeId: null });
  const [portSetModal, setPortSetModal] = useState<{
    open: boolean;
    branchName: string;
    portSet: PortSet | null;
  }>({ open: false, branchName: "", portSet: null });
  const [destroyConfirmBranch, setDestroyConfirmBranch] = useState<
    string | null
  >(null);
  const [dataTemplatesModalMode, setDataTemplatesModalMode] = useState<
    "closed" | "list" | "save-branch"
  >("closed");
  const [saveTemplateRuntimeId, setSaveTemplateRuntimeId] = useState<
    string | null
  >(null);
  const [branchConsoleModal, setBranchConsoleModal] = useState<{
    branchName: string;
    tab: "console" | "activity";
  } | null>(null);
  const [uncommittedWarning, setUncommittedWarning] = useState<{
    branchName: string;
    commitSha: string;
  } | null>(null);

  // GitHub Sync modals & transient state
  const [isGitHubFetching, setIsGitHubFetching] = useState(false);
  const [isGitHubPushing, setIsGitHubPushing] = useState(false);
  const [githubSyncAlert, setGithubSyncAlert] =
    useState<GitHubSyncAlertState | null>(null);
  const [isConnectGitHubOpen, setIsConnectGitHubOpen] = useState(false);
  const [isRotateGitHubOpen, setIsRotateGitHubOpen] = useState(false);
  const [isDisconnectGitHubOpen, setIsDisconnectGitHubOpen] = useState(false);
  const [isWebhookDeliveriesOpen, setIsWebhookDeliveriesOpen] = useState(false);

  const mainBranchObj = branches.find((b) => b.name === "main") ?? null;
  const snapshotBranchObj =
    branches.find((b) => b.name === (snapshotBranch ?? selectedBranch)) ?? null;
  const isDirectCommitBlocked = Boolean(
    snapshotBranchObj?.is_protected &&
      snapshotBranchObj.protection_policy &&
      !snapshotBranchObj.protection_policy.allow_direct_commit,
  );
  const allowForceBypass = Boolean(
    snapshotBranchObj?.protection_policy?.allow_force_bypass,
  );

  const liveCommitSha = refreshState?.latest_journal?.target_main_sha || null;
  const latestJournal = refreshState?.latest_journal ?? null;
  const canConfirmUpgrade = Boolean(
    refreshState?.can_confirm_upgrade && latestJournal?.phase === "COMPLETED",
  );
  const canReleasePins = Boolean(
    latestJournal &&
      (latestJournal.phase === "ROLLED_BACK" ||
        latestJournal.phase === "FAILED_CLEAN") &&
      Boolean(latestJournal.class_c_snapshot_id),
  );

  // Surface critical query load failures honestly
  const loadError =
    branchesQuery.error || commitsQuery.error || refreshStateQuery.error;
  const loadErrorMsg =
    loadError instanceof Error ? loadError.message : null;

  // Simple Mode Guard: zero versioning API calls fired!
  if (isSimpleMode) {
    return (
      <div className="max-w-4xl mx-auto p-4 sm:p-6">
        <div
          data-testid="versioning-simple-mode-guard"
          className="rounded-xl border border-border-default bg-surface-card p-6 sm:p-8 text-center space-y-4 shadow-xs"
        >
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-accent-primary/10 text-accent-primary">
            <Icon name="version-branch" size={24} />
          </div>
          <div className="space-y-1.5">
            <h1 className="text-xl font-bold text-text-primary">
              Versions &amp; Sandboxes Requires Advanced Mode
            </h1>
            <p className="text-sm text-text-muted max-w-lg mx-auto">
              This server is currently running in Simple Mode. Switch to Git-backed Advanced Mode in Server Settings to unlock branches, isolated test sandboxes, snapshots, and instant rollback.
            </p>
          </div>
          <div>
            <Link
              to={`/servers/${serverId}/settings?tab=lifecycle`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover shadow-xs transition-colors"
            >
              <Icon name="settings" size={14} />
              Open Lifecycle Settings
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const refreshAll = () => {
    void invalidateVersioningScope(queryClient, serverId, selectedBranch);
  };

  const handleCreateBranch = async () => {
    const trimmed = newBranchName.trim();
    if (!serverId || !trimmed || !canEdit) return;
    setError(null);
    try {
      await mutations.createBranch.mutateAsync({ name: trimmed });
      selectBranch(trimmed);
      setNewBranchName("");
      setIsNewBranchOpen(false);
      setActionSuccess(`Branch '${trimmed}' created.`);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to create branch.",
      );
    }
  };

  const handleCreateCommit = async () => {
    const targetBranch = snapshotBranch ?? selectedBranch;
    if (!serverId || !newCommitMessage.trim() || !canEdit) return;
    setError(null);
    try {
      await mutations.createCommit.mutateAsync({
        message: newCommitMessage.trim(),
        branch_name: targetBranch,
        ...(commitForceBypass
          ? {
              force: true,
              force_reason: commitForceReason.trim() || undefined,
            }
          : {}),
      });
      setNewCommitMessage("");
      setCommitForceBypass(false);
      setCommitForceReason("");
      setSnapshotBranch(null);
      setActionSuccess(`Snapshot saved on '${targetBranch}'.`);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to save snapshot.",
      );
    }
  };

  const handleDeployOrRestore = async (
    retentionPolicy: string,
    targetCommitSha?: string | null,
  ) => {
    if (!serverId || !canEdit) return;
    setError(null);
    await mutations.refreshServer.mutateAsync({
      retention_policy: retentionPolicy,
      ...(targetCommitSha ? { target_main_sha: targetCommitSha } : {}),
    });
    setDeployModalTarget({ open: false, commit: null });
    setActionSuccess(
      targetCommitSha
        ? `Restored snapshot ${targetCommitSha.slice(0, 8)} to the live server.`
        : "Deployed main to the live server.",
    );
  };

  const handleGitHubFetch = async () => {
    if (!serverId || !api.fetchGitHubSync || !canEdit) return;
    setIsGitHubFetching(true);
    setGithubSyncAlert(null);
    try {
      const res = await api.fetchGitHubSync(serverId);
      setActionSuccess(
        res.main_fast_forwarded
          ? "Fetched from GitHub and fast-forwarded 'main'."
          : "Fetched from GitHub.",
      );
      refreshAll();
    } catch (err: unknown) {
      const classified = classifyGitHubSyncError(
        err,
        "Failed to fetch from GitHub.",
      );
      setGithubSyncAlert(classified);
      if (
        classified.kind === "auth_failed" ||
        classified.kind === "non_fast_forward_main"
      ) {
        refreshAll();
      }
    } finally {
      setIsGitHubFetching(false);
    }
  };

  const handleGitHubPush = async () => {
    if (!serverId || !selectedBranch || !api.pushGitHubBranch || !canEdit) {
      return;
    }
    setIsGitHubPushing(true);
    setGithubSyncAlert(null);
    try {
      const res = await api.pushGitHubBranch(serverId, {
        branch_name: selectedBranch,
      });
      setActionSuccess(
        `Pushed branch '${res.branch_name}' (${res.commit_sha.slice(0, 8)}) to GitHub.`,
      );
      refreshAll();
    } catch (err: unknown) {
      const classified = classifyGitHubSyncError(
        err,
        `Failed to push branch '${selectedBranch}' to GitHub.`,
      );
      setGithubSyncAlert(classified);
      if (
        classified.kind === "auth_failed" ||
        classified.kind === "non_fast_forward_main"
      ) {
        refreshAll();
      }
    } finally {
      setIsGitHubPushing(false);
    }
  };

  const activeSandboxBranch =
    sandboxTargetBranch ??
    (startSandboxModal.open
      ? startSandboxModal.branchName
      : stopSandboxModal.open
        ? stopSandboxModal.branchName
        : portSetModal.open
          ? portSetModal.branchName
          : selectedBranch);
  const activeSandboxBranchObj =
    branches.find((b) => b.name === activeSandboxBranch) ?? null;

  return (
    <div className="space-y-5 max-w-7xl mx-auto p-4 sm:p-6">
      {/* Compact Single-Row Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-border-default pb-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <Icon name="backup" size={22} className="text-accent-primary" />
            <h1 className="text-2xl font-bold text-text-primary">
              Versions &amp; Sandboxes
            </h1>
            {(liveCommitSha || mainBranchObj?.head_commit_id) && (
              <span
                data-testid="live-deployment-pill"
                className="inline-flex items-center gap-1.5 rounded-full border border-border-default bg-surface-card px-2.5 py-0.5 font-mono text-[11px] text-text-secondary"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-status-success" />
                Live:{" "}
                {(liveCommitSha || mainBranchObj?.head_commit_id || "").slice(
                  0,
                  8,
                )}
              </span>
            )}
            {githubStatus?.connected && (
              <button
                type="button"
                onClick={() => setActiveTab("sync")}
                className="inline-flex items-center gap-1 rounded-full border border-status-info-border bg-status-info-bg px-2.5 py-0.5 text-[11px] font-semibold text-status-info hover:opacity-90 cursor-pointer"
              >
                <Icon name="version-branch" size={11} />
                GitHub: {githubStatus.sync_status}
              </button>
            )}
            {!canEdit && (
              <span
                data-testid="versioning-readonly-badge"
                className="inline-flex items-center gap-1 rounded-full border border-border-default bg-surface-elevated px-2.5 py-0.5 text-[11px] font-semibold text-text-muted"
              >
                <Icon name="lock" size={11} />
                Read-only access
              </span>
            )}
          </div>
          <p className="text-xs text-text-muted">
            Test changes safely in isolated branch sandboxes, merge to main, and deploy with instant undo.
          </p>
        </div>

        {canEdit && (
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => setIsNewBranchOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover shadow-xs transition-colors cursor-pointer"
            >
              <Icon name="plus" size={13} />
              New Branch
            </button>

            {selectedBranch !== "main" && (
              <button
                type="button"
                onClick={() => setSnapshotBranch(selectedBranch)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs font-semibold text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
              >
                <Icon name="check" size={13} />
                Save Snapshot ({selectedBranch})
              </button>
            )}

            <button
              type="button"
              onClick={() =>
                setDeployModalTarget({ open: true, commit: null })
              }
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs font-semibold text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
            >
              <Icon name="upload" size={13} />
              Deploy main to Live
            </button>
          </div>
        )}
      </div>

      {/* Contextual Recovery Strip (ONLY rendered when undo or recovery pin release is active) */}
      {(refreshState?.can_rollback || canReleasePins) && (
        <div
          data-testid="contextual-recovery-strip"
          className="rounded-xl border border-status-info-border bg-status-info-bg p-3.5 flex flex-wrap items-center justify-between gap-3 text-xs"
        >
          {refreshState?.can_rollback ? (
            <>
              <div className="flex items-center gap-2 text-text-primary">
                <Icon
                  name="restart"
                  size={15}
                  className="text-status-info shrink-0"
                />
                <span>
                  Live server updated to{" "}
                  <code className="font-mono font-semibold">
                    {(
                      latestJournal?.target_main_sha ||
                      refreshState.active_journal?.target_main_sha ||
                      "latest"
                    ).slice(0, 8)}
                  </code>
                  . Previous server files are retained for instant undo.
                </span>
              </div>
              {canEdit && (
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={mutations.rollbackRefresh.isPending}
                    onClick={() => setShowRollbackConfirm(true)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-status-warning-border bg-surface-card px-3 py-1.5 font-semibold text-status-warning hover:bg-status-warning-bg disabled:opacity-50 cursor-pointer"
                  >
                    <Icon name="restart" size={12} />
                    {mutations.rollbackRefresh.isPending
                      ? "Undoing..."
                      : "Undo Last Deploy"}
                  </button>
                  {canConfirmUpgrade && (
                    <button
                      type="button"
                      disabled={mutations.confirmUpgrade.isPending}
                      onClick={async () => {
                        try {
                          await mutations.confirmUpgrade.mutateAsync({
                            journal_id: latestJournal?.journal_id,
                          });
                          setActionSuccess(
                            "Deployment confirmed and previous backup freed.",
                          );
                        } catch (err: unknown) {
                          setError(
                            err instanceof Error
                              ? err.message
                              : "Failed to confirm deployment.",
                          );
                        }
                      }}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 font-medium text-text-primary hover:bg-surface-hover disabled:opacity-50 cursor-pointer"
                    >
                      <Icon name="check" size={12} />
                      {mutations.confirmUpgrade.isPending
                        ? "Confirming..."
                        : "Keep & Free Disk Space"}
                    </button>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 text-text-primary">
                <Icon
                  name="lock"
                  size={15}
                  className="text-status-info shrink-0"
                />
                <span>
                  Recovery backup from a previous rollback is still pinned on disk.
                </span>
              </div>
              {canEdit && (
                <button
                  type="button"
                  disabled={mutations.releasePins.isPending}
                  onClick={async () => {
                    try {
                      await mutations.releasePins.mutateAsync({
                        journal_id: latestJournal?.journal_id,
                      });
                      setActionSuccess("Recovery backup pins released.");
                    } catch (err: unknown) {
                      setError(
                        err instanceof Error
                          ? err.message
                          : "Failed to release recovery backup.",
                      );
                    }
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 py-1.5 font-medium text-text-primary hover:bg-surface-hover disabled:opacity-50 cursor-pointer"
                >
                  <Icon name="lock" size={12} />
                  {mutations.releasePins.isPending
                    ? "Releasing..."
                    : "Release Recovery Backup"}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {/* Honest Load / Action Alerts */}
      {(error || loadErrorMsg) && (
        <div
          role="alert"
          className="rounded-xl bg-status-danger-bg border border-status-danger-border p-3.5 text-xs text-status-danger flex items-center justify-between gap-2"
        >
          <div className="flex items-center gap-2">
            <Icon name="alert" size={15} className="shrink-0" />
            <span>{error ?? loadErrorMsg}</span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {loadErrorMsg && (
              <button
                type="button"
                onClick={refreshAll}
                className="rounded border border-status-danger-border bg-surface-card px-2 py-1 text-[11px] font-medium hover:bg-surface-hover cursor-pointer"
              >
                Retry
              </button>
            )}
            {error && (
              <button
                type="button"
                aria-label="Dismiss error"
                onClick={() => setError(null)}
                className="hover:opacity-75 cursor-pointer"
              >
                <Icon name="x" size={15} />
              </button>
            )}
          </div>
        </div>
      )}

      {actionSuccess && (
        <div className="rounded-xl bg-status-success-bg border border-status-success/30 p-3.5 text-xs text-status-success flex items-center justify-between gap-2">
          <span>{actionSuccess}</span>
          <button
            type="button"
            aria-label="Dismiss message"
            onClick={() => setActionSuccess(null)}
            className="hover:opacity-75 cursor-pointer"
          >
            <Icon name="x" size={15} />
          </button>
        </div>
      )}

      {uncommittedWarning && (
        <div
          role="alert"
          data-testid="uncommitted-changes-warning"
          className="flex items-start justify-between gap-3 rounded-xl border border-status-warning-border bg-status-warning-bg p-3 text-xs text-status-warning"
        >
          <div className="flex items-start gap-2">
            <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
            <span>
              Uncommitted changes in{" "}
              <code className="font-mono font-semibold">
                {uncommittedWarning.branchName}
              </code>{" "}
              were not included. The sandbox is running the last committed snapshot (
              {uncommittedWarning.commitSha.slice(0, 8)}).
            </span>
          </div>
          <button
            type="button"
            onClick={() => setUncommittedWarning(null)}
            aria-label="Dismiss uncommitted changes warning"
            className="rounded p-0.5 hover:bg-status-warning/10 cursor-pointer"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      )}

      {/* 3-Tab Workspace Navigation */}
      <div
        role="tablist"
        aria-label="Versions and Sandboxes sections"
        className="flex flex-wrap items-center justify-between gap-2 border-b border-border-default pb-2"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              ["branches", "Branches & Sandboxes", "version-branch"],
              ["snapshots", "Snapshots & Rollback", "clock"],
              ["sync", "Sync & Vault", "lock"],
            ] as const
          ).map(([tabId, label, icon]) => (
            <button
              key={tabId}
              type="button"
              role="tab"
              aria-selected={activeTab === tabId}
              onClick={() => setActiveTab(tabId)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                activeTab === tabId
                  ? "bg-accent-primary text-accent-contrast-text shadow-xs"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
              }`}
            >
              <Icon name={icon} size={13} />
              <span>{label}</span>
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => setIsManageBranchesOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer"
        >
          <Icon name="settings" size={12} />
          <span>Manage All Branches ({branches.length})</span>
        </button>
      </div>

      {/* TAB 1: Branches & Sandboxes */}
      {activeTab === "branches" && (
        <BranchCockpitTab
          serverId={serverId}
          branches={branches}
          selectedBranch={selectedBranch}
          onSelectBranch={selectBranch}
          branchRuntime={branchRuntime}
          liveChangesCount={liveChanges?.changes?.length ?? 0}
          refreshState={refreshState}
          githubStatus={githubStatus}
          dataTemplates={dataTemplates}
          hasPendingSettings={Boolean(serverDetail?.pending_settings_branch)}
          canEdit={canEdit}
          isDestroyingBranch={
            mutations.destroyBranch.isPending ? destroyConfirmBranch : null
          }
          onOpenConsole={(branchName) => {
            selectBranch(branchName);
            navigate(
              `/servers/${serverId}/console?branch=${encodeURIComponent(branchName)}`,
            );
          }}
          onBrowseFiles={(branchName) => {
            selectBranch(branchName);
            navigate(
              branchName === "main"
                ? `/servers/${serverId}/files`
                : `/servers/${serverId}/files?branch=${encodeURIComponent(branchName)}`,
            );
          }}
          onDeployMainToLive={() =>
            setDeployModalTarget({ open: true, commit: null })
          }
          onNewBranch={() => setIsNewBranchOpen(true)}
          onOpenSnapshotModal={(branchName) => {
            selectBranch(branchName);
            setSnapshotBranch(branchName);
          }}
          onOpenMergeModal={(sourceBranch) => {
            setMergeSourceBranch(sourceBranch);
            setIsMergeBranchOpen(true);
          }}
          onOpenDiffVsMain={(branchName) =>
            setDiffParams({ from: "main", to: branchName })
          }
          onViewBranchSnapshots={(branchName) => {
            selectBranch(branchName);
            setActiveTab("snapshots");
          }}
          onOpenStartRun={(branchName) => {
            selectBranch(branchName);
            setSandboxTargetBranch(branchName);
            setStartSandboxModal({
              open: true,
              branchName,
              commitSha: null,
            });
          }}
          onOpenStopRun={(branchName, runtimeId) => {
            selectBranch(branchName);
            setSandboxTargetBranch(branchName);
            setStopSandboxModal({ open: true, branchName, runtimeId });
          }}
          onOpenPortSet={(branchName, portSet) => {
            selectBranch(branchName);
            setSandboxTargetBranch(branchName);
            setPortSetModal({ open: true, branchName, portSet });
          }}
          onOpenConsoleActivity={(branchName, tab) => {
            selectBranch(branchName);
            setBranchConsoleModal({ branchName, tab });
          }}
          onOpenSaveTemplate={(branchName, runtimeId) => {
            selectBranch(branchName);
            setSaveTemplateRuntimeId(runtimeId ?? null);
            setDataTemplatesModalMode("save-branch");
          }}
          onDestroyContainer={(branchName) =>
            setDestroyConfirmBranch(branchName)
          }
          onOpenProtection={(branch) => setProtectionModalBranch(branch)}
          onArchiveBranch={(branch) => setArchiveConfirmBranch(branch)}
          onDeleteBranch={(branch) => setDeleteConfirmBranch(branch)}
        />
      )}

      {/* TAB 2: Snapshots & Rollback */}
      {activeTab === "snapshots" && (
        <div className="space-y-4" data-testid="snapshots-rollback-tab">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border-default bg-surface-card p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-semibold text-text-secondary mr-1">
                Branch:
              </span>
              {branches.map((b) => (
                <button
                  key={b.name}
                  type="button"
                  onClick={() => selectBranch(b.name)}
                  className={`rounded-lg px-2.5 py-1 font-mono text-xs font-medium cursor-pointer transition-colors ${
                    selectedBranch === b.name
                      ? "bg-accent-primary text-accent-contrast-text"
                      : "border border-border-default bg-surface-page text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                  }`}
                >
                  {b.name}
                </button>
              ))}
            </div>

            {canEdit && selectedBranch !== "main" && (
              <button
                type="button"
                onClick={() => setSnapshotBranch(selectedBranch)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer"
              >
                <Icon name="plus" size={12} />
                Save Snapshot
              </button>
            )}
          </div>

          <CommitTimeline
            commits={commits}
            tags={tags}
            selectedBranch={selectedBranch}
            liveCommitSha={liveCommitSha}
            canEdit={canEdit}
            isLoading={commitsQuery.isLoading}
            onTagCommit={(commitId) => setTagModalCommitId(commitId)}
            onDiff={(from, to, parentIds) =>
              setDiffParams({ from, to, parentIds })
            }
            onRestoreToLive={(commit) =>
              setDeployModalTarget({ open: true, commit })
            }
            onTestInSandbox={(commit) =>
              setStartSandboxModal({
                open: true,
                branchName: selectedBranch,
                commitSha: commit.id,
              })
            }
          />
        </div>
      )}

      {/* TAB 3: Sync & Vault */}
      {activeTab === "sync" && (
        <SyncAndVaultTab
          serverId={serverId}
          selectedBranch={selectedBranch}
          branches={branches}
          canEdit={canEdit}
          settings={settings}
          isSavingRetention={mutations.updateSettings.isPending}
          onSaveRetention={async (policy) => {
            await mutations.updateSettings.mutateAsync({
              previous_tree_retention: policy,
            });
          }}
          githubStatus={githubStatus}
          isGitHubFetching={isGitHubFetching}
          isGitHubPushing={isGitHubPushing}
          githubSyncAlert={githubSyncAlert}
          onDismissSyncAlert={() => setGithubSyncAlert(null)}
          onFetchNow={handleGitHubFetch}
          onPushBranch={handleGitHubPush}
          onOpenConnectGitHub={() => setIsConnectGitHubOpen(true)}
          onOpenRotateGitHub={() => setIsRotateGitHubOpen(true)}
          onOpenDisconnectGitHub={() => setIsDisconnectGitHubOpen(true)}
          onOpenWebhookDeliveries={() => setIsWebhookDeliveriesOpen(true)}
          dataTemplates={dataTemplates}
          onOpenCreateTemplate={() => setDataTemplatesModalMode("list")}
          onDeleteTemplate={async (templateId) => {
            await api.deleteDataTemplate(serverId, templateId);
            refreshAll();
          }}
        />
      )}

      {/* Confirmation Dialogs */}
      <ConfirmDialog
        open={showRollbackConfirm}
        title="Undo Last Live Deployment?"
        description="Stops the live server, restores the previous server files and live world/plugin data snapshot, and restarts the server."
        confirmLabel="Undo Last Deploy"
        variant="danger"
        isPending={mutations.rollbackRefresh.isPending}
        onConfirm={async () => {
          try {
            await mutations.rollbackRefresh.mutateAsync({
              journal_id:
                refreshState?.active_journal?.journal_id ??
                latestJournal?.journal_id,
              reason: "operator_requested",
            });
            setShowRollbackConfirm(false);
            setActionSuccess("Reverted live server to previous deployment.");
          } catch (err: unknown) {
            setShowRollbackConfirm(false);
            setError(
              err instanceof Error ? err.message : "Undo deploy failed.",
            );
          }
        }}
        onCancel={() => setShowRollbackConfirm(false)}
      />

      <ConfirmDialog
        open={Boolean(destroyConfirmBranch)}
        title={`Destroy container for "${destroyConfirmBranch}"?`}
        description="Removes this branch's Docker container and /data export and releases its Host Port Set while keeping Git commits."
        confirmLabel="Destroy Container"
        variant="danger"
        isPending={mutations.destroyBranch.isPending}
        onConfirm={async () => {
          const target = destroyConfirmBranch;
          if (!target) return;
          try {
            await mutations.destroyBranch.mutateAsync(target);
            setDestroyConfirmBranch(null);
            setActionSuccess(`Destroyed container for branch '${target}'.`);
          } catch (err: unknown) {
            setDestroyConfirmBranch(null);
            setError(
              err instanceof Error
                ? err.message
                : "Failed to destroy branch container.",
            );
          }
        }}
        onCancel={() => setDestroyConfirmBranch(null)}
      />

      <ConfirmDialog
        open={Boolean(archiveConfirmBranch)}
        title={`Archive branch "${archiveConfirmBranch?.name}"?`}
        description="Archived branches become read-only and their worktree is removed while preserving Git commit history."
        confirmLabel="Archive Branch"
        variant="danger"
        isPending={mutations.archiveBranch.isPending}
        onConfirm={async () => {
          const target = archiveConfirmBranch;
          if (!target) return;
          try {
            await mutations.archiveBranch.mutateAsync(target.name);
            setArchiveConfirmBranch(null);
            setActionSuccess(`Branch '${target.name}' archived.`);
          } catch (err: unknown) {
            setArchiveConfirmBranch(null);
            setError(
              err instanceof Error ? err.message : "Failed to archive branch.",
            );
          }
        }}
        onCancel={() => setArchiveConfirmBranch(null)}
      />

      <ConfirmDialog
        open={Boolean(deleteConfirmBranch)}
        title={`Delete branch "${deleteConfirmBranch?.name}"?`}
        description="Permanently removes this branch's worktree, Git ref, and any stopped sandbox container. Commits already merged into main remain intact."
        confirmLabel="Delete Branch"
        variant="danger"
        isPending={mutations.deleteBranch.isPending}
        onConfirm={async () => {
          const target = deleteConfirmBranch;
          if (!target) return;
          try {
            await mutations.deleteBranch.mutateAsync(target.name);
            setDeleteConfirmBranch(null);
            if (selectedBranch === target.name) {
              selectBranch("main");
            }
            setActionSuccess(`Branch '${target.name}' deleted.`);
          } catch (err: unknown) {
            setDeleteConfirmBranch(null);
            setError(
              err instanceof Error ? err.message : "Failed to delete branch.",
            );
          }
        }}
        onCancel={() => setDeleteConfirmBranch(null)}
      />

      {/* Modals */}
      <CreateBranchModal
        isOpen={isNewBranchOpen}
        branchName={newBranchName}
        onBranchNameChange={setNewBranchName}
        onSubmit={handleCreateBranch}
        onClose={() => setIsNewBranchOpen(false)}
        isPending={mutations.createBranch.isPending}
      />

      <CreateCommitModal
        isOpen={Boolean(snapshotBranch)}
        message={newCommitMessage}
        onMessageChange={setNewCommitMessage}
        forceBypass={commitForceBypass}
        onForceBypassChange={setCommitForceBypass}
        forceReason={commitForceReason}
        onForceReasonChange={setCommitForceReason}
        selectedBranch={snapshotBranch ?? selectedBranch}
        currentBranchObj={snapshotBranchObj}
        isDirectCommitBlocked={isDirectCommitBlocked}
        allowForceBypass={allowForceBypass}
        onSubmit={handleCreateCommit}
        onClose={() => setSnapshotBranch(null)}
        isPending={mutations.createCommit.isPending}
      />

      <DeployLiveModal
        isOpen={deployModalTarget.open}
        targetCommit={deployModalTarget.commit}
        mainHeadSha={mainBranchObj?.head_commit_id}
        defaultRetention={settings?.previous_tree_retention}
        isPending={mutations.refreshServer.isPending}
        onConfirm={handleDeployOrRestore}
        onClose={() => setDeployModalTarget({ open: false, commit: null })}
      />

      <MergeBranchModal
        isOpen={isMergeBranchOpen}
        serverId={serverId}
        branches={branches}
        selectedBranch={selectedBranch}
        initialSourceBranch={mergeSourceBranch}
        onMerged={refreshAll}
        onDeployMain={() => setDeployModalTarget({ open: true, commit: null })}
        onClose={() => {
          setIsMergeBranchOpen(false);
          setMergeSourceBranch(null);
        }}
      />

      <ClassCVaultModal
        isOpen={isVaultModalOpen}
        serverId={serverId}
        canEdit={canEdit}
        onClose={() => setIsVaultModalOpen(false)}
      />

      {protectionModalBranch && (
        <BranchProtectionModal
          isOpen={Boolean(protectionModalBranch)}
          onClose={() => setProtectionModalBranch(null)}
          serverId={serverId}
          branch={protectionModalBranch}
          canEdit={canEdit}
          onProtectionUpdated={refreshAll}
        />
      )}

      {isManageBranchesOpen && (
        <ManageBranchesModal
          isOpen={isManageBranchesOpen}
          onClose={() => setIsManageBranchesOpen(false)}
          serverId={serverId}
          branches={branches}
          currentBranchName={selectedBranch}
          canEdit={canEdit}
          onBranchesChanged={refreshAll}
          onOpenProtectionModal={(b) => setProtectionModalBranch(b)}
        />
      )}

      {tagModalCommitId && (
        <CreateTagModal
          isOpen={Boolean(tagModalCommitId)}
          onClose={() => setTagModalCommitId(null)}
          serverId={serverId}
          commitId={tagModalCommitId}
          onTagCreated={refreshAll}
        />
      )}

      {diffParams && (
        <CommitDiffModal
          isOpen={Boolean(diffParams)}
          onClose={() => setDiffParams(null)}
          serverId={serverId}
          fromCommitId={diffParams.from}
          toCommitId={diffParams.to}
          parentCommitIds={diffParams.parentIds}
          headCommitId={commits[0]?.id ?? null}
        />
      )}

      {serverId && (
        <StartBranchRunModal
          isOpen={startSandboxModal.open}
          serverId={serverId}
          branchName={startSandboxModal.branchName || activeSandboxBranch}
          commitSha={startSandboxModal.commitSha}
          dataTemplates={dataTemplates}
          portSet={
            (startSandboxModal.branchName === selectedBranch
              ? branchRuntime?.port_set
              : null) ??
            activeSandboxBranchObj?.port_set ??
            null
          }
          onStarted={(result) => {
            if (result.uncommitted_changes_warning) {
              setUncommittedWarning({
                branchName: result.branch_name,
                commitSha: result.commit_sha,
              });
            }
            setActionSuccess(
              `Sandbox started for '${result.branch_name}' (${result.commit_sha.slice(0, 8)}).`,
            );
            refreshAll();
          }}
          onClose={() =>
            setStartSandboxModal({
              open: false,
              branchName: "",
              commitSha: null,
            })
          }
        />
      )}

      {serverId && (
        <StopBranchRunModal
          isOpen={stopSandboxModal.open}
          serverId={serverId}
          branchName={stopSandboxModal.branchName || activeSandboxBranch}
          runtimeId={stopSandboxModal.runtimeId}
          onStopped={(result) => {
            setActionSuccess(
              result.saved_template_name
                ? `Stopped sandbox '${result.branch_name}' and saved template '${result.saved_template_name}'.`
                : `Stopped sandbox for '${result.branch_name}'.`,
            );
            refreshAll();
          }}
          onClose={() =>
            setStopSandboxModal({
              open: false,
              branchName: "",
              runtimeId: null,
            })
          }
        />
      )}

      {serverId && (
        <BranchPortSetModal
          isOpen={portSetModal.open}
          serverId={serverId}
          branchName={portSetModal.branchName || activeSandboxBranch}
          portSet={portSetModal.portSet}
          onUpdated={(portSet) => {
            setActionSuccess(
              `Updated ports for '${portSetModal.branchName || activeSandboxBranch}' (Game ${portSet.game_port}, RCON ${portSet.rcon_port}).`,
            );
            refreshAll();
          }}
          onClose={() =>
            setPortSetModal({ open: false, branchName: "", portSet: null })
          }
        />
      )}

      {serverId && (
        <DataTemplatesModal
          isOpen={dataTemplatesModalMode !== "closed"}
          serverId={serverId}
          branches={branches}
          selectedBranch={selectedBranch}
          initialMode={
            dataTemplatesModalMode === "save-branch" ? "save-branch" : "list"
          }
          activeRuntimeId={saveTemplateRuntimeId}
          onTemplatesChanged={refreshAll}
          onClose={() => {
            setDataTemplatesModalMode("closed");
            setSaveTemplateRuntimeId(null);
          }}
        />
      )}

      {serverId && branchConsoleModal && (
        <BranchConsoleActivityModal
          isOpen={Boolean(branchConsoleModal)}
          serverId={serverId}
          branchName={branchConsoleModal.branchName}
          isRuntimeActive={Boolean(
            (() => {
              const targetObj = branches.find(
                (b) => b.name === branchConsoleModal.branchName,
              );
              const rtStatus =
                (branchConsoleModal.branchName === selectedBranch
                  ? branchRuntime?.runtime_status
                  : targetObj?.runtime_status) ?? "stopped";
              return rtStatus === "running" || rtStatus === "starting";
            })(),
          )}
          initialTab={branchConsoleModal.tab}
          onClose={() => setBranchConsoleModal(null)}
        />
      )}

      {serverId && (
        <ConnectGitHubModal
          isOpen={isConnectGitHubOpen}
          serverId={serverId}
          onConnected={() => {
            setGithubSyncAlert(null);
            setActionSuccess("Connected GitHub repository.");
            refreshAll();
          }}
          onClose={() => setIsConnectGitHubOpen(false)}
        />
      )}

      {serverId && (
        <RotateGitHubCredentialsModal
          isOpen={isRotateGitHubOpen}
          serverId={serverId}
          currentStatus={githubStatus}
          onRotated={() => {
            setGithubSyncAlert(null);
            setActionSuccess("Rotated GitHub credentials.");
            refreshAll();
          }}
          onClose={() => setIsRotateGitHubOpen(false)}
        />
      )}

      {serverId && (
        <DisconnectGitHubModal
          isOpen={isDisconnectGitHubOpen}
          serverId={serverId}
          remoteUrl={githubStatus?.remote_url ?? null}
          onDisconnected={() => {
            setGithubSyncAlert(null);
            setActionSuccess(
              "Disconnected from GitHub (local Git history preserved).",
            );
            refreshAll();
          }}
          onClose={() => setIsDisconnectGitHubOpen(false)}
        />
      )}

      {serverId && (
        <GitHubWebhookDeliveriesModal
          isOpen={isWebhookDeliveriesOpen}
          serverId={serverId}
          webhookEnabled={Boolean(githubStatus?.webhook_enabled)}
          webhookPath={githubStatus?.webhook_path ?? null}
          onRedelivered={(res) => {
            setActionSuccess(
              `Webhook delivery ${res.delivery_id} (${res.status}).`,
            );
            refreshAll();
          }}
          onClose={() => setIsWebhookDeliveriesOpen(false)}
        />
      )}
    </div>
  );
}

export function ServerVersioningPage() {
  const existingClient = useContext(QueryClientContext);
  const fallbackClient = useMemo(
    () =>
      existingClient ??
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
        },
      }),
    [existingClient],
  );

  if (existingClient) {
    return <ServerVersioningPageInner />;
  }

  return (
    <QueryClientProvider client={fallbackClient}>
      <ServerVersioningPageInner />
    </QueryClientProvider>
  );
}
