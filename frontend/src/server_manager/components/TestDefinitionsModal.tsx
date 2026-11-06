import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import type { TestDefinition, CreateTestDefinitionRequest } from "@/server_manager/types";

export interface TestDefinitionsModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  onDefinitionsChanged?: () => void;
}

export function TestDefinitionsModal({
  isOpen,
  onClose,
  serverId,
  onDefinitionsChanged,
}: TestDefinitionsModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);

  const [definitions, setDefinitions] = useState<TestDefinition[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Form state for creating a new profile
  const [isCreating, setIsCreating] = useState<boolean>(false);
  const [profileName, setProfileName] = useState<string>("");
  const [profileDescription, setProfileDescription] = useState<string>("");
  const [botCount, setBotCount] = useState<number>(10);
  const [durationMinutes, setDurationMinutes] = useState<number>(15);
  const [placementMode, setPlacementMode] = useState<string>("sidecar");
  const [botTech, setBotTech] = useState<string>("auto");
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const isDeletingRef = useRef<boolean>(false);

  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setIsCreating(false);
      setError(null);
      setDeleteTarget(null);
    }
  }

  const isBusy = isSubmitting || isDeleting;

  const handleClose = () => {
    if (isBusy) return;
    onClose();
  };

  const loadDefinitions = useCallback(() => {
    setIsLoading(true);
    api
      .getTestDefinitions(serverId)
      .then((data) => {
        setDefinitions(data);
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load test profiles.";
        setError(msg);
        setIsLoading(false);
      });
  }, [api, serverId]);

  useEffect(() => {
    let alive = true;
    if (isOpen) {
      void Promise.resolve().then(() => {
        if (alive) {
          loadDefinitions();
        }
      });
    }
    return () => {
      alive = false;
    };
  }, [isOpen, loadDefinitions]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!profileName.trim()) {
      setError("Profile name cannot be empty.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const payload: CreateTestDefinitionRequest = {
        name: profileName.trim(),
        description: profileDescription.trim() || undefined,
        bot_count: botCount,
        duration_seconds: durationMinutes * 60,
        placement_mode: placementMode,
        bot_technology: botTech,
      };
      await api.createTestDefinition(serverId, payload);
      toast("success", "Profile Created", `Test profile '${profileName.trim()}' created`);
      setProfileName("");
      setProfileDescription("");
      setIsCreating(false);
      loadDefinitions();
      onDefinitionsChanged?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create test profile.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget || isDeletingRef.current || isDeleting) return;
    isDeletingRef.current = true;
    const { id, name } = deleteTarget;
    setIsDeleting(true);
    try {
      await api.deleteTestDefinition(serverId, id);
      toast("success", "Profile Deleted", `Test profile '${name}' deleted`);
      setDeleteTarget(null);
      loadDefinitions();
      onDefinitionsChanged?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete test profile.";
      toast("error", "Delete Failed", msg);
      setDeleteTarget(null);
    } finally {
      isDeletingRef.current = false;
      setIsDeleting(false);
    }
  };

  return (
    <>
      <Modal
        open={isOpen}
        onClose={handleClose}
        title="Reusable Test Profiles"
        description="Manage reusable test configurations and assertion parameters."
        size="xl"
        closeOnBackdrop={!isBusy}
        closeOnEscape={!isBusy}
      >
      <div className="flex flex-col space-y-4 text-text-primary max-h-[75vh]">
        {error && (
          <div role="alert" className="rounded-lg bg-status-danger-bg border border-status-danger-border p-3 text-xs text-status-danger">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-4 pr-1">
          {isCreating ? (
            <form onSubmit={handleCreate} className="space-y-4 rounded-lg border border-border-default bg-surface-card p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-primary">
                  New Test Profile
                </h3>
                <button
                  type="button"
                  onClick={() => setIsCreating(false)}
                  disabled={isSubmitting}
                  className="text-xs text-text-muted hover:text-text-primary disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>

              <div>
                <label htmlFor="def-profile-name" className="block text-xs font-medium text-text-secondary mb-1">
                  Profile Name *
                </label>
                <input
                  id="def-profile-name"
                  type="text"
                  required
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  placeholder="e.g. Standard 10-Bot Stress Test"
                  className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:border-border-focus"
                />
              </div>

              <div>
                <label htmlFor="def-profile-desc" className="block text-xs font-medium text-text-secondary mb-1">
                  Description
                </label>
                <input
                  id="def-profile-desc"
                  type="text"
                  value={profileDescription}
                  onChange={(e) => setProfileDescription(e.target.value)}
                  placeholder="e.g. Purpur stress run before promoting modpack updates"
                  className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:border-border-focus"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="def-bot-count" className="block text-xs font-medium text-text-secondary mb-1">
                    Bot Count
                  </label>
                  <input
                    id="def-bot-count"
                    type="number"
                    min={1}
                    max={50}
                    value={botCount}
                    onChange={(e) => setBotCount(Number(e.target.value))}
                    className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:border-border-focus"
                  />
                </div>
                <div>
                  <label htmlFor="def-duration" className="block text-xs font-medium text-text-secondary mb-1">
                    Duration (Minutes)
                  </label>
                  <input
                    id="def-duration"
                    type="number"
                    min={1}
                    max={60}
                    value={durationMinutes}
                    onChange={(e) => setDurationMinutes(Number(e.target.value))}
                    className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:border-border-focus"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="def-placement" className="block text-xs font-medium text-text-secondary mb-1">
                    Placement Mode
                  </label>
                  <select
                    id="def-placement"
                    value={placementMode}
                    onChange={(e) => setPlacementMode(e.target.value)}
                    className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:border-border-focus"
                  >
                    <option value="sidecar">Sidecar (Docker Bridge)</option>
                    <option value="host">Host Loopback</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="def-bot-tech" className="block text-xs font-medium text-text-secondary mb-1">
                    Bot Technology
                  </label>
                  <select
                    id="def-bot-tech"
                    value={botTech}
                    onChange={(e) => setBotTech(e.target.value)}
                    className="w-full rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-xs text-text-primary focus:outline-none focus:border-border-focus"
                  >
                    <option value="auto">Auto-Detect</option>
                    <option value="fakeplayer">FakePlayer-Next</option>
                    <option value="mineflayer">Mineflayer</option>
                  </select>
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsCreating(false)}
                  disabled={isSubmitting}
                  className="rounded-lg border border-border-default bg-surface-muted px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-surface-hover disabled:opacity-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="rounded-lg bg-accent-primary hover:bg-accent-hover px-3.5 py-1.5 text-xs font-semibold text-accent-contrast-text disabled:opacity-50 transition-colors"
                >
                  {isSubmitting ? "Creating..." : "Save Profile"}
                </button>
              </div>
            </form>
          ) : (
            <div className="flex justify-between items-center">
              <span className="text-xs text-text-muted">
                {definitions.length} saved profile(s)
              </span>
              <button
                type="button"
                onClick={() => setIsCreating(true)}
                className="inline-flex items-center gap-1 rounded-lg bg-accent-primary hover:bg-accent-hover border border-border-subtle px-2.5 py-1 text-xs font-semibold text-accent-contrast-text transition-colors"
              >
                <Icon name="plus" size={12} />
                New Profile
              </button>
            </div>
          )}

          {isLoading ? (
            <div className="py-8 text-center text-xs text-text-muted">
              Loading test profiles...
            </div>
          ) : definitions.length === 0 && !isCreating ? (
            <div className="py-8 text-center text-xs text-text-muted border border-dashed border-border-default rounded-lg">
              No saved test profiles yet. Create a reusable profile to standardize testing parameters across commits.
            </div>
          ) : (
            <div className="space-y-2">
              {definitions.map((def) => (
                <div
                  key={def.id}
                  className="flex items-center justify-between p-3 rounded-lg border border-border-default bg-surface-card hover:border-border-strong transition-colors"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-text-primary">
                        {def.name}
                      </span>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-muted text-text-secondary">
                        {def.bot_count} bots • {Math.round(def.duration_seconds / 60)}m
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-status-info-bg text-status-info border border-status-info-border">
                        {def.placement_mode}
                      </span>
                    </div>
                    {def.description && (
                      <p className="text-[11px] text-text-muted mt-0.5">
                        {def.description}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => setDeleteTarget({ id: def.id, name: def.name })}
                    className="p-1 text-text-muted hover:text-status-danger rounded transition-colors"
                    title="Delete profile"
                  >
                    <Icon name="trash" size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>

    <ConfirmDialog
      open={Boolean(deleteTarget)}
      title="Delete Test Profile"
      description={
        deleteTarget
          ? `Delete test profile '${deleteTarget.name}'? This action cannot be undone.`
          : undefined
      }
      confirmLabel={isDeleting ? "Deleting..." : "Delete Profile"}
      variant="danger"
      isPending={isDeleting}
      onConfirm={handleConfirmDelete}
      onCancel={() => {
        if (isDeleting) return;
        setDeleteTarget(null);
      }}
    />
  </>
  );
}
