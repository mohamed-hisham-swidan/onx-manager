import { Icon } from "@/components/ui/Icon";
import type {
  GitHubBranchSyncState,
  GitHubBranchSyncStatus,
  GitHubConnectionStatusResponse,
} from "@/server_manager/types";

export interface GitHubSyncAlertState {
  kind: "auth_failed" | "non_fast_forward_main" | "push_rejected" | "generic";
  code: string | null;
  message: string;
  localSha?: string | null;
  remoteSha?: string | null;
  branch?: string | null;
  reason?: string | null;
  forbiddenPaths?: string[];
}

export interface GitHubSyncPanelProps {
  status: GitHubConnectionStatusResponse | null;
  selectedBranch: string;
  isFetching: boolean;
  isPushing: boolean;
  syncAlert: GitHubSyncAlertState | null;
  onDismissSyncAlert: () => void;
  onFetchNow: () => void;
  onPushBranch: () => void;
  onOpenConnectModal: () => void;
  onOpenRotateModal: () => void;
  onOpenDisconnectModal: () => void;
  onOpenDeliveriesModal: () => void;
}

const PANEL_CLASS =
  "rounded-xl border border-border-default bg-surface-card p-3.5 space-y-3 shadow-2xs";
const BADGE_CLASS =
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold";
const SECONDARY_BUTTON_CLASS =
  "inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY_BUTTON_CLASS =
  "inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const DANGER_BUTTON_CLASS =
  "inline-flex items-center gap-1.5 rounded-lg border border-status-danger-border bg-status-danger-bg px-3 py-1.5 text-xs font-medium text-status-danger hover:bg-status-danger/10 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";

function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 8) : "—";
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function syncStatusBadge(status: string): { label: string; className: string } {
  if (status === "synced") {
    return {
      label: "Synced",
      className: "border-status-success-border bg-status-success-bg text-status-success",
    };
  }
  if (status === "idle") {
    return {
      label: "Connected",
      className: "border-status-info-border bg-status-info-bg text-status-info",
    };
  }
  if (status === "ahead") {
    return {
      label: "Ahead",
      className: "border-status-info-border bg-status-info-bg text-status-info",
    };
  }
  if (status === "behind" || status === "diverged") {
    return {
      label: status === "behind" ? "Behind" : "Diverged",
      className: "border-status-warning-border bg-status-warning-bg text-status-warning",
    };
  }
  if (status === "conflict") {
    return {
      label: "Conflict",
      className: "border-status-danger-border bg-status-danger-bg text-status-danger",
    };
  }
  if (status === "auth_failed") {
    return {
      label: "Auth Required",
      className: "border-status-danger-border bg-status-danger-bg text-status-danger",
    };
  }
  if (status === "error") {
    return {
      label: "Sync Error",
      className: "border-status-danger-border bg-status-danger-bg text-status-danger",
    };
  }
  return {
    label: "Not Connected",
    className: "border-border-default bg-surface-elevated text-text-muted",
  };
}

