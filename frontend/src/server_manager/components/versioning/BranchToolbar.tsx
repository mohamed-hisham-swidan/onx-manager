import { Icon } from "@/components/ui/Icon";
import type { ServerBranch } from "@/server_manager/types";

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
              {b.name} {b.is_protected ? "🔒" : ""} {b.status === "archived" ? "(archived)" : ""}
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
