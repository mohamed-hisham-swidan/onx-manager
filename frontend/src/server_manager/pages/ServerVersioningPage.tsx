import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
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
import { CommitTimeline } from "@/server_manager/components/versioning/CommitTimeline";
import { TestRunList } from "@/server_manager/components/versioning/TestRunList";
import {
  CreateBranchModal,
  CreateCommitModal,
  PromoteModal,
  InspectCommitModal,
  ViewLogsModal,
  BotSettingsModal,
} from "@/server_manager/components/versioning/VersioningModals";
import type {
  ServerBranch,
  ServerCommit,
  ServerTestRun,
  PreflightStatus,
  ServerTag,
  ScanLiveChangesResponse,
} from "@/server_manager/types";

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
  const [isWorkflowGuideOpen, setIsWorkflowGuideOpen] = useState(true);

  const refresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  // Modals state
  const [isNewBranchOpen, setIsNewBranchOpen] = useState(false);
  const [newBranchName, setNewBranchName] = useState("");

  const [isNewCommitOpen, setIsNewCommitOpen] = useState(false);
  const [newCommitMessage, setNewCommitMessage] = useState("");
  const [commitForceBypass, setCommitForceBypass] = useState(false);
  const [commitForceReason, setCommitForceReason] = useState("");

  const [testModalCommitId, setTestModalCommitId] = useState<string | null>(null);

  const [isPromoteModalOpen, setIsPromoteModalOpen] = useState(false);
  const [promoteTestId, setPromoteTestId] = useState<string | null>(null);
  const [keepWorldChanges, setKeepWorldChanges] = useState(false);

  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [settingsBotCount, setSettingsBotCount] = useState(10);
  const [settingsDuration, setSettingsDuration] = useState(15);
  const [settingsTech, setSettingsTech] = useState("auto");
  const [settingsPlacement, setSettingsPlacement] = useState("sidecar");

  const [inspectCommit, setInspectCommit] = useState<ServerCommit | null>(null);
  const [viewLogTestRun, setViewLogTestRun] = useState<ServerTestRun | null>(null);

  const [forceReason, setForceReason] = useState("");

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
  const [isPromotePending, setIsPromotePending] = useState(false);
  const [isSettingsPending, setIsSettingsPending] = useState(false);

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

  const promoteTestRun = useMemo(
    () => testRuns.find((r) => r.id === promoteTestId) || null,
    [testRuns, promoteTestId]
  );
  const isForcePromote = Boolean(promoteTestRun && promoteTestRun.status !== "PASSED");

  useEffect(() => {
    if (!serverId) return;
    let isMounted = true;

    const run = async () => {
      try {
        const [branchesData, commitsData, settingsData, preflightData, testRunsData, tagsData, liveData] =
          await Promise.all([
            api.getServerBranches(serverId),
            api.getServerCommits(serverId),
            api.getBotSettings(serverId),
            api.getPreflightStatus(serverId),
            api.getServerTestRuns?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
            api.getServerTags?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
            api.getLiveChanges?.(serverId, selectedBranch || "main")?.catch(() => null) ??
              Promise.resolve(null),
          ]);

        if (!isMounted) return;
        setBranches(branchesData);
        setCommits(commitsData);
        setPreflight(preflightData);
        setTestRuns(testRunsData);
        setTags(tagsData);
        setLiveChanges(liveData);

        if (settingsData) {
          setSettingsBotCount(settingsData.effective_bot_count);
          setSettingsDuration(settingsData.effective_duration_minutes);
          setSettingsTech(settingsData.effective_bot_tech);
          setSettingsPlacement(settingsData.effective_placement_mode);
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

  const handlePromote = async () => {
    if (!serverId || !promoteTestId) return;
    setIsPromotePending(true);
    try {
      await api.promoteTestCommit(serverId, promoteTestId, {
        keep_world_changes: keepWorldChanges,
        ...(isForcePromote
          ? { force: true, ...(forceReason.trim() ? { force_reason: forceReason.trim() } : {}) }
          : {}),
      });
      setIsPromoteModalOpen(false);
      setPromoteTestId(null);
      setForceReason("");
      setActionSuccess(
        isForcePromote
          ? "Commit forcibly promoted to production (audit logged)."
          : "Test commit promoted to production successfully."
      );
      refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to promote commit.");
    } finally {
      setIsPromotePending(false);
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

  const filteredCommits = commits.filter((c) => {
    const branchObj = branches.find((b) => b.name === selectedBranch);
    return !branchObj || c.branch_id === branchObj.id || !c.branch_id;
  });

  return (
    <div className="space-y-6 max-w-7xl mx-auto p-4 sm:p-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-border-default pb-5">
        <div>
          <div className="flex items-center gap-2">
            <Icon name="backup" size={24} className="text-accent-primary" />
            <h1 className="text-2xl font-bold text-text-primary">
              Versions & Isolated Testing
            </h1>
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
            <div className="flex flex-col justify-between rounded-lg border border-border-subtle bg-surface-elevated/50 p-3.5 space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-bold text-accent-primary">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-primary/20 text-[11px] font-mono font-bold">
                    1
                  </span>
                  <span>Step 1: Snapshot World (Commit)</span>
                </div>
                <p className="text-xs text-text-muted leading-relaxed">
                  Capture an instant zero-copy Btrfs/ZFS snapshot of your world &amp; configs.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsNewCommitOpen(true)}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-surface-card hover:bg-surface-hover border border-border-default px-3 py-1.5 text-xs font-semibold text-text-primary transition-colors shadow-2xs cursor-pointer w-full sm:w-auto self-start"
              >
                <Icon name="plus" size={12} className="text-accent-primary" />
                Create Snapshot
              </button>
            </div>

            {/* Step 2 */}
            <div className="flex flex-col justify-between rounded-lg border border-border-subtle bg-surface-elevated/50 p-3.5 space-y-3">
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
              <button
                type="button"
                onClick={() => setIsNewBranchOpen(true)}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-surface-card hover:bg-surface-hover border border-border-default px-3 py-1.5 text-xs font-semibold text-text-primary transition-colors shadow-2xs cursor-pointer w-full sm:w-auto self-start"
              >
                <Icon name="version-branch" size={12} className="text-accent-primary" />
                New Branch
              </button>
            </div>

            {/* Step 3 */}
            <div className="flex flex-col justify-between rounded-lg border border-border-subtle bg-surface-elevated/50 p-3.5 space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-bold text-accent-primary">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent-primary/20 text-[11px] font-mono font-bold">
                    3
                  </span>
                  <span>Step 3: Automated Bot Dry-Run (Verify)</span>
                </div>
                <p className="text-xs text-text-muted leading-relaxed">
                  Spawn an isolated sidecar container with simulated players (fakeplayer_next) to audit TPS and crashes.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsTestDefinitionsOpen(true)}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-surface-card hover:bg-surface-hover border border-border-default px-3 py-1.5 text-xs font-semibold text-text-primary transition-colors shadow-2xs cursor-pointer"
                >
                  <Icon name="settings" size={12} className="text-accent-primary" />
                  Test Profiles
                </button>
                <button
                  type="button"
                  onClick={() => setIsSettingsModalOpen(true)}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-surface-card hover:bg-surface-hover border border-border-default px-3 py-1.5 text-xs font-semibold text-text-secondary hover:text-text-primary transition-colors shadow-2xs cursor-pointer"
                >
                  Configure Bots
                </button>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Alerts */}
      {error && (
        <div role="alert" className="rounded-xl bg-status-danger-bg border border-status-danger/30 p-4 text-sm text-status-danger flex items-center justify-between">
          <span>{error}</span>
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
      {Boolean(liveChanges?.has_changes || (liveChanges?.changes && liveChanges.changes.length > 0)) && (
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

      {/* Preflight & Storage Health Banner */}
      <StorageHealthBanner preflight={preflight} />

      {/* Branch Navigation Toolbar */}
      <BranchToolbar
        branches={branches}
        selectedBranch={selectedBranch}
        onSelectBranch={setSelectedBranch}
        currentBranchObj={currentBranchObj}
        filteredCommitsCount={filteredCommits.length}
        onNewBranch={() => setIsNewBranchOpen(true)}
        onProtectionRules={() => {
          setProtectionModalBranch(currentBranchObj);
          setIsProtectionModalOpen(true);
        }}
        onManageBranches={() => setIsManageBranchesOpen(true)}
        onExploreWorktree={() => setIsMaterializationOpen(true)}
      />

      {/* 12-Column Split Workspace (Commit Graph + Isolated Bot Testing) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-7">
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

        <div className="lg:col-span-5">
          <TestRunList
            testRuns={testRuns}
            serverId={serverId}
            onTestProfiles={() => setIsTestDefinitionsOpen(true)}
            onEvidence={(testId) => setEvidenceModalTestId(testId)}
            onLogs={(run) => setViewLogTestRun(run)}
            onPromote={(testId) => {
              setPromoteTestId(testId);
              setIsPromoteModalOpen(true);
            }}
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

      {/* Promote Confirmation Modal */}
      <PromoteModal
        isOpen={isPromoteModalOpen}
        isForcePromote={isForcePromote}
        promoteTestRun={promoteTestRun}
        forceReason={forceReason}
        onForceReasonChange={setForceReason}
        keepWorldChanges={keepWorldChanges}
        onKeepWorldChangesChange={setKeepWorldChanges}
        onSubmit={handlePromote}
        onClose={() => {
          setIsPromoteModalOpen(false);
          setForceReason("");
        }}
        isPending={isPromotePending}
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
        onSubmit={handleSaveSettings}
        onClose={() => setIsSettingsModalOpen(false)}
        isPending={isSettingsPending}
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
    </div>
  );
}
