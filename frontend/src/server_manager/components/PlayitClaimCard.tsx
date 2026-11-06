import { useState, useEffect, useMemo, useCallback } from "react";
import { useClipboard } from "@/hooks/useClipboard";
import { Icon } from "@/components/ui/Icon";
import { parseServerDate } from "@/server_manager/utils/format";

export interface PlayitClaimCardProps {
  /** True when the agent is already claimed and verified */
  claimed: boolean;
  /** True when a claim code exchange is currently active and awaiting user claim in playit.gg */
  claimActive: boolean;
  /** The 6-character or token claim code from backend */
  claimCode?: string | null;
  /** The full claim URL (e.g. https://playit.gg/claim/xxxx) */
  claimUrl?: string | null;
  /** Expiration timestamp ISO string */
  claimExpiresAt?: string | null;
  /** Handler to generate a new claim */
  onGenerateClaim: () => void | Promise<void>;
  /** True while the claim creation API request is in-flight */
  isGenerating?: boolean;
  /** Optional handler to reset the host agent credentials */
  onResetAgent?: () => void | Promise<void>;
  /** True while agent reset is in-flight */
  isResetting?: boolean;
  /** Optional custom title (defaults to "playit.gg Account Authorization") */
  title?: string;
  /** Optional custom description */
  description?: string;
}

