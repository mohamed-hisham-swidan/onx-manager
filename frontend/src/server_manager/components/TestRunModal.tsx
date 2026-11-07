import { useState, useEffect, useMemo } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { createAuthenticatedApi } from "@/services/api";
import type { PreflightStatus, TestDefinition } from "@/server_manager/types";

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
  const [definitions, setDefinitions] = useState<TestDefinition[]>([]);
  const [selectedDefId, setSelectedDefId] = useState<string>("");
  const [botCountInput, setBotCountInput] = useState<string>("10");
  const [durationInput, setDurationInput] = useState<string>("15");
  const [placementMode, setPlacementMode] = useState<string>("sidecar");
  const [botTech, setBotTech] = useState<string>("auto");

  const botCount = useMemo(() => Math.max(1, parseInt(botCountInput, 10) || 1), [botCountInput]);
  const durationMinutes = useMemo(() => Math.max(1, parseInt(durationInput, 10) || 1), [durationInput]);

  const [preflight, setPreflight] = useState<PreflightStatus | null>(null);
  const [isLoadingPreflight, setIsLoadingPreflight] = useState<boolean>(true);
  const [isLaunching, setIsLaunching] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch test definitions when modal opens
  useEffect(() => {
    if (!isOpen) return;
    let isMounted = true;
    api
      .getTestDefinitions(serverId)
      .then((defs) => {
        if (isMounted) setDefinitions(defs);
      })
      .catch(() => {});
    return () => {
      isMounted = false;
    };
  }, [isOpen, serverId, api]);

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

  const handleClose = () => {
    if (isLaunching) return;
    onClose();
  };

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
        test_definition_id: selectedDefId || undefined,
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
    <Modal
      open={isOpen}
      onClose={handleClose}
      title="Launch Isolated Bot Test"
      description={
        <span>
          Target Commit: <span className="font-mono">{commitId.slice(0, 8)}</span>
        </span>
      }
      size="xl"
      closeOnBackdrop={!isLaunching}
      closeOnEscape={!isLaunching}
    >
      <div className="space-y-6 text-text-primary">
        {error && (
          <div role="alert" className="rounded-lg bg-status-danger-bg border border-status-danger-border p-3 text-sm text-status-danger">
            {error}
          </div>
        )}

        {/* Profile Selector */}
        {definitions.length > 0 && (
          <div>
            <label
              htmlFor="test-profile-select"
              className="block text-xs font-medium text-text-secondary mb-1"
            >
              Test Profile (Optional)
            </label>
            <select
              id="test-profile-select"
              value={selectedDefId}
              onChange={(e) => {
                const id = e.target.value;
                setSelectedDefId(id);
                const def = definitions.find((d) => d.id === id);
                if (def) {
                  setBotCountInput(String(def.bot_count));
                  setDurationInput(String(Math.max(1, Math.round(def.duration_seconds / 60))));
                  if (def.placement_mode) setPlacementMode(def.placement_mode);
                  if (def.bot_technology) setBotTech(def.bot_technology);
                }
              }}
              className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:border-border-focus"
            >
              <option value="">Custom Settings (Manual)</option>
              {definitions.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.bot_count} bots, {Math.round(d.duration_seconds / 60)}m)
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Preflight Status Card */}
        <div className="rounded-lg border border-border-default bg-surface-card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
              Host Preflight Verification
            </span>
            {isLoadingPreflight ? (
              <span className="text-xs text-text-muted flex items-center gap-1">
                <Icon name="clock" size={12} /> Checking headroom...
              </span>
            ) : preflight?.passed ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-status-success-bg px-2 py-0.5 text-xs font-medium text-status-success border border-status-success-border">
                <Icon name="check" size={12} /> Preflight Passed
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-status-danger-bg px-2 py-0.5 text-xs font-medium text-status-danger border border-status-danger-border">
                <Icon name="alert" size={12} /> Insufficient Resources
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded bg-surface-muted p-2 border border-border-subtle">
              <span className="text-text-muted block mb-0.5">COW (Reflink)</span>
              <span className="font-medium text-text-primary">
                {preflight ? (preflight.reflink_supported ? "Supported (Btrfs/ZFS)" : "Not Supported") : "..."}
              </span>
            </div>
            <div className="rounded bg-surface-muted p-2 border border-border-subtle">
              <span className="text-text-muted block mb-0.5">Headroom (RAM / Cores)</span>
              <span className="font-medium text-text-primary">
                {preflight
                  ? `${preflight.available_ram_mb} MB (${preflight.min_required_ram_mb} MB req) / ${preflight.available_cores} cores`
                  : "..."}
              </span>
            </div>
          </div>

          {preflight && !preflight.passed && preflight.error && (
            <p className="text-xs text-status-danger font-medium">
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
                className="block text-xs font-medium text-text-secondary mb-1"
              >
                Verification Bot Count
              </label>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  aria-label="Decrease bot count"
                  onClick={() => {
                    const cur = parseInt(botCountInput, 10) || 1;
                    const next = Math.max(1, cur - 1);
                    setBotCountInput(String(next));
                  }}
                  className="h-9 w-9 rounded-lg border border-border-default bg-surface-muted flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-hover text-sm font-semibold transition-colors shrink-0 cursor-pointer"
                >
                  -
                </button>
                <input
                  id="bot-count-input"
                  type="number"
                  min={1}
                  value={botCountInput}
                  onChange={(e) => setBotCountInput(e.target.value)}
                  onBlur={() => {
                    const parsed = parseInt(botCountInput, 10);
                    if (isNaN(parsed) || parsed < 1) {
                      setBotCountInput("1");
                    } else {
                      setBotCountInput(String(parsed));
                    }
                  }}
                  className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-none text-center"
                />
                <button
                  type="button"
                  aria-label="Increase bot count"
                  onClick={() => {
                    const cur = parseInt(botCountInput, 10) || 1;
                    setBotCountInput(String(cur + 1));
                  }}
                  className="h-9 w-9 rounded-lg border border-border-default bg-surface-muted flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-hover text-sm font-semibold transition-colors shrink-0 cursor-pointer"
                >
                  +
                </button>
              </div>
              <span className="text-[10px] text-text-muted mt-1 block">
                Unrestricted: dynamically validated against system headroom.
              </span>
            </div>

            <div>
              <label
                htmlFor="duration-input"
                className="block text-xs font-medium text-text-secondary mb-1"
              >
                Test Duration (Minutes)
              </label>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  aria-label="Decrease duration"
                  onClick={() => {
                    const cur = parseInt(durationInput, 10) || 1;
                    const next = Math.max(1, cur - 1);
                    setDurationInput(String(next));
                  }}
                  className="h-9 w-9 rounded-lg border border-border-default bg-surface-muted flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-hover text-sm font-semibold transition-colors shrink-0 cursor-pointer"
                >
                  -
                </button>
                <input
                  id="duration-input"
                  type="number"
                  min={1}
                  value={durationInput}
                  onChange={(e) => setDurationInput(e.target.value)}
                  onBlur={() => {
                    const parsed = parseInt(durationInput, 10);
                    if (isNaN(parsed) || parsed < 1) {
                      setDurationInput("1");
                    } else {
                      setDurationInput(String(parsed));
                    }
                  }}
                  className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-none text-center"
                />
                <button
                  type="button"
                  aria-label="Increase duration"
                  onClick={() => {
                    const cur = parseInt(durationInput, 10) || 1;
                    setDurationInput(String(cur + 1));
                  }}
                  className="h-9 w-9 rounded-lg border border-border-default bg-surface-muted flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-hover text-sm font-semibold transition-colors shrink-0 cursor-pointer"
                >
                  +
                </button>
              </div>
              <span className="text-[10px] text-text-muted mt-1 block">
                Active connection & activity period.
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="bot-tech-select"
                className="block text-xs font-medium text-text-secondary mb-1"
              >
                Bot Technology
              </label>
              <select
                id="bot-tech-select"
                value={botTech}
                onChange={(e) => setBotTech(e.target.value)}
                className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-none"
              >
                <option value="auto">Auto (Server-type aware)</option>
                <option value="mineflayer">Mineflayer (External Protocol)</option>
                <option value="fakeplayer_next">FakePlayerNext (Paper In-Process)</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="placement-mode-select"
                className="block text-xs font-medium text-text-secondary mb-1"
              >
                Placement Mode
              </label>
              <select
                id="placement-mode-select"
                value={placementMode}
                onChange={(e) => setPlacementMode(e.target.value)}
                className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-none"
              >
                <option value="sidecar">Sidecar (Container Isolation)</option>
                <option value="in_container">In Container</option>
              </select>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-end gap-3 border-t border-border-default pt-4">
          <button
            type="button"
            onClick={handleClose}
            disabled={isLaunching}
            className="rounded-lg border border-border-default bg-surface-muted px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleLaunch}
            disabled={isLaunching || (preflight !== null && !preflight.passed)}
            className="inline-flex items-center gap-2 rounded-lg bg-accent-primary hover:bg-accent-hover px-4 py-2 text-sm font-semibold text-accent-contrast-text disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-colors"
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
    </Modal>
  );
}
