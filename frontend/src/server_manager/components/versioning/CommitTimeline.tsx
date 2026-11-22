import { useState, useEffect } from "react";
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
  const [openMenuCommitId, setOpenMenuCommitId] = useState<string | null>(null);

  useEffect(() => {
    if (!openMenuCommitId) return;
    const handlePointerDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target?.closest("[data-commit-actions-menu]")) {
        setOpenMenuCommitId(null);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpenMenuCommitId(null);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [openMenuCommitId]);

  return (
    <div className="h-full rounded-xl border border-border-subtle bg-surface-card dark:bg-gray-800 shadow-2xs overflow-hidden flex flex-col">
      {/* Header */}
      <div className="border-b border-border-subtle px-5 py-3.5 flex items-center justify-between bg-surface-elevated/40">
        <div className="flex items-center gap-2">
          <Icon name="version-branch" size={16} className="text-accent-primary" />
          <h2 className="text-xs font-bold uppercase tracking-wider text-text-primary">
            Commit History Timeline
          </h2>
        </div>
        <span className="font-mono text-xs tabular-nums text-text-muted">
          {commits.length} snapshot{commits.length === 1 ? "" : "s"}
        </span>
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
        <div className="relative divide-y divide-border-subtle/50 flex-1">
          {commits.map((commit, index) => {
            const commitTags = tags.filter((t) => t.commit_id === commit.id);
            const parentId =
              commit.parent_id ||
              commit.parent_commit_id ||
              (commit.parent_commit_ids && commit.parent_commit_ids[0]);
            const isMerge = commit.parent_commit_ids && commit.parent_commit_ids.length > 1;
            const isHead = index === 0;

            return (
              <div
                key={commit.id}
                className="group relative flex items-start gap-4 p-4.5 transition-colors hover:bg-surface-hover/40"
              >
                {/* Visual SVG Git Graph Rail */}
                <div className="relative flex flex-col items-center shrink-0 self-stretch w-6">
                  {/* Vertical connecting line */}
                  {index < commits.length - 1 && (
                    <div className="absolute top-6 bottom-0 w-0.5 bg-border-strong/40 group-hover:bg-accent-primary/40 transition-colors" />
                  )}
                  {index > 0 && (
                    <div className="absolute top-0 h-3 w-0.5 bg-border-strong/40" />
                  )}

                  {/* Git Node Circle */}
                  <div
                    className={`relative z-10 mt-1 flex h-4 w-4 items-center justify-center rounded-full border-2 transition-transform duration-150 group-hover:scale-125 ${
                      isHead
                        ? "border-accent-primary bg-surface-card ring-2 ring-accent-primary/40 shadow-xs"
                        : "border-border-strong bg-surface-elevated ring-1 ring-border-subtle"
                    }`}
                  >
                    <div
                      className={`h-1.5 w-1.5 rounded-full ${
                        isHead ? "bg-accent-primary" : "bg-text-muted"
                      }`}
                    />
                  </div>
                </div>

                {/* Commit Content Card */}
                <div className="flex-1 min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {/* Commit Hash Monospace Chip */}
                    <span className="font-mono text-xs font-semibold tabular-nums bg-surface-elevated text-text-primary px-2 py-0.5 rounded border border-border-subtle">
                      {commit.id.slice(0, 8)}
                    </span>

                    {/* HEAD Tag & Branch Pointer */}
                    {isHead && (
                      <div className="inline-flex items-center gap-1">
                        <span className="rounded bg-accent-primary/15 border border-accent-primary/30 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-accent-primary">
                          HEAD
                        </span>
                        <span className="rounded bg-surface-elevated border border-border-subtle px-1.5 py-0.5 text-[10px] font-semibold text-text-secondary flex items-center gap-1">
                          <Icon name="version-branch" size={10} className="text-accent-primary" />
                          <span>→ {selectedBranch}</span>
                        </span>
                      </div>
                    )}

                    {isMerge && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-accent-primary/20 text-accent-primary">
                        MERGE ({commit.parent_commit_ids!.length} parents)
                      </span>
                    )}

                    {commitTags.map((tag) => (
                      <span
                        key={tag.name}
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-accent-primary/20 text-accent-primary border border-accent-primary/40"
                      >
                        <Icon name="tag" size={10} />
                        {tag.name}
                      </span>
                    ))}

                    <span className="text-sm font-bold text-text-primary">
                      {commit.message}
                    </span>
                  </div>

                  {/* Metadata Row */}
                  <div className="flex flex-wrap items-center gap-2.5 text-xs text-text-muted">
                    <span className="font-mono">
                      {commit.manifest?.server_type} ({commit.manifest?.minecraft_version})
                    </span>
                    <span className="text-border-subtle">•</span>
                    <span>{formatDateTime(commit.created_at)}</span>
                    {commit.author_id && (
                      <>
                        <span className="text-border-subtle">•</span>
                        <span>Author: {commit.author_id}</span>
                      </>
                    )}
                  </div>

                  {/* Action Toolbar */}
                  <div className="flex items-center justify-between gap-1.5 pt-1">
                    {/* Secondary Actions Dropdown */}
                    <div className="relative" data-commit-actions-menu>
                      <button
                        type="button"
                        aria-label="More commit actions"
                        aria-expanded={openMenuCommitId === commit.id}
                        onClick={() =>
                          setOpenMenuCommitId((prev) => (prev === commit.id ? null : commit.id))
                        }
                        className="inline-flex items-center justify-center rounded-md border border-border-default bg-surface-elevated px-2 py-1 text-xs font-semibold text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
                        title="More commit actions"
                      >
                        •••
                      </button>
                      {openMenuCommitId === commit.id && (
                        <div className="absolute left-0 top-full mt-1 z-20 min-w-36 rounded-lg border border-border-default bg-surface-card p-1 shadow-lg text-xs space-y-0.5">
                            <button
                              type="button"
                              onClick={() => {
                                setOpenMenuCommitId(null);
                                onTagCommit(commit.id);
                              }}
                              className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer text-left"
                              title="Create immutable tag snapshot for this commit"
                            >
                              <Icon name="backup" size={12} />
                              <span>Tag</span>
                            </button>
                            {parentId && (
                              <button
                                type="button"
                                onClick={() => {
                                  setOpenMenuCommitId(null);
                                  onDiff(parentId, commit.id);
                                }}
                                className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer text-left"
                                title="View configuration and file differences against parent commit"
                              >
                                <Icon name="activity" size={12} />
                                <span>Diff</span>
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => {
                                setOpenMenuCommitId(null);
                                onInspect(commit);
                              }}
                              className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer text-left"
                              title="Inspect captured configuration files, mod JARs, and SHA256 checksums"
                            >
                              <Icon name="file" size={12} />
                              <span>Inspect Manifest</span>
                            </button>
                          </div>
                      )}
                    </div>

                    {/* Primary Action */}
                    <button
                      type="button"
                      onClick={() => onRunTest(commit.id)}
                      className="inline-flex items-center gap-1.5 rounded-md bg-accent-primary px-3 py-1 text-xs font-bold text-accent-contrast-text hover:bg-accent-hover transition-colors shadow-2xs cursor-pointer ml-auto"
                      title="Spawn a safe test environment and execute bot-driven dry-run verification"
                    >
                      <Icon name="play" size={12} />
                      Run Isolated Test
                    </button>
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
