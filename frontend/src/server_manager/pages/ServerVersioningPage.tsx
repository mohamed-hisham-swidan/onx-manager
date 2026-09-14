import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { TestRunModal } from "@/server_manager/components/TestRunModal";
import type {
  ServerBranch,
  ServerCommit,
  ServerTestRun,
  PreflightStatus,
} from "@/server_manager/types";

export function ServerVersioningPage() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { serverId } = useParams<{ serverId: string }>();

  const [branches, setBranches] = useState<ServerBranch[]>([]);
  const [selectedBranch, setSelectedBranch] = useState<string>("main");
  const [commits, setCommits] = useState<ServerCommit[]>([]);
  const [testRuns, setTestRuns] = useState<ServerTestRun[]>([]);
  const [preflight, setPreflight] = useState<PreflightStatus | null>(null);

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

  useEffect(() => {
    if (!serverId) return;
    let isMounted = true;

    const run = async () => {
      try {
        const [branchesData, commitsData, settingsData, preflightData] = await Promise.all([
          api.getServerBranches(serverId),
          api.getServerCommits(serverId),
          api.getBotSettings(serverId),
          api.getPreflightStatus(serverId),
        ]);

        if (!isMounted) return;
        setBranches(branchesData);
        setCommits(commitsData);
        setPreflight(preflightData);

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
      });
      setNewCommitMessage("");
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
      });
      setIsPromoteModalOpen(false);
      setPromoteTestId(null);
      setActionSuccess("Test commit promoted to production successfully.");
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
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-750 transition-colors"
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

      {/* Preflight & Storage Health Banner */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 p-4 shadow-sm">
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
      <div className="flex items-center justify-between gap-4 bg-gray-50 dark:bg-gray-800/60 p-3 rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <Icon name="folder" size={16} className="text-gray-500" />
          <span className="text-xs font-medium text-gray-600 dark:text-gray-300">Branch:</span>
          <select
            value={selectedBranch}
            onChange={(e) => setSelectedBranch(e.target.value)}
            className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-800 dark:border-gray-600 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500"
          >
            {branches.map((b) => (
              <option key={b.id} value={b.name}>
                {b.name}
              </option>
            ))}
          </select>
          <button
            onClick={() => setIsNewBranchOpen(true)}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-950/50 transition-colors"
          >
            <Icon name="plus" size={12} />
            New Branch
          </button>
        </div>

        <div className="text-xs text-gray-500 dark:text-gray-400">
          Showing {filteredCommits.length} commits
        </div>
      </div>

      {/* Commit History Timeline */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 shadow-sm overflow-hidden">
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
            {filteredCommits.map((commit) => (
              <div
                key={commit.id}
                className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 px-2 py-0.5 rounded">
                      {commit.id.slice(0, 8)}
                    </span>
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

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setInspectCommit(commit)}
                    className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-750 transition-colors"
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
            ))}
          </div>
        )}
      </div>

      {/* Isolated Test Runs Section */}
      <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-850 shadow-sm overflow-hidden">
        <div className="border-b border-gray-200 dark:border-gray-800 px-6 py-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider">
            Isolated Test Runs
          </h2>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {testRuns.length} runs recorded
          </span>
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
                  {run.log_output && (
                    <button
                      onClick={() => setViewLogTestRun(run)}
                      className="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
                    >
                      Logs
                    </button>
                  )}

                  {run.status === "PASSED" && (
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
                  )}

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
          <div className="w-full max-w-md rounded-xl bg-white dark:bg-gray-850 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700">
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
          <div className="w-full max-w-md rounded-xl bg-white dark:bg-gray-850 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">Create Snapshot Commit</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Captures all configs, mod jars, and creates an instant COW world snapshot on branch &lsquo;{selectedBranch}&rsquo;.
            </p>
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
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:outline-none focus:border-indigo-500"
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
                className="rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500"
              >
                Commit Snapshot
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
          <div className="w-full max-w-md rounded-xl bg-white dark:bg-gray-850 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-3 text-emerald-600 dark:text-emerald-400">
              <Icon name="check" size={24} />
              <h3 className="text-base font-semibold text-gray-900 dark:text-white">Promote Verified Commit</h3>
            </div>
            <p className="text-xs text-gray-600 dark:text-gray-300">
              This will atomically swap verified config and addon files into your production server. If the server is running, it will be safely restarted.
            </p>

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
                  Also copy world block/entity modifications made by test bots into production. Leave unchecked for config-only promotion.
                </span>
              </label>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setIsPromoteModalOpen(false)}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 dark:border-gray-700 dark:text-gray-300"
              >
                Cancel
              </button>
              <button
                onClick={handlePromote}
                className="rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 shadow-sm"
              >
                Confirm Promotion
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
          <div className="w-full max-w-2xl rounded-xl bg-white dark:bg-gray-850 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700 max-h-[85vh] flex flex-col">
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
          <div className="w-full max-w-3xl rounded-xl bg-white dark:bg-gray-850 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700 max-h-[85vh] flex flex-col">
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
          <div className="w-full max-w-md rounded-xl bg-white dark:bg-gray-850 p-6 space-y-4 shadow-2xl border border-gray-200 dark:border-gray-700">
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
    </div>
  );
}
