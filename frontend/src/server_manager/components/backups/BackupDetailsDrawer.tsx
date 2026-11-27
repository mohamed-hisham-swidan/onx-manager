import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Icon } from "@/components/ui/Icon";
import { HashBadge } from "@/components/ui/HashBadge";
import { useClipboard } from "@/hooks/useClipboard";
import { formatBytes, formatDateTime, formatRelativeTime } from "@/server_manager/utils/format";
import {
  getScopeMeta,
  getStatusMeta,
  getTierMeta,
  resolveBackupServer,
} from "./backupUtils";
import type { BackupResponse, VerifyBackupResponse } from "@/types";

export interface BackupDetailsDrawerProps {
  backup: BackupResponse | null;
  serverMap: Map<string, string>;
  serversResolved: boolean;
  verification?: VerifyBackupResponse | null;
  isVerifying?: boolean;
  canRestore?: boolean;
  canDelete?: boolean;
  onClose: () => void;
  onVerify: (backup: BackupResponse) => void;
  onRestore: (backup: BackupResponse) => void;
  onDelete: (backup: BackupResponse) => void;
}

export function BackupDetailsDrawer({
  backup,
  serverMap,
  serversResolved,
  verification,
  isVerifying = false,
  canRestore = true,
  canDelete = true,
  onClose,
  onVerify,
  onRestore,
  onDelete,
}: BackupDetailsDrawerProps) {
  const [copiedChecksum, setCopiedChecksum] = useState(false);
  const { copy } = useClipboard();

  if (!backup) {
    return null;
  }

  const server = resolveBackupServer(backup, serverMap, serversResolved);
  const tierMeta = getTierMeta(backup.tier);
  const scopeMeta = getScopeMeta(backup.backup_type);
  const statusMeta = getStatusMeta(backup.status);
  const isCompleted = backup.status === "completed";

  const handleCopyChecksum = () => {
    if (!backup.checksum) return;
    void copy(backup.checksum, "Checksum copied to clipboard");
    setCopiedChecksum(true);
    setTimeout(() => setCopiedChecksum(false), 2000);
  };

  return (
    <Modal
      open={true}
      onClose={onClose}
      variant="drawer"
      title={
        <div className="flex flex-wrap items-center gap-2">
          <span className={server.deleted ? "text-text-muted italic" : "text-text-primary"}>
            {server.name}
          </span>
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${statusMeta.badgeClass}`}
          >
            {statusMeta.label}
          </span>
        </div>
      }
      description={
        <span className="inline-flex items-center gap-2 mt-1">
          <HashBadge hash={backup.backup_id} />
          <span className="text-xs text-text-muted">{tierMeta.label}</span>
        </span>
      }
      footer={
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] text-text-muted">
            {backup.pinned ? "Pinned for upgrade rollback. Confirm the upgrade or release pins to unlock deletion." : null}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {isCompleted && canRestore && (
              <button
                type="button"
                onClick={() => onRestore(backup)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-status-warning-border bg-status-warning-bg px-3 py-1.5 text-xs font-semibold text-status-warning hover:opacity-90 cursor-pointer"
              >
                <Icon name="restart" size={13} />
                <span>Restore Backup</span>
              </button>
            )}
            {canDelete && (
              <button
                type="button"
                onClick={() => onDelete(backup)}
                disabled={backup.pinned}
                title={
                  backup.pinned
                    ? "Pinned for upgrade rollback. Confirm the upgrade or release pins to unlock deletion."
                    : "Delete backup"
                }
                className="inline-flex items-center gap-1.5 rounded-lg border border-status-danger-border bg-status-danger-bg px-3 py-1.5 text-xs font-semibold text-status-danger hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                <Icon name="trash" size={13} />
                <span>Delete</span>
              </button>
            )}
          </div>
        </div>
      }
    >
      <div className="space-y-4">
          {backup.error_message && (
            <div
              role="alert"
              className="rounded-xl border border-status-danger-border bg-status-danger-bg/50 p-3.5 space-y-1.5"
            >
              <div className="flex items-center gap-1.5 text-xs font-semibold text-status-danger">
                <Icon name="alert" size={14} />
                <span>Failure Details</span>
              </div>
              <p className="font-mono text-xs text-text-primary whitespace-pre-wrap break-words">
                {backup.error_message}
              </p>
            </div>
          )}

          {/* Integrity Verification Card */}
          <div className="rounded-xl border border-border-subtle bg-surface-page p-4 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Icon name="shield" size={15} className="text-text-muted" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                  Integrity Check
                </h3>
              </div>
              {isCompleted && (
                <button
                  type="button"
                  onClick={() => onVerify(backup)}
                  disabled={isVerifying}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-card px-2.5 py-1 text-xs font-medium text-text-primary hover:bg-surface-hover disabled:opacity-50 cursor-pointer"
                >
                  {isVerifying ? (
                    <span
                      className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                      aria-hidden="true"
                    />
                  ) : (
                    <Icon name="check" size={12} />
                  )}
                  <span>{isVerifying ? "Checking..." : "Run Integrity Check"}</span>
                </button>
              )}
            </div>

            {verification ? (
              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Overall Status</span>
                  <span
                    className={`font-semibold ${
                      verification.valid ? "text-status-success" : "text-status-danger"
                    }`}
                  >
                    {verification.valid ? "Verified" : "Integrity Failed"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Checksum Valid</span>
                  <span className="font-medium text-text-primary">
                    {verification.checksum_valid ? "Yes" : "No"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Size Valid</span>
                  <span className="font-medium text-text-primary">
                    {verification.size_valid ? "Yes" : "No"}
                  </span>
                </div>
                {verification.artifact_present !== undefined &&
                  verification.artifact_present !== null && (
                    <div className="flex items-center justify-between">
                      <span className="text-text-muted">Artifact Present</span>
                      <span className="font-medium text-text-primary">
                        {verification.artifact_present ? "Yes" : "No"}
                      </span>
                    </div>
                  )}
                {verification.artifact_error && (
                  <div className="rounded-lg border border-status-danger-border bg-status-danger-bg/50 p-2.5 font-mono text-[11px] text-status-danger break-words">
                    {verification.artifact_error}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-text-muted">
                {isCompleted
                  ? "Run an integrity check to verify artifact presence and SHA-256 checksum."
                  : "Integrity checks are only available for completed backups."}
              </p>
            )}
          </div>

          {/* Metadata Grid */}
          <dl className="grid grid-cols-2 gap-3 rounded-xl border border-border-subtle bg-surface-page p-4 text-xs">
            <div>
              <dt className="text-text-muted">Backup Type</dt>
              <dd className="mt-0.5 font-medium text-text-primary">{tierMeta.label}</dd>
            </div>
            <div>
              <dt className="text-text-muted">Scope</dt>
              <dd className="mt-0.5 font-medium text-text-primary">{scopeMeta.label}</dd>
            </div>
            <div>
              <dt className="text-text-muted">Protection</dt>
              <dd className="mt-0.5 font-medium text-text-primary">
                {backup.pinned ? "Pinned (Protected)" : "Standard"}
              </dd>
            </div>
            <div>
              <dt className="text-text-muted">File Size</dt>
              <dd className="mt-0.5 font-mono font-medium tabular-nums text-text-primary">
                {formatBytes(backup.size_bytes)}
              </dd>
            </div>
            <div>
              <dt className="text-text-muted">Created</dt>
              <dd className="mt-0.5 font-medium text-text-primary" title={formatDateTime(backup.created_at)}>
                {formatRelativeTime(backup.created_at) || "just now"}
                <span className="block text-[11px] text-text-muted">
                  {formatDateTime(backup.created_at)}
                </span>
              </dd>
            </div>
            <div>
              <dt className="text-text-muted">Completed</dt>
              <dd className="mt-0.5 font-medium text-text-primary">
                {backup.completed_at ? formatDateTime(backup.completed_at) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-text-muted">Storage Tier</dt>
              <dd className="mt-0.5 font-mono text-text-secondary">{backup.tier}</dd>
            </div>
            <div>
              <dt className="text-text-muted">Server</dt>
              <dd className="mt-0.5 font-medium text-text-primary truncate">{server.name}</dd>
            </div>
          </dl>

          {/* Checksum Block */}
          <div className="rounded-xl border border-border-subtle bg-surface-page p-4 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-text-muted">SHA-256 Checksum</span>
              {backup.checksum && (
                <button
                  type="button"
                  onClick={handleCopyChecksum}
                  className="inline-flex items-center gap-1 rounded border border-border-subtle bg-surface-card px-2 py-0.5 text-[11px] font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary cursor-pointer"
                >
                  <Icon name={copiedChecksum ? "check" : "copy"} size={11} />
                  <span>{copiedChecksum ? "Copied" : "Copy"}</span>
                </button>
              )}
            </div>
            <div className="rounded-lg bg-surface-card border border-border-subtle px-2.5 py-2 font-mono text-[11px] text-text-secondary break-all">
              {backup.checksum || "No checksum recorded"}
            </div>
          </div>
      </div>
    </Modal>
  );
}
