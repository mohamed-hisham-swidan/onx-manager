import { Icon } from "@/components/ui/Icon";
import { formatDateTime } from "@/server_manager/utils/format";
import {
  formatCommitAuthor,
  formatServerTypeLabel,
} from "@/server_manager/utils/versioningFormat";
import type { ServerCommit, ServerTag } from "@/server_manager/types";

interface CommitTimelineProps {
  commits: ServerCommit[];
  tags: ServerTag[];
  selectedBranch: string;
  liveCommitSha?: string | null;
  canEdit?: boolean;
  isLoading: boolean;
  onTagCommit: (commitId: string) => void;
  onDiff: (from: string, to: string, parentIds?: string[]) => void;
  onRestoreToLive?: (commit: ServerCommit) => void;
  onTestInSandbox?: (commit: ServerCommit) => void;
}

export function CommitTimeline({
  commits,
  tags,
  selectedBranch,
  liveCommitSha,
  canEdit = true,
  isLoading,
  onTagCommit,
  onDiff,
  onRestoreToLive,
  onTestInSandbox,
}: CommitTimelineProps) {
  const headCommitId = commits[0]?.id ?? null;

  return (
    <div className="h-full rounded-xl border border-border-subtle bg-surface-card shadow-2xs overflow-hidden flex flex-col">
      {/* Header */}
      <div className="border-b border-border-subtle px-5 py-3.5 flex items-center justify-between bg-surface-elevated/40">
        <div className="flex items-center gap-2">
          <Icon name="version-branch" size={16} className="text-accent-primary" />
          <h2 className="text-xs font-bold uppercase tracking-wider text-text-primary">
            Snapshot History · <span className="font-mono">{selectedBranch}</span>
          </h2>
        </div>
        <span className="font-mono text-xs tabular-nums text-text-muted">
          {commits.length} snapshot{commits.length === 1 ? "" : "s"}
        </span>
      </div>

      {isLoading && commits.length === 0 ? (
        <div className="p-8 text-center text-sm text-text-muted">
          Loading snapshots...
        </div>
      ) : commits.length === 0 ? (
        <div className="p-8 text-center text-sm text-text-muted">
          {selectedBranch === "main"
            ? "No snapshots on main yet. Create a working branch, save a snapshot, and merge it to main."
            : `No snapshot commits yet on branch '${selectedBranch}'. Click "Save Snapshot" to capture your current branch state.`}
        </div>
      ) : (
        <div className="relative divide-y divide-border-subtle/50 flex-1">
          {commits.map((commit, index) => {
            const commitTags = tags.filter((t) => t.commit_id === commit.id);
            const parentIds =
              commit.parent_commit_ids && commit.parent_commit_ids.length > 0
                ? commit.parent_commit_ids
                : commit.parent_commit_id
                  ? [commit.parent_commit_id]
                  : commit.parent_id
                    ? [commit.parent_id]
                    : [];
            const primaryParentId = parentIds[0] ?? null;
            const isMerge = parentIds.length > 1;
            const isHead = index === 0;
            const isLive = Boolean(liveCommitSha && commit.id === liveCommitSha);
            const serverTypeLabel = formatServerTypeLabel(
              commit.manifest?.server_type,
            );
            const mcVersion = commit.manifest?.minecraft_version?.trim() || "";
            const authorLabel = formatCommitAuthor(commit.author_id);

            return (
              <div
                key={commit.id}
                className="group relative flex items-start gap-4 p-4 transition-colors hover:bg-surface-hover/40"
              >
                {/* Timeline Graph Rail */}
                <div className="relative flex flex-col items-center shrink-0 self-stretch w-6">
                  {index < commits.length - 1 && (
                    <div className="absolute top-6 bottom-0 w-0.5 bg-border-strong/40 group-hover:bg-accent-primary/40 transition-colors" />
                  )}
                  {index > 0 && (
                    <div className="absolute top-0 h-3 w-0.5 bg-border-strong/40" />
                  )}

                  <div
                    className={`relative z-10 mt-1 flex h-4 w-4 items-center justify-center rounded-full border-2 transition-transform duration-150 group-hover:scale-110 ${
                      isLive
                        ? "border-status-success bg-surface-card ring-2 ring-status-success/30 shadow-xs"
                        : isHead
                          ? "border-accent-primary bg-surface-card ring-2 ring-accent-primary/35 shadow-xs"
                          : "border-border-strong bg-surface-elevated ring-1 ring-border-subtle"
                    }`}
                  >
                    <div
                      className={`h-1.5 w-1.5 rounded-full ${
                        isLive
                          ? "bg-status-success"
                          : isHead
                            ? "bg-accent-primary"
                            : "bg-text-muted"
                      }`}
                    />
                  </div>
                </div>

                {/* Commit Content */}
                <div className="flex-1 min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-semibold tabular-nums bg-surface-elevated text-text-primary px-2 py-0.5 rounded border border-border-subtle">
                      {commit.id.slice(0, 8)}
                    </span>

                    {isLive && (
                      <span
                        data-testid={`commit-live-badge-${commit.id}`}
                        className="inline-flex items-center gap-1 rounded bg-status-success-bg border border-status-success-border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-status-success"
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-status-success" />
                        LIVE
                      </span>
                    )}

                    {isHead && (
                      <div className="inline-flex items-center gap-1">
                        <span className="rounded bg-accent-primary/15 border border-accent-primary/30 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-accent-primary">
                          HEAD
                        </span>
                        <span className="rounded bg-surface-elevated border border-border-subtle px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary flex items-center gap-1">
                          <Icon
                            name="version-branch"
                            size={10}
                            className="text-accent-primary"
                          />
                          <span>{selectedBranch}</span>
                        </span>
                      </div>
                    )}

                    {isMerge && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-accent-primary/15 text-accent-primary border border-accent-primary/25">
                        MERGE ({parentIds.length} parents)
                      </span>
                    )}

                    {commitTags.map((tag) => (
                      <span
                        key={tag.name}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-accent-primary/15 text-accent-primary border border-accent-primary/30"
                      >
                        <Icon name="tag" size={10} />
                        {tag.name}
                      </span>
                    ))}

                    <span className="text-sm font-bold text-text-primary break-words">
                      {commit.message || "(No commit message)"}
                    </span>
                  </div>

                  {/* Metadata Row */}
                  <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
                    {(serverTypeLabel || mcVersion) && (
                      <>
                        <span className="inline-flex items-center gap-1 rounded border border-border-subtle bg-surface-page px-1.5 py-0.5 text-[11px] font-medium text-text-secondary">
                          {[serverTypeLabel, mcVersion].filter(Boolean).join(" ")}
                        </span>
                        <span className="text-border-subtle">•</span>
                      </>
                    )}
                    <span>{formatDateTime(commit.created_at)}</span>
                    {authorLabel && (
                      <>
                        <span className="text-border-subtle">•</span>
                        <span>by {authorLabel}</span>
                      </>
                    )}
                  </div>

                  {/* Direct Inline Actions */}
                  <div className="flex flex-wrap items-center gap-1.5 pt-1">
                    {primaryParentId && (
                      <button
                        type="button"
                        onClick={() => onDiff(primaryParentId, commit.id, parentIds)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                      >
                        <Icon name="activity" size={12} />
                        <span>View Changes</span>
                      </button>
                    )}

                    {!primaryParentId && headCommitId && headCommitId !== commit.id && (
                      <button
                        type="button"
                        onClick={() => onDiff(commit.id, headCommitId)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                      >
                        <Icon name="activity" size={12} />
                        <span>Compare vs HEAD</span>
                      </button>
                    )}

                    {canEdit && onRestoreToLive && !isLive && (
                      <button
                        type="button"
                        onClick={() => onRestoreToLive(commit)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-accent-primary/40 bg-accent-primary/10 px-2.5 py-1 text-xs font-semibold text-accent-primary hover:bg-accent-primary/20 transition-colors cursor-pointer"
                      >
                        <Icon name="restart" size={12} />
                        <span>Restore to Live</span>
                      </button>
                    )}

                    {canEdit && onTestInSandbox && selectedBranch !== "main" && (
                      <button
                        type="button"
                        onClick={() => onTestInSandbox(commit)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                      >
                        <Icon name="play" size={12} />
                        <span>Test in Sandbox</span>
                      </button>
                    )}

                    {canEdit && (
                      <button
                        type="button"
                        onClick={() => onTagCommit(commit.id)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                      >
                        <Icon name="tag" size={12} />
                        <span>Tag</span>
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
