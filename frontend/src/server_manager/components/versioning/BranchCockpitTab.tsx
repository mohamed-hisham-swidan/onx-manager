import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { useClipboard } from "@/hooks/useClipboard";
import { formatDateTime } from "@/server_manager/utils/format";
import type {
  BranchRuntimeStatus,
  DataTemplate,
  GitHubConnectionStatusResponse,
  PortSet,
  RefreshStateResponse,
  ServerBranch,
} from "@/server_manager/types";

export interface BranchCockpitTabProps {
  serverId: string;
  branches: ServerBranch[];
  selectedBranch: string;
  onSelectBranch: (branchName: string) => void;
  branchRuntime: BranchRuntimeStatus | null;
  liveChangesCount: number;
  refreshState: RefreshStateResponse | null;
  githubStatus: GitHubConnectionStatusResponse | null;
  dataTemplates: DataTemplate[];
  hasPendingSettings: boolean;
  canEdit: boolean;
  isDestroyingBranch?: string | null;
  onOpenConsole: (branchName: string) => void;
  onBrowseFiles: (branchName: string) => void;
  onDeployMainToLive: () => void;
  onNewBranch: () => void;
  onOpenSnapshotModal: (branchName: string) => void;
  onOpenMergeModal: (sourceBranch: string) => void;
  onOpenDiffVsMain: (branchName: string) => void;
  onViewBranchSnapshots: (branchName: string) => void;
  onOpenStartRun: (branchName: string) => void;
  onOpenStopRun: (branchName: string, runtimeId?: string | null) => void;
  onOpenPortSet: (branchName: string, portSet: PortSet | null) => void;
  onOpenConsoleActivity: (branchName: string, tab: "console" | "activity") => void;
  onOpenSaveTemplate: (branchName: string, runtimeId?: string | null) => void;
  onDestroyContainer: (branchName: string) => void;
  onOpenProtection: (branch: ServerBranch) => void;
  onArchiveBranch: (branch: ServerBranch) => void;
  onDeleteBranch: (branch: ServerBranch) => void;
}

function runtimePillClasses(status: string): string {
  if (status === "running") {
    return "border-status-success-border bg-status-success-bg text-status-success";
  }
  if (status === "starting") {
    return "border-status-warning-border bg-status-warning-bg text-status-warning";
  }
  if (status === "crashed" || status === "failed") {
    return "border-status-danger-border bg-status-danger-bg text-status-danger";
  }
  return "border-border-default bg-surface-elevated text-text-muted";
}

