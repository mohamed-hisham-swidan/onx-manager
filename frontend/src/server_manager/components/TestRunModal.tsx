import { useState, useEffect, useMemo } from "react";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import type { PreflightStatus } from "@/server_manager/types";

export interface TestRunModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  commitId: string;
  onTestStarted: (testId: string) => void;
}

export function TestRunModal({
  isOpen,
  onClose,
  serverId,
  commitId,
  onTestStarted,
}: TestRunModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [botCount, setBotCount] = useState<number>(10);
  const [durationMinutes, setDurationMinutes] = useState<number>(15);
  const [placementMode, setPlacementMode] = useState<string>("sidecar");
  const [botTech, setBotTech] = useState<string>("auto");

  const [preflight, setPreflight] = useState<PreflightStatus | null>(null);
  const [isLoadingPreflight, setIsLoadingPreflight] = useState<boolean>(true);
  const [isLaunching, setIsLaunching] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Handle ESC key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isLaunching) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isLaunching, onClose]);

  // Fetch preflight whenever botCount or isOpen changes
  useEffect(() => {
    if (!isOpen) return;
    let isMounted = true;

    api
      .getPreflightStatus(serverId, botCount)
      .then((data: PreflightStatus) => {
        if (isMounted) {
          setPreflight(data);
          setIsLoadingPreflight(false);
        }
      })
      .catch((err: { message?: string }) => {
        if (isMounted) {
          setPreflight(null);
          setIsLoadingPreflight(false);
          setError(err.message || "Failed to check system preflight.");
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, serverId, botCount, api]);

  if (!isOpen) return null;

  const handleLaunch = async () => {
    setIsLaunching(true);
    setError(null);
    try {
      const res = await api.runIsolatedTest(serverId, {
        commit_id: commitId,
        bot_count: botCount,
        duration_minutes: durationMinutes,
        placement_mode: placementMode,
        bot_tech: botTech,
      });
      const testId = (res as { test_id?: string; entity_id?: string }).test_id ||
        (res as { entity_id?: string }).entity_id ||
        "";
      onTestStarted(testId);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to launch isolated test.";
      setError(msg);
    } finally {
      setIsLaunching(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="test-run-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isLaunching) onClose();
      }}
    >
      <div className="relative w-full max-w-xl rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800 p-6 space-y-6">
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400">
              <Icon name="activity" size={22} />
            </div>
            <div>
              <h2
                id="test-run-modal-title"
                className="text-lg font-semibold text-gray-900 dark:text-white"
              >
                Launch Isolated Bot Test
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Target Commit: <span className="font-mono">{commitId.slice(0, 8)}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isLaunching}
            className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-200"
            aria-label="Close modal"
          >
            <Icon name="x" size={20} />
          </button>
        </div>

        {error && (
          <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:border-rose-900 dark:text-rose-300">
            {error}
          </div>
        )}

        {/* Preflight Status Card */}
        <div className="rounded-lg border border-gray-200 dark:border-gray-700/80 bg-gray-50/50 dark:bg-gray-800/40 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Host Preflight Verification
            </span>
            {isLoadingPreflight ? (
              <span className="text-xs text-gray-400 flex items-center gap-1">
                <Icon name="clock" size={12} /> Checking headroom...
              </span>
            ) : preflight?.passed ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                <Icon name="check" size={12} /> Preflight Passed
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-800 dark:bg-rose-950/60 dark:text-rose-300">
                <Icon name="alert" size={12} /> Insufficient Resources
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded bg-white dark:bg-gray-900 p-2 border border-gray-100 dark:border-gray-800">
              <span className="text-gray-500 dark:text-gray-400 block mb-0.5">COW (Reflink)</span>
              <span className="font-medium text-gray-800 dark:text-gray-200">
                {preflight ? (preflight.reflink_supported ? "Supported (Btrfs/ZFS)" : "Not Supported") : "..."}
              </span>
            </div>
            <div className="rounded bg-white dark:bg-gray-900 p-2 border border-gray-100 dark:border-gray-800">
              <span className="text-gray-500 dark:text-gray-400 block mb-0.5">Headroom (RAM / Cores)</span>
              <span className="font-medium text-gray-800 dark:text-gray-200">
                {preflight
                  ? `${preflight.available_ram_mb} MB (${preflight.min_required_ram_mb} MB req) / ${preflight.available_cores} cores`
                  : "..."}
              </span>
            </div>
          </div>

          {preflight && !preflight.passed && preflight.error && (
            <p className="text-xs text-rose-600 dark:text-rose-400 font-medium">
              {preflight.error}
            </p>
          )}
        </div>

        {/* Configuration Inputs */}
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="bot-count-input"
                className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                Verification Bot Count
              </label>
              <input
                id="bot-count-input"
                type="number"
                min={1}
                value={botCount}
                onChange={(e) => setBotCount(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:border-indigo-500 focus:outline-none"
              />
              <span className="text-[10px] text-gray-500 dark:text-gray-400">
                Unrestricted: dynamically validated against system headroom.
              </span>
            </div>

            <div>
              <label
                htmlFor="duration-input"
                className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                Test Duration (Minutes)
              </label>
              <input
                id="duration-input"
                type="number"
                min={1}
                value={durationMinutes}
                onChange={(e) => setDurationMinutes(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:border-indigo-500 focus:outline-none"
              />
              <span className="text-[10px] text-gray-500 dark:text-gray-400">
                Active connection & activity period.
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="bot-tech-select"
                className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                Bot Technology
              </label>
              <select
                id="bot-tech-select"
                value={botTech}
                onChange={(e) => setBotTech(e.target.value)}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:border-indigo-500 focus:outline-none"
              >
                <option value="auto">Auto (Server-type aware)</option>
                <option value="mineflayer">Mineflayer (External Protocol)</option>
                <option value="fakeplayer_next">FakePlayerNext (Paper In-Process)</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="placement-mode-select"
                className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                Placement Mode
              </label>
              <select
                id="placement-mode-select"
                value={placementMode}
                onChange={(e) => setPlacementMode(e.target.value)}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-white focus:border-indigo-500 focus:outline-none"
              >
                <option value="sidecar">Sidecar (Container Isolation)</option>
                <option value="in_container">In Container</option>
              </select>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-end gap-3 border-t border-gray-100 dark:border-gray-800 pt-4">
          <button
            type="button"
            onClick={onClose}
            disabled={isLaunching}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleLaunch}
            disabled={isLaunching || (preflight !== null && !preflight.passed)}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-colors"
          >
            {isLaunching ? (
              <>
                <Icon name="clock" size={16} className="animate-spin" />
                Launching...
              </>
            ) : (
              <>
                <Icon name="play" size={16} />
                Launch Test Run
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
