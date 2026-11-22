import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { isModpackSupportedLoader } from "@/server_manager/utils/loaderCapabilities";
import { TestRunModal } from "@/server_manager/components/TestRunModal";
import { BranchProtectionModal } from "@/server_manager/components/BranchProtectionModal";
import { TestDefinitionsModal } from "@/server_manager/components/TestDefinitionsModal";
import { TestEvidenceModal } from "@/server_manager/components/TestEvidenceModal";
import { MaterializationBrowserModal } from "@/server_manager/components/MaterializationBrowserModal";
import { ImportReviewModal } from "@/server_manager/components/ImportReviewModal";
import { ManageBranchesModal } from "@/server_manager/components/ManageBranchesModal";
import { CreateTagModal } from "@/server_manager/components/CreateTagModal";
import { CommitDiffModal } from "@/server_manager/components/CommitDiffModal";
import { StorageHealthBanner } from "@/server_manager/components/versioning/StorageHealthBanner";
import { BranchToolbar } from "@/server_manager/components/versioning/BranchToolbar";
import {
  GitHubSyncPanel,
  type GitHubSyncAlertState,
} from "@/server_manager/components/versioning/GitHubSyncPanel";
import {
  ConnectGitHubModal,
  DisconnectGitHubModal,
  GitHubWebhookDeliveriesModal,
  RotateGitHubCredentialsModal,
} from "@/server_manager/components/versioning/GitHubModals";
import { BranchRunPanel } from "@/server_manager/components/versioning/BranchRunPanel";
import {
  ModpackInstallWizardModal,
  SafeUpgradeWizardModal,
} from "@/server_manager/components/p55";
import {
  BranchConsoleActivityModal,
  BranchPortSetModal,
  DataTemplatesModal,
  StartBranchRunModal,
  StopBranchRunModal,
} from "@/server_manager/components/versioning/BranchRunModals";
import { CommitTimeline } from "@/server_manager/components/versioning/CommitTimeline";
import { TestRunList } from "@/server_manager/components/versioning/TestRunList";
import {
  CreateBranchModal,
  CreateCommitModal,
  InspectCommitModal,
  ViewLogsModal,
  BotSettingsModal,
  MergeBranchModal,
  ClassCVaultModal,
} from "@/server_manager/components/versioning/VersioningModals";
import type {
  BranchRuntimeStatus,
  ClassCSnapshot,
  DataTemplate,
  DynamicClassCEntry,
  GitHubConnectionStatusResponse,
  PortSet,
  PreflightStatus,
  RefreshStateResponse,
  ScanLiveChangesResponse,
  SecretMetadata,
  ServerBranch,
  ServerCommit,
  ServerTag,
  ServerTestRun,
} from "@/server_manager/types";

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
    return {
      kind: "auth_failed",
      code,
      message,
    };
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
  return {
    kind: "generic",
    code,
    message,
  };
}

