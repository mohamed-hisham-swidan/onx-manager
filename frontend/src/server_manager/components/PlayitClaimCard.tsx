import { useState, useEffect, useMemo, useCallback } from "react";
import { useClipboard } from "@/hooks/useClipboard";
import { Icon } from "@/components/ui/Icon";

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
    const expiryMs = new Date(claimExpiresAt).getTime();
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
      <div className="rounded-xl border border-green-200 bg-green-50/50 dark:border-green-800/40 dark:bg-green-900/10 p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-green-800 dark:text-green-300 font-semibold text-sm">
            <Icon name="check" size={18} />
            <span>playit.gg Host Agent Claimed</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onGenerateClaim}
              disabled={isGenerating || isResetting}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 text-xs font-medium transition-colors shadow-sm disabled:opacity-50"
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
                className="text-xs text-red-600 hover:text-red-700 dark:text-red-400 font-medium disabled:opacity-50 px-2 py-1"
              >
                {isResetting ? "Resetting..." : "Reset Agent"}
              </button>
            )}
          </div>
        </div>
        <p className="text-xs text-gray-600 dark:text-gray-300">
          This host is authorized and connected to your playit.gg account. Tunnels will automatically be established.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/40 dark:border-blue-900/40 dark:bg-blue-900/10 p-5 space-y-4">
      {/* Screen Reader Milestone Announcer (F-74-06) */}
      <div aria-live="polite" className="sr-only">
        {milestoneAnnounce}
      </div>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</h4>
          <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">{description}</p>
        </div>
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300 border border-yellow-200 dark:border-yellow-800 shrink-0">
          Authorization Required
        </span>
      </div>

      {!claimActive ? (
        <div className="pt-2">
          <button
            type="button"
            onClick={onGenerateClaim}
            disabled={isGenerating}
            className="inline-flex items-center justify-center px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
          >
            {isGenerating ? "Generating Claim..." : "Authorize with playit.gg"}
          </button>
        </div>
      ) : isExpired ? (
        /* Expired State - Explicit user regeneration required (F-74-09) */
        <div className="rounded-lg border border-red-200 bg-red-50 dark:border-red-900/40 dark:bg-red-900/20 p-4 space-y-3">
          <div className="flex items-center gap-2 text-xs font-medium text-red-700 dark:text-red-300">
            <Icon name="alert" size={16} />
            <span>Claim code expired. Please generate a new claim to continue.</span>
          </div>
          <button
            type="button"
            onClick={onGenerateClaim}
            disabled={isGenerating}
            className="inline-flex items-center justify-center px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
          >
            {isGenerating ? "Generating..." : "Generate New Claim"}
          </button>
        </div>
      ) : (
        /* Active Claim State */
        <div className="space-y-4 pt-1">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-lg bg-white dark:bg-gray-800 border border-blue-200 dark:border-blue-800/60 shadow-sm">
            <div>
              <span className="text-[11px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                Claim Code
              </span>
              <div className="flex items-center gap-2 mt-0.5">
                <code
                  className="font-mono text-base font-bold text-blue-700 dark:text-blue-300 tracking-wider select-all"
                  aria-label={`Claim code: ${claimCode ?? "none"}`}
                >
                  {claimCode || "------"}
                </code>
                {claimCode && (
                  <button
                    type="button"
                    onClick={() => copy(claimCode, "Claim code copied to clipboard")}
                    aria-label="Copy claim code to clipboard"
                    className="p-1 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 rounded hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                    title="Copy code"
                  >
                    <Icon name="copy" size={14} />
                  </button>
                )}
              </div>
            </div>

            {/* Visual countdown timer */}
            <div className="text-right">
              <span className="text-[11px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                Time Remaining
              </span>
              <div
                role="timer"
                aria-live="off"
                className="font-mono text-sm font-semibold text-gray-700 dark:text-gray-300 mt-0.5"
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
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium transition-colors shadow-sm"
              >
                <span>Open playit.gg Authorization Page</span>
                <Icon name="external" size={14} />
              </a>
            )}
            <button
              type="button"
              onClick={onGenerateClaim}
              disabled={isGenerating}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 text-xs font-medium transition-colors shadow-sm disabled:opacity-50"
              title="Generate a new claim code and restart authorization"
            >
              <Icon name="restart" size={13} className={isGenerating ? "animate-spin" : ""} />
              <span>{isGenerating ? "Restarting..." : "Restart Claiming"}</span>
            </button>
            <a
              href="https://playit.gg/manage"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200 underline underline-offset-2"
            >
              <span>Open playit.gg Dashboard</span>
              <Icon name="external" size={12} />
            </a>
          </div>

          <p className="text-[11px] text-gray-500 dark:text-gray-400 italic">
            Once confirmed in playit.gg, this panel will automatically detect the authorization and connect.
          </p>
        </div>
      )}
    </div>
  );
}
