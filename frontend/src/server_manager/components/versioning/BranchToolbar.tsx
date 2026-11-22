import { Icon } from "@/components/ui/Icon";
import type {
  GitHubBranchSyncState,
  ServerBranch,
} from "@/server_manager/types";

interface BranchToolbarProps {
  branches: ServerBranch[];
  selectedBranch: string;
  onSelectBranch: (branch: string) => void;
  currentBranchObj: ServerBranch | null;
  filteredCommitsCount: number;
  onNewBranch: () => void;
  onProtectionRules: () => void;
  onManageBranches: () => void;
  onExploreWorktree: () => void;
  onMergeBranch?: () => void;
  githubBranchSync?: GitHubBranchSyncState | null;
}

function githubSyncPillClasses(status: GitHubBranchSyncState["status"]): string {
  if (status === "synced") {
    return "border-status-success-border bg-status-success-bg text-status-success";
  }
  if (status === "ahead") {
    return "border-status-info-border bg-status-info-bg text-status-info";
  }
  if (status === "behind" || status === "remote_only") {
    return "border-status-warning-border bg-status-warning-bg text-status-warning";
  }
  if (status === "diverged") {
    return "border-status-danger-border bg-status-danger-bg text-status-danger";
  }
  return "border-border-default bg-surface-elevated text-text-muted";
}

function githubSyncPillLabel(sync: GitHubBranchSyncState): string {
  if (sync.status === "synced") return "GitHub: Synced";
  if (sync.status === "ahead") return `GitHub: ${sync.ahead_count} ahead`;
  if (sync.status === "behind") return `GitHub: ${sync.behind_count} behind`;
  if (sync.status === "diverged") return "GitHub: Diverged";
  if (sync.status === "local_only") return "GitHub: Local only";
  if (sync.status === "remote_only") return "GitHub: Remote only";
  return "GitHub: Unknown";
}

export function BranchToolbar({
  branches,
  selectedBranch,
  onSelectBranch,
  currentBranchObj,
  filteredCommitsCount,
  onNewBranch,
  onProtectionRules,
  onManageBranches,
  onExploreWorktree,
  onMergeBranch,
  githubBranchSync,
}: BranchToolbarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 bg-surface-card p-3 rounded-xl border border-border-default">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name="folder" size={16} className="text-text-muted" />
        <span className="text-xs font-medium text-text-secondary">Branch:</span>
        <select
          value={selectedBranch}
          onChange={(e) => onSelectBranch(e.target.value)}
          className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-semibold text-text-primary focus:outline-none focus:border-accent-primary"
        >
          {branches.map((b) => (
            <option key={b.id} value={b.name}>
              {b.name}{b.is_protected ? " (protected)" : ""}{b.status === "archived" ? " (archived)" : ""}
            </option>
          ))}
        </select>

        {currentBranchObj?.is_protected && (
          <span className="inline-flex items-center gap-1 rounded bg-status-success-bg px-2 py-0.5 text-[11px] font-semibold text-status-success">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            Protected
          </span>
        )}

        {currentBranchObj?.status === "archived" && (
          <span className="inline-flex items-center rounded bg-surface-hover px-2 py-0.5 text-[11px] font-semibold text-text-muted">
            Archived (Read-Only)
          </span>
        )}

        {(currentBranchObj?.runtime_status === "running" ||
          currentBranchObj?.runtime_status === "starting") && (
          <span
            data-testid="branch-runtime-badge"
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
              currentBranchObj.runtime_status === "running"
                ? "bg-status-success-bg text-status-success border-status-success-border"
                : "bg-status-warning-bg text-status-warning border-status-warning-border"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                currentBranchObj.runtime_status === "running"
                  ? "bg-status-success"
                  : "bg-status-warning animate-pulse"
              }`}
              aria-hidden="true"
            />
            Runtime: {currentBranchObj.runtime_status}
          </span>
        )}

        {currentBranchObj?.worktree_locked && (
          <span
            data-testid="branch-lock-badge"
            title={currentBranchObj.worktree_lock_reason ?? "Worktree locked by active runtime"}
            className="inline-flex items-center gap-1 rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 text-[11px] font-semibold text-text-secondary"
          >
            <Icon name="lock" size={11} />
            Locked
          </span>
        )}

        {githubBranchSync && (
          <span
            data-testid="branch-github-sync-pill"
            title={`GitHub sync for '${githubBranchSync.branch}'`}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${githubSyncPillClasses(githubBranchSync.status)}`}
          >
            <Icon name="version-branch" size={11} />
            {githubSyncPillLabel(githubBranchSync)}
          </span>
        )}

        <button
          type="button"
          onClick={onNewBranch}
          className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-accent-primary hover:bg-surface-hover transition-colors cursor-pointer"
        >
          <Icon name="plus" size={12} />
          New Branch
        </button>

        <button
          type="button"
          onClick={onProtectionRules}
          className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
        >
          <Icon name="settings" size={12} />
          Protection Rules
        </button>

        <button
          type="button"
          onClick={onManageBranches}
          className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
        >
          <Icon name="backup" size={12} />
          Manage Branches
        </button>

        <button
          type="button"
          onClick={onExploreWorktree}
          className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-status-success hover:bg-surface-hover transition-colors cursor-pointer"
        >
          <Icon name="folder" size={12} />
          Explore Worktree
        </button>

        {onMergeBranch && (
          <button
            type="button"
            onClick={onMergeBranch}
            className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium text-accent-primary hover:bg-surface-hover transition-colors cursor-pointer"
          >
            <Icon name="plus" size={12} />
            Merge Branch
          </button>
        )}
      </div>

      <div className="text-xs text-text-muted">
        Showing {filteredCommitsCount} commits
      </div>
    </div>
  );
}
