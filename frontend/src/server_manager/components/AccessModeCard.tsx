import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import { Skeleton } from "@/components/Skeleton";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Banner } from "@/components/ui/Banner";
import { Icon } from "@/components/ui/Icon";

export function AccessModeCard() {
  const queryClient = useQueryClient();
  const api = useMemo(() => createAuthenticatedApi(), []);

  const [pendingMode, setPendingMode] = useState<"LOCAL" | "GLOBAL" | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: systemStatus, isLoading: loadingStatus, isError: statusError } = useQuery({
    queryKey: ["systemStatus"],
    queryFn: () => api.getSetupStatus(),
  });

  const updateMutation = useMutation({
    mutationFn: (newMode: "LOCAL" | "GLOBAL") =>
      api.updateAccessMode({ access_mode: newMode }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["systemStatus"] });
      toast("success", "Registration mode updated", `Instance mode is now ${data.access_mode}.`);
      setPendingMode(null);
      setErrorMsg(null);
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Failed to update registration mode";
      setErrorMsg(msg);
      toast("error", "Mode update failed", msg);
    },
  });

  if (loadingStatus) {
    return (
      <div className="rounded-xl border border-border-subtle bg-surface-card p-5 space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (statusError || !systemStatus) {
    return (
      <Banner
        variant="danger"
        title="Unable to load registration mode"
        description="Verify panel connectivity and try again."
      />
    );
  }

  const currentMode = systemStatus.access_mode as "LOCAL" | "GLOBAL";

  return (
    <section className="rounded-xl border border-border-subtle bg-surface-card p-5 shadow-2xs space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">User Registration Mode</h3>
          <p className="text-xs text-text-muted mt-0.5">
            Control whether new users can register themselves.
          </p>
        </div>
        <span
          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${
            currentMode === "LOCAL"
              ? "bg-status-success-bg text-status-success border-status-success-border"
              : "bg-accent-primary/10 text-text-accent border-accent-primary/25"
          }`}
        >
          {currentMode} MODE
        </span>
      </div>

      {errorMsg && <Banner variant="danger" title="Update failed" description={errorMsg} />}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* LOCAL Mode Card */}
        <div
          className={`rounded-xl border p-4 space-y-3 transition-colors ${
            currentMode === "LOCAL"
              ? "border-accent-primary bg-accent-primary/8"
              : "border-border-subtle bg-surface-page"
          }`}
        >
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-text-primary">Local / Open</h4>
            {currentMode === "LOCAL" && (
              <Icon name="check" size={15} className="text-text-accent" />
            )}
          </div>
          <p className="text-xs text-text-muted">
            LAN &amp; self-hosted — open registration as Viewer.
          </p>
          {currentMode !== "LOCAL" && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="w-full"
              onClick={() => setPendingMode("LOCAL")}
            >
              Switch to LOCAL Mode
            </Button>
          )}
        </div>

        {/* GLOBAL Mode Card */}
        <div
          className={`rounded-xl border p-4 space-y-3 transition-colors ${
            currentMode === "GLOBAL"
              ? "border-accent-primary bg-accent-primary/8"
              : "border-border-subtle bg-surface-page"
          }`}
        >
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-text-primary">Global / Invite-Only</h4>
            {currentMode === "GLOBAL" && (
              <Icon name="check" size={15} className="text-text-accent" />
            )}
          </div>
          <p className="text-xs text-text-muted">
            VPS — locked down, invite link required.
          </p>
          {currentMode !== "GLOBAL" && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="w-full"
              onClick={() => setPendingMode("GLOBAL")}
            >
              Switch to GLOBAL Mode
            </Button>
          )}
        </div>
      </div>

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
              ? "Open sign-ups will close immediately. New users will need an invitation link. Existing accounts stay unchanged."
              : "Open sign-ups will open immediately with default Viewer permissions. Existing accounts stay unchanged."}
          </p>

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={updateMutation.isPending}
              onClick={() => setPendingMode(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              loading={updateMutation.isPending}
              onClick={() => {
                if (pendingMode) updateMutation.mutate(pendingMode);
              }}
            >
              {updateMutation.isPending
                ? "Updating Mode..."
                : pendingMode === "GLOBAL"
                ? "Confirm Switch to GLOBAL"
                : "Confirm Switch to LOCAL"}
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  );
}
