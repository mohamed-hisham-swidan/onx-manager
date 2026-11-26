import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Banner } from "@/components/ui/Banner";
import { createAuthenticatedApi, ApiError } from "@/services/api";
import { queryKeys } from "@/services/queryClient";
import { toast } from "@/stores/toastStore";
import { useOperationStore } from "@/operations/stores/operationStore";
import type { LecPrewarmResponse, P55LoaderId } from "@/server_manager/types";

const LOADERS: { id: P55LoaderId; label: string }[] = [
  { id: "fabric", label: "Fabric" },
  { id: "quilt", label: "Quilt" },
  { id: "forge", label: "Forge" },
  { id: "neoforge", label: "NeoForge" },
  { id: "paper", label: "Paper" },
];

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : "Pre-warm failed";
}

export interface PreWarmCacheModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: (result: LecPrewarmResponse) => void;
}

export function PreWarmCacheModal({ open, onClose, onSuccess }: PreWarmCacheModalProps) {
  const api = createAuthenticatedApi();
  const queryClient = useQueryClient();

  const [loaderId, setLoaderId] = useState<P55LoaderId>("fabric");
  const [mcVersion, setMcVersion] = useState("");
  const [loaderVersion, setLoaderVersion] = useState("");
  const [installerVersion, setInstallerVersion] = useState("1.0.1");
  const [asyncMode, setAsyncMode] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClose = () => {
    if (isPending) return;
    setError(null);
    onClose();
  };

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (typeof api.prewarmLecEntry !== "function") return;
    if (!mcVersion.trim() || !loaderVersion.trim()) {
      setError("Minecraft version and loader build version are required.");
      return;
    }
    if (loaderId === "fabric" && !installerVersion.trim()) {
      setError("Fabric installer version is required.");
      return;
    }

    setIsPending(true);
    setError(null);
    try {
      const result = await api.prewarmLecEntry({
        loader_id: loaderId,
        mc_version: mcVersion.trim(),
        loader_version: loaderVersion.trim(),
        installer_version: loaderId === "fabric" ? installerVersion.trim() : null,
        async_mode: asyncMode,
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.p55.lecEntries() });
      toast(
        "success",
        result.status === "queued" ? "Pre-warm queued" : "Loader cached",
        result.status === "queued"
          ? `Queued background download for ${result.lec_key}.`
          : `Cached ${result.file_count} files for ${result.lec_key}.`,
      );
      if (result.operation_id && asyncMode) {
        useOperationStore.getState().openDrawer(result.operation_id);
      }
      onSuccess?.(result);
      onClose();
    } catch (err) {
      const msg = errorMessage(err);
      setError(msg);
      toast("error", "Pre-warm failed", msg);
    } finally {
      setIsPending(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Pre-Warm Loader"
      description="Download and verify a server runtime before creating or upgrading."
      size="md"
      closeOnBackdrop={!isPending}
      closeOnEscape={!isPending}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <Banner variant="danger" title="Pre-warm error" description={error} />}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label htmlFor="lec-loader" className="mb-1 block text-xs font-medium text-text-secondary">
              Loader
            </label>
            <select
              id="lec-loader"
              value={loaderId}
              onChange={(e) => {
                setError(null);
                setLoaderId(e.target.value as P55LoaderId);
              }}
              className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-hidden focus:ring-2 focus:ring-border-focus"
            >
              {LOADERS.map((loader) => (
                <option key={loader.id} value={loader.id}>
                  {loader.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="lec-mc-version" className="mb-1 block text-xs font-medium text-text-secondary">
              Minecraft Version
            </label>
            <input
              id="lec-mc-version"
              value={mcVersion}
              onChange={(e) => {
                setError(null);
                setMcVersion(e.target.value);
              }}
              placeholder="e.g. 1.21.1"
              className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus"
            />
          </div>

          <div className={loaderId === "fabric" ? "" : "sm:col-span-2"}>
            <label htmlFor="lec-loader-version" className="mb-1 block text-xs font-medium text-text-secondary">
              Loader / Build Version
            </label>
            <input
              id="lec-loader-version"
              value={loaderVersion}
              onChange={(e) => {
                setError(null);
                setLoaderVersion(e.target.value);
              }}
              placeholder={loaderId === "paper" ? "e.g. 130" : "e.g. 0.16.9"}
              className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus"
            />
          </div>

          {loaderId === "fabric" && (
            <div>
              <label htmlFor="lec-installer-version" className="mb-1 block text-xs font-medium text-text-secondary">
                Fabric Installer
              </label>
              <input
                id="lec-installer-version"
                value={installerVersion}
                onChange={(e) => {
                  setError(null);
                  setInstallerVersion(e.target.value);
                }}
                placeholder="e.g. 1.0.1"
                className="w-full rounded-lg border border-border-subtle bg-surface-page px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-hidden focus:ring-2 focus:ring-border-focus"
              />
            </div>
          )}
        </div>

        <label className="inline-flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none">
          <input
            type="checkbox"
            checked={asyncMode}
            onChange={(e) => setAsyncMode(e.target.checked)}
            className="onx-checkbox"
          />
          <span>Run in background</span>
        </label>

        <div className="flex justify-end gap-2 pt-2 border-t border-border-subtle">
          <Button type="button" variant="outline" size="sm" disabled={isPending} onClick={handleClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            data-testid="lec-prewarm-btn"
            variant="primary"
            size="sm"
            icon="download"
            loading={isPending}
          >
            Start Pre-Warm
          </Button>
        </div>
      </form>
    </Modal>
  );
}
