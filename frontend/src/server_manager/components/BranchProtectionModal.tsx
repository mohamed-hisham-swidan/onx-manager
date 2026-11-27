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
  canEdit?: boolean;
  onProtectionUpdated: () => void;
}

const DEFAULT_POLICY: BranchProtectionPolicy = {
  require_test_pass: false,
  allow_direct_commit: false,
  allow_force_bypass: true,
  prevent_deletion: true,
};

export function BranchProtectionModal({
  isOpen,
  onClose,
  serverId,
  branch,
  canEdit = true,
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

  useEffect(() => {
    if (!isOpen || !branch) return;
    let isMounted = true;

    api
      .getBranchProtection(serverId, branch.name)
      .then((res: BranchProtectionResponse) => {
        if (!isMounted) return;
        const isMain = branch.name === "main";
        setIsProtected(isMain ? true : res.is_protected);
        if (res.policy) {
          setPolicy({
            require_test_pass: res.policy.require_test_pass ?? false,
            allow_direct_commit: isMain ? false : (res.policy.allow_direct_commit ?? false),
            allow_force_bypass: res.policy.allow_force_bypass ?? true,
            prevent_deletion: isMain ? true : (res.policy.prevent_deletion ?? true),
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

  const isMainBranch = branch.name === "main";

  const handleClose = () => {
    if (!isSaving) {
      onClose();
    }
  };

  const handleSavePolicy = async () => {
    if (!canEdit) return;
    setIsSaving(true);
    setError(null);
    try {
      if (isProtected || isMainBranch) {
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
          <span className="font-mono font-semibold text-accent-primary">
            {branch.name}
          </span>
        </span>
      }
      size="lg"
      closeOnBackdrop={!isSaving}
      closeOnEscape={!isSaving}
      closeButtonAriaLabel="Close modal"
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={handleClose}
            disabled={isSaving}
            className="rounded-lg border border-border-default bg-surface-muted px-3.5 py-2 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-surface-hover disabled:opacity-50 transition-colors cursor-pointer"
          >
            Cancel
          </button>
          {canEdit && (
            <button
              type="button"
              onClick={handleSavePolicy}
              disabled={isLoading || isSaving}
              className="rounded-lg bg-accent-primary hover:bg-accent-hover px-4 py-2 text-xs font-semibold text-accent-contrast-text disabled:opacity-50 transition-colors cursor-pointer"
            >
              {isSaving
                ? "Saving Policy..."
                : isProtected || isMainBranch
                  ? "Apply Protection"
                  : "Disable Protection"}
            </button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        {error && (
          <div
            role="alert"
            className="rounded-lg bg-status-danger-bg border border-status-danger-border p-3 text-sm text-status-danger"
          >
            {error}
          </div>
        )}

        {isLoading ? (
          <div className="py-8 text-center text-sm text-text-muted">
            Loading protection configuration...
          </div>
        ) : (
          <div className="space-y-4">
            {isMainBranch && (
              <div className="rounded-lg border border-status-info-border bg-status-info-bg p-3 text-xs text-text-primary">
                Production branch <code className="font-mono font-semibold">main</code> is
                always system-protected (cannot be deleted, archived, or committed to directly;
                changes enter <code className="font-mono font-semibold">main</code> via branch merge).
              </div>
            )}

            {/* Protection Master Toggle */}
            <div className="flex items-center justify-between p-3 rounded-lg border border-border-default bg-surface-card">
              <label htmlFor="master-protection-toggle" className="cursor-pointer">
                <span className="text-sm font-semibold text-text-primary block">
                  Enable Branch Protection
                </span>
                <span className="text-xs text-text-muted">
                  Enforce commit gating and deletion safeguards on this branch.
                </span>
              </label>
              <label
                htmlFor="master-protection-toggle"
                className={`relative inline-flex items-center ${isMainBranch || !canEdit ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}
              >
                <input
                  id="master-protection-toggle"
                  type="checkbox"
                  aria-label="Enable branch protection"
                  checked={isProtected || isMainBranch}
                  onChange={(e) => setIsProtected(e.target.checked)}
                  disabled={isSaving || isMainBranch || !canEdit}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-surface-muted peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-accent-contrast-text after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-accent-contrast-text after:border-border-default after:border after:rounded-full after:h-5 after:w-5 after:transition-all border border-border-default peer-checked:bg-accent-primary"></div>
              </label>
            </div>

            {/* Granular Policies */}
            {(isProtected || isMainBranch) && (
              <div className="space-y-3 pt-1">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                  Enforcement Rules
                </h3>

                {/* Allow Direct Commit */}
                <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-border-default bg-surface-card">
                  <label htmlFor="rule-allow-direct" className="cursor-pointer">
                    <span className="text-xs font-semibold text-text-primary block">
                      Allow Direct Commits
                    </span>
                    <span className="text-xs text-text-muted">
                      {isMainBranch
                        ? "Always disabled on main; updates enter via working branch merges."
                        : "If disabled, direct commits to this branch are blocked unless overridden."}
                    </span>
                  </label>
                  <input
                    id="rule-allow-direct"
                    type="checkbox"
                    aria-label="Allow direct commits"
                    checked={isMainBranch ? false : policy.allow_direct_commit}
                    onChange={(e) =>
                      setPolicy((p) => ({ ...p, allow_direct_commit: e.target.checked }))
                    }
                    disabled={isSaving || isMainBranch || !canEdit}
                    className="mt-1 h-4 w-4 rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
                  />
                </div>

                {/* Allow Force Bypass */}
                <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-border-default bg-surface-card">
                  <label htmlFor="rule-force-bypass" className="cursor-pointer">
                    <span className="text-xs font-semibold text-text-primary block">
                      Allow Administrative Force Bypass
                    </span>
                    <span className="text-xs text-text-muted">
                      Allow server admins and operators to override protection with an audit-logged reason.
                    </span>
                  </label>
                  <input
                    id="rule-force-bypass"
                    type="checkbox"
                    aria-label="Allow administrative force bypass"
                    checked={policy.allow_force_bypass}
                    onChange={(e) =>
                      setPolicy((p) => ({ ...p, allow_force_bypass: e.target.checked }))
                    }
                    disabled={isSaving || !canEdit}
                    className="mt-1 h-4 w-4 rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
                  />
                </div>

                {/* Prevent Deletion / Archival */}
                <div className="flex items-start justify-between gap-4 p-3 rounded-lg border border-border-default bg-surface-card">
                  <label htmlFor="rule-prevent-deletion" className="cursor-pointer">
                    <span className="text-xs font-semibold text-text-primary block">
                      Prevent Branch Deletion &amp; Archival
                    </span>
                    <span className="text-xs text-text-muted">
                      Disallow archiving or deleting this branch while protection remains active.
                    </span>
                  </label>
                  <input
                    id="rule-prevent-deletion"
                    type="checkbox"
                    aria-label="Prevent branch deletion and archival"
                    checked={isMainBranch ? true : policy.prevent_deletion}
                    onChange={(e) =>
                      setPolicy((p) => ({ ...p, prevent_deletion: e.target.checked }))
                    }
                    disabled={isSaving || isMainBranch || !canEdit}
                    className="mt-1 h-4 w-4 rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
                  />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
