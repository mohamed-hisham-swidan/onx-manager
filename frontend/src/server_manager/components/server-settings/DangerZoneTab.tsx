import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";

export interface DangerZoneTabProps {
  canDelete: boolean;
  isDeleting: boolean;
  onRequestDelete: () => void;
}

export function DangerZoneTab({
  canDelete,
  isDeleting,
  onRequestDelete,
}: DangerZoneTabProps) {
  return (
    <div className="space-y-6" data-testid="server-settings-tab-danger">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight text-text-primary">
          Danger Zone
        </h2>
        <p className="text-xs text-text-muted">
          Irreversible actions for this server.
        </p>
      </header>

      <section
        data-testid="server-danger-zone"
        className="rounded-xl border border-status-danger-border/60 bg-status-danger-bg/30 p-5"
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-status-danger-bg text-status-danger">
                <Icon name="trash" size={15} />
              </span>
              <h3 className="text-sm font-semibold text-text-primary">
                Delete Server
              </h3>
            </div>
            <p className="text-xs text-text-muted">
              Permanently deletes this server, its files, and container.
            </p>
            {!canDelete && (
              <p className="text-xs text-text-muted pt-0.5">
                Requires delete permission to perform this action.
              </p>
            )}
          </div>

          <Button
            type="button"
            variant="danger"
            size="md"
            icon="trash"
            disabled={!canDelete || isDeleting}
            onClick={onRequestDelete}
          >
            {isDeleting ? "Deleting..." : "Delete Server"}
          </Button>
        </div>
      </section>
    </div>
  );
}
