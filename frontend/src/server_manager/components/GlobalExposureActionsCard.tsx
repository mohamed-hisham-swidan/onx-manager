import { useState, useRef, useMemo } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { createAuthenticatedApi } from "@/services/api";
import { toast } from "@/stores/toastStore";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/services/queryClient";

type DestructiveActionType = "STOP_ALL" | "RESET_AGENT" | "REMOVE_CREDENTIALS" | null;

interface ActionConfig {
  type: DestructiveActionType;
  title: string;
  description: string;
  requiredText: string;
  buttonLabel: string;
  inFlightLabel: string;
  isDanger: boolean;
}

const ACTION_CONFIGS: Record<string, ActionConfig> = {
  STOP_ALL: {
    type: "STOP_ALL",
    title: "Stop All Instance Exposures",
    description:
      "This will immediately disable all active network exposures across all Minecraft servers and the web panel. Stored credentials and tunnel configurations will be preserved.",
    requiredText: "STOP ALL",
    buttonLabel: "Stop All Exposures",
    inFlightLabel: "Stopping All...",
    isDanger: true,
  },
  RESET_AGENT: {
    type: "RESET_AGENT",
    title: "Reset playit.gg Host Agent",
    description:
      "This will clear stored host credentials and unclaim the playit agent. All active playit tunnels across all game servers and panel will be disconnected until re-authorized.",
    requiredText: "RESET",
    buttonLabel: "Reset Agent Credentials",
    inFlightLabel: "Resetting Agent...",
    isDanger: true,
  },
  REMOVE_CREDENTIALS: {
    type: "REMOVE_CREDENTIALS",
    title: "Remove All Exposure Credentials",
    description:
      "This will permanently delete all stored encrypted tokens (Cloudflare API tokens, playit secret keys) from this instance and stop all supervisor processes.",
    requiredText: "REMOVE CREDENTIALS",
    buttonLabel: "Delete All Credentials",
    inFlightLabel: "Deleting Credentials...",
    isDanger: true,
  },
};

