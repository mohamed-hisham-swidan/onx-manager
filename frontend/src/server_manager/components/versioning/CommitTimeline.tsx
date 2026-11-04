import { Icon } from "@/components/ui/Icon";
import { formatDateTime } from "@/server_manager/utils/format";
import type { ServerCommit, ServerTag } from "@/server_manager/types";

interface CommitTimelineProps {
  commits: ServerCommit[];
  tags: ServerTag[];
  selectedBranch: string;
  isLoading: boolean;
  onTagCommit: (commitId: string) => void;
  onDiff: (from: string, to: string) => void;
  onInspect: (commit: ServerCommit) => void;
  onRunTest: (commitId: string) => void;
}

export function CommitTimeline({
  commits,
  tags,
  selectedBranch,
  isLoading,
  onTagCommit,
  onDiff,
  onInspect,
  onRunTest,
}: CommitTimelineProps) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-800 bg-surface-panel shadow-sm overflow-hidden">
      <div className="border-b border-border-subtle px-6 py-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
          Commit History Timeline
        </h2>
      </div>

      {isLoading && commits.length === 0 ? (
        <div className="p-8 text-center text-sm text-text-muted">
          Loading commits...
        </div>
      ) : commits.length === 0 ? (
        <div className="p-8 text-center text-sm text-text-muted">
          No snapshot commits yet on branch &lsquo;{selectedBranch}&rsquo;. Click &ldquo;Create Snapshot Commit&rdquo; above to create your first commit.
        </div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {commits.map((commit) => {
            const commitTags = tags.filter((t) => t.commit_id === commit.id);
            const parentId =
              commit.parent_id ||
              commit.parent_commit_id ||
              (commit.parent_commit_ids && commit.parent_commit_ids[0]);
            const isMerge = commit.parent_commit_ids && commit.parent_commit_ids.length > 1;

            return (
              <div
                key={commit.id}
                className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-surface-hover/50 transition-colors"
              >
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-semibold bg-surface-canvas text-text-primary px-2 py-0.5 rounded border border-border-subtle">
                      {commit.id.slice(0, 8)}
                    </span>
                    {isMerge && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-accent-muted/20 text-accent-primary">
                        MERGE ({commit.parent_commit_ids!.length} parents)
                      </span>
                    )}
                    {commitTags.map((tag) => (
                      <span
                        key={tag.name}
                        className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-accent-muted/20 text-accent-primary border border-accent-muted/40"
                      >
                        🏷️ {tag.name}
                      </span>
                    ))}
                    <span className="text-sm font-semibold text-text-primary">
                      {commit.message}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-text-muted">
                    <span>
                      Type: {commit.manifest?.server_type} ({commit.manifest?.minecraft_version})
                    </span>
                    <span>•</span>
                    <span>{formatDateTime(commit.created_at)}</span>
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
                    type="button"
                    onClick={() => onTagCommit(commit.id)}
                    className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-canvas px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
                    title="Create immutable tag"
                  >
                    <Icon name="backup" size={12} />
                    Tag
                  </button>
                  {parentId && (
                    <button
                      type="button"
                      onClick={() => onDiff(parentId, commit.id)}
                      className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-canvas px-2.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
                      title="View changes against parent commit"
                    >
                      <Icon name="activity" size={12} />
                      Diff
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onInspect(commit)}
                    className="inline-flex items-center gap-1 rounded-lg border border-border-default bg-surface-canvas px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors cursor-pointer"
                  >
                    <Icon name="file" size={14} />
                    Inspect Manifest
                  </button>
                  <button
                    type="button"
                    onClick={() => onRunTest(commit.id)}
                    className="inline-flex items-center gap-1 rounded-lg bg-accent-muted/20 border border-accent-muted/40 px-3 py-1.5 text-xs font-semibold text-accent-primary hover:bg-accent-muted/30 transition-colors cursor-pointer"
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
  );
}
