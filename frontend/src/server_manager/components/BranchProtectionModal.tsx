import { useState, useEffect, useMemo } from "react";
import { Modal } from "@/components/ui/Modal";
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

  const handleClose = () => {
    if (!isSaving) {
      onClose();
    }
  };

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
    <Modal
      open={isOpen}
      onClose={handleClose}
      title="Branch Protection Policy"
      description={
        <span>
          Target Branch:{" "}
          <span className="font-mono font-semibold text-indigo-600 dark:text-indigo-400">
            {branch.name}
          </span>
        </span>
      }
      size="lg"
      closeOnBackdrop={!isSaving}
      closeOnEscape={!isSaving}
      closeButtonAriaLabel="Close modal"
    >
      <div className="space-y-6">
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
                  disabled={isSaving}
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
                    disabled={isSaving}
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
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
                    disabled={isSaving}
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
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
                    disabled={isSaving}
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
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
                    disabled={isSaving}
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
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
            onClick={handleClose}
            disabled={isSaving}
            className="rounded-lg border border-gray-300 bg-white px-3.5 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 disabled:opacity-50"
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
    </Modal>
  );
}
