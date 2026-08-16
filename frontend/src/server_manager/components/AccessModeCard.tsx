import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { createApiClient } from "@/services/api";
import { toast } from "@/stores/toastStore";
import { Skeleton } from "@/components/Skeleton";

export function AccessModeCard() {
  const queryClient = useQueryClient();
  const api = useMemo(() => createApiClient(window.location.origin, () => null), []);

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
      <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 p-6 space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (statusError || !systemStatus) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 dark:border-red-900/40 dark:bg-red-900/20 p-6 text-center text-xs text-red-700 dark:text-red-300">
        Unable to load system status. Please verify server connectivity.
      </div>
    );
  }

  const currentMode = systemStatus.access_mode as "LOCAL" | "GLOBAL";

  return (
    <div className="rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800 p-6 space-y-6">
      <div className="border-b border-gray-200 dark:border-gray-700 pb-4">
        <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Instance Access Control
        </h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          Configure how new users register and access this MCS Manager instance.
        </p>
      </div>

      {errorMsg && (
        <div role="alert" className="p-3 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
          {errorMsg}
        </div>
      )}

      {/* Current status overview banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-lg bg-gray-50 dark:bg-gray-700/50 border border-gray-200 dark:border-gray-700">
        <div>
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            Current Access Mode
          </span>
          <div className="flex items-center gap-2 mt-1">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
              currentMode === "LOCAL"
                ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300 border border-green-200 dark:border-green-800"
                : "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300 border border-purple-200 dark:border-purple-800"
            }`}>
              {currentMode} MODE
            </span>
          </div>
        </div>
        <p className="text-xs text-gray-600 dark:text-gray-300 max-w-md">
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
            ? "border-blue-500 bg-blue-50/50 dark:border-blue-500/50 dark:bg-blue-900/10"
            : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
        }`}>
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              LOCAL (LAN / Self-Hosted)
            </h4>
            {currentMode === "LOCAL" && (
              <span className="text-xs font-medium text-blue-600 dark:text-blue-400">
                Active
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Ideal for local networks and home labs. Open self-registration is enabled. New users are assigned Viewer permissions by default.
          </p>
          {currentMode !== "LOCAL" && (
            <button
              type="button"
              onClick={() => setPendingMode("LOCAL")}
              className="w-full py-2 px-3 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-800 dark:text-gray-200 text-xs font-medium border border-gray-300 dark:border-gray-600 transition-colors"
            >
              Switch to LOCAL Mode
            </button>
          )}
        </div>

        {/* GLOBAL Mode Card */}
        <div className={`rounded-xl border p-5 space-y-3 transition-colors ${
          currentMode === "GLOBAL"
            ? "border-purple-500 bg-purple-50/50 dark:border-purple-500/50 dark:bg-purple-900/10"
            : "border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 bg-white dark:bg-gray-800"
        }`}>
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              GLOBAL (VPS / Multi-Tenant)
            </h4>
            {currentMode === "GLOBAL" && (
              <span className="text-xs font-medium text-purple-600 dark:text-purple-400">
                Active
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Ideal for internet-facing servers or cloud VPS deployments. Public self-registration is locked down; users can only join via invitation tokens.
          </p>
          {currentMode !== "GLOBAL" && (
            <button
              type="button"
              onClick={() => setPendingMode("GLOBAL")}
              className="w-full py-2 px-3 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-800 dark:text-gray-200 text-xs font-medium border border-gray-300 dark:border-gray-600 transition-colors"
            >
              Switch to GLOBAL Mode
            </button>
          )}
        </div>
      </div>

      {/* Confirmation Modal */}
      {pendingMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 p-6 space-y-4">
            <div className="border-b border-gray-200 dark:border-gray-700 pb-3">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                {pendingMode === "GLOBAL"
                  ? "Switch to GLOBAL Access Mode?"
                  : "Switch to LOCAL Access Mode?"}
              </h3>
            </div>

            <p className="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
              {pendingMode === "GLOBAL"
                ? "Changing the instance Access Mode to GLOBAL will immediately disable open self-registration. All future registrations will require a valid invitation link created by an Owner or Admin. Existing user accounts will remain unaffected."
                : "Changing the instance Access Mode to LOCAL will immediately enable open self-registration. Anyone with access to this panel will be able to create a new account (assigned Viewer role by default). Existing user accounts will remain unaffected."}
            </p>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setPendingMode(null)}
                disabled={updateMutation.isPending}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => updateMutation.mutate(pendingMode)}
                disabled={updateMutation.isPending}
                className={`px-4 py-2 rounded-lg text-xs font-medium text-white transition-colors disabled:opacity-50 ${
                  pendingMode === "GLOBAL"
                    ? "bg-purple-600 hover:bg-purple-700"
                    : "bg-blue-600 hover:bg-blue-700"
                }`}
              >
                {updateMutation.isPending
                  ? "Updating Mode..."
                  : pendingMode === "GLOBAL"
                  ? "Confirm Switch to GLOBAL"
                  : "Confirm Switch to LOCAL"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
