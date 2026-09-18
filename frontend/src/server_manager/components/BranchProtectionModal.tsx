import { useState, useEffect, useMemo } from "react";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import type {
  BranchProtectionPolicy,
  BranchProtectionResponse,
  ServerBranch,
} from "@/server_manager/types";

export interface BranchProtectionModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  branch: ServerBranch | null;
  onProtectionUpdated: () => void;
}

const DEFAULT_POLICY: BranchProtectionPolicy = {
  require_test_pass: true,
  allow_direct_commit: false,
  allow_force_bypass: true,
  prevent_deletion: true,
};

export function BranchProtectionModal({
  isOpen,
  onClose,
  serverId,
  branch,
  onProtectionUpdated,
}: BranchProtectionModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);

  const [isProtected, setIsProtected] = useState<boolean>(false);
  const [policy, setPolicy] = useState<BranchProtectionPolicy>(DEFAULT_POLICY);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);

  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setIsLoading(true);
      setError(null);
    }
  }

  // Handle ESC key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isSaving) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isSaving, onClose]);

  // Load branch protection state
  useEffect(() => {
    if (!isOpen || !branch) return;
    let isMounted = true;

    api
      .getBranchProtection(serverId, branch.name)
      .then((res: BranchProtectionResponse) => {
        if (!isMounted) return;
        setIsProtected(res.is_protected);
        if (res.policy) {
          setPolicy({
            require_test_pass: res.policy.require_test_pass ?? true,
            allow_direct_commit: res.policy.allow_direct_commit ?? false,
            allow_force_bypass: res.policy.allow_force_bypass ?? true,
            prevent_deletion: res.policy.prevent_deletion ?? true,
          });
        } else {
          setPolicy(DEFAULT_POLICY);
        }
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        const msg = err instanceof Error ? err.message : "Failed to load branch protection.";
        setError(msg);
        setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, serverId, branch, api]);

  if (!isOpen || !branch) return null;

  const handleSavePolicy = async () => {
    setIsSaving(true);
    setError(null);
    try {
      if (isProtected) {
        await api.setBranchProtection(serverId, branch.name, { policy });
        toast("success", "Protection Updated", `Branch protection updated for '${branch.name}'`);
      } else {
        await api.removeBranchProtection(serverId, branch.name);
        toast("success", "Protection Removed", `Branch protection removed from '${branch.name}'`);
      }
      onProtectionUpdated();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to update protection policy.";
      setError(msg);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="branch-protection-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isSaving) onClose();
      }}
    >
      <div className="relative w-full max-w-lg rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800 p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <h2
                id="branch-protection-modal-title"
                className="text-lg font-semibold text-gray-900 dark:text-white"
              >
                Branch Protection Policy
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Target Branch: <span className="font-mono font-semibold text-indigo-600 dark:text-indigo-400">{branch.name}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isSaving}
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

        {isLoading ? (
          <div className="py-8 text-center text-sm text-gray-500 dark:text-gray-400">
            Loading protection configuration...
          </div>
        ) : (
          <div className="space-y-4">
            {/* Protection Master Toggle */}
            <div className="flex items-center justify-between p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-900/50">
              <div>
                <span className="text-sm font-semibold text-gray-900 dark:text-white block">
                  Enable Branch Protection
                </span>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  Enforce promotion gating and deletion invariants on this branch.
                </span>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  aria-label="Enable branch protection"
                  checked={isProtected}
                  onChange={(e) => setIsProtected(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-indigo-600"></div>
              </label>
            </div>

            {/* Granular Policies */}
            {isProtected && (
              <div className="space-y-3 pt-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Enforcement Rules
                </h3>

                {/* Require Test Pass */}
                <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-gray-100 dark:border-gray-700/60 bg-white dark:bg-gray-800">
                  <div>
                    <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 block">
                      Require Passing Test Run
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      Block commit promotion if the latest test run failed or no verified test exists.
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    aria-label="Require passing test run"
                    checked={policy.require_test_pass}
                    onChange={(e) =>
                      setPolicy((p) => ({ ...p, require_test_pass: e.target.checked }))
                    }
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>

                {/* Allow Direct Commit */}
                <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-gray-100 dark:border-gray-700/60 bg-white dark:bg-gray-800">
                  <div>
                    <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 block">
                      Allow Direct Commits
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      If disabled, direct commits and live changes are rejected without an isolated test run.
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    aria-label="Allow direct commits"
                    checked={policy.allow_direct_commit}
                    onChange={(e) =>
                      setPolicy((p) => ({ ...p, allow_direct_commit: e.target.checked }))
                    }
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>

                {/* Allow Force Bypass */}
                <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-gray-100 dark:border-gray-700/60 bg-white dark:bg-gray-800">
                  <div>
                    <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 block">
                      Allow Administrative Force Bypass
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      Allow operators with bypass permission to override protection during emergencies.
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    aria-label="Allow administrative force bypass"
                    checked={policy.allow_force_bypass}
                    onChange={(e) =>
                      setPolicy((p) => ({ ...p, allow_force_bypass: e.target.checked }))
                    }
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>

                {/* Prevent Deletion / Archival */}
                <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-gray-100 dark:border-gray-700/60 bg-white dark:bg-gray-800">
                  <div>
                    <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 block">
                      Prevent Branch Deletion & Archival
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      Disallow archiving or deleting this branch while protection remains active.
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    aria-label="Prevent branch deletion and archival"
                    checked={policy.prevent_deletion}
                    onChange={(e) =>
                      setPolicy((p) => ({ ...p, prevent_deletion: e.target.checked }))
                    }
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Footer Actions */}
        <div className="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSavePolicy}
            disabled={isLoading || isSaving}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {isSaving ? "Saving Policy..." : isProtected ? "Apply Protection" : "Disable Protection"}
          </button>
        </div>
      </div>
    </div>
  );
}