function capitalize(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

export function BranchCockpitTab({
  branches,
  selectedBranch,
  onSelectBranch,
  branchRuntime,
  liveChangesCount,
  refreshState,
  githubStatus,
  dataTemplates,
  hasPendingSettings,
  canEdit,
  isDestroyingBranch,
  onOpenConsole,
  onBrowseFiles,
  onDeployMainToLive,
  onNewBranch,
  onOpenSnapshotModal,
  onOpenMergeModal,
  onOpenDiffVsMain,
  onViewBranchSnapshots,
  onOpenStartRun,
  onOpenStopRun,
  onOpenPortSet,
  onOpenConsoleActivity,
  onOpenSaveTemplate,
  onDestroyContainer,
  onOpenProtection,
  onArchiveBranch,
  onDeleteBranch,
}: BranchCockpitTabProps) {
  const { copy } = useClipboard();
  const [copiedBranchPort, setCopiedBranchPort] = useState<string | null>(null);
  const [openMenuBranch, setOpenMenuBranch] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  useEffect(() => {
    if (!openMenuBranch) return;
    const handleDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target?.closest("[data-branch-overflow-menu]")) {
        setOpenMenuBranch(null);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenMenuBranch(null);
    };
    document.addEventListener("mousedown", handleDown);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleDown);
      document.removeEventListener("keydown", handleKey);
    };
  }, [openMenuBranch]);

  const mainBranch = branches.find((b) => b.name === "main") ?? null;
  const workingBranches = branches.filter(
    (b) => b.name !== "main" && b.status !== "archived",
  );
  const archivedBranches = branches.filter(
    (b) => b.name !== "main" && b.status === "archived",
  );

  const liveSha = refreshState?.latest_journal?.target_main_sha || null;
  const mainHeadSha = mainBranch?.head_commit_id || null;
  const mainHasUndeployed = Boolean(
    liveSha && mainHeadSha && liveSha !== mainHeadSha,
  );

  const findGitHubBranch = (name: string) =>
    githubStatus?.connected
      ? githubStatus.branches.find((gb) => gb.branch === name) ?? null
      : null;

  const mainGh = findGitHubBranch("main");

  return (
    <div className="space-y-5" data-testid="branch-cockpit-tab">
      {/* Pinned Production Branch Card */}
      {mainBranch && (
        <section
          data-testid="production-branch-card"
          aria-label="Production branch main"
          className={`rounded-xl border bg-surface-card p-4 shadow-2xs space-y-3 transition-colors ${
            selectedBranch === "main"
              ? "border-accent-primary/50"
              : "border-border-default"
          }`}
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1.5 min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Icon name="server" size={16} className="text-accent-primary shrink-0" />
                <span className="font-mono text-sm font-bold text-text-primary">
                  main
                </span>
                <span className="rounded-full border border-accent-primary/30 bg-accent-primary/10 px-2 py-0.5 text-[11px] font-semibold text-accent-primary">
                  Production
                </span>
                <span className="inline-flex items-center gap-1 rounded-full border border-status-success-border bg-status-success-bg px-2 py-0.5 text-[11px] font-semibold text-status-success">
                  <Icon name="lock" size={10} />
                  Protected
                </span>
                {mainHeadSha && (
                  <span className="rounded-md border border-border-default bg-surface-page px-2 py-0.5 font-mono text-[11px] text-text-secondary">
                    HEAD {mainHeadSha.slice(0, 8)}
                  </span>
                )}
                {hasPendingSettings && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[11px] font-semibold text-status-warning">
                    <Icon name="alert" size={10} />
                    Pending Settings
                  </span>
                )}
                {mainGh && (
                  <span
                    data-testid="branch-github-sync-pill"
                    className="rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 text-[11px] font-medium text-text-secondary"
                  >
                    GitHub: {mainGh.status === "synced" ? "Synced" : mainGh.status}
                  </span>
                )}
              </div>
              <p className="text-xs text-text-muted">
                {mainHasUndeployed ? (
                  <span className="text-status-warning font-medium">
                    New merged commits on main are ready to deploy to the live server (currently live: {liveSha?.slice(0, 8)}).
                  </span>
                ) : liveSha ? (
                  <span>
                    Live server is up to date with main ({liveSha.slice(0, 8)}).
                  </span>
                ) : (
                  <span>
                    Protected production baseline. Create a working branch to test changes safely, then merge to main.
                  </span>
                )}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2 shrink-0">
              {canEdit && (
                <button
                  type="button"
                  onClick={onDeployMainToLive}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover shadow-xs transition-colors cursor-pointer"
                >
                  <Icon name="upload" size={13} />
                  Deploy main to Live
                </button>
              )}
              {canEdit && (
                <button
                  type="button"
                  onClick={onNewBranch}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                >
                  <Icon name="plus" size={13} />
                  New Branch
                </button>
              )}
              <button
                type="button"
                onClick={() => onBrowseFiles("main")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
              >
                <Icon name="folder" size={13} />
                Browse Live Files
              </button>
              <button
                type="button"
                onClick={() => onViewBranchSnapshots("main")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
              >
                <Icon name="clock" size={13} />
                Snapshots
              </button>
              {canEdit && (
                <button
                  type="button"
                  onClick={() => onOpenProtection(mainBranch)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                >
                  <Icon name="lock" size={13} />
                  Protection
                </button>
              )}
            </div>
          </div>
        </section>
      )}

      {/* Working Branches & Isolated Sandboxes */}
      <section className="space-y-3" aria-label="Working branches and sandboxes">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold text-text-primary">
              Working Branches &amp; Sandboxes ({workingBranches.length})
            </h2>
            <p className="text-xs text-text-muted">
              Edit configs or plugins in an isolated branch, start its sandbox container to test, then compare and merge into main.
            </p>
          </div>
        </div>

        {workingBranches.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-default bg-surface-card p-8 text-center space-y-3">
            <p className="text-sm text-text-muted">
              No active working branches yet.
            </p>
            {canEdit && (
              <button
                type="button"
                onClick={onNewBranch}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover shadow-xs transition-colors cursor-pointer"
              >
                <Icon name="plus" size={14} />
                Create Working Branch
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {workingBranches.map((branch) => {
              const isSelected = branch.name === selectedBranch;
              const liveRt = isSelected ? branchRuntime : null;
              const rawStatus =
                liveRt?.runtime_status ?? branch.runtime_status ?? "stopped";
              const runtimeStatus = rawStatus.toLowerCase();
              const isActive =
                runtimeStatus === "running" || runtimeStatus === "starting";
              const isProvisioned = Boolean(
                liveRt?.container_provisioned ??
                  branch.container_provisioned ??
                  branch.active_runtime_id ??
                  isActive,
              );
              const portSet = liveRt?.port_set ?? branch.port_set ?? null;
              const activeCommitSha =
                liveRt?.active_commit_sha ?? branch.active_commit_sha ?? null;
              const activeTemplateId =
                liveRt?.data_template_id ?? branch.active_data_template_id ?? null;
              const activeTemplate = dataTemplates.find(
                (t) => t.id === activeTemplateId,
              );
              const worktreeLocked = Boolean(
                liveRt?.worktree_locked ?? branch.worktree_locked,
              );
              const ghSync = findGitHubBranch(branch.name);
              const isDestroyingThis = isDestroyingBranch === branch.name;

              return (
                <div
                  key={branch.name}
                  data-testid={`branch-card-${branch.name}`}
                  className={`rounded-xl border bg-surface-card p-4 shadow-2xs space-y-3 transition-colors ${
                    isSelected
                      ? "border-accent-primary/60 ring-1 ring-accent-primary/20"
                      : "border-border-default hover:border-border-hover"
                  }`}
                >
                  {/* Top Row: Identity & Runtime Status */}
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1.5 min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => onSelectBranch(branch.name)}
                          className="inline-flex items-center gap-1.5 font-mono text-sm font-bold text-text-primary hover:text-accent-primary cursor-pointer"
                        >
                          <Icon
                            name="version-branch"
                            size={15}
                            className="text-accent-primary shrink-0"
                          />
                          <span>{branch.name}</span>
                        </button>
                        {isSelected && (
                          <span className="rounded bg-accent-primary/15 border border-accent-primary/30 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-accent-primary">
                            Active Context
                          </span>
                        )}
                        <span
                          data-testid={`branch-runtime-status-${branch.name}`}
                          className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${runtimePillClasses(runtimeStatus)}`}
                        >
                          {isActive && (
                            <span
                              className={`h-1.5 w-1.5 rounded-full ${
                                runtimeStatus === "running"
                                  ? "bg-status-success animate-pulse"
                                  : "bg-status-warning animate-pulse"
                              }`}
                            />
                          )}
                          {isProvisioned || isActive
                            ? capitalize(runtimeStatus)
                            : "No Container"}
                        </span>
                        {branch.head_commit_id && (
                          <span className="rounded-md border border-border-default bg-surface-page px-2 py-0.5 font-mono text-[11px] text-text-secondary">
                            HEAD {branch.head_commit_id.slice(0, 8)}
                          </span>
                        )}
                        {branch.is_protected && (
                          <span className="inline-flex items-center gap-1 rounded-full border border-status-success-border bg-status-success-bg px-2 py-0.5 text-[11px] font-semibold text-status-success">
                            <Icon name="lock" size={10} />
                            Protected
                          </span>
                        )}
                        {worktreeLocked && (
                          <span
                            data-testid="worktree-lock-badge"
                            className="inline-flex items-center gap-1 rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 text-[11px] font-semibold text-text-secondary"
                          >
                            <Icon name="lock" size={10} />
                            Worktree Locked
                          </span>
                        )}
                        {ghSync && (
                          <span
                            data-testid={
                              isSelected ? "branch-github-sync-pill" : undefined
                            }
                            className="rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 text-[11px] font-medium text-text-secondary"
                          >
                            GitHub:{" "}
                            {ghSync.status === "ahead"
                              ? `${ghSync.ahead_count} ahead`
                              : ghSync.status}
                          </span>
                        )}
                        {isSelected && liveChangesCount > 0 && (
                          <span className="inline-flex items-center gap-1 rounded-full border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[11px] font-semibold text-status-warning">
                            {liveChangesCount} unsaved change
                            {liveChangesCount === 1 ? "" : "s"}
                          </span>
                        )}
                      </div>

                      {/* Sandbox Ports & Commit Strip */}
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
                        {activeCommitSha && (
                          <span className="font-mono text-text-secondary">
                            Serving {activeCommitSha.slice(0, 8)}
                          </span>
                        )}
                        {isActive && (
                          <span>
                            ·{" "}
                            {activeTemplate
                              ? `Template: ${activeTemplate.name}`
                              : "Fresh seed world"}
                          </span>
                        )}
                        {portSet ? (
                          <span className="inline-flex flex-wrap items-center gap-2 font-mono text-text-secondary">
                            <span>Game: {portSet.game_port}</span>
                            <span>RCON: {portSet.rcon_port}</span>
                            {typeof portSet.query_port === "number" && (
                              <span>Query: {portSet.query_port}</span>
                            )}
                            <button
                              type="button"
                              onClick={() => {
                                void copy(String(portSet.game_port));
                                setCopiedBranchPort(branch.name);
                                window.setTimeout(
                                  () => setCopiedBranchPort(null),
                                  1800,
                                );
                              }}
                              aria-label={`Copy join port for ${branch.name}`}
                              className="inline-flex items-center gap-1 rounded border border-border-default bg-surface-page px-1.5 py-0.5 text-[10px] font-sans font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer"
                            >
                              <Icon name="copy" size={10} />
                              {copiedBranchPort === branch.name
                                ? "Copied!"
                                : "Copy Port"}
                            </button>
                          </span>
                        ) : (
                          <span>Ports auto-assign on sandbox start</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Action Bar */}
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border-subtle">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {canEdit &&
                        (!isActive ? (
                          <button
                            type="button"
                            onClick={() => onOpenStartRun(branch.name)}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-2.5 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover shadow-xs transition-colors cursor-pointer"
                          >
                            <Icon name="play" size={12} />
                            Start Sandbox
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() =>
                              onOpenStopRun(
                                branch.name,
                                liveRt?.runtime_id ?? branch.active_runtime_id,
                              )
                            }
                            className="inline-flex items-center gap-1.5 rounded-lg border border-status-danger-border bg-status-danger-bg px-2.5 py-1.5 text-xs font-semibold text-status-danger hover:opacity-90 transition-colors cursor-pointer"
                          >
                            <Icon name="stop" size={12} />
                            Stop Sandbox
                          </button>
                        ))}

                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => onOpenSnapshotModal(branch.name)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover transition-colors cursor-pointer"
                        >
                          <Icon name="plus" size={12} />
                          Save Snapshot
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => onBrowseFiles(branch.name)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                      >
                        <Icon name="folder" size={12} />
                        Browse Files
                      </button>

                      <button
                        type="button"
                        onClick={() => onOpenConsole(branch.name)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                      >
                        <Icon name="terminal" size={12} />
                        Open Console
                      </button>

                      <button
                        type="button"
                        onClick={() => onOpenDiffVsMain(branch.name)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                      >
                        <Icon name="activity" size={12} />
                        Compare vs main
                      </button>

                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => onOpenMergeModal(branch.name)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-accent-primary/40 bg-accent-primary/10 px-2.5 py-1.5 text-xs font-semibold text-accent-primary hover:bg-accent-primary/20 transition-colors cursor-pointer"
                        >
                          <Icon name="version-branch" size={12} />
                          Merge to main
                        </button>
                      )}
                    </div>

                    {/* Overflow menu */}
                    <div className="relative" data-branch-overflow-menu>
                      <button
                        type="button"
                        aria-label={`More actions for ${branch.name}`}
                        aria-expanded={openMenuBranch === branch.name}
                        onClick={() =>
                          setOpenMenuBranch((prev) =>
                            prev === branch.name ? null : branch.name,
                          )
                        }
                        className="inline-flex items-center justify-center rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs font-semibold text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                      >
                        •••
                      </button>

                      {openMenuBranch === branch.name && (
                        <div className="absolute right-0 bottom-full mb-1.5 z-30 min-w-48 rounded-xl border border-border-default bg-surface-card p-1.5 shadow-xl text-xs space-y-0.5">
                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuBranch(null);
                              onViewBranchSnapshots(branch.name);
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer text-left"
                          >
                            <Icon name="clock" size={12} />
                            <span>View Snapshots</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuBranch(null);
                              onOpenConsoleActivity(branch.name, "console");
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer text-left"
                          >
                            <Icon name="terminal" size={12} />
                            <span>Sandbox Console &amp; Logs</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => {
                              setOpenMenuBranch(null);
                              onOpenConsoleActivity(branch.name, "activity");
                            }}
                            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer text-left"
                          >
                            <Icon name="activity" size={12} />
                            <span>Branch Activity</span>
                          </button>

                          {canEdit && (
                            <>
                              <button
                                type="button"
                                disabled={isActive}
                                title={
                                  isActive
                                    ? "Stop the sandbox before changing ports"
                                    : undefined
                                }
                                onClick={() => {
                                  setOpenMenuBranch(null);
                                  onOpenPortSet(branch.name, portSet);
                                }}
                                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:opacity-40 cursor-pointer text-left"
                              >
                                <Icon name="network" size={12} />
                                <span>Configure Ports</span>
                              </button>

                              {isActive && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    setOpenMenuBranch(null);
                                    onOpenSaveTemplate(
                                      branch.name,
                                      liveRt?.runtime_id ??
                                        branch.active_runtime_id,
                                    );
                                  }}
                                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer text-left"
                                >
                                  <Icon name="database" size={12} />
                                  <span>Save Data Template</span>
                                </button>
                              )}

                              {!isActive && isProvisioned && (
                                <button
                                  type="button"
                                  disabled={isDestroyingThis}
                                  onClick={() => {
                                    setOpenMenuBranch(null);
                                    onDestroyContainer(branch.name);
                                  }}
                                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-status-danger hover:bg-status-danger-bg disabled:opacity-40 cursor-pointer text-left"
                                >
                                  <Icon name="trash" size={12} />
                                  <span>Destroy Container</span>
                                </button>
                              )}

                              <div className="my-1 border-t border-border-subtle" />

                              <button
                                type="button"
                                onClick={() => {
                                  setOpenMenuBranch(null);
                                  onOpenProtection(branch);
                                }}
                                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer text-left"
                              >
                                <Icon name="lock" size={12} />
                                <span>Protection Rules</span>
                              </button>

                              <button
                                type="button"
                                disabled={Boolean(branch.is_protected) || isActive}
                                title={
                                  branch.is_protected
                                    ? "Protected branches cannot be archived"
                                    : isActive
                                      ? "Stop sandbox before archiving"
                                      : undefined
                                }
                                onClick={() => {
                                  setOpenMenuBranch(null);
                                  onArchiveBranch(branch);
                                }}
                                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-status-warning hover:bg-status-warning-bg disabled:opacity-40 cursor-pointer text-left"
                              >
                                <Icon name="backup" size={12} />
                                <span>Archive Branch</span>
                              </button>

                              <button
                                type="button"
                                disabled={Boolean(branch.is_protected) || isActive}
                                title={
                                  branch.is_protected
                                    ? "Disable branch protection before deleting"
                                    : isActive
                                      ? "Stop the running sandbox before deleting"
                                      : undefined
                                }
                                onClick={() => {
                                  setOpenMenuBranch(null);
                                  onDeleteBranch(branch);
                                }}
                                className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-status-danger hover:bg-status-danger-bg disabled:opacity-40 cursor-pointer text-left"
                              >
                                <Icon name="trash" size={12} />
                                <span>Delete Branch</span>
                              </button>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Collapsible Archived Branches */}
      {archivedBranches.length > 0 && (
        <section className="rounded-xl border border-border-default bg-surface-card overflow-hidden">
          <button
            type="button"
            onClick={() => setShowArchived((prev) => !prev)}
            className="w-full flex items-center justify-between px-4 py-3 text-xs font-semibold text-text-secondary hover:bg-surface-hover cursor-pointer"
          >
            <span>Archived Branches ({archivedBranches.length})</span>
            <Icon
              name={showArchived ? "chevron-up" : "chevron-down"}
              size={14}
            />
          </button>
          {showArchived && (
            <div className="divide-y divide-border-subtle border-t border-border-subtle">
              {archivedBranches.map((branch) => (
                <div
                  key={branch.name}
                  className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-xs"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono font-semibold text-text-primary">
                      {branch.name}
                    </span>
                    <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase text-text-muted">
                      Archived
                    </span>
                    {branch.head_commit_id && (
                      <span className="font-mono text-text-muted">
                        {branch.head_commit_id.slice(0, 8)}
                      </span>
                    )}
                    {branch.created_at && (
                      <span className="text-text-muted">
                        Created {formatDateTime(branch.created_at)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => onViewBranchSnapshots(branch.name)}
                      className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs text-text-secondary hover:bg-surface-hover cursor-pointer"
                    >
                      View Snapshots
                    </button>
                    {canEdit && (
                      <button
                        type="button"
                        disabled={Boolean(branch.is_protected)}
                        title={
                          branch.is_protected
                            ? "Disable protection rules before deleting"
                            : undefined
                        }
                        onClick={() => onDeleteBranch(branch)}
                        className="rounded-lg border border-status-danger-border bg-status-danger-bg px-2.5 py-1 text-xs text-status-danger hover:opacity-90 disabled:opacity-40 cursor-pointer"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