function branchStatusClasses(status: GitHubBranchSyncStatus): string {
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

function selectedBranchStatusLabel(state: GitHubBranchSyncState | null): string {
  if (!state) return "Not yet fetched";
  if (state.status === "synced") return "Synced";
  if (state.status === "ahead") return `${state.ahead_count} ahead`;
  if (state.status === "behind") return `${state.behind_count} behind`;
  if (state.status === "diverged") {
    return `Diverged (+${state.ahead_count} / -${state.behind_count})`;
  }
  if (state.status === "local_only") return "Local only (not on remote)";
  if (state.status === "remote_only") return "Remote only";
  return "Not yet fetched";
}

function branchOverviewLabel(state: GitHubBranchSyncState): string {
  if (state.status === "ahead") return `ahead (+${state.ahead_count})`;
  if (state.status === "behind") return `behind (-${state.behind_count})`;
  if (state.status === "diverged") {
    return `diverged (+${state.ahead_count} / -${state.behind_count})`;
  }
  if (state.status === "local_only") return "local only";
  if (state.status === "remote_only") return "remote only";
  return state.status;
}

function authMethodLabel(status: GitHubConnectionStatusResponse): string {
  const base =
    status.auth_method === "ssh_deploy_key"
      ? "SSH Deploy Key"
      : status.auth_method === "pat"
        ? "PAT"
        : "Credential";
  const hint = status.credential_hint?.trim();
  return hint ? `${base} (${hint})` : base;
}

export function GitHubSyncPanel({
  status,
  selectedBranch,
  isFetching,
  isPushing,
  syncAlert,
  onDismissSyncAlert,
  onFetchNow,
  onPushBranch,
  onOpenConnectModal,
  onOpenRotateModal,
  onOpenDisconnectModal,
  onOpenDeliveriesModal,
}: GitHubSyncPanelProps) {
  if (!status || !status.connected) {
    return (
      <section
        data-testid="github-sync-panel"
        aria-label="GitHub Repository Sync"
        className={PANEL_CLASS}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Icon
              name="version-branch"
              size={16}
              className="text-accent-primary"
            />
            <span className="text-xs font-semibold text-text-secondary">
              GitHub Sync
            </span>
            <span
              data-testid="github-sync-status-badge"
              className={`${BADGE_CLASS} border-border-default bg-surface-elevated text-text-muted`}
            >
              Not Connected
            </span>
          </div>
          <button
            type="button"
            onClick={onOpenConnectModal}
            className={PRIMARY_BUTTON_CLASS}
          >
            <Icon name="plus" size={13} />
            Connect GitHub
          </button>
        </div>
        <p className="text-xs text-text-muted">
          Connect a private GitHub repository using a fine-grained PAT or
          per-server Ed25519 deploy key for fetch-first 1:1 branch sync.
        </p>
      </section>
    );
  }

  const branches = Array.isArray(status.branches) ? status.branches : [];
  const selectedBranchState =
    branches.find((branch) => branch.branch === selectedBranch) ?? null;
  const mainBranchState =
    branches.find((branch) => branch.branch === "main") ?? null;
  const badge = syncStatusBadge(status.sync_status);

  const showReauthBanner =
    status.needs_reauth ||
    status.sync_status === "auth_failed" ||
    syncAlert?.kind === "auth_failed";
  const showNonFastForwardBanner =
    syncAlert?.kind === "non_fast_forward_main" ||
    status.last_error_code === "GITHUB_NON_FAST_FORWARD_MAIN" ||
    status.sync_status === "conflict";
  const showPushRejectedBanner = syncAlert?.kind === "push_rejected";
  const showGenericErrorBanner =
    syncAlert?.kind === "generic" ||
    (Boolean(status.last_error_message) &&
      !showReauthBanner &&
      !showNonFastForwardBanner &&
      !showPushRejectedBanner);

  const reauthMessage =
    syncAlert?.kind === "auth_failed"
      ? syncAlert.message
      : status.last_error_message;
  const localSha = syncAlert?.localSha ?? mainBranchState?.local_sha ?? null;
  const remoteSha =
    syncAlert?.remoteSha ?? mainBranchState?.remote_sha ?? null;
  const genericMessage =
    syncAlert?.kind === "generic"
      ? syncAlert.message
      : status.last_error_message ?? "GitHub sync failed.";
  const pushDisabled =
    isFetching ||
    isPushing ||
    !selectedBranch ||
    Boolean(status.needs_reauth);

  return (
    <section
      data-testid="github-sync-panel"
      aria-label="GitHub Repository Sync"
      className={PANEL_CLASS}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Icon
            name="version-branch"
            size={16}
            className="text-accent-primary"
          />
          <span className="text-xs font-semibold text-text-secondary">
            GitHub Sync
          </span>
          <span
            data-testid="github-sync-status-badge"
            className={`${BADGE_CLASS} ${badge.className}`}
          >
            {badge.label}
          </span>
          {status.remote_url && (
            <span
              title={status.remote_url}
              className="max-w-[18rem] truncate rounded-md border border-border-default bg-surface-page px-2 py-0.5 font-mono text-[11px] text-text-secondary"
            >
              {status.remote_url}
            </span>
          )}
          <span
            className={`${BADGE_CLASS} border-border-default bg-surface-elevated text-text-secondary`}
          >
            <Icon name="lock" size={11} />
            {authMethodLabel(status)}
          </span>
          {status.webhook_enabled ? (
            <span
              className={`${BADGE_CLASS} border-status-success-border bg-status-success-bg text-status-success`}
            >
              <Icon name="bell" size={11} />
              Webhook Active
            </span>
          ) : (
            <span
              className={`${BADGE_CLASS} border-border-default bg-surface-elevated text-text-muted`}
            >
              Polling Only
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onFetchNow}
            disabled={isFetching || isPushing}
            className={SECONDARY_BUTTON_CLASS}
          >
            <Icon name="download" size={13} />
            {isFetching ? "Fetching..." : "Fetch Now"}
          </button>
          <button
            type="button"
            onClick={onPushBranch}
            disabled={pushDisabled}
            title={
              status.needs_reauth
                ? "Rotate or reconnect your GitHub credential before pushing"
                : `Push branch '${selectedBranch}' to GitHub`
            }
            className={SECONDARY_BUTTON_CLASS}
          >
            <Icon name="upload" size={13} />
            {isPushing ? "Pushing..." : `Push ${selectedBranch}`}
          </button>
          <button
            type="button"
            onClick={onOpenDeliveriesModal}
            className={SECONDARY_BUTTON_CLASS}
          >
            <Icon name="bell" size={13} />
            Webhook Deliveries
          </button>
          <button
            type="button"
            onClick={onOpenRotateModal}
            className={SECONDARY_BUTTON_CLASS}
          >
            <Icon name="restart" size={13} />
            Rotate Credentials
          </button>
          <button
            type="button"
            onClick={onOpenDisconnectModal}
            className={DANGER_BUTTON_CLASS}
          >
            <Icon name="x" size={13} />
            Disconnect
          </button>
        </div>
      </div>

      {showReauthBanner && (
        <div
          role="alert"
          data-testid="github-reauth-banner"
          className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
        >
          <div className="flex items-start gap-2">
            <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="font-semibold">
                GitHub authentication failed — credential revoked, expired, or
                missing write permissions. Rotate or reconnect your credential
                to resume sync.
              </p>
              {reauthMessage && (
                <p className="text-[11px] text-status-danger/90">
                  {reauthMessage}
                </p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onOpenRotateModal}
            className="inline-flex items-center gap-1 rounded-lg border border-status-danger-border bg-surface-card px-2.5 py-1 text-[11px] font-semibold text-status-danger hover:bg-status-danger/10 transition-colors cursor-pointer"
          >
            <Icon name="restart" size={11} />
            Reconnect / Rotate Credentials
          </button>
        </div>
      )}

      {showNonFastForwardBanner && (
        <div
          role="alert"
          data-testid="github-nff-conflict-alert"
          className="flex items-start justify-between gap-3 rounded-lg border border-status-warning-border bg-status-warning-bg p-3 text-xs text-status-warning"
        >
          <div className="flex items-start gap-2">
            <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="font-semibold">
                Non-fast-forward update on &apos;main&apos; rejected. Force-push
                is disabled to protect server history.
              </p>
              {(localSha || remoteSha) && (
                <p className="font-mono text-[11px]">
                  Local: {shortSha(localSha)} · Remote: {shortSha(remoteSha)}
                </p>
              )}
            </div>
          </div>
          {syncAlert?.kind === "non_fast_forward_main" && (
            <button
              type="button"
              onClick={onDismissSyncAlert}
              aria-label="Dismiss sync alert"
              className="rounded p-0.5 hover:bg-status-warning/10 transition-colors cursor-pointer"
            >
              <Icon name="x" size={14} />
            </button>
          )}
        </div>
      )}

      {showPushRejectedBanner && (
        <div
          role="alert"
          data-testid="github-push-rejected-alert"
          className="flex items-start justify-between gap-3 rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
        >
          <div className="flex items-start gap-2">
            <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
            <div className="space-y-1">
              {syncAlert?.reason === "plain_jar_blob_forbidden" ? (
                <>
                  <p className="font-semibold">
                    Push rejected: plain .jar binaries cannot be pushed to
                    GitHub.
                  </p>
                  {syncAlert.forbiddenPaths &&
                    syncAlert.forbiddenPaths.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {syncAlert.forbiddenPaths.map((path) => (
                          <span
                            key={path}
                            className="rounded border border-status-danger-border bg-surface-card px-1.5 py-0.5 font-mono text-[11px]"
                          >
                            {path}
                          </span>
                        ))}
                      </div>
                    )}
                </>
              ) : (
                <p className="font-semibold">
                  {syncAlert?.message ?? "GitHub rejected the push."}
                </p>
              )}
              {syncAlert?.reason &&
                syncAlert.reason !== "plain_jar_blob_forbidden" && (
                  <p className="font-mono text-[11px]">{syncAlert.reason}</p>
                )}
              {syncAlert?.branch && (
                <p className="font-mono text-[11px]">
                  Branch: {syncAlert.branch}
                </p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onDismissSyncAlert}
            aria-label="Dismiss sync alert"
            className="rounded p-0.5 hover:bg-status-danger/10 transition-colors cursor-pointer"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      )}

      {showGenericErrorBanner && (
        <div
          role="alert"
          data-testid="github-generic-error-alert"
          className="flex items-start justify-between gap-3 rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
        >
          <div className="flex items-start gap-2">
            <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="font-semibold">{genericMessage}</p>
              {syncAlert?.code && (
                <p className="font-mono text-[11px]">{syncAlert.code}</p>
              )}
            </div>
          </div>
          {syncAlert?.kind === "generic" && (
            <button
              type="button"
              onClick={onDismissSyncAlert}
              aria-label="Dismiss sync alert"
              className="rounded p-0.5 hover:bg-status-danger/10 transition-colors cursor-pointer"
            >
              <Icon name="x" size={14} />
            </button>
          )}
        </div>
      )}

      <div
        data-testid="github-branch-sync-strip"
        className="flex flex-wrap items-center gap-2 rounded-lg border border-border-subtle bg-surface-page p-2.5 text-[11px]"
      >
        <Icon name="version-branch" size={13} className="text-text-muted" />
        <span className="font-semibold text-text-secondary">
          Selected Branch (1:1 Sync):
        </span>
        <span className="rounded border border-border-default bg-surface-card px-1.5 py-0.5 font-mono font-semibold text-text-primary">
          {selectedBranch || "—"}
        </span>
        <span
          data-testid="selected-branch-sync-status"
          className={`${BADGE_CLASS} ${branchStatusClasses(
            selectedBranchState?.status ?? "local_only",
          )}`}
        >
          {selectedBranchStatusLabel(selectedBranchState)}
        </span>
        {selectedBranchState?.local_sha && (
          <span className="font-mono text-text-secondary">
            Local {shortSha(selectedBranchState.local_sha)}
          </span>
        )}
        {selectedBranchState?.remote_sha && (
          <span className="font-mono text-text-secondary">
            Remote {shortSha(selectedBranchState.remote_sha)}
          </span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-3 text-text-muted">
          <span className="inline-flex items-center gap-1">
            <Icon name="clock" size={11} />
            Last fetch: {formatTimestamp(status.last_fetch_at)}
          </span>
          <span className="inline-flex items-center gap-1">
            <Icon name="clock" size={11} />
            Last push: {formatTimestamp(status.last_push_at)}
          </span>
        </div>
      </div>

      {branches.length > 0 && (
        <div
          data-testid="github-branch-sync-overview"
          className="flex flex-wrap items-center gap-1.5"
        >
          {branches.map((branch) => (
            <span
              key={branch.branch}
              className={`${BADGE_CLASS} ${branchStatusClasses(branch.status)}`}
            >
              <span className="font-mono">{branch.branch}</span>:{" "}
              {branchOverviewLabel(branch)}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