export function PlayitClaimCard({
  claimed,
  claimActive,
  claimCode,
  claimUrl,
  claimExpiresAt,
  onGenerateClaim,
  isGenerating = false,
  onResetAgent,
  isResetting = false,
  title = "playit.gg Account Authorization",
  description = "A one-time claim code authorizes this host with your playit.gg account to create secure public tunnels.",
}: PlayitClaimCardProps) {
  const { copy } = useClipboard();

  const calculateRemaining = useCallback(() => {
    if (!claimExpiresAt) return 0;
    const d = parseServerDate(claimExpiresAt);
    const expiryMs = d ? d.getTime() : 0;
    return Math.max(0, Math.floor((expiryMs - Date.now()) / 1000));
  }, [claimExpiresAt]);

  const [remainingSeconds, setRemainingSeconds] = useState<number>(() => calculateRemaining());
  const [milestoneAnnounce, setMilestoneAnnounce] = useState<string>("");

  // Sync state during rendering if expiry timestamp changes (React 19 pattern)
  const [prevExpiresAt, setPrevExpiresAt] = useState<string | null | undefined>(claimExpiresAt);
  if (prevExpiresAt !== claimExpiresAt) {
    setPrevExpiresAt(claimExpiresAt);
    setRemainingSeconds(calculateRemaining());
  }

  useEffect(() => {
    if (!claimActive || !claimExpiresAt) return;

    const interval = setInterval(() => {
      const rem = calculateRemaining();
      setRemainingSeconds(rem);

      // Milestone announcements for screen readers (F-74-06)
      if (rem === 60) {
        setMilestoneAnnounce("Claim code expires in 60 seconds.");
      } else if (rem === 30) {
        setMilestoneAnnounce("Claim code expires in 30 seconds.");
      } else if (rem === 10) {
        setMilestoneAnnounce("Claim code expires in 10 seconds.");
      } else if (rem === 0) {
        setMilestoneAnnounce("Claim code has expired. Please generate a new claim.");
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [claimActive, claimExpiresAt, calculateRemaining]);

  const isExpired = claimActive && remainingSeconds <= 0;

  const formattedTime = useMemo(() => {
    const minutes = Math.floor(remainingSeconds / 60);
    const seconds = remainingSeconds % 60;
    return `${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }, [remainingSeconds]);

  // If already claimed
  if (claimed && !claimActive) {
    return (
      <div className="rounded-xl border border-status-success-border bg-status-success-bg p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-status-success font-semibold text-sm">
            <Icon name="check" size={18} />
            <span>playit.gg Host Agent Claimed</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onGenerateClaim}
              disabled={isGenerating || isResetting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border-default bg-surface-card hover:bg-surface-hover text-text-secondary text-xs font-medium transition-colors shadow-xs disabled:opacity-50"
              title="Restart claiming to connect a different account or re-authorize"
            >
              <Icon name="restart" size={13} className={isGenerating ? "animate-spin" : ""} />
              <span>{isGenerating ? "Restarting..." : "Restart Claiming"}</span>
            </button>
            {onResetAgent && (
              <button
                type="button"
                onClick={onResetAgent}
                disabled={isResetting || isGenerating}
                className="text-xs text-status-danger hover:opacity-90 font-medium disabled:opacity-50 px-2 py-1"
              >
                {isResetting ? "Resetting..." : "Reset Agent"}
              </button>
            )}
          </div>
        </div>
        <p className="text-xs text-text-secondary">
          This host is authorized and connected to your playit.gg account. Tunnels will automatically be established.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border-default bg-surface-card p-5 space-y-4">
      {/* Screen Reader Milestone Announcer (F-74-06) */}
      <div aria-live="polite" className="sr-only">
        {milestoneAnnounce}
      </div>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h4 className="text-sm font-semibold text-text-primary">{title}</h4>
          <p className="text-xs text-text-muted mt-1">{description}</p>
        </div>
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-status-warning-bg text-status-warning border border-status-warning-border shrink-0">
          Authorization Required
        </span>
      </div>

      {!claimActive ? (
        <div className="pt-2">
          <button
            type="button"
            onClick={onGenerateClaim}
            disabled={isGenerating}
            className="inline-flex items-center justify-center px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
          >
            {isGenerating ? "Generating Claim..." : "Authorize with playit.gg"}
          </button>
        </div>
      ) : isExpired ? (
        /* Expired State - Explicit user regeneration required (F-74-09) */
        <div className="rounded-lg border border-status-danger-border bg-status-danger-bg p-4 space-y-3">
          <div className="flex items-center gap-2 text-xs font-medium text-status-danger">
            <Icon name="alert" size={16} />
            <span>Claim code expired. Please generate a new claim to continue.</span>
          </div>
          <button
            type="button"
            onClick={onGenerateClaim}
            disabled={isGenerating}
            className="inline-flex items-center justify-center px-3 py-1.5 rounded-lg bg-status-danger hover:opacity-90 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
          >
            {isGenerating ? "Generating..." : "Generate New Claim"}
          </button>
        </div>
      ) : (
        /* Active Claim State */
        <div className="space-y-4 pt-1">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-lg bg-surface-elevated border border-border-default shadow-xs">
            <div>
              <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
                Claim Code
              </span>
              <div className="flex items-center gap-2 mt-0.5">
                <code
                  className="font-mono text-base font-bold text-accent-primary tracking-wider select-all"
                  aria-label={`Claim code: ${claimCode ?? "none"}`}
                >
                  {claimCode || "------"}
                </code>
                {claimCode && (
                  <button
                    type="button"
                    onClick={() => copy(claimCode, "Claim code copied to clipboard")}
                    aria-label="Copy claim code to clipboard"
                    className="p-1 text-text-muted hover:text-text-primary rounded hover:bg-surface-hover transition-colors"
                    title="Copy code"
                  >
                    <Icon name="copy" size={14} />
                  </button>
                )}
              </div>
            </div>

            {/* Visual countdown timer */}
            <div className="text-right">
              <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
                Time Remaining
              </span>
              <div
                role="timer"
                aria-live="off"
                className="font-mono text-sm font-semibold text-text-secondary mt-0.5"
              >
                {formattedTime}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {claimUrl && (
              <a
                href={claimUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-xs font-medium transition-colors shadow-xs"
              >
                <span>Open playit.gg Authorization Page</span>
                <Icon name="external" size={14} />
              </a>
            )}
            <button
              type="button"
              onClick={onGenerateClaim}
              disabled={isGenerating}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border-default bg-surface-card hover:bg-surface-hover text-text-secondary text-xs font-medium transition-colors shadow-xs disabled:opacity-50"
              title="Generate a new claim code and restart authorization"
            >
              <Icon name="restart" size={13} className={isGenerating ? "animate-spin" : ""} />
              <span>{isGenerating ? "Restarting..." : "Restart Claiming"}</span>
            </button>
            <a
              href="https://playit.gg/manage"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary underline underline-offset-2"
            >
              <span>Open playit.gg Dashboard</span>
              <Icon name="external" size={12} />
            </a>
          </div>

          <p className="text-[11px] text-text-muted italic">
            Once confirmed in playit.gg, this panel will automatically detect the authorization and connect.
          </p>
        </div>
      )}
    </div>
  );
}
