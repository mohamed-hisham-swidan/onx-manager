import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { parseServerDate } from "@/server_manager/utils/format";

export interface StartingMonitorBannerProps {
  /** The server or test run name */
  targetName?: string;
  /** Timestamp when starting began (epoch ms, ISO string, or number) */
  startedAt?: number | string | null;
  /** Timeout in seconds (default 120) */
  timeoutSeconds?: number;
  /** Whether this banner is for an isolated test run */
  isTestRun?: boolean;
  /** Callback for manual check-now */
  onCheckNow?: () => void | Promise<void>;
  /** Callback when dismissed */
  onDismiss?: () => void;
  className?: string;
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function StartingMonitorBanner({
  targetName,
  startedAt,
  timeoutSeconds = 120,
  isTestRun = false,
  onCheckNow,
  onDismiss,
  className = "",
}: StartingMonitorBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  // Determine initial start epoch in ms
  const [mountEpoch] = useState(() => Date.now());
  const startEpoch = (() => {
    if (!startedAt) return mountEpoch;
    const d = parseServerDate(startedAt);
    return d ? d.getTime() : mountEpoch;
  })();

  useEffect(() => {
    const setTimer = typeof window !== "undefined" ? window.setInterval : setInterval;
    const clearTimer = typeof window !== "undefined" ? window.clearInterval : clearInterval;
    const timer = setTimer(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearTimer(timer);
  }, []);

  if (dismissed) {
    return null;
  }

  const elapsedSeconds = Math.max(0, Math.floor((now - startEpoch) / 1000));
  const isOverdue = elapsedSeconds >= timeoutSeconds;
  const progressPct = Math.min(100, Math.round((elapsedSeconds / timeoutSeconds) * 100));

  const handleDismiss = () => {
    setDismissed(true);
    onDismiss?.();
  };

  const handleCheckNow = async () => {
    if (isChecking) return;
    setIsChecking(true);
    try {
      await onCheckNow?.();
    } finally {
      setIsChecking(false);
    }
  };

  return (
    <div
      data-testid="starting-monitor-banner"
      data-status={isOverdue ? "warning" : "starting"}
      className={`rounded-xl border p-4 transition-all shadow-sm ${
        isOverdue
          ? "border-status-warning-border bg-status-warning-bg text-text-primary"
          : "border-status-info-border bg-status-info-bg text-text-primary"
      } ${className}`}
      role="region"
      aria-label="Starting monitor"
      aria-live="polite"
    >
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className={`p-2 rounded-lg shrink-0 ${
              isOverdue
                ? "bg-status-warning-bg text-status-warning"
                : "bg-status-info-bg text-status-info animate-pulse"
            }`}
          >
            <Icon name={isOverdue ? "alert" : "activity"} size={18} />
          </div>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-sm">
                {targetName ? `${targetName}: ` : ""}
                {isTestRun ? "Test Boot Verification" : "Server Boot in Progress"}
              </span>
              <span
                data-testid="starting-monitor-timer"
                className={`font-mono text-xs px-2 py-0.5 rounded-full font-medium ${
                  isOverdue
                    ? "bg-status-warning-bg border border-status-warning-border text-status-warning"
                    : "bg-status-info-bg border border-status-info-border text-status-info"
                }`}
              >
                {formatDuration(elapsedSeconds)} / {formatDuration(timeoutSeconds)}
              </span>
            </div>

            <p className="text-xs mt-0.5 text-text-secondary">
              {isOverdue
                ? "Startup is taking longer than configured timeout. World generation or mod downloads may still be progressing."
                : isTestRun
                ? "Waiting for isolated container log-marker confirmation before executing bot drivers..."
                : "Gating active post-boot interactions until log-marker boot confirmation is received..."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 self-end sm:self-center shrink-0">
          {onCheckNow && (
            <button
              type="button"
              data-testid="starting-monitor-check-now"
              onClick={handleCheckNow}
              disabled={isChecking}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                isOverdue
                  ? "border-status-warning-border bg-surface-card hover:bg-surface-hover text-status-warning"
                  : "border-status-info-border bg-surface-card hover:bg-surface-hover text-status-info"
              }`}
            >
              <span className={isChecking ? "animate-spin" : ""}>
                <Icon name="restart" size={13} />
              </span>
              {isChecking ? "Checking..." : "Check Now"}
            </button>
          )}

          <button
            type="button"
            data-testid="starting-monitor-dismiss"
            onClick={handleDismiss}
            className="p-1 rounded-md text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
            title="Dismiss starting monitor"
            aria-label="Dismiss banner"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      </div>

      {/* Progress Track */}
      <div className="mt-3 w-full bg-surface-muted rounded-full h-1.5 overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ${
            isOverdue
              ? "bg-status-warning"
              : "bg-status-info"
          }`}
          style={{ width: `${progressPct}%` }}
        />
      </div>
    </div>
  );
}