export function ServerVersioningPage() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { serverId } = useParams<{ serverId: string }>();

  const [branches, setBranches] = useState<ServerBranch[]>([]);
  const [selectedBranch, setSelectedBranch] = useState<string>("main");
  const [commits, setCommits] = useState<ServerCommit[]>([]);
  const [testRuns, setTestRuns] = useState<ServerTestRun[]>([]);
  const [preflight, setPreflight] = useState<PreflightStatus | null>(null);
  const [tags, setTags] = useState<ServerTag[]>([]);
  const [liveChanges, setLiveChanges] = useState<ScanLiveChangesResponse | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState<number>(0);
  const [isWorkflowGuideOpen, setIsWorkflowGuideOpen] = useState(false);

  const refresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  // Modals state
  const [isNewBranchOpen, setIsNewBranchOpen] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");
  const [isP55ModpackWizardOpen, setIsP55ModpackWizardOpen] = useState(false);
  const [isP55SafeUpgradeWizardOpen, setIsP55SafeUpgradeWizardOpen] = useState(false);

  const [isNewCommitOpen, setIsNewCommitOpen] = useState(false);
  const [newCommitMessage, setNewCommitMessage] = useState("");
  const [commitForceBypass, setCommitForceBypass] = useState(false);
  const [commitForceReason, setCommitForceReason] = useState("");

  const [testModalCommitId, setTestModalCommitId] = useState<string | null>(null);

  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [settingsBotCount, setSettingsBotCount] = useState(10);
  const [settingsDuration, setSettingsDuration] = useState(15);
  const [settingsTech, setSettingsTech] = useState("auto");
  const [settingsPlacement, setSettingsPlacement] = useState("sidecar");
  const [settingsRetention, setSettingsRetention] = useState("until_health_gate");

  const [refreshState, setRefreshState] = useState<RefreshStateResponse | null>(null);
  const [, setClassCSnapshots] = useState<ClassCSnapshot[]>([]);
  const [, setDynamicClassC] = useState<DynamicClassCEntry[]>([]);
  const [, setSecrets] = useState<SecretMetadata[]>([]);

  const [isMergeBranchOpen, setIsMergeBranchOpen] = useState(false);
  const [isVaultModalOpen, setIsVaultModalOpen] = useState(false);

  // P4 branch runs, port sets & data templates state
  const [dataTemplates, setDataTemplates] = useState<DataTemplate[]>([]);
  const [branchRuntime, setBranchRuntime] = useState<BranchRuntimeStatus | null>(null);
  const [uncommittedWarning, setUncommittedWarning] = useState<{ commitSha: string } | null>(null);
  const [isStartBranchRunOpen, setIsStartBranchRunOpen] = useState(false);
  const [isStopBranchRunOpen, setIsStopBranchRunOpen] = useState(false);
  const [isPortSetModalOpen, setIsPortSetModalOpen] = useState(false);
  const [dataTemplatesModalMode, setDataTemplatesModalMode] = useState<"closed" | "list" | "save-branch">("closed");
  const [branchConsoleModalTab, setBranchConsoleModalTab] = useState<null | "console" | "activity">(null);

  // P5 GitHub sync state & modals
  const [githubStatus, setGithubStatus] = useState<GitHubConnectionStatusResponse | null>(null);
  const [isGitHubFetching, setIsGitHubFetching] = useState(false);
  const [isGitHubPushing, setIsGitHubPushing] = useState(false);
  const [githubSyncAlert, setGithubSyncAlert] = useState<GitHubSyncAlertState | null>(null);
  const [isConnectGitHubOpen, setIsConnectGitHubOpen] = useState(false);
  const [isRotateGitHubOpen, setIsRotateGitHubOpen] = useState(false);
  const [isDisconnectGitHubOpen, setIsDisconnectGitHubOpen] = useState(false);
  const [isWebhookDeliveriesOpen, setIsWebhookDeliveriesOpen] = useState(false);

  const [inspectCommit, setInspectCommit] = useState<ServerCommit | null>(null);
  const [viewLogTestRun, setViewLogTestRun] = useState<ServerTestRun | null>(null);

  // Advanced feature modal controls
  const [isProtectionModalOpen, setIsProtectionModalOpen] = useState(false);
  const [protectionModalBranch, setProtectionModalBranch] = useState<ServerBranch | null>(null);
  const [isTestDefinitionsOpen, setIsTestDefinitionsOpen] = useState(false);
  const [evidenceModalTestId, setEvidenceModalTestId] = useState<string | null>(null);
  const [isMaterializationOpen, setIsMaterializationOpen] = useState(false);
  const [isLiveChangesOpen, setIsLiveChangesOpen] = useState(false);
  const [isManageBranchesOpen, setIsManageBranchesOpen] = useState(false);
  const [tagModalCommitId, setTagModalCommitId] = useState<string | null>(null);
  const [diffParams, setDiffParams] = useState<{ from: string; to: string } | null>(null);

  // Mutation pending guards for modals
  const [isBranchPending, setIsBranchPending] = useState(false);
  const [isCommitPending, setIsCommitPending] = useState(false);
  const [isSettingsPending, setIsSettingsPending] = useState(false);
  const [serverType, setServerType] = useState<string | null>(null);

  const currentBranchObj = useMemo(
    () => branches.find((b) => b.name === selectedBranch) || null,
    [branches, selectedBranch]
  );

  const isDirectCommitBlocked = Boolean(
    currentBranchObj?.is_protected &&
    currentBranchObj.protection_policy &&
    !currentBranchObj.protection_policy.allow_direct_commit
  );
  const allowForceBypass = Boolean(
    currentBranchObj?.protection_policy?.allow_force_bypass
  );

  const resolvedServerType = serverType ?? commits[0]?.manifest?.server_type ?? null;
  const supportsModpacks = resolvedServerType
    ? isModpackSupportedLoader(resolvedServerType)
    : false;

  const branchRuntimeStatus =
    branchRuntime?.runtime_status ?? currentBranchObj?.runtime_status ?? "stopped";
  const isBranchRuntimeActive =
    branchRuntimeStatus === "running" || branchRuntimeStatus === "starting";
  const effectivePortSet =
    branchRuntime?.port_set ?? currentBranchObj?.port_set ?? null;
  const selectedBranchGitHubSync = useMemo(() => {
    if (!githubStatus?.connected) return null;
    return githubStatus.branches.find((b) => b.branch === selectedBranch) ?? null;
  }, [githubStatus, selectedBranch]);

  useEffect(() => {
    if (!serverId) return;
    let isMounted = true;

    const run = async () => {
      try {
        const [branchesData, commitsData, settingsData, preflightData, testRunsData, tagsData, liveData, refreshStateData, snapshotsData, dynamicData, secretsData, templatesData, runtimeData, githubStatusData, serverDetailData] =
          await Promise.all([
            api.getServerBranches(serverId),
            api.getServerCommits(serverId, undefined, undefined, selectedBranch),
            api.getBotSettings(serverId),
            api.getPreflightStatus(serverId),
            api.getServerTestRuns?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
            api.getServerTags?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
            api.getLiveChanges?.(serverId, selectedBranch || "main")?.catch(() => null) ??
              Promise.resolve(null),
            api.getRefreshState?.(serverId)?.catch(() => null) ?? Promise.resolve(null),
            api.listClassCSnapshots?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
            api.listDynamicClassC?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
            api.listSecrets?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
            api.listDataTemplates?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
            selectedBranch && selectedBranch !== "main"
              ? (api.getBranchRuntime?.(serverId, selectedBranch)?.catch(() => null) ?? Promise.resolve(null))
              : Promise.resolve(null),
            api.getGitHubStatus?.(serverId)?.catch(() => null) ?? Promise.resolve(null),
            api.getServer?.(serverId)?.catch(() => null) ?? Promise.resolve(null),
          ]);

        if (!isMounted) return;
        setBranches(branchesData);
        setCommits(commitsData);
        setPreflight(preflightData);
        setTestRuns(testRunsData);
        setTags(tagsData);
        setLiveChanges(liveData);
        setRefreshState(refreshStateData);
        setClassCSnapshots(Array.isArray(snapshotsData) ? snapshotsData : []);
        setDynamicClassC(Array.isArray(dynamicData) ? dynamicData : []);
        setSecrets(Array.isArray(secretsData) ? secretsData : []);
        setDataTemplates(Array.isArray(templatesData) ? templatesData : []);
        setBranchRuntime(runtimeData ?? null);
        setGithubStatus(githubStatusData ?? null);
        setServerType(serverDetailData?.server_type ?? null);

        if (settingsData) {
          setSettingsBotCount(settingsData.effective_bot_count);
          setSettingsDuration(settingsData.effective_duration_minutes);
          setSettingsTech(settingsData.effective_bot_tech);
          setSettingsPlacement(settingsData.effective_placement_mode);
          if (settingsData.previous_tree_retention) setSettingsRetention(settingsData.previous_tree_retention);
        }

        if (
          branchesData.length > 0 &&
          !branchesData.some((b: ServerBranch) => b.name === selectedBranch)
        ) {
          setSelectedBranch(branchesData[0].name);
        }
      } catch (err: unknown) {
        if (!isMounted) return;
        const msg = err instanceof Error ? err.message : "Failed to load versioning state.";
        setError(msg);
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };

    run();

    return () => {
      isMounted = false;
    };
  }, [serverId, selectedBranch, api, refreshKey]);

  // Polling: refresh test runs every 3 seconds only while active runs exist
  const hasActiveRuns = useMemo(
    () => testRuns.some((r) => r.status === "RUNNING" || r.status === "PENDING"),
    [testRuns]
  );

  useEffect(() => {
    if (!hasActiveRuns || !serverId) return;
    const interval = setInterval(async () => {
      try {
        const runs = await api.getServerTestRuns(serverId);
        setTestRuns(runs);
      } catch {
        // Silent catch on background polling error
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [hasActiveRuns, serverId, api]);

  // Poll branch runtime every 5s only while the selected branch is starting/running.
  useEffect(() => {
    if (!serverId || selectedBranch === "main") return;
    const runtimeStatus = branchRuntime?.runtime_status;
    if (runtimeStatus !== "running" && runtimeStatus !== "starting") return;
    let isMounted = true;

    const interval = setInterval(async () => {
      try {
        const runtime =
          (await (api.getBranchRuntime?.(serverId, selectedBranch)?.catch(() => null) ??
            Promise.resolve(null)));
        if (isMounted && runtime) {
          setBranchRuntime(runtime);
        }
      } catch {
        // Silent catch on background polling error
      }
    }, 5000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [serverId, selectedBranch, branchRuntime?.runtime_status, api]);

  const handleCreateBranch = async () => {
    if (!serverId || !newBranchName.trim()) return;
    setIsBranchPending(true);
    try {
      await api.createServerBranch(serverId, { name: newBranchName.trim() });
      setSelectedBranch(newBranchName.trim());
      setNewBranchName("");
      setIsNewBranchOpen(false);
      setActionSuccess(`Branch '${newBranchName.trim()}' created.`);
      refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create branch.");
    } finally {
      setIsBranchPending(false);
    }
  };

  const handleCreateCommit = async () => {
    if (!serverId || !newCommitMessage.trim()) return;
    setIsCommitPending(true);
    try {
      await api.createServerCommit(serverId, {
        message: newCommitMessage.trim(),
        branch_name: selectedBranch,
        ...(commitForceBypass
          ? { force: true, force_reason: commitForceReason.trim() || undefined }
          : {}),
      });
      setNewCommitMessage("");
      setCommitForceBypass(false);
      setCommitForceReason("");
      setIsNewCommitOpen(false);
      setActionSuccess("Snapshot commit created successfully.");
      refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create commit.");
    } finally {
      setIsCommitPending(false);
    }
  };

  const handleDiscard = async (testId: string) => {
    if (!serverId) return;
    try {
      await api.discardTest(serverId, testId);
      setActionSuccess("Test run discarded.");
      setTestRuns((prev) =>
        prev.map((t) => (t.id === testId ? { ...t, status: "CANCELLED" } : t))
      );
      refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to discard test run.");
    }
  };

  const handleSaveSettings = async () => {
    if (!serverId) return;
    setIsSettingsPending(true);
    try {
      await api.updateBotSettings(serverId, {
        bot_count: settingsBotCount,
        duration_minutes: settingsDuration,
        bot_tech: settingsTech,
        placement_mode: settingsPlacement,
        previous_tree_retention: settingsRetention,
      });
      setIsSettingsModalOpen(false);
      setActionSuccess("Bot verification settings updated.");
      refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update settings.");
    } finally {
      setIsSettingsPending(false);
    }
  };

  const onTestStarted = (testId: string) => {
    setActionSuccess(`Isolated test launched (ID: ${testId.slice(0, 8)}).`);
    if (serverId && testId) {
      api.getTestStatus(serverId, testId).then((t: ServerTestRun) => {
        setTestRuns((prev) => [t, ...prev.filter((item) => item.id !== t.id)]);
      }).catch(() => {
        refresh();
      });
    }
  };

  const handleGitHubFetch = async () => {
    if (!serverId || !api.fetchGitHubSync) return;
    setIsGitHubFetching(true);
    setGithubSyncAlert(null);
    try {
      const res = await api.fetchGitHubSync(serverId);
      setActionSuccess(
        res.main_fast_forwarded
          ? "Fetched from GitHub and fast-forwarded 'main'."
          : "Fetched from GitHub.",
      );
      refresh();
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
        refresh();
      }
    } finally {
      setIsGitHubFetching(false);
    }
  };

  const handleGitHubPush = async () => {
    if (!serverId || !selectedBranch || !api.pushGitHubBranch) return;
    setIsGitHubPushing(true);
    setGithubSyncAlert(null);
    try {
      const res = await api.pushGitHubBranch(serverId, {
        branch_name: selectedBranch,
      });
      setActionSuccess(
        `Pushed branch '${res.branch_name}' (${res.commit_sha.slice(0, 8)}) to GitHub.`,
      );
      refresh();
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
        refresh();
      }
    } finally {
      setIsGitHubPushing(false);
    }
  };

  const filteredCommits = commits.filter((c) => {
    const branchObj = branches.find((b) => b.name === selectedBranch);
    return !branchObj || c.branch_id === branchObj.id || !c.branch_id;
  });

  return (
    <div className="space-y-6 max-w-7xl mx-auto p-4 sm:p-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-border-default pb-5">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <Icon name="backup" size={24} className="text-accent-primary" />
            <h1 className="text-2xl font-bold text-text-primary">
              Versions & Isolated Testing
            </h1>
            <StorageHealthBanner preflight={preflight} />
          </div>
          <p className="mt-1 text-sm text-text-muted">
            Git-inspired server snapshots, config commits, and isolated bot-verified dry-runs.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsSettingsModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-3 py-2 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            <Icon name="settings" size={14} />
            Verification Defaults
          </button>
          <button
            type="button"
            onClick={() => setIsNewCommitOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-2 text-xs font-semibold text-white hover:bg-accent-hover shadow-xs transition-colors cursor-pointer"
          >
            <Icon name="plus" size={14} />
            Create Snapshot Commit
          </button>
        </div>
      </div>

      {/* P3 Live Refresh & Upgrade Bar */}
      <div className="flex flex-wrap items-center gap-2" data-testid="p3-refresh-toolbar">
        <button
          type="button"
          aria-label="Live Refresh"
          onClick={async () => {
            if (!serverId) return;
            try {
              await api.refreshServer(serverId, { retention_policy: settingsRetention });
              setActionSuccess("Live Refresh completed");
              refresh();
            } catch (e) {
              setError(e instanceof Error ? e.message : "Live Refresh failed");
            }
          }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
        >
          <Icon name="activity" size={13} />
          <span>Live Refresh</span>
          {refreshState?.active_journal?.phase || refreshState?.latest_journal?.phase ? (
            <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[10px] font-semibold text-text-muted">
              {refreshState?.active_journal?.phase || refreshState?.latest_journal?.phase}
            </span>
          ) : null}
        </button>
        <button
          type="button"
          aria-label="Rollback"
          disabled={!refreshState?.can_rollback}
          title={!refreshState?.can_rollback ? "No active or rollback-eligible refresh journal" : undefined}
          onClick={async () => {
            if (!serverId) return;
            try {
              await api.rollbackRefresh(serverId, {
                journal_id: refreshState?.active_journal?.journal_id ?? refreshState?.latest_journal?.journal_id,
                reason: "operator_requested",
              });
              setActionSuccess("Rollback completed");
              refresh();
            } catch (e) {
              setError(e instanceof Error ? e.message : "Rollback failed");
            }
          }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer disabled:opacity-50"
        >
          <Icon name="restart" size={13} />
          <span>Rollback</span>
        </button>
        <button
          type="button"
          aria-label="Confirm Upgrade"
          disabled={!refreshState?.can_confirm_upgrade}
          onClick={async () => {
            if (!serverId) return;
            try {
              await api.confirmUpgrade(serverId, { journal_id: refreshState?.latest_journal?.journal_id });
              setActionSuccess("Upgrade confirmed");
              refresh();
            } catch (e) {
              setError(e instanceof Error ? e.message : "Confirm upgrade failed");
            }
          }}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer disabled:opacity-50"
        >
          <Icon name="check" size={13} />
          <span>Confirm Upgrade</span>
        </button>
        {(refreshState?.latest_journal?.class_c_snapshot_id || refreshState?.can_confirm_upgrade) && (
          <button
            type="button"
            aria-label="Release Pins"
            onClick={async () => {
              if (!serverId) return;
              try {
                await api.releaseRefreshPins(serverId, { journal_id: refreshState?.latest_journal?.journal_id });
                setActionSuccess("Pins released");
                refresh();
              } catch (e) {
                setError(e instanceof Error ? e.message : "Release pins failed");
              }
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            <Icon name="lock" size={13} />
            <span>Release Pins</span>
          </button>
        )}
        <button
          type="button"
          aria-label="Class-C & Secret Vault"
          onClick={() => setIsVaultModalOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
        >
          <Icon name="lock" size={13} />
          <span>Class-C & Secret Vault</span>
        </button>
        <button
          type="button"
          aria-label="Data Templates"
          onClick={() => setDataTemplatesModalMode("list")}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
        >
          <Icon name="database" size={13} />
          <span>Data Templates</span>
        </button>
        {supportsModpacks && (
          <button
            type="button"
            data-testid="versioning-open-modpack-wizard-btn"
            onClick={() => setIsP55ModpackWizardOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-accent-primary/40 bg-accent-primary/10 px-2.5 py-1.5 text-xs font-medium text-accent-primary hover:bg-accent-primary/20 transition-colors cursor-pointer"
          >
            <Icon name="download" size={13} />
            <span>Install Modpack</span>
          </button>
        )}
        <button
          type="button"
          data-testid="versioning-open-safe-upgrade-wizard-btn"
          onClick={() => setIsP55SafeUpgradeWizardOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-accent-primary/40 bg-accent-primary/10 px-2.5 py-1.5 text-xs font-medium text-accent-primary hover:bg-accent-primary/20 transition-colors cursor-pointer"
        >
          <Icon name="restart" size={13} />
          <span>1-Click Safe Upgrade Wizard</span>
        </button>
      </div>

      {/* Interactive 3-Step Visual Workflow Guide Banner */}
      <section
        aria-label="Guided Versioning & Testing Workflow"
        className="rounded-xl border border-border-default bg-surface-card p-4 sm:p-5 shadow-xs space-y-4"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-accent-primary/15 text-accent-primary shrink-0">
              <Icon name="activity" size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold text-text-primary">
                3-Step Safe Testing &amp; Promotion Workflow
              </h2>
              <p className="text-xs text-text-muted">
                Follow this automated cycle to preview changes safely without risking your production world.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIsWorkflowGuideOpen((prev) => !prev)}
            aria-expanded={isWorkflowGuideOpen}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer shrink-0"
          >
            <Icon name={isWorkflowGuideOpen ? "chevron-up" : "chevron-down"} size={14} />
            <span>{isWorkflowGuideOpen ? "Collapse Guide" : "Expand Guide"}</span>
          </button>
        </div>

        {isWorkflowGuideOpen && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5 pt-1">
            {/* Step 1 */}
            <div className="flex flex-col justify-between rounded-lg bg-surface-elevated/50 p-3.5 space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-bold text-accent-primary">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-primary/20 text-[11px] font-mono font-bold">
                    1
                  </span>
                  <span>Step 1: Snapshot World (Commit)</span>
                </div>
                <p className="text-xs text-text-muted leading-relaxed" title="copy-on-write / Btrfs / ZFS">
                  Capture an instant storage snapshot of your world &amp; configs.
                </p>
              </div>
            </div>

            {/* Step 2 */}
            <div className="flex flex-col justify-between rounded-lg bg-surface-elevated/50 p-3.5 space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-bold text-accent-primary">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-primary/20 text-[11px] font-mono font-bold">
                    2
                  </span>
                  <span>Step 2: Isolate (Branch / Worktree)</span>
                </div>
                <p className="text-xs text-text-muted leading-relaxed">
                  Create a safe branch to test new plugins or server updates without risking production.
                </p>
              </div>
            </div>

            {/* Step 3 */}
            <div className="flex flex-col justify-between rounded-lg bg-surface-elevated/50 p-3.5 space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-bold text-accent-primary">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-primary/20 text-[11px] font-mono font-bold">
                    3
                  </span>
                  <span>Step 3: Automated Bot Dry-Run (Verify)</span>
                </div>
                <p className="text-xs text-text-muted leading-relaxed">
                  Spawn a safe test environment with simulated players to audit TPS and crashes.
                </p>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Alerts */}
      {error && (
        <div role="alert" className="rounded-xl bg-surface-muted border border-border-subtle p-4 text-sm text-status-danger flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon name="alert" size={16} className="text-status-danger shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError(null)}
            className="text-status-danger hover:opacity-75 cursor-pointer"
          >
            <Icon name="x" size={16} />
          </button>
        </div>
      )}

      {actionSuccess && (
        <div className="rounded-xl bg-status-success-bg border border-status-success/30 p-4 text-sm text-status-success flex items-center justify-between">
          <span>{actionSuccess}</span>
          <button
            type="button"
            aria-label="Dismiss message"
            onClick={() => setActionSuccess(null)}
            className="text-status-success hover:opacity-75 cursor-pointer"
          >
            <Icon name="x" size={16} />
          </button>
        </div>
      )}

      {/* Live Changes Callout Banner */}
      {Boolean(liveChanges?.changes && liveChanges.changes.length > 0) && (
        <div className="rounded-xl border border-status-warning/40 bg-status-warning-bg p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 animate-fade-in">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-status-warning/20 rounded-lg text-status-warning shrink-0">
              <Icon name="alert" size={20} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-primary">
                Uncommitted Live Server Changes Detected
              </h3>
              <p className="text-xs text-text-muted">
                {liveChanges?.changes?.length || 0} file{liveChanges?.changes?.length === 1 ? "" : "s"} modified or created on the server filesystem since HEAD.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIsLiveChangesOpen(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-status-warning hover:bg-status-warning/90 rounded-lg transition-colors shadow-xs shrink-0 cursor-pointer"
          >
            Review & Commit Changes
          </button>
        </div>
      )}

      {/* Branch Navigation Toolbar */}
      <BranchToolbar
        branches={branches}
        selectedBranch={selectedBranch}
        onSelectBranch={(branch) => {
          setSelectedBranch(branch);
          setUncommittedWarning(null);
          setBranchRuntime(null);
        }}
        currentBranchObj={currentBranchObj}
        filteredCommitsCount={filteredCommits.length}
        onNewBranch={() => setIsNewBranchOpen(true)}
        onProtectionRules={() => {
          setProtectionModalBranch(currentBranchObj);
          setIsProtectionModalOpen(true);
        }}
        onManageBranches={() => setIsManageBranchesOpen(true)}
        onExploreWorktree={() => setIsMaterializationOpen(true)}
        onMergeBranch={() => setIsMergeBranchOpen(true)}
        githubBranchSync={selectedBranchGitHubSync}
      />

      {/* P5 GitHub Sync Panel */}
      <GitHubSyncPanel
        status={githubStatus}
        selectedBranch={selectedBranch}
        isFetching={isGitHubFetching}
        isPushing={isGitHubPushing}
        syncAlert={githubSyncAlert}
        onDismissSyncAlert={() => setGithubSyncAlert(null)}
        onFetchNow={handleGitHubFetch}
        onPushBranch={handleGitHubPush}
        onOpenConnectModal={() => setIsConnectGitHubOpen(true)}
        onOpenRotateModal={() => setIsRotateGitHubOpen(true)}
        onOpenDisconnectModal={() => setIsDisconnectGitHubOpen(true)}
        onOpenDeliveriesModal={() => setIsWebhookDeliveriesOpen(true)}
      />

      {/* P4 Branch Runtime Panel (non-main branches only) */}
      {selectedBranch !== "main" && (
        <BranchRunPanel
          branchName={selectedBranch}
          runtime={branchRuntime}
          branchObj={currentBranchObj}
          dataTemplates={dataTemplates}
          uncommittedWarning={uncommittedWarning}
          onDismissUncommittedWarning={() => setUncommittedWarning(null)}
          onOpenStartModal={() => setIsStartBranchRunOpen(true)}
          onOpenStopModal={() => setIsStopBranchRunOpen(true)}
          onOpenPortSetModal={() => setIsPortSetModalOpen(true)}
          onOpenConsoleActivityModal={(initialTab) => setBranchConsoleModalTab(initialTab)}
          onOpenSaveTemplateModal={() => setDataTemplatesModalMode("save-branch")}
        />
      )}

      {/* 12-Column Split Workspace (Commit Graph + Isolated Bot Testing) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
        <div className="lg:col-span-7 h-full">
          <CommitTimeline
            commits={filteredCommits}
            tags={tags}
            selectedBranch={selectedBranch}
            isLoading={isLoading}
            onTagCommit={(commitId) => setTagModalCommitId(commitId)}
            onDiff={(from, to) => setDiffParams({ from, to })}
            onInspect={(commit) => setInspectCommit(commit)}
            onRunTest={(commitId) => setTestModalCommitId(commitId)}
          />
        </div>

        <div className="lg:col-span-5 h-full">
          <TestRunList
            testRuns={testRuns}
            serverId={serverId}
            onTestProfiles={() => setIsTestDefinitionsOpen(true)}
            onEvidence={(testId) => setEvidenceModalTestId(testId)}
            onLogs={(run) => setViewLogTestRun(run)}
            onDiscard={handleDiscard}
            onRunTest={(commitId) => setTestModalCommitId(commitId)}
            onCheckNow={async (run) => {
              if (serverId) {
                const updated = await api.getTestStatus?.(serverId, run.id);
                if (updated) {
                  setTestRuns((prev) => [updated, ...prev.filter((item) => item.id !== updated.id)]);
                }
              }
            }}
          />
        </div>
      </div>

      {/* TestRunModal */}
      {testModalCommitId && (
        <TestRunModal
          isOpen={Boolean(testModalCommitId)}
          onClose={() => setTestModalCommitId(null)}
          serverId={serverId!}
          commitId={testModalCommitId}
          onTestStarted={onTestStarted}
        />
      )}

      {/* Create Branch Modal */}
      <CreateBranchModal
        isOpen={isNewBranchOpen}
        branchName={newBranchName}
        onBranchNameChange={setNewBranchName}
        onSubmit={handleCreateBranch}
        onClose={() => setIsNewBranchOpen(false)}
        isPending={isBranchPending}
      />

      {/* Create Commit Modal */}
      <CreateCommitModal
        isOpen={isNewCommitOpen}
        message={newCommitMessage}
        onMessageChange={setNewCommitMessage}
        forceBypass={commitForceBypass}
        onForceBypassChange={setCommitForceBypass}
        forceReason={commitForceReason}
        onForceReasonChange={setCommitForceReason}
        selectedBranch={selectedBranch}
        currentBranchObj={currentBranchObj}
        isDirectCommitBlocked={isDirectCommitBlocked}
        allowForceBypass={allowForceBypass}
        onSubmit={handleCreateCommit}
        onClose={() => setIsNewCommitOpen(false)}
        isPending={isCommitPending}
      />

      {/* Manifest Inspect Modal */}
      <InspectCommitModal
        commit={inspectCommit}
        onClose={() => setInspectCommit(null)}
      />

      {/* Test Run Log Modal */}
      <ViewLogsModal
        testRun={viewLogTestRun}
        onClose={() => setViewLogTestRun(null)}
      />

      {/* Bot Settings Modal */}
      <BotSettingsModal
        isOpen={isSettingsModalOpen}
        botCount={settingsBotCount}
        onBotCountChange={setSettingsBotCount}
        duration={settingsDuration}
        onDurationChange={setSettingsDuration}
        tech={settingsTech}
        onTechChange={setSettingsTech}
        placement={settingsPlacement}
        onPlacementChange={setSettingsPlacement}
        retention={settingsRetention}
        onRetentionChange={setSettingsRetention}
        onSubmit={handleSaveSettings}
        onClose={() => setIsSettingsModalOpen(false)}
        isPending={isSettingsPending}
      />

      <MergeBranchModal
        isOpen={isMergeBranchOpen}
        serverId={serverId!}
        branches={branches}
        selectedBranch={selectedBranch}
        onClose={() => setIsMergeBranchOpen(false)}
      />

      <ClassCVaultModal
        isOpen={isVaultModalOpen}
        serverId={serverId!}
        onClose={() => setIsVaultModalOpen(false)}
      />

      {/* Branch Protection Modal */}
      {isProtectionModalOpen && (
        <BranchProtectionModal
          isOpen={isProtectionModalOpen}
          onClose={() => setIsProtectionModalOpen(false)}
          serverId={serverId!}
          branch={protectionModalBranch}
          onProtectionUpdated={refresh}
        />
      )}

      {/* Test Definitions Profile Modal */}
      {isTestDefinitionsOpen && (
        <TestDefinitionsModal
          isOpen={isTestDefinitionsOpen}
          onClose={() => setIsTestDefinitionsOpen(false)}
          serverId={serverId!}
          onDefinitionsChanged={refresh}
        />
      )}

      {/* Diagnostic Test Evidence Modal */}
      {evidenceModalTestId && (
        <TestEvidenceModal
          isOpen={Boolean(evidenceModalTestId)}
          onClose={() => setEvidenceModalTestId(null)}
          serverId={serverId!}
          testId={evidenceModalTestId}
        />
      )}

      {/* Worktree Materialization Explorer */}
      {isMaterializationOpen && (
        <MaterializationBrowserModal
          isOpen={isMaterializationOpen}
          onClose={() => setIsMaterializationOpen(false)}
          serverId={serverId!}
          initialRevision={{ revision_type: "branch", revision_ref: selectedBranch }}
        />
      )}

      {/* Live Uncommitted Changes Review Modal */}
      {isLiveChangesOpen && (
        <ImportReviewModal
          isOpen={isLiveChangesOpen}
          onClose={() => setIsLiveChangesOpen(false)}
          serverId={serverId!}
          liveData={liveChanges}
          onReviewResolved={refresh}
        />
      )}

      {/* Manage Branches & Archive Modal */}
      {isManageBranchesOpen && (
        <ManageBranchesModal
          isOpen={isManageBranchesOpen}
          onClose={() => setIsManageBranchesOpen(false)}
          serverId={serverId!}
          branches={branches}
          currentBranchName={selectedBranch}
          onBranchesChanged={refresh}
          onOpenProtectionModal={(b) => {
            setProtectionModalBranch(b);
            setIsProtectionModalOpen(true);
          }}
        />
      )}

      {/* Create Immutable Tag Modal */}
      {tagModalCommitId && (
        <CreateTagModal
          isOpen={Boolean(tagModalCommitId)}
          onClose={() => setTagModalCommitId(null)}
          serverId={serverId!}
          commitId={tagModalCommitId}
          onTagCreated={refresh}
        />
      )}

      {/* Commit Diff Inspector */}
      {diffParams && (
        <CommitDiffModal
          isOpen={Boolean(diffParams)}
          onClose={() => setDiffParams(null)}
          serverId={serverId!}
          fromCommitId={diffParams.from}
          toCommitId={diffParams.to}
        />
      )}

      {/* P4 Start Branch Run Modal */}
      {serverId && (
        <StartBranchRunModal
          isOpen={isStartBranchRunOpen}
          serverId={serverId}
          branchName={selectedBranch}
          dataTemplates={dataTemplates}
          portSet={effectivePortSet}
          onStarted={(result) => {
            if (result.uncommitted_changes_warning) {
              setUncommittedWarning({ commitSha: result.commit_sha });
            }
            setActionSuccess(`Branch run started for '${result.branch_name}'.`);
            refresh();
          }}
          onClose={() => setIsStartBranchRunOpen(false)}
        />
      )}

      {/* P4 Stop Branch Run Modal */}
      {serverId && (
        <StopBranchRunModal
          isOpen={isStopBranchRunOpen}
          serverId={serverId}
          branchName={selectedBranch}
          runtimeId={branchRuntime?.runtime_id ?? currentBranchObj?.active_runtime_id ?? null}
          onStopped={(result) => {
            setActionSuccess(`Branch run stopped for '${result.branch_name}'.`);
            refresh();
          }}
          onClose={() => setIsStopBranchRunOpen(false)}
        />
      )}

      {/* P4 Branch Port Set Modal */}
      {serverId && (
        <BranchPortSetModal
          isOpen={isPortSetModalOpen}
          serverId={serverId}
          branchName={selectedBranch}
          portSet={effectivePortSet}
          onUpdated={(_portSet: PortSet) => {
            setActionSuccess("Branch port set updated.");
            refresh();
          }}
          onClose={() => setIsPortSetModalOpen(false)}
        />
      )}

      {/* P4 Data Templates Modal */}
      {serverId && (
        <DataTemplatesModal
          isOpen={dataTemplatesModalMode !== "closed"}
          serverId={serverId}
          branches={branches}
          selectedBranch={selectedBranch}
          initialMode={dataTemplatesModalMode === "save-branch" ? "save-branch" : "list"}
          activeRuntimeId={branchRuntime?.runtime_id ?? null}
          onClose={() => setDataTemplatesModalMode("closed")}
          onTemplatesChanged={() => refresh()}
        />
      )}

      {/* P4 Branch Console & Activity Modal */}
      {serverId && (
        <BranchConsoleActivityModal
          isOpen={branchConsoleModalTab !== null}
          serverId={serverId}
          branchName={selectedBranch}
          isRuntimeActive={isBranchRuntimeActive}
          initialTab={branchConsoleModalTab ?? "console"}
          onClose={() => setBranchConsoleModalTab(null)}
        />
      )}

      {/* P5 GitHub Sync Modals */}
      {serverId && (
        <ConnectGitHubModal
          isOpen={isConnectGitHubOpen}
          serverId={serverId}
          onConnected={(st) => {
            setGithubStatus(st);
            setGithubSyncAlert(null);
            setActionSuccess("Connected to GitHub repository.");
            refresh();
          }}
          onClose={() => setIsConnectGitHubOpen(false)}
        />
      )}

      {serverId && (
        <RotateGitHubCredentialsModal
          isOpen={isRotateGitHubOpen}
          serverId={serverId}
          currentStatus={githubStatus}
          onRotated={(st) => {
            setGithubStatus(st);
            setGithubSyncAlert(null);
            setActionSuccess("GitHub credentials updated.");
            refresh();
          }}
          onClose={() => setIsRotateGitHubOpen(false)}
        />
      )}

      {serverId && (
        <DisconnectGitHubModal
          isOpen={isDisconnectGitHubOpen}
          serverId={serverId}
          remoteUrl={githubStatus?.remote_url ?? null}
          onDisconnected={(res) => {
            setGithubStatus(null);
            setGithubSyncAlert(null);
            setActionSuccess(
              res.purged_deliveries > 0
                ? `Disconnected from GitHub (local Git history preserved; purged ${res.purged_deliveries} deliveries).`
                : "Disconnected from GitHub (local Git history preserved).",
            );
            refresh();
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
              `Webhook delivery '${res.delivery_id}' queued for redelivery.`,
            );
            refresh();
          }}
          onClose={() => setIsWebhookDeliveriesOpen(false)}
        />
      )}

      {serverId && (
        <>
          {supportsModpacks && (
            <ModpackInstallWizardModal
              serverId={serverId}
              isOpen={isP55ModpackWizardOpen}
              onClose={() => setIsP55ModpackWizardOpen(false)}
            />
          )}
          <SafeUpgradeWizardModal
            serverId={serverId}
            isOpen={isP55SafeUpgradeWizardOpen}
            onClose={() => setIsP55SafeUpgradeWizardOpen(false)}
            serverMode="advanced"
          />
        </>
      )}
    </div>
  );
}
