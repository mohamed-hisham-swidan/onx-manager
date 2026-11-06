import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import { Skeleton } from "@/components/Skeleton";
import { Modal } from "@/components/ui/Modal";

export function AccessModeCard() {
  const queryClient = useQueryClient();
  const api = useMemo(() => createAuthenticatedApi(), []);

  const [pendingMode, setPendingMode] = useState<"LOCAL" | "GLOBAL" | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // System status (canonical access_mode)
  const { data: systemStatus, isLoading: loadingStatus, isError: statusError } = useQuery({
    queryKey: ["systemStatus"],
    queryFn: () => api.getSetupStatus(),
  });

  const updateMutation = useMutation({
    mutationFn: (newMode: "LOCAL" | "GLOBAL") =>
      api.updateAccessMode({ access_mode: newMode }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["systemStatus"] });
      toast("success", "Access Mode Updated", `Instance access mode successfully changed to ${data.access_mode}.`);
      setPendingMode(null);
      setErrorMsg(null);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to update Access Mode";
      setErrorMsg(msg);
      toast("error", "Access Mode Update Failed", msg);
    },
  });

  if (loadingStatus) {
    return (
      <div className="rounded-xl border border-border-default bg-surface-card p-6 space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (statusError || !systemStatus) {
    return (
      <div className="rounded-xl border border-status-danger-border bg-status-danger-bg p-6 text-center text-xs text-status-danger">
        Unable to load system status. Please verify server connectivity.
      </div>
    );
  }

  const currentMode = systemStatus.access_mode as "LOCAL" | "GLOBAL";

  return (
    <div className="rounded-xl border border-border-default bg-surface-card p-6 space-y-6">
      <div className="border-b border-border-default pb-4">
        <h3 className="text-base font-semibold text-text-primary">
          Instance Access Control
        </h3>
        <p className="text-xs text-text-muted mt-1">
          Configure how new users register and access this onx-manager instance.
        </p>
      </div>

      {errorMsg && (
        <div role="alert" className="p-3 text-xs text-status-danger bg-status-danger-bg rounded-lg border border-status-danger-border">
          {errorMsg}
        </div>
      )}

      {/* Current status overview banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-lg bg-surface-page border border-border-default">
        <div>
          <span className="text-xs font-medium text-text-muted uppercase tracking-wider">
            Current Access Mode
          </span>
          <div className="flex items-center gap-2 mt-1">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
              currentMode === "LOCAL"
                ? "bg-status-success-bg text-status-success border border-status-success-border"
                : "bg-accent-primary/10 text-accent-primary border border-accent-primary/20"
            }`}>
              {currentMode} MODE
            </span>
          </div>
        </div>
        <p className="text-xs text-text-secondary max-w-md">
          {currentMode === "LOCAL"
            ? "Open self-registration is ENABLED. Anyone on your local network can create an account (assigned Viewer role by default)."
            : "Open self-registration is DISABLED. Registration requires a valid invitation link created by an Owner or Admin."}
        </p>
      </div>

      {/* Mode selection cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
        {/* LOCAL Mode Card */}
        <div className={`rounded-xl border p-5 space-y-3 transition-colors ${
          currentMode === "LOCAL"
            ? "border-accent-primary bg-surface-elevated ring-1 ring-accent-primary/20"
            : "border-border-default hover:border-border-strong bg-surface-page"
        }`}>
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-text-primary">
              LOCAL (LAN / Self-Hosted)
            </h4>
            {currentMode === "LOCAL" && (
              <span className="text-xs font-medium text-accent-primary">
                Active
              </span>
            )}
          </div>
          <p className="text-xs text-text-muted">
            Ideal for local networks and home labs. Open self-registration is enabled. New users are assigned Viewer permissions by default.
          </p>
          {currentMode !== "LOCAL" && (
            <button
              type="button"
              onClick={() => setPendingMode("LOCAL")}
              className="w-full py-2 px-3 rounded-lg bg-surface-elevated hover:bg-surface-hover text-text-secondary text-xs font-medium border border-border-default transition-colors cursor-pointer"
            >
              Switch to LOCAL Mode
            </button>
          )}
        </div>

        {/* GLOBAL Mode Card */}
        <div className={`rounded-xl border p-5 space-y-3 transition-colors ${
          currentMode === "GLOBAL"
            ? "border-accent-primary bg-surface-elevated ring-1 ring-accent-primary/20"
            : "border-border-default hover:border-border-strong bg-surface-page"
        }`}>
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-text-primary">
              GLOBAL (VPS / Multi-Tenant)
            </h4>
            {currentMode === "GLOBAL" && (
              <span className="text-xs font-medium text-accent-primary">
                Active
              </span>
            )}
          </div>
          <p className="text-xs text-text-muted">
            Ideal for internet-facing servers or cloud VPS deployments. Public self-registration is locked down; users can only join via invitation tokens.
          </p>
          {currentMode !== "GLOBAL" && (
            <button
              type="button"
              onClick={() => setPendingMode("GLOBAL")}
              className="w-full py-2 px-3 rounded-lg bg-surface-elevated hover:bg-surface-hover text-text-secondary text-xs font-medium border border-border-default transition-colors cursor-pointer"
            >
              Switch to GLOBAL Mode
            </button>
          )}
        </div>
      </div>

      {/* Confirmation Modal */}
      <Modal
        open={Boolean(pendingMode)}
        onClose={() => {
          if (updateMutation.isPending) return;
          setPendingMode(null);
        }}
        title={
          pendingMode === "GLOBAL"
            ? "Switch to GLOBAL Access Mode?"
            : "Switch to LOCAL Access Mode?"
        }
        size="md"
        closeOnBackdrop={false}
        closeOnEscape={!updateMutation.isPending}
        closeButtonAriaLabel="Close dialog"
      >
        <div className="space-y-4">
          <p className="text-xs text-text-secondary leading-relaxed">
            {pendingMode === "GLOBAL"
              ? "Changing the instance Access Mode to GLOBAL will immediately disable open self-registration. All future registrations will require a valid invitation link created by an Owner or Admin. Existing user accounts will remain unaffected."
              : "Changing the instance Access Mode to LOCAL will immediately enable open self-registration. Anyone with access to this panel will be able to create a new account (assigned Viewer role by default). Existing user accounts will remain unaffected."}
          </p>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={() => setPendingMode(null)}
              disabled={updateMutation.isPending}
              className="px-4 py-2 rounded-lg border border-border-default text-xs font-medium text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                if (pendingMode) updateMutation.mutate(pendingMode);
              }}
              disabled={updateMutation.isPending}
              className="px-4 py-2 rounded-lg text-xs font-medium bg-accent-primary hover:bg-accent-hover text-accent-contrast-text transition-colors disabled:opacity-50 cursor-pointer"
            >
              {updateMutation.isPending
                ? "Updating Mode..."
                : pendingMode === "GLOBAL"
                ? "Confirm Switch to GLOBAL"
                : "Confirm Switch to LOCAL"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