export function GlobalExposureActionsCard() {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const { data: currentUser } = useQuery({
    queryKey: ["currentUser"],
    queryFn: () => api.getMe(),
  });
  const isOwner = Boolean(currentUser?.roles?.includes("owner"));

  const queryClient = useQueryClient();

  const [activeModal, setActiveModal] = useState<DestructiveActionType>(null);
  const [confirmationInput, setConfirmationInput] = useState("");
  const [isInFlight, setIsInFlight] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  // Gated strictly on Owner role (Spec §7, F-75-09, F-75-18)
  if (!isOwner) return null;

  const currentConfig = activeModal ? ACTION_CONFIGS[activeModal] : null;
  const isMatch = currentConfig
    ? confirmationInput.trim() === currentConfig.requiredText
    : false;

  const handleExecuteAction = async () => {
    if (!currentConfig || !isMatch || isInFlight) return;

    try {
      setIsInFlight(true);
      if (activeModal === "STOP_ALL") {
        const res = await api.stopAllExposures();
        await queryClient.invalidateQueries({ queryKey: queryKeys.exposure.all });
        toast(
          "success",
          "All Exposures Stopped",
          `Successfully disabled ${res?.disabled_count ?? 0} active exposure(s).`
        );
      } else if (activeModal === "RESET_AGENT") {
        await api.resetAgent();
        await queryClient.invalidateQueries({ queryKey: queryKeys.exposure.agent() });
        await queryClient.invalidateQueries({ queryKey: queryKeys.exposure.all });
        toast(
          "success",
          "Agent Credentials Reset",
          "Host playit agent credentials cleared and unclaimed."
        );
      } else if (activeModal === "REMOVE_CREDENTIALS") {
        await api.removeCredentials();
        await queryClient.invalidateQueries({ queryKey: queryKeys.exposure.all });
        toast(
          "success",
          "Credentials Removed",
          "All stored encrypted tokens deleted and tunnel supervisors stopped."
        );
      }

      setActiveModal(null);
      setConfirmationInput("");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to execute global action.";
      toast("error", "Action Failed", msg);
    } finally {
      setIsInFlight(false);
    }
  };

  return (
    <div className="rounded-xl border border-red-200 bg-white p-5 shadow-sm dark:border-red-900/40 dark:bg-gray-800 space-y-4">
      <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
        <Icon name="alert" size={18} />
        <h3 className="text-sm font-semibold uppercase tracking-wider">
          Instance Exposure Controls (Owner-Only)
        </h3>
      </div>

      <p className="text-xs text-gray-500 dark:text-gray-400">
        Instance-wide administrative controls for stopping all public endpoints, revoking tokens, or resetting external tunnel agents. These actions affect all servers immediately.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
        {/* Stop All */}
        <button
          type="button"
          onClick={() => {
            setActiveModal("STOP_ALL");
            setConfirmationInput("");
          }}
          className="flex flex-col justify-between p-3.5 rounded-lg border border-red-200 bg-red-50/50 hover:bg-red-100/60 dark:border-red-900/40 dark:bg-red-950/20 dark:hover:bg-red-950/40 text-left transition-colors group"
        >
          <div>
            <h4 className="text-xs font-semibold text-red-900 dark:text-red-300">
              Stop All Exposures
            </h4>
            <p className="text-[11px] text-red-700 dark:text-red-400 mt-1">
              Disable all active game tunnels and panel exposure across the instance.
            </p>
          </div>
          <span className="text-[11px] font-medium text-red-700 dark:text-red-400 mt-3 group-hover:underline">
            Emergency Stop →
          </span>
        </button>

        {/* Reset Agent */}
        <button
          type="button"
          onClick={() => {
            setActiveModal("RESET_AGENT");
            setConfirmationInput("");
          }}
          className="flex flex-col justify-between p-3.5 rounded-lg border border-red-200 bg-red-50/50 hover:bg-red-100/60 dark:border-red-900/40 dark:bg-red-950/20 dark:hover:bg-red-950/40 text-left transition-colors group"
        >
          <div>
            <h4 className="text-xs font-semibold text-red-900 dark:text-red-300">
              Reset playit Agent
            </h4>
            <p className="text-[11px] text-red-700 dark:text-red-400 mt-1">
              Clear host credentials and unclaim agent. Required when re-claiming account.
            </p>
          </div>
          <span className="text-[11px] font-medium text-red-700 dark:text-red-400 mt-3 group-hover:underline">
            Reset Agent →
          </span>
        </button>

        {/* Remove Credentials */}
        <button
          type="button"
          onClick={() => {
            setActiveModal("REMOVE_CREDENTIALS");
            setConfirmationInput("");
          }}
          className="flex flex-col justify-between p-3.5 rounded-lg border border-red-200 bg-red-50/50 hover:bg-red-100/60 dark:border-red-900/40 dark:bg-red-950/20 dark:hover:bg-red-950/40 text-left transition-colors group"
        >
          <div>
            <h4 className="text-xs font-semibold text-red-900 dark:text-red-300">
              Remove Credentials
            </h4>
            <p className="text-[11px] text-red-700 dark:text-red-400 mt-1">
              Permanently delete all stored encrypted tokens and stop all tunnels.
            </p>
          </div>
          <span className="text-[11px] font-medium text-red-700 dark:text-red-400 mt-3 group-hover:underline">
            Remove Credentials →
          </span>
        </button>
      </div>

      {/* Typed Confirmation Modal (F-75-18) */}
      <Modal
        open={Boolean(activeModal && currentConfig)}
        onClose={() => {
          if (isInFlight) return;
          setActiveModal(null);
          setConfirmationInput("");
        }}
        title={
          <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
            <Icon name="alert" size={20} />
            <span>{currentConfig?.title}</span>
          </div>
        }
        description={currentConfig?.description}
        size="md"
        closeOnBackdrop={false}
        closeOnEscape={!isInFlight}
        closeButtonAriaLabel="Close dialog"
        initialFocusRef={inputRef}
      >
        {currentConfig && (
          <div className="space-y-4">
            <div className="space-y-2 rounded-lg bg-red-50 p-3.5 dark:bg-red-900/20 border border-red-200 dark:border-red-800/40">
              <label
                htmlFor="typed-confirm-input"
                className="block text-xs font-semibold text-red-900 dark:text-red-300"
              >
                Type <span className="font-mono underline">{currentConfig.requiredText}</span> to confirm:
              </label>
              <input
                ref={inputRef}
                id="typed-confirm-input"
                type="text"
                disabled={isInFlight}
                value={confirmationInput}
                onChange={(e) => setConfirmationInput(e.target.value)}
                placeholder={`Type "${currentConfig.requiredText}"`}
                className="w-full px-3 py-2 rounded-lg border border-red-300 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-xs font-mono focus:ring-2 focus:ring-red-500 focus:border-transparent outline-none transition-all disabled:opacity-50"
              />
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setActiveModal(null);
                  setConfirmationInput("");
                }}
                disabled={isInFlight}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleExecuteAction}
                disabled={!isMatch || isInFlight}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-medium transition-colors disabled:opacity-40 shadow-sm"
              >
                {isInFlight ? currentConfig.inFlightLabel : currentConfig.buttonLabel}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
