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
import { StartingMonitorBanner } from "@/server_manager/components/StartingMonitorBanner";
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

  // Stage B/C/F/G modal controls
  const [isProtectionModalOpen, setIsProtectionModalOpen] = useState(false);
  const [protectionModalBranch, setProtectionModalBranch] = useState<ServerBranch | null>(null);
  const [isTestDefinitionsOpen, setIsTestDefinitionsOpen] = useState(false);
  const [evidenceModalTestId, setEvidenceModalTestId] = useState<string | null>(null);
  const [isMaterializationOpen, setIsMaterializationOpen] = useState(false);
  const [isLiveChangesOpen, setIsLiveChangesOpen] = useState(false);
  const [isManageBranchesOpen, setIsManageBranchesOpen] = useState(false);
  const [tagModalCommitId, setTagModalCommitId] = useState<string | null>(null);
  const [diffParams, setDiffParams] = useState<{ from: string; to: string } | null>(null);

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
        const [branchesData, commitsData, settingsData, preflightData, testRunsData, tagsData, liveData] = await Promise.all([
          api.getServerBranches(serverId),
          api.getServerCommits(serverId),
          api.getBotSettings(serverId),
          api.getPreflightStatus(serverId),
          api.getServerTestRuns?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
          api.getServerTags?.(serverId)?.catch(() => []) ?? Promise.resolve([]),
          api.getLiveChanges?.(serverId)?.catch(() => null) ?? Promise.resolve(null),
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
    try {
      await api.createServerBranch(serverId, { name: newBranchName.trim() });
      setSelectedBranch(newBranchName.trim());
      setNewBranchName("");
      setIsNewBranchOpen(false);
      setActionSuccess(`Branch '${newBranchName.trim()}' created.`);
      refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create branch.");
    }
  };

  const handleCreateCommit = async () => {
    if (!serverId || !newCommitMessage.trim()) return;
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
    }
  };

  const handlePromote = async () => {
    if (!serverId || !promoteTestId) return;
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
    }
  };

  const handleDiscard = async (testId: string) => {
    if (!serverId) return;
    try {
      await api.discardTest(serverId, testId);
      setActionSuccess("Test run discarded.");
      // Refresh test run state
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
    }
  };

  const onTestStarted = (testId: string) => {
    setActionSuccess(`Isolated test launched (ID: ${testId.slice(0, 8)}).`);
    // Immediately fetch test status and prepend
    if (serverId && testId) {
      api.getTestStatus(serverId, testId).then((t: ServerTestRun) => {
        setTestRuns((prev) => [t, ...prev.filter((item) => item.id !== t.id)]);
      }).catch(() => {
        refresh();
      });
    }
  };

  const filteredCommits = commits.filter((c) => {
    const currentBranchObj = branches.find((b) => b.name === selectedBranch);
    return !currentBranchObj || c.branch_id === currentBranchObj.id || !c.branch_id;
  });

  return (
    <div className="space-y-6 max-w-7xl mx-auto p-4 sm:p-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-gray-200 dark:border-gray-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <Icon name="backup" size={24} className="text-indigo-600 dark:text-indigo-400" />
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              Versions & Isolated Testing
            </h1>
          </div>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Git-inspired server snapshots, config commits, and isolated bot-verified dry-runs.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsSettingsModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700 transition-colors"
          >
            <Icon name="settings" size={14} />
            Verification Defaults
          </button>
          <button
            onClick={() => setIsNewCommitOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-500 shadow-sm transition-colors"
          >
            <Icon name="plus" size={14} />
            Create Snapshot Commit
          </button>
        </div>
      </div>

      {/* Alerts */}
      {error && (
        <div className="rounded-lg bg-rose-50 border border-rose-200 p-4 text-sm text-rose-700 dark:bg-rose-950/50 dark:border-rose-900 dark:text-rose-300 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-rose-500 hover:text-rose-700">
            <Icon name="x" size={16} />
          </button>
        </div>
      )}

      {actionSuccess && (
        <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-4 text-sm text-emerald-700 dark:bg-emerald-950/50 dark:border-emerald-900 dark:text-emerald-300 flex items-center justify-between">
          <span>{actionSuccess}</span>
          <button onClick={() => setActionSuccess(null)} className="text-emerald-500 hover:text-emerald-700">
            <Icon name="x" size={16} />
          </button>
        </div>
      )}

      {/* Live Changes Callout Banner */}
      {Boolean(liveChanges?.has_changes || (liveChanges?.changes && liveChanges.changes.length > 0)) && (
        <div className="rounded-xl border border-amber-300 bg-amber-50/80 p-4 dark:border-amber-800 dark:bg-amber-950/40 flex flex-col sm:flex-row sm:items-center justify-between gap-3 animate-fade-in">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-100 dark:bg-amber-900/60 rounded-lg text-amber-700 dark:text-amber-300 shrink-0">
              <Icon name="alert" size={20} />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-100">
                Uncommitted Live Server Changes Detected
              </h3>
              <p className="text-xs text-amber-700 dark:text-amber-300">
                {liveChanges?.changes?.length || 0} file{liveChanges?.changes?.length === 1 ? "" : "s"} modified or created on the server filesystem since HEAD.
              </p>
            </div>
          </div>
          <button
            onClick={() => setIsLiveChangesOpen(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-amber-600 hover:bg-amber-700 rounded-lg transition-colors shadow-sm shrink-0"
          >
            Review & Commit Changes
          </button>
        </div>
      )}

      {/* Preflight & Storage Health Banner */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-800 p-4 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                preflight?.reflink_supported
                  ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400"
                  : "bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400"
              }`}
            >
              <Icon name={preflight?.reflink_supported ? "check" : "alert"} size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                  Storage Copy-On-Write Capability
                </h3>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    preflight?.reflink_supported
                      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300"
                      : "bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300"
                  }`}
                >
                  {preflight?.reflink_supported ? "Active (Reflink / Btrfs / ZFS)" : "Reflink Not Supported"}
                </span>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {preflight?.reflink_supported
                  ? "Instant world snapshots enabled via zero-copy reflink cloning."
                  : "Filesystem does not support reflink block cloning. Testing requires COW storage."}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs">
            <div className="text-right">
              <span className="text-gray-500 dark:text-gray-400 block">Available Host Headroom</span>
              <span className="font-semibold text-gray-800 dark:text-gray-200">
                {preflight ? `${preflight.available_ram_mb} MB RAM • ${preflight.available_cores} Cores` : "Checking..."}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Branch Navigation Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-gray-50 dark:bg-gray-800/60 p-3 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="flex flex-wrap items-center gap-2">
          <Icon name="folder" size={16} className="text-gray-500" />
          <span className="text-xs font-medium text-gray-600 dark:text-gray-300">Branch:</span>
          <select
            value={selectedBranch}
            onChange={(e) => setSelectedBranch(e.target.value)}
            className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-800 dark:border-gray-600 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500"
          >
            {branches.map((b) => (
              <option key={b.id} value={b.name}>
                {b.name} {b.is_protected ? "🔒" : ""} {b.status === "archived" ? "(archived)" : ""}
              </option>
            ))}
          </select>

          {currentBranchObj?.is_protected && (
            <span className="inline-flex items-center gap-1 rounded bg-emerald-100 dark:bg-emerald-950/60 px-2 py-0.5 text-[11px] font-semibold text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
              Protected
            </span>
          )}

          {currentBranchObj?.status === "archived" && (
            <span className="inline-flex items-center rounded bg-gray-200 dark:bg-gray-700 px-2 py-0.5 text-[11px] font-semibold text-gray-700 dark:text-gray-300">
              Archived (Read-Only)
            </span>
          )}

          <button
            onClick={() => setIsNewBranchOpen(true)}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-950/50 transition-colors"
          >
            <Icon name="plus" size={12} />
            New Branch
          </button>

          <button
            onClick={() => {
              setProtectionModalBranch(currentBranchObj);
              setIsProtectionModalOpen(true);
            }}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
          >
            <Icon name="settings" size={12} />
            Protection Rules
          </button>

          <button
            onClick={() => setIsManageBranchesOpen(true)}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
          >
            <Icon name="backup" size={12} />
            Manage Branches
          </button>

          <button
            onClick={() => setIsMaterializationOpen(true)}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-emerald-600 hover:bg-emerald-50 dark:text-emerald-400 dark:hover:bg-emerald-950/50 transition-colors"
          >
            <Icon name="folder" size={12} />
            Explore Worktree
          </button>
        </div>

        <div className="text-xs text-gray-500 dark:text-gray-400">
          Showing {filteredCommits.length} commits
        </div>
      </div>

      {/* Commit History Timeline */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-800 shadow-sm overflow-hidden">
        <div className="border-b border-gray-200 dark:border-gray-800 px-6 py-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider">
            Commit History Timeline
          </h2>
        </div>

        {isLoading && commits.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-500 dark:text-gray-400">
            Loading commits...
          </div>
        ) : filteredCommits.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-500 dark:text-gray-400">
            No snapshot commits yet on branch &lsquo;{selectedBranch}&rsquo;. Click &ldquo;Create Snapshot Commit&rdquo; above to create your first commit.
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {filteredCommits.map((commit) => {
              const commitTags = tags.filter((t) => t.commit_id === commit.id);
              const parentId = commit.parent_id || commit.parent_commit_id || (commit.parent_commit_ids && commit.parent_commit_ids[0]);
              const isMerge = commit.parent_commit_ids && commit.parent_commit_ids.length > 1;

              return (
                <div
                  key={commit.id}
                  className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
                >
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs font-semibold bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 px-2 py-0.5 rounded">
                        {commit.id.slice(0, 8)}
                      </span>
                      {isMerge && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300">
                          MERGE ({commit.parent_commit_ids!.length} parents)
                        </span>
                      )}
                      {commitTags.map((tag) => (
                        <span
                          key={tag.name}
                          className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800"
                        >
                          🏷️ {tag.name}
                        </span>
                      ))}
                      <span className="text-sm font-semibold text-gray-900 dark:text-white">
                        {commit.message}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                      <span>Type: {commit.manifest?.server_type} ({commit.manifest?.minecraft_version})</span>
                      <span>•</span>
                      <span>{new Date(commit.created_at).toLocaleString()}</span>
                      {commit.author_id && (
                        <>
                          <span>•</span>
                          <span>Author: {commit.author_id}</span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => setTagModalCommitId(commit.id)}
                      className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
                      title="Create immutable tag"
                    >
                      <Icon name="backup" size={12} />
                      Tag
                    </button>
                    {parentId && (
                      <button
                        onClick={() => setDiffParams({ from: parentId, to: commit.id })}
                        className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
                        title="View changes against parent commit"
                      >
                        <Icon name="activity" size={12} />
                        Diff
                      </button>
                    )}
                    <button
                      onClick={() => setInspectCommit(commit)}
                      className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
                    >
                      <Icon name="file" size={14} />
                      Inspect Manifest
                    </button>
                    <button
                      onClick={() => setTestModalCommitId(commit.id)}
                      className="inline-flex items-center gap-1 rounded-lg bg-indigo-50 border border-indigo-200 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 dark:bg-indigo-950/50 dark:border-indigo-800 dark:text-indigo-300 dark:hover:bg-indigo-900/60 transition-colors"
                    >
                      <Icon name="play" size={14} />
                      Run Isolated Test
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Isolated Test Runs Section */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-800 shadow-sm overflow-hidden">
        <div className="border-b border-gray-200 dark:border-gray-800 px-6 py-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider">
            Isolated Test Runs
          </h2>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsTestDefinitionsOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors"
            >
              <Icon name="settings" size={12} />
              Test Profiles
            </button>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {testRuns.length} runs recorded
            </span>
          </div>
        </div>

        {testRuns.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-500 dark:text-gray-400">
            No isolated test runs active or recorded. Launch a test from any commit above.
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {testRuns.map((run) => (
              <div
                key={run.id}
                className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${
                        run.status === "PASSED"
                          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300"
                          : run.status === "FAILED"
                          ? "bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300"
                          : run.status === "RUNNING"
                          ? "bg-blue-100 text-blue-800 dark:bg-blue-950/80 dark:text-blue-300 animate-pulse"
                          : run.status === "BOOTING"
                          ? "bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 animate-pulse"
                          : "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300"
                      }`}
                    >
                      {run.status}
                    </span>
                    <span className="font-mono text-xs text-gray-500">
                      ID: {run.id.slice(0, 8)}
                    </span>
                    <span className="text-xs text-gray-400">
                      Target Commit: <span className="font-mono">{run.commit_id.slice(0, 8)}</span>
                    </span>
                  </div>

                  {run.status === "BOOTING" && (
                    <div className="mt-2">
                      <StartingMonitorBanner
                        targetName={`Test Run ${run.id.slice(0, 8)}`}
                        startedAt={run.created_at}
                        timeoutSeconds={120}
                        isTestRun={true}
                        onCheckNow={async () => {
                          if (serverId) {
                            const updated = await api.getTestStatus?.(serverId, run.id);
                            if (updated) {
                              setTestRuns((prev) => [updated, ...prev.filter((item) => item.id !== updated.id)]);
                            }
                          }
                        }}
                      />
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                    <span>Bots: {run.bot_count} ({run.bot_tech})</span>
                    <span>•</span>
                    <span>Duration: {run.duration_minutes}m</span>
                    <span>•</span>
                    <span>Placement: {run.placement_mode}</span>
                    {run.ephemeral_port && (
                      <>
                        <span>•</span>
                        <span>Port: {run.ephemeral_port}</span>
                      </>
                    )}
                  </div>

                  {run.failure_reason && (
                    <div className="rounded bg-rose-50 border border-rose-200 p-2 text-xs text-rose-700 dark:bg-rose-950/40 dark:border-rose-900 dark:text-rose-300 mt-2">
                      <span className="font-semibold">Failure / Blame:</span> {run.failure_reason}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setEvidenceModalTestId(run.id)}
                    className="inline-flex items-center gap-1 rounded border border-indigo-200 bg-indigo-50/60 px-2.5 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-300 transition-colors"
                    title="View diagnostic evidence and root-cause analysis"
                  >
                    <Icon name="activity" size={12} />
                    Evidence
                  </button>
                  {run.log_output && (
                    <button
                      onClick={() => setViewLogTestRun(run)}
                      className="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
                    >
                      Logs
                    </button>
                  )}

                  {run.status === "PASSED" ? (
                    <button
                      onClick={() => {
                        setPromoteTestId(run.id);
                        setIsPromoteModalOpen(true);
                      }}
                      className="inline-flex items-center gap-1 rounded bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-500 transition-colors shadow-sm"
                    >
                      <Icon name="check" size={14} />
                      Promote to Live
                    </button>
                  ) : run.status === "FAILED" ? (
                    <button
                      onClick={() => {
                        setPromoteTestId(run.id);
                        setIsPromoteModalOpen(true);
                      }}
                      className="inline-flex items-center gap-1 rounded border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300 dark:hover:bg-amber-950/60 transition-colors"
                      title="Force promotion with administrative override"
                    >
                      <Icon name="alert" size={14} />
                      Force Promote
                    </button>
                  ) : null}

                  {(run.status === "RUNNING" || run.status === "PASSED" || run.status === "FAILED") && (
                    <button
                      onClick={() => handleDiscard(run.id)}
                      className="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50 dark:border-gray-700 dark:bg-gray-800 dark:text-rose-400 dark:hover:bg-rose-950/40 transition-colors"
                    >
                      Discard
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
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

      {/* New Branch Modal */}
      {isNewBranchOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-xl bg-white dark:bg-gray-800 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Create New Branch</h3>
            <div>
              <label htmlFor="branch-name-input" className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                Branch Name
              </label>
              <input
                id="branch-name-input"
                type="text"
                value={newBranchName}
                onChange={(e) => setNewBranchName(e.target.value)}
                placeholder="e.g. feat-mod-upgrade"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setIsNewBranchOpen(false)}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 dark:border-gray-700 dark:text-gray-300"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateBranch}
                className="rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
              >
                Create Branch
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New Commit Modal */}
      {isNewCommitOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-xl bg-white dark:bg-gray-800 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Create Snapshot Commit</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Captures all configs, mod jars, and creates an instant COW world snapshot on branch &lsquo;{selectedBranch}&rsquo;.
            </p>

            {currentBranchObj?.status === "archived" && (
              <div className="rounded-lg bg-gray-100 dark:bg-gray-700/60 p-3 text-xs text-gray-700 dark:text-gray-300">
                ⚠️ Branch &lsquo;{selectedBranch}&rsquo; is archived and read-only. Committing is disabled.
              </div>
            )}

            {isDirectCommitBlocked && (
              <div className="p-3 bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800 rounded-lg text-xs space-y-2">
                <div className="flex items-center gap-1.5 font-semibold text-amber-800 dark:text-amber-200">
                  <Icon name="alert" size={14} />
                  <span>Direct Commits Blocked by Protection Policy</span>
                </div>
                <p className="text-amber-700 dark:text-amber-300">
                  Branch &lsquo;{selectedBranch}&rsquo; requires changes to be verified in an isolated test run and promoted.
                </p>
                {allowForceBypass ? (
                  <div className="pt-2 border-t border-amber-200 dark:border-amber-800/60 space-y-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={commitForceBypass}
                        onChange={(e) => setCommitForceBypass(e.target.checked)}
                        className="rounded border-amber-400 text-amber-600 focus:ring-amber-500"
                      />
                      <span className="font-semibold text-amber-900 dark:text-amber-100">
                        Emergency Force Bypass
                      </span>
                    </label>
                    {commitForceBypass && (
                      <div>
                        <label className="block text-[11px] font-medium text-amber-800 dark:text-amber-300 mb-1">
                          Bypass Reason (Audit Logged)
                        </label>
                        <input
                          type="text"
                          value={commitForceReason}
                          onChange={(e) => setCommitForceReason(e.target.value)}
                          placeholder="e.g. Hotfix for critical crash"
                          className="w-full rounded border border-amber-300 dark:border-amber-700 bg-white dark:bg-gray-900 px-2.5 py-1 text-xs text-gray-900 dark:text-white"
                          required
                        />
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-red-600 dark:text-red-400 font-semibold text-[11px]">
                    Force bypass is disabled on this branch.
                  </p>
                )}
              </div>
            )}

            <div>
              <label htmlFor="commit-message-input" className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                Commit Message
              </label>
              <input
                id="commit-message-input"
                type="text"
                value={newCommitMessage}
                onChange={(e) => setNewCommitMessage(e.target.value)}
                placeholder="e.g. Pre-WorldEdit update snapshot"
                disabled={currentBranchObj?.status === "archived"}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500 disabled:opacity-50"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setIsNewCommitOpen(false)}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 dark:border-gray-700 dark:text-gray-300"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateCommit}
                disabled={
                  !newCommitMessage.trim() ||
                  currentBranchObj?.status === "archived" ||
                  (isDirectCommitBlocked && (!allowForceBypass || !commitForceBypass || !commitForceReason.trim()))
                }
                className="rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {commitForceBypass ? "Force Commit Snapshot" : "Commit Snapshot"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Promote Confirmation Modal */}
      {isPromoteModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-xl bg-white dark:bg-gray-800 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700">
            {isForcePromote ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                  <Icon name="alert" size={24} />
                  <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                    Force Promotion Override
                  </h3>
                </div>
                <div className="rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900/60 p-3 space-y-2 text-xs">
                  <p className="text-amber-800 dark:text-amber-200">
                    This test run did not pass (status: <strong>{promoteTestRun?.status}</strong>).
                    Promoting this commit bypasses automated verification gating and requires the{" "}
                    <code className="font-mono bg-amber-100 dark:bg-amber-900/60 px-1 py-0.5 rounded text-amber-900 dark:text-amber-200">
                      server:version:promote:force
                    </code>{" "}
                    permission.
                  </p>
                  <p className="text-amber-700 dark:text-amber-300/80">
                    This administrative bypass will be permanently recorded in the server activity log.
                  </p>
                </div>
                <div>
                  <label
                    htmlFor="force-reason-input"
                    className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1"
                  >
                    Bypass Reason (Required for audit log)
                  </label>
                  <input
                    id="force-reason-input"
                    type="text"
                    value={forceReason}
                    onChange={(e) => setForceReason(e.target.value)}
                    placeholder="e.g. Verified manually in offline client"
                    className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-amber-500"
                  />
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-3 text-emerald-600 dark:text-emerald-400">
                  <Icon name="check" size={24} />
                  <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                    Promote Verified Commit
                  </h3>
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-300">
                  This will atomically swap verified config and addon files into your production
                  server. If the server is running, it will be safely restarted.
                </p>
              </>
            )}

            <div className="rounded-lg bg-gray-50 dark:bg-gray-900 p-3 border border-gray-200 dark:border-gray-800">
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={keepWorldChanges}
                  onChange={(e) => setKeepWorldChanges(e.target.checked)}
                  className="mt-0.5 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-xs text-gray-700 dark:text-gray-300">
                  <strong className="block text-gray-900 dark:text-white">Keep World Changes</strong>
                  Also copy world block/entity modifications made by test bots into production. Leave
                  unchecked for config-only promotion.
                </span>
              </label>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setIsPromoteModalOpen(false);
                  setForceReason("");
                }}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 dark:border-gray-700 dark:text-gray-300"
              >
                Cancel
              </button>
              <button
                onClick={handlePromote}
                disabled={isForcePromote && !forceReason.trim()}
                className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors ${
                  isForcePromote
                    ? "bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed"
                    : "bg-emerald-600 hover:bg-emerald-500"
                }`}
              >
                {isForcePromote ? "Confirm Force Promotion" : "Confirm Promotion"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Manifest Inspect Modal */}
      {inspectCommit && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
        >
          <div className="w-full max-w-2xl rounded-xl bg-white dark:bg-gray-800 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700 max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-800 pb-3">
              <div>
                <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                  Manifest Snapshot Inspector
                </h3>
                <span className="font-mono text-xs text-gray-500">
                  Commit {inspectCommit.id.slice(0, 8)} • {inspectCommit.message}
                </span>
              </div>
              <button
                onClick={() => setInspectCommit(null)}
                className="rounded p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <Icon name="x" size={18} />
              </button>
            </div>

            <div className="overflow-y-auto space-y-4 pr-1">
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 block mb-1">
                  Captured Configurations ({Object.keys(inspectCommit.manifest?.configs || {}).length} files)
                </span>
                <div className="rounded bg-gray-50 dark:bg-gray-900 p-2 border border-gray-200 dark:border-gray-800 text-xs font-mono max-h-40 overflow-y-auto">
                  {Object.keys(inspectCommit.manifest?.configs || {}).map((f) => (
                    <div key={f} className="text-gray-700 dark:text-gray-300 py-0.5">
                      📄 {f}
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 block mb-1">
                  Captured Mods / Plugins ({(inspectCommit.manifest?.mods || []).length} items)
                </span>
                <div className="rounded bg-gray-50 dark:bg-gray-900 p-2 border border-gray-200 dark:border-gray-800 text-xs font-mono max-h-40 overflow-y-auto">
                  {(inspectCommit.manifest?.mods || []).map((m) => (
                    <div key={m.filename} className="text-gray-700 dark:text-gray-300 py-0.5">
                      📦 {m.filename} <span className="text-gray-400">({m.sha256.slice(0, 10)}...)</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-3 border-t border-gray-200 dark:border-gray-800">
              <button
                onClick={() => setInspectCommit(null)}
                className="rounded-lg bg-gray-100 px-4 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Log Output Modal */}
      {viewLogTestRun && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
        >
          <div className="w-full max-w-3xl rounded-xl bg-white dark:bg-gray-800 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700 max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-800 pb-3">
              <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                Test Run Console Output ({viewLogTestRun.id.slice(0, 8)})
              </h3>
              <button
                onClick={() => setViewLogTestRun(null)}
                className="rounded p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                <Icon name="x" size={18} />
              </button>
            </div>
            <pre className="overflow-y-auto rounded bg-gray-900 p-3 text-xs font-mono text-emerald-400 flex-1 whitespace-pre-wrap">
              {viewLogTestRun.log_output || "No log output recorded."}
            </pre>
            <div className="flex justify-end pt-2">
              <button
                onClick={() => setViewLogTestRun(null)}
                className="rounded-lg bg-gray-100 px-4 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bot Settings Modal */}
      {isSettingsModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-xl bg-white dark:bg-gray-800 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">
              Bot Verification Server Defaults
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Configure baseline parameters applied when launching dry-runs on this server.
            </p>

            <div className="space-y-3 text-xs">
              <div>
                <label htmlFor="settings-bot-count-input" className="block font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Default Bot Count
                </label>
                <input
                  id="settings-bot-count-input"
                  type="number"
                  min={1}
                  value={settingsBotCount}
                  onChange={(e) => setSettingsBotCount(Math.max(1, parseInt(e.target.value) || 1))}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label htmlFor="settings-duration-input" className="block font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Default Duration (Minutes)
                </label>
                <input
                  id="settings-duration-input"
                  type="number"
                  min={1}
                  value={settingsDuration}
                  onChange={(e) => setSettingsDuration(Math.max(1, parseInt(e.target.value) || 1))}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label htmlFor="settings-tech-select" className="block font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Default Bot Technology
                </label>
                <select
                  id="settings-tech-select"
                  value={settingsTech}
                  onChange={(e) => setSettingsTech(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="auto">Auto (Server-type aware)</option>
                  <option value="mineflayer">Mineflayer (External Protocol)</option>
                  <option value="fakeplayer_next">FakePlayerNext (Paper In-Process)</option>
                </select>
              </div>

              <div>
                <label htmlFor="settings-placement-select" className="block font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Default Placement Mode
                </label>
                <select
                  id="settings-placement-select"
                  value={settingsPlacement}
                  onChange={(e) => setSettingsPlacement(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="sidecar">Sidecar (Container Isolation)</option>
                  <option value="in_container">In Container</option>
                </select>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-gray-200 dark:border-gray-800">
              <button
                onClick={() => setIsSettingsModalOpen(false)}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 dark:border-gray-700 dark:text-gray-300"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveSettings}
                className="rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
              >
                Save Defaults
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Stage G: Branch Protection Modal */}
      {isProtectionModalOpen && (
        <BranchProtectionModal
          isOpen={isProtectionModalOpen}
          onClose={() => setIsProtectionModalOpen(false)}
          serverId={serverId!}
          branch={protectionModalBranch}
          onProtectionUpdated={refresh}
        />
      )}

      {/* Stage F: Test Definitions Profile Modal */}
      {isTestDefinitionsOpen && (
        <TestDefinitionsModal
          isOpen={isTestDefinitionsOpen}
          onClose={() => setIsTestDefinitionsOpen(false)}
          serverId={serverId!}
          onDefinitionsChanged={refresh}
        />
      )}

      {/* Stage F: Diagnostic Test Evidence Modal */}
      {evidenceModalTestId && (
        <TestEvidenceModal
          isOpen={Boolean(evidenceModalTestId)}
          onClose={() => setEvidenceModalTestId(null)}
          serverId={serverId!}
          testId={evidenceModalTestId}
        />
      )}

      {/* Stage C: Worktree Materialization Explorer */}
      {isMaterializationOpen && (
        <MaterializationBrowserModal
          isOpen={isMaterializationOpen}
          onClose={() => setIsMaterializationOpen(false)}
          serverId={serverId!}
          initialRevision={{ revision_type: "branch", revision_ref: selectedBranch }}
        />
      )}

      {/* Stage C: Live Uncommitted Changes Review Modal */}
      {isLiveChangesOpen && (
        <ImportReviewModal
          isOpen={isLiveChangesOpen}
          onClose={() => setIsLiveChangesOpen(false)}
          serverId={serverId!}
          liveData={liveChanges}
          onReviewResolved={refresh}
        />
      )}

      {/* Stage B: Manage Branches & Archive Modal */}
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

      {/* Stage B: Create Immutable Tag Modal */}
      {tagModalCommitId && (
        <CreateTagModal
          isOpen={Boolean(tagModalCommitId)}
          onClose={() => setTagModalCommitId(null)}
          serverId={serverId!}
          commitId={tagModalCommitId}
          onTagCreated={refresh}
        />
      )}

      {/* Stage B: Commit Diff Inspector */}
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
