import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";

export interface StickyServerSaveBarProps {
  dirtyCount: number;
  hasValidationErrors: boolean;
  isPending: boolean;
  gitBacked: boolean;
  isMainBranch: boolean;
  branchName?: string;
  onDiscard: () => void;
  onSave: () => void;
}

export function StickyServerSaveBar({
  dirtyCount,
  hasValidationErrors,
  isPending,
  gitBacked,
  isMainBranch,
  branchName,
  onDiscard,
  onSave,
}: StickyServerSaveBarProps) {
  if (dirtyCount <= 0) {
    return null;
  }

  const modeNote = gitBacked
    ? isMainBranch
      ? "Queued for next restart"
      : `Commits to ${branchName}`
    : null;

  const submitLabel = gitBacked
    ? isMainBranch
      ? "Queue for Restart"
      : `Commit to ${branchName}`
    : "Save";

  return (
    <div
      data-testid="sticky-server-save-bar"
      role="region"
      aria-label="Unsaved settings changes"
      className="sticky top-16 z-30 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-warning-border bg-surface-card/95 px-4 py-3 shadow-lg backdrop-blur-md"
    >
      <div className="flex flex-wrap items-center gap-2.5 text-xs">
        <span className="inline-flex items-center gap-1.5 font-semibold text-text-primary">
          <span className="h-2 w-2 rounded-full bg-status-warning animate-pulse" />
          {dirtyCount} unsaved {dirtyCount === 1 ? "change" : "changes"}
        </span>
        {modeNote && (
          <span className="text-text-muted">· {modeNote}</span>
        )}
      </div>

      <div className="flex items-center gap-2.5">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={isPending}
          onClick={onDiscard}
        >
          Undo All
        </Button>
        <Button
          type="button"
          variant="primary"
          size="sm"
          loading={isPending}
          disabled={hasValidationErrors || isPending}
          onClick={onSave}
        >
          <Icon name="check" size={14} />
          <span>{submitLabel}</span>
        </Button>
      </div>
    </div>
  );
}
